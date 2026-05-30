"""
نظام الرتب - يحدد صلاحيات كل مستخدم
الرتب من الأعلى للأدنى:
  مطور (DEV_ID) > مالك البوت (botowner) > Dev² > Myth > مالك أساسي > مالك > مدير > ادمن > مميز > عضو

✅ تحسين الأداء:
  - كل فحص رتبة يجلب جميع المفاتيح بـ mget واحد
  - نتيجة الفحص تُخزَّن مؤقتاً 8 ثواني (TTL)
  - حد أقصى 10,000 إدخال في الكاش لمنع Memory Leak
  - is_locked مع كاش 30 ثانية
"""

import time
import logging
from collections import OrderedDict as _OD
from config import r, ar, DEV_ID, DEV_ID_INT

logger = logging.getLogger("helpers.ranks")

# ─────────────────────────────────────────────────────────────────────────
# كاش الرتب
# ─────────────────────────────────────────────────────────────────────────
_rank_cache: _OD = _OD()
_lock_cache: _OD = _OD()
_RANK_TTL = 8
_LOCK_TTL = 30
_MAX_RANK_CACHE = 20000
_MAX_LOCK_CACHE = 5000


def _rank_cache_cleanup():
    if len(_rank_cache) < _MAX_RANK_CACHE:
        return
    now = time.monotonic()
    expired = [k for k, (_, t) in list(_rank_cache.items()) if now - t > _RANK_TTL]
    for k in expired:
        _rank_cache.pop(k, None)
    while len(_rank_cache) > int(_MAX_RANK_CACHE * 0.8):
        _rank_cache.popitem(last=False)


def _lock_cache_cleanup():
    if len(_lock_cache) < _MAX_LOCK_CACHE:
        return
    now = time.monotonic()
    expired = [k for k, (_, t) in list(_lock_cache.items()) if now - t > _LOCK_TTL]
    for k in expired:
        _lock_cache.pop(k, None)
    while len(_lock_cache) > int(_MAX_LOCK_CACHE * 0.8):
        _lock_cache.popitem(last=False)


def _compute_level(su: str, vals) -> int:
    """يحسب مستوى الرتبة من نتائج mget — منفصل لإعادة الاستخدام"""
    owner_id, rank_dev2, rank_dev, rank_go, rank_ow, rank_mo, rank_adm, rank_pre = vals
    if su == str(DEV_ID):           return 9
    if owner_id and su == owner_id: return 8
    if rank_dev2:  return 7
    if rank_dev:   return 6
    if rank_go:    return 5
    if rank_ow:    return 4
    if rank_mo:    return 3
    if rank_adm:   return 2
    if rank_pre:   return 1
    return 0


def _make_rank_keys(su: str, sc: str) -> list:
    return [
        f"{DEV_ID}:owner",
        f"{su}:rankDEV2:{DEV_ID}",
        f"{su}:rankDEV:{DEV_ID}",
        f"{sc}:rankGOWNER:{su}:{DEV_ID}",
        f"{sc}:rankOWNER:{su}:{DEV_ID}",
        f"{sc}:rankMOD:{su}:{DEV_ID}",
        f"{sc}:rankADMIN:{su}:{DEV_ID}",
        f"{sc}:rankPRE:{su}:{DEV_ID}",
    ]


def _get_rank_level(uid: int, cid: int) -> int:
    """
    يُرجع مستوى الرتبة بدقة فورية في كل حالة.

    ✅ إصلاح الخطأ الحرج:
    المشكلة: عند أول رسالة لمستخدم، الكود القديم يُعيد 0 (عضو عادي) ويجدول
    async refresh — مما يُسبب رفض أوامر المدير عند أول استخدام.

    الحل: أول استدعاء يُنفّذ r.mget() بشكل متزامن (blocking) مرة واحدة فقط.
    هذا blocking مقبول لأن:
    1. يحدث مرة واحدة فقط لكل مستخدم منذ آخر تشغيل
    2. بعدها يُخزَّن في الكاش 8 ثوانٍ — لا blocking بعدها
    3. إعطاء صلاحيات خاطئة أسوأ بكثير من blocking لثوانٍ جزئية

    الفرق عن utils.py: هناك False الافتراضي آمن (البوت لا يرد مرة واحدة)،
    أما هنا فالخطأ في الصلاحيات يحجب المدير عن إدارة مجموعته.
    """
    now = time.monotonic()
    cache_key = (uid, cid)
    entry = _rank_cache.get(cache_key)

    if entry:
        level, ts = entry
        if now - ts < _RANK_TTL:
            _rank_cache.move_to_end(cache_key)
            return level
        # الكاش انتهى — stale-while-revalidate (لا blocking)
        import asyncio
        try:
            asyncio.get_running_loop().create_task(_refresh_rank_level(uid, cid))
        except RuntimeError:
            pass
        return level

    # ✅ إصلاح: أول مرة — مطور البوت لا يحتاج Redis
    su, sc = str(uid), str(cid)
    if su == str(DEV_ID):
        _rank_cache_cleanup()
        _rank_cache[cache_key] = (9, now)
        _rank_cache.move_to_end(cache_key)
        return 9

    # ✅ إصلاح: أول مرة لغير المطور — r.mget() متزامن مرة واحدة فقط
    # blocking مقبول لأنه يحدث مرة واحدة لكل مستخدم، والخطأ في الصلاحيات أخطر
    try:
        keys = _make_rank_keys(su, sc)
        vals = r.mget(keys)
        level = _compute_level(su, vals)
    except Exception as e:
        logger.error("get_user_level sync error uid=%s cid=%s: %s", uid, cid, e)
        level = 0

    _rank_cache_cleanup()
    _rank_cache[cache_key] = (level, time.monotonic())
    _rank_cache.move_to_end(cache_key)
    return level


async def _refresh_rank_level(uid: int, cid: int):
    """يُحدِّث كاش الرتبة من Redis بشكل async — يُستدعى في الخلفية فقط"""
    su, sc = str(uid), str(cid)
    try:
        keys = _make_rank_keys(su, sc)
        vals = await ar.mget(keys)
        level = _compute_level(su, vals)
    except Exception as e:
        logger.error("aget_user_level redis error uid=%s cid=%s: %s", uid, cid, e)
        return
    _rank_cache_cleanup()
    cache_key = (uid, cid)
    _rank_cache[cache_key] = (level, time.monotonic())
    _rank_cache.move_to_end(cache_key)


def rank_cache_invalidate(uid: int, cid: int):
    """امسح كاش المستخدم فوراً بعد تغيير رتبته"""
    _rank_cache.pop((uid, cid), None)


# ─────────────────────────── الاسم المعروض ──────────────────────────────

async def get_rank(uid: int, cid: int) -> str:
    su, sc = str(uid), str(cid)
    level = _get_rank_level(uid, cid)

    try:
        all_keys = [
            f"{DEV_ID}:rankName:dev",
            f"{DEV_ID}:rankName:owner_g",
            f"{DEV_ID}:rankName:dev2",
            f"{DEV_ID}:rankName:myth",
            f"{sc}:RankGowner:{DEV_ID}",
            f"{sc}:RankOwner:{DEV_ID}",
            f"{sc}:RankMod:{DEV_ID}",
            f"{sc}:RankAdm:{DEV_ID}",
            f"{sc}:RankPre:{DEV_ID}",
            f"{sc}:RankMem:{DEV_ID}",
            f"{su}:gban:{DEV_ID}",
            f"{su}:mute:{DEV_ID}",
        ]
        vals = await ar.mget(all_keys)
    except Exception as e:
        logger.error("get_rank_title redis error uid=%s cid=%s: %s", uid, cid, e)
        vals = [None] * 12

    if level == 9:  return vals[0] or "مطوّر 🎖️"
    if level == 8:  return vals[1] or "مالك البوت 🎖️"
    if vals[10]: return "محظور عام 🔴"
    if vals[11]: return "مكتوم عام 🔇"
    if level == 7:  return vals[2] or "Dev²🎖"
    if level == 6:  return vals[3] or "Myth🎖️"
    if level == 5:  return vals[4] or "المالك الأساسي 👑"
    if level == 4:  return vals[5] or "المالك 💎"
    if level == 3:  return vals[6] or "المدير ⚙️"
    if level == 2:  return vals[7] or "ادمن 🛡️"
    if level == 1:  return vals[8] or "مميز ⭐"
    return vals[9] or "عضو"


# ─────────────────────────── فحص الصلاحيات ──────────────────────────────

def is_dev(uid: int, cid: int = 0) -> bool:
    return _get_rank_level(uid, cid) >= 9

def is_botowner(uid: int, cid: int = 0) -> bool:
    return _get_rank_level(uid, cid) >= 8

def is_dev2(uid: int, cid: int = 0) -> bool:
    return _get_rank_level(uid, cid) >= 7

def is_myth(uid: int, cid: int = 0) -> bool:
    return _get_rank_level(uid, cid) >= 6

def is_gowner(uid: int, cid: int) -> bool:
    return _get_rank_level(uid, cid) >= 5

def is_owner(uid: int, cid: int) -> bool:
    return _get_rank_level(uid, cid) >= 4

def is_mod(uid: int, cid: int) -> bool:
    return _get_rank_level(uid, cid) >= 3

def is_admin(uid: int, cid: int) -> bool:
    return _get_rank_level(uid, cid) >= 2

def is_pre(uid: int, cid: int) -> bool:
    return _get_rank_level(uid, cid) >= 1


# ─── aliases ────────────────────────────────────────────────────────────

def admin_pls(uid: int, cid: int) -> bool:  return is_admin(uid, cid)
def mod_pls(uid: int, cid: int) -> bool:    return is_mod(uid, cid)
def owner_pls(uid: int, cid: int) -> bool:  return is_owner(uid, cid)
def gowner_pls(uid: int, cid: int) -> bool: return is_gowner(uid, cid)
def dev_pls(uid: int, cid: int) -> bool:    return is_myth(uid, cid)
def dev2_pls(uid: int, cid: int) -> bool:   return is_dev2(uid, cid)
def devp_pls(uid: int, cid: int) -> bool:   return is_botowner(uid, cid)
def pre_pls(uid: int, cid: int) -> bool:    return is_pre(uid, cid)


# ─────────────────────────── قفل الأوامر — مع كاش ──────────────────────

LOCK_LEVELS = {0: is_gowner, 1: is_owner, 2: is_mod, 3: is_admin, 4: is_pre}


async def _refresh_locks_async(cid: int):
    try:
        locks = await ar.hgetall(f"{DEV_ID}:locks:{cid}")
    except Exception:
        return
    _lock_cache_cleanup()
    ck = f"locks:{cid}"
    _lock_cache[ck] = (locks, time.monotonic())
    _lock_cache.move_to_end(ck)


def is_locked(uid: int, cid: int, text: str) -> bool:
    """يرجع True إذا كان الأمر مقفولاً — stale-while-revalidate"""
    import asyncio
    now = time.monotonic()
    cache_key = f"locks:{cid}"
    entry = _lock_cache.get(cache_key)

    if entry:
        locks, ts = entry
        if now - ts < _LOCK_TTL:
            _lock_cache.move_to_end(cache_key)
        else:
            try:
                asyncio.get_running_loop().create_task(_refresh_locks_async(cid))
            except RuntimeError:
                try:
                    locks = r.hgetall(f"{DEV_ID}:locks:{cid}")
                    _lock_cache_cleanup()
                    _lock_cache[cache_key] = (locks, time.monotonic())
                    _lock_cache.move_to_end(cache_key)
                except Exception:
                    pass
    else:
        # أول مرة — blocking مقبول لأن قائمة الأقفال ضرورية للأمان
        try:
            locks = r.hgetall(f"{DEV_ID}:locks:{cid}")
        except Exception as e:
            logger.error("is_locked redis error cid=%s: %s", cid, e)
            return False
        _lock_cache_cleanup()
        _lock_cache[cache_key] = (locks, now)
        _lock_cache.move_to_end(cache_key)

    if not locks:
        return False
    txt_lower = text.lower()
    for cmd, level in locks.items():
        if cmd.lower() in txt_lower:
            checker = LOCK_LEVELS.get(int(level), is_gowner)
            return not checker(uid, cid)
    return False


def lock_cache_invalidate(cid: int):
    """امسح كاش الأقفال لمجموعة معينة"""
    _lock_cache.pop(f"locks:{cid}", None)


# alias قديم
def isLockCommand(uid: int, cid: int, text: str) -> bool:
    return is_locked(uid, cid, text)


# ─────────────────────────── get_devs ──────────────────────────────────

_devs_cache: tuple | None = None
_devs_cache_time: float = 0
_DEVS_TTL = 60


async def get_devs() -> list:
    """يُرجع قائمة بكل معرّفات المطورين — مع كاش 60 ثانية"""
    global _devs_cache, _devs_cache_time
    now = time.monotonic()
    if _devs_cache is not None and now - _devs_cache_time < _DEVS_TTL:
        return list(_devs_cache)

    try:
        devs = [DEV_ID_INT]
        owner_id = await ar.get(f"{DEV_ID}:owner")
        if owner_id and int(owner_id) != DEV_ID_INT:
            devs.append(int(owner_id))
        for uid in await ar.smembers(f"{DEV_ID}:DEV2"):
            try: devs.append(int(uid))
            except ValueError as e:
                logger.error("Invalid DEV2 uid '%s': %s", uid, e)
        for uid in await ar.smembers(f"{DEV_ID}:DEV"):
            try: devs.append(int(uid))
            except ValueError as e:
                logger.error("Invalid DEV uid '%s': %s", uid, e)
        result = list(dict.fromkeys(devs))
    except Exception as e:
        logger.error("get_devs redis error: %s", e)
        result = [DEV_ID_INT]

    _devs_cache = tuple(result)
    _devs_cache_time = now
    return result
