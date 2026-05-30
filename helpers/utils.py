"""
وظائف مساعدة مشتركة
"""
import asyncio
import time
import hashlib
from collections import OrderedDict as _OD
from config import r, ar, DEV_ID, botname, cached_smembers
from helpers.ranks import is_admin


def _txt_key(text: str) -> str:
    """
    ينتج مفتاح كاش قصيراً من النص:
    - نصوص <= 40 حرفاً: تُستخدم مباشرة.
    - نصوص أطول: أول 20 حرف + md5 مختصر لمنع تضخم الكاش.
    """
    if len(text) <= 40:
        return text
    digest = hashlib.md5(text.encode("utf-8", errors="replace"), usedforsecurity=False).hexdigest()[:8]
    return f"{text[:20]}{digest}"


_utils_cache: _OD = _OD()
_MAX_UTILS_CACHE = 10000
_ENABLE_TTL = 30
_MUTE_TTL   = 3
# ✅ إصلاح 3: رُفع من 5 ثوانٍ إلى 30 ثانية — الأوامر المخصصة لا تتغير كثيراً
_RTXT_TTL   = 30


def _utils_cache_cleanup():
    if len(_utils_cache) < _MAX_UTILS_CACHE:
        return
    now = time.monotonic()
    expired = [k for k, (_, t, ttl) in list(_utils_cache.items()) if now - t > ttl]
    for k in expired:
        _utils_cache.pop(k, None)
    while len(_utils_cache) > int(_MAX_UTILS_CACHE * 0.8):
        _utils_cache.popitem(last=False)


async def _refresh_bool_async(key: str, ttl: float):
    try:
        val = bool(await ar.get(key))
    except Exception:
        return
    _utils_cache_cleanup()
    _utils_cache[key] = (val, time.monotonic(), ttl)
    _utils_cache.move_to_end(key)


def _bool_cached(key: str, ttl: float = _ENABLE_TTL) -> bool:
    """
    ✅ إصلاح 1: لا blocking Redis أبداً.
    - الكاش موجود وحديث → إرجاع فوري.
    - الكاش منتهٍ → أعد القيمة القديمة + جدول async refresh.
    - أول مرة → أعد False فوراً + جدول async refresh.
      (False آمن هنا: group_enabled/is_muted يُعيدان False = لا تصرف،
       بدلاً من blocking يُجمّد كل المجموعات)
    """
    now = time.monotonic()
    entry = _utils_cache.get(key)
    if entry:
        val, ts, stored_ttl = entry
        if now - ts < stored_ttl:
            _utils_cache.move_to_end(key)
            return val
        # الكاش انتهى — stale-while-revalidate
        try:
            asyncio.get_running_loop().create_task(_refresh_bool_async(key, ttl))
        except RuntimeError:
            pass
        return val

    # ✅ إصلاح 1: أول مرة — لا r.get() blocking، إعادة False + async fetch
    _utils_cache_cleanup()
    _utils_cache[key] = (False, now - ttl + 1, ttl)  # ttl-1 لضمان refresh سريع
    _utils_cache.move_to_end(key)
    try:
        asyncio.get_running_loop().create_task(_refresh_bool_async(key, ttl))
    except RuntimeError:
        # خارج event loop (مثلاً عند الإقلاع) — blocking مقبول مرة واحدة فقط
        try:
            val = bool(r.get(key))
            _utils_cache[key] = (val, time.monotonic(), ttl)
        except Exception:
            pass
    return False


async def _refresh_str_async(cache_key: str, redis_key: str):
    try:
        val = await ar.get(redis_key)
    except Exception:
        return
    _utils_cache_cleanup()
    _utils_cache[cache_key] = (val, time.monotonic(), _RTXT_TTL)
    _utils_cache.move_to_end(cache_key)


def _str_cached(cache_key: str, redis_key: str) -> str | None:
    """
    ✅ إصلاح 2: لا blocking Redis أبداً.
    أول مرة → None (= لا أمر مخصص) + async fetch في الخلفية.
    None هنا آمن تماماً: resolve_text تُعيد النص الأصلي إذا لم يوجد أمر مخصص.
    """
    now = time.monotonic()
    entry = _utils_cache.get(cache_key)
    if entry:
        val, ts, _ = entry
        if now - ts < _RTXT_TTL:
            _utils_cache.move_to_end(cache_key)
            return val
        # الكاش انتهى — stale-while-revalidate
        try:
            asyncio.get_running_loop().create_task(_refresh_str_async(cache_key, redis_key))
        except RuntimeError:
            pass
        return val

    # ✅ إصلاح 2: أول مرة — لا r.get() blocking، إعادة None + async fetch
    # None = لا يوجد أمر مخصص = آمن تماماً (النص الأصلي يُستخدم)
    _utils_cache_cleanup()
    _utils_cache[cache_key] = (None, now - _RTXT_TTL + 1, _RTXT_TTL)
    _utils_cache.move_to_end(cache_key)
    try:
        asyncio.get_running_loop().create_task(_refresh_str_async(cache_key, redis_key))
    except RuntimeError:
        # خارج event loop — blocking مقبول مرة واحدة فقط
        try:
            val = r.get(redis_key)
            _utils_cache[cache_key] = (val, time.monotonic(), _RTXT_TTL)
        except Exception:
            pass
    return None


def utils_cache_invalidate(key: str):
    _utils_cache.pop(key, None)


def group_enabled(cid: int) -> bool:
    return _bool_cached(f"{cid}:enable:{DEV_ID}")


def is_muted_user(uid: int, cid: int) -> bool:
    return (
        _bool_cached(f"{uid}:mute:{cid}:{DEV_ID}", ttl=_MUTE_TTL) or
        _bool_cached(f"{uid}:mute:{DEV_ID}", ttl=_MUTE_TTL)
    )


def is_gbanned(uid: int) -> bool:
    return _bool_cached(f"{uid}:gban:{DEV_ID}", ttl=_MUTE_TTL)


def group_muted(cid: int) -> bool:
    return _bool_cached(f"{cid}:mute:{DEV_ID}")


def can_speak(uid: int, cid: int) -> bool:
    if group_muted(cid) and not is_admin(uid, cid):
        return False
    if is_muted_user(uid, cid):
        return False
    return True


def resolve_text(text: str, cid: int) -> str:
    name = botname()
    if text.startswith(f"{name} "):
        text = text[len(name) + 1:]

    # نستخدم _txt_key لتقصير مفتاح الكاش — يمنع تضخم الكاش بالنصوص الطويلة
    k = _txt_key(text)
    local = _str_cached(f"rtxt:l:{cid}:{k}", f"{cid}:Custom:{cid}:{DEV_ID}&text={text}")
    if local:
        return local

    global_ = _str_cached(f"rtxt:g:{k}", f"Custom:{DEV_ID}&text={text}")
    if global_:
        return global_

    return text
