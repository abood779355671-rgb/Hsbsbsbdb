import os
import time
import logging
import asyncio
import redis
import redis.asyncio as aioredis
from collections import OrderedDict as _OD
from pyrogram import Client

logger = logging.getLogger("config")

API_ID    = int(os.getenv("API_ID", "0"))
API_HASH  = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
REDIS_URL = os.getenv("REDIS_URL", "")
DEV_ID    = os.getenv("DEV_ID", "").strip()

# ── التحقق من المتغيرات الإلزامية عند الإقلاع ─────────────────────────────
_missing = [k for k, v in {"API_ID": API_ID, "API_HASH": API_HASH,
                             "BOT_TOKEN": BOT_TOKEN, "DEV_ID": DEV_ID}.items()
            if not v or str(v) == "0"]
if _missing:
    raise EnvironmentError(
        f"❌ المتغيرات البيئية التالية مفقودة أو غير مضبوطة: {', '.join(_missing)}\n"
        f"   أضفها في إعدادات Render / Heroku قبل التشغيل."
    )

try:
    DEV_ID_INT: int = int(DEV_ID)
except ValueError:
    raise EnvironmentError("❌ DEV_ID يجب أن يكون رقم Telegram صحيح (أرقام فقط).")

if DEV_ID == "123456789":
    raise EnvironmentError(
        "❌ DEV_ID لا يزال على القيمة الافتراضية '123456789'.\n"
        "   هذا خطر أمني — أي شخص بهذا الـ ID سيملك صلاحيات المطور الكاملة.\n"
        "   اضبط DEV_ID بـ ID الحقيقي الخاص بك في المتغيرات البيئية."
    )

# ── Redis clients ─────────────────────────────────────────────────────────
_REDIS_POOL_SIZE = 50

if REDIS_URL:
    r  = redis.from_url(REDIS_URL, decode_responses=True, max_connections=_REDIS_POOL_SIZE)
    _ar = aioredis.from_url(REDIS_URL, decode_responses=True, max_connections=_REDIS_POOL_SIZE)
else:
    r  = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True, max_connections=_REDIS_POOL_SIZE)
    _ar = aioredis.Redis(host="localhost", port=6379, db=0, decode_responses=True, max_connections=_REDIS_POOL_SIZE)

ar = _ar

__all__ = [
    "r", "ar", "DEV_ID", "DEV_ID_INT",
    "botkey", "botname", "cached_smembers",
    "cache_invalidate", "cache_invalidate_prefix",
    "safe_get", "safe_set", "safe_delete", "Client",
]

_cache: _OD = _OD()
_MAX_CACHE_SIZE = 10000
_STR_TTL = 60
_SET_TTL = 45


def _cache_cleanup():
    if len(_cache) < _MAX_CACHE_SIZE:
        return
    now = time.monotonic()
    expired = [k for k, (_, t, ttl) in list(_cache.items()) if now - t > ttl]
    for k in expired:
        _cache.pop(k, None)
    while len(_cache) > int(_MAX_CACHE_SIZE * 0.8):
        _cache.popitem(last=False)


def _cached_get(cache_key: str, redis_key: str, default: str, ttl: int = _STR_TTL) -> str:
    now = time.monotonic()
    entry = _cache.get(cache_key)
    if entry:
        value, ts, _ = entry
        if now - ts < ttl:
            _cache.move_to_end(cache_key)
            return value
        try:
            asyncio.get_running_loop().create_task(
                _refresh_cached_get(cache_key, redis_key, default, ttl)
            )
        except RuntimeError:
            pass
        return value
    _cache_cleanup()
    _cache[cache_key] = (default, now - ttl + 2, ttl)
    _cache.move_to_end(cache_key)
    try:
        asyncio.get_running_loop().create_task(
            _refresh_cached_get(cache_key, redis_key, default, ttl)
        )
    except RuntimeError:
        try:
            loop = asyncio.new_event_loop()
            value = loop.run_until_complete(_refresh_cached_get_return(redis_key, default))
            loop.close()
            _cache[cache_key] = (value, time.monotonic(), ttl)
        except Exception:
            pass
    return default


async def _refresh_cached_get(cache_key: str, redis_key: str, default: str, ttl: int):
    try:
        value = await _ar.get(redis_key) or default
    except Exception:
        return
    _cache_cleanup()
    _cache[cache_key] = (value, time.monotonic(), ttl)
    _cache.move_to_end(cache_key)


async def _refresh_cached_get_return(redis_key: str, default: str) -> str:
    try:
        return await _ar.get(redis_key) or default
    except Exception:
        return default


def _cached_smembers(cache_key: str, redis_key: str) -> frozenset:
    now = time.monotonic()
    entry = _cache.get(cache_key)
    if entry:
        value, ts, _ = entry
        if now - ts < _SET_TTL:
            _cache.move_to_end(cache_key)
            return value
        try:
            asyncio.get_running_loop().create_task(
                _refresh_smembers_async(cache_key, redis_key)
            )
        except RuntimeError:
            pass
        return value
    _cache_cleanup()
    _cache[cache_key] = (frozenset(), now - _SET_TTL + 2, _SET_TTL)
    _cache.move_to_end(cache_key)
    try:
        asyncio.get_running_loop().create_task(
            _refresh_smembers_async(cache_key, redis_key)
        )
    except RuntimeError:
        try:
            value = frozenset(r.smembers(redis_key))
            _cache[cache_key] = (value, time.monotonic(), _SET_TTL)
        except Exception:
            pass
    return frozenset()


async def _refresh_smembers_async(cache_key: str, redis_key: str):
    try:
        value = frozenset(await _ar.smembers(redis_key))
    except Exception:
        return
    _cache_cleanup()
    _cache[cache_key] = (value, time.monotonic(), _SET_TTL)
    _cache.move_to_end(cache_key)


def cache_invalidate(cache_key: str):
    _cache.pop(cache_key, None)


def cache_invalidate_prefix(prefix: str):
    for k in list(_cache.keys()):
        if k.startswith(prefix):
            _cache.pop(k, None)


def botkey() -> str:
    return _cached_get("botkey", f"{DEV_ID}:botkey", "⚡")


def botname() -> str:
    return _cached_get("botname", f"{DEV_ID}:BotName", "بوتي")


def cached_smembers(redis_key: str) -> frozenset:
    return _cached_smembers(f"sm:{redis_key}", redis_key)


def safe_get(key: str, default=None):
    try:
        return r.get(key) or default
    except Exception as e:
        logger.warning("Redis get error: %s", e)
        return default


def safe_set(key: str, value, **kwargs) -> bool:
    try:
        r.set(key, value, **kwargs)
        return True
    except Exception as e:
        logger.warning("Redis set error: %s", e)
        return False


def safe_delete(*keys) -> bool:
    try:
        r.delete(*keys)
        return True
    except Exception as e:
        logger.warning("Redis delete error: %s", e)
        return False


Client = Client(
    "my_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    plugins=dict(root="Plugins"),
    # ✅ إصلاح 5: رفع workers من 4 (افتراضي) إلى 16
    # 4 workers تعني أن Pyrogram لا يعالج أكثر من 4 رسائل في نفس الوقت
    # في البوت بـ 50+ مجموعة نشطة هذا يُسبب تأخراً ملحوظاً
    # 16 worker توازن جيد بين الأداء واستهلاك الذاكرة
    workers=16,
)
