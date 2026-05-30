"""
نظام الرفع والتنزيل - أوامر تعيين وإزالة الرتب
أوامر الرفع:
  رفع Dev @user / رد      → رفع إلى Dev²🎖 (يحتاج botowner)
  رفع MY @user / رد       → رفع إلى Myth🎖️ (يحتاج Dev²)
  رفع مالك اساسي @user   → يحتاج gowner وفوق
  رفع مالك @user          → يحتاج gowner
  رفع مدير @user          → يحتاج owner
  رفع ادمن @user          → يحتاج mod
  رفع مميز @user          → يحتاج admin
  تعطيل الرفع / تفعيل الرفع → يحتاج owner
أوامر التنزيل:
  تنزيل Dev / تنزيل MY / تنزيل مالك اساسي / تنزيل مالك
  تنزيل مدير / تنزيل ادمن / تنزيل مميز / تنزيل الكل
"""

import re
import time
from pyrogram import Client, filters
from pyrogram.types import Message

from config import r, DEV_ID, DEV_ID_INT, botkey, ar
from helpers.ranks import (
    get_rank, is_dev, is_botowner, is_dev2, is_myth,
    is_gowner, is_owner, is_mod, is_admin, is_pre,
    rank_cache_invalidate, isLockCommand, _get_rank_level,  # المشكلة 4: نُقل لأعلى الملف
)
from helpers.utils import group_enabled, can_speak, resolve_text


def _key(cid, rkey, uid):
    """تنسيق مفاتيح Redis الموحّد"""
    return f"{cid}:{rkey}:{uid}:{DEV_ID}"

def _list_key(cid, rkey):
    return f"{cid}:{rkey}s:{DEV_ID}"


# المشكلة 2: cache محلي لنتائج get_users — {query: (uid, mention, expires_at)}
_USER_CACHE_TTL = 300  # 5 دقائق
_user_resolve_cache: dict[str, tuple[int, str, float]] = {}


async def _resolve_target(c: Client, m: Message, text_part: str | None):
    """يُرجع (user_id, mention) مع cache لتجنب استدعاء Telegram API في كل أمر."""
    if text_part is None:
        if m.reply_to_message and m.reply_to_message.from_user:
            u = m.reply_to_message.from_user
            return u.id, u.mention
        return None, None

    try:
        uid_key = int(text_part)
    except ValueError:
        uid_key = text_part.lstrip("@").lower()

    cache_key = str(uid_key)
    entry = _user_resolve_cache.get(cache_key)
    if entry and time.monotonic() < entry[2]:
        return entry[0], entry[1]

    try:
        u = await c.get_users(uid_key)
        _user_resolve_cache[cache_key] = (u.id, u.mention, time.monotonic() + _USER_CACHE_TTL)
        return u.id, u.mention
    except Exception:
        return None, None


def _self_check(m, target_id):
    return target_id == m.from_user.id

def _dev_check(target_id):
    return target_id == DEV_ID_INT


# المشكلة 5: استخراج parse الهدف في دالة واحدة بدلاً من تكرارها في كل re.match
def _extract_raw_target(text: str) -> str | None:
    """يُرجع آخر كلمة في النص إذا كانت يوزر أو آيدي، وإلا None."""
    parts = text.split()
    if len(parts) > 1:
        last = parts[-1]
        if last.startswith("@") or last.lstrip("-").isdigit():
            return last
    return None


# المشكلة 1: _clear_mute مُعرَّفة مرة واحدة على مستوى الملف
async def _clear_mute(tid: int, c_id: int) -> None:
    """يرفع الكتم عن المستخدم من جميع مفاتيح Redis دفعة واحدة."""
    async with ar.pipeline(transaction=False) as pipe:
        pipe.delete(f"{tid}:mute:{DEV_ID}")
        pipe.srem(f"listMUTE:{DEV_ID}", tid)
        pipe.delete(f"{tid}:mute:{c_id}:{DEV_ID}")
        pipe.srem(f"{c_id}:listMUTEs:{DEV_ID}", tid)
        await pipe.execute()


# المشكلة 1: do_promote مُعرَّفة مرة واحدة على مستوى الملف
async def do_promote(
    c: Client, m: Message, text: str, k: str,
    rkey: str, list_rkey: str, rank_label: str,
) -> None:
    """ينفّذ عملية الرفع: يحدد الهدف، يتحقق، يكتب Redis، يُبطل cache."""
    raw = _extract_raw_target(text)  # المشكلة 5: استخدام الدالة المشتركة
    target_id, mention = await _resolve_target(c, m, raw)

    if target_id is None:
        return await m.reply(f"{k} حدد المستخدم برد أو يوزر/آيدي")
    if _self_check(m, target_id):
        return await m.reply(f"{k} هطف تبي ترفع نفسك؟")
    if _dev_check(target_id):
        return await m.reply("ركز حبيبي كيف ارفع نفسي")

    key = _key(m.chat.id, rkey, target_id)
    if await ar.get(key):
        return await m.reply(f"「 {mention} 」\n{k} {rank_label} من قبل\n☆")

    async with ar.pipeline(transaction=False) as pipe:
        pipe.set(key, 1)
        pipe.sadd(_list_key(m.chat.id, list_rkey), target_id)
        await pipe.execute()
    rank_cache_invalidate(target_id, m.chat.id)
    await _clear_mute(target_id, m.chat.id)
    return await m.reply(f"{k} الحلو 「 {mention} 」\n{k} رفعته صار {rank_label}\n☆")


# المشكلة 1: do_demote مُعرَّفة مرة واحدة على مستوى الملف
async def do_demote(
    c: Client, m: Message, text: str, k: str, rank: str,
    rkey: str, list_rkey: str, rank_label: str,
) -> None:
    """ينفّذ عملية التنزيل: يحدد الهدف، يتحقق، يحذف من Redis، يُبطل cache."""
    raw = _extract_raw_target(text)  # المشكلة 5: استخدام الدالة المشتركة
    target_id, mention = await _resolve_target(c, m, raw)

    if target_id is None:
        return await m.reply(f"{k} حدد المستخدم برد أو يوزر/آيدي")
    if _dev_check(target_id):
        return await m.reply("ركز حبيبي كيف انزل نفسي")

    # المشكلة 3: get_rank للهدف مرة واحدة فقط، لا ثلاث مرات
    target_rank = await get_rank(target_id, m.chat.id)
    if rank == target_rank:
        return await m.reply("نفس رتبتك ترا")

    key = _key(m.chat.id, rkey, target_id)
    if not await ar.get(key):
        return await m.reply(f"「 {mention} 」\n{k} مو {rank_label}\n☆")

    async with ar.pipeline(transaction=False) as pipe:
        pipe.delete(key)
        pipe.srem(_list_key(m.chat.id, list_rkey), target_id)
        await pipe.execute()
    rank_cache_invalidate(target_id, m.chat.id)
    return await m.reply(f"「 {mention} 」\n{k} نزلته من {rank_label}\n☆")


@Client.on_message(filters.text & filters.group, group=7)
async def set_ranks_handler(c: Client, m: Message):
    if not m.from_user:
        return
    cid, uid = m.chat.id, m.from_user.id
    if not group_enabled(cid):
        return
    if not can_speak(uid, cid):
        return

    text = resolve_text(m.text, cid)
    k    = botkey()

    if isLockCommand(uid, cid, text):
        return

    # ── تعطيل / تفعيل الرفع ──────────────────────────────────────────────
    if text == "تعطيل الرفع":
        if not is_owner(uid, cid):
            return await m.reply(f"{k} هذا الامر يخص ( المالك وفوق ) بس")
        if await ar.get(f"{cid}:disableRanks:{DEV_ID}"):
            return await m.reply(f"{k} من「 {m.from_user.mention} 」\n{k} الرفع معطل من قبل\n☆")
        await ar.set(f"{cid}:disableRanks:{DEV_ID}", 1)
        return await m.reply(f"{k} من「 {m.from_user.mention} 」\n{k} ابشر عطلت الرفع\n☆")

    if text == "تفعيل الرفع":
        if not is_owner(uid, cid):
            return await m.reply(f"{k} هذا الامر يخص ( المالك وفوق ) بس")
        if not await ar.get(f"{cid}:disableRanks:{DEV_ID}"):
            return await m.reply(f"「 {m.from_user.mention} 」\n{k} الرفع مفعل من قبل\n☆")
        await ar.delete(f"{cid}:disableRanks:{DEV_ID}")
        return await m.reply(f"{k} من「 {m.from_user.mention} 」\n{k} ابشر فعلت الرفع\n☆")

    if await ar.get(f"{cid}:disableRanks:{DEV_ID}"):
        return

    rank = await get_rank(uid, cid)

    # ═══════════════════════════════════════════════════════════════════════
    # ── أوامر الرفع ────────────────────────────────────────────────────────
    # ═══════════════════════════════════════════════════════════════════════

    # رفع Dev² (يحتاج botowner)
    if re.match(r"^رفع Dev($| .+)", text):
        if not is_botowner(uid, cid):
            return await m.reply(f"{k} هذا الامر يخص ( Dev🎖️ ) بس")
        raw = _extract_raw_target(text)  # المشكلة 5: دالة مشتركة
        target_id, mention = await _resolve_target(c, m, raw)
        if target_id is None:
            return await m.reply(f"{k} حدد المستخدم برد أو يوزر/آيدي")
        if _self_check(m, target_id): return await m.reply(f"{k} هطف تبي ترفع نفسك؟")
        if _dev_check(target_id):     return await m.reply("ركز حبيبي كيف ارفع نفسي")
        key = f"{target_id}:rankDEV2:{DEV_ID}"
        if await ar.get(key):
            return await m.reply(f"「 {mention} 」\n{k} Dev²🎖 من قبل\n☆")
        async with ar.pipeline(transaction=False) as pipe:
            pipe.set(key, 1)
            pipe.sadd(f"{DEV_ID}:DEV2", target_id)
            await pipe.execute()
        rank_cache_invalidate(target_id, cid)
        await _clear_mute(target_id, cid)
        return await m.reply(f"{k} الحلو 「 {mention} 」\n{k} رفعته صار Dev²🎖\n☆")

    # رفع Myth (يحتاج Dev²)
    if re.match(r"^رفع MY($| .+)", text):
        if not is_dev2(uid, cid):
            return await m.reply(f"{k} هذا الامر يخص ( Dev²🎖️ وفوق ) بس")
        raw = _extract_raw_target(text)  # المشكلة 5: دالة مشتركة
        target_id, mention = await _resolve_target(c, m, raw)
        if target_id is None:
            return await m.reply(f"{k} حدد المستخدم برد أو يوزر/آيدي")
        if _self_check(m, target_id): return await m.reply(f"{k} هطف تبي ترفع نفسك؟")
        if _dev_check(target_id):     return await m.reply("ركز حبيبي كيف ارفع نفسي")
        # المشكلة 3: get_rank للهدف مرة واحدة فقط
        target_rank = await get_rank(target_id, cid)
        if rank == target_rank: return await m.reply("نفس رتبتك ترا")
        key = f"{target_id}:rankDEV:{DEV_ID}"
        if await ar.get(key):
            return await m.reply(f"「 {mention} 」\n{k} Myth🎖️ من قبل\n☆")
        async with ar.pipeline(transaction=False) as pipe:
            pipe.set(key, 1)
            pipe.sadd(f"{DEV_ID}:DEV", target_id)
            await pipe.execute()
        rank_cache_invalidate(target_id, cid)
        await _clear_mute(target_id, cid)
        return await m.reply(f"{k} الحلو 「 {mention} 」\n{k} رفعته صار Myth🎖️\n☆")

    # رفع مالك اساسي (يحتاج gowner)
    if re.match(r"^رفع مالك اساسي($| .+)", text):
        if not is_gowner(uid, cid):
            return await m.reply(f"{k} هذا الامر يخص ( المالك الاساسي وفوق ) بس")
        return await do_promote(c, m, text, k, "rankGOWNER", "rankGOWNER", "المالك الاساسي")

    # رفع مالك (يحتاج gowner)
    if re.match(r"^رفع مالك($| .+)", text):
        if not is_gowner(uid, cid):
            return await m.reply(f"{k} هذا الامر يخص ( المالك الاساسي ) بس")
        return await do_promote(c, m, text, k, "rankOWNER", "rankOWNER", "المالك")

    # رفع مدير (يحتاج owner)
    if re.match(r"^رفع مدير($| .+)", text):
        if not is_owner(uid, cid):
            return await m.reply(f"{k} هذا الامر يخص ( المالك وفوق ) بس")
        return await do_promote(c, m, text, k, "rankMOD", "rankMOD", "المدير")

    # رفع ادمن (يحتاج mod)
    if re.match(r"^رفع ادمن($| .+)", text):
        if not is_mod(uid, cid):
            return await m.reply(f"{k} هذا الامر يخص ( المدير وفوق ) بس")
        return await do_promote(c, m, text, k, "rankADMIN", "rankADMIN", "الادمن")

    # رفع مميز (يحتاج admin)
    if re.match(r"^رفع مميز($| .+)", text):
        if not is_admin(uid, cid):
            return await m.reply(f"{k} هذا الامر يخص ( الادمن وفوق ) بس")
        return await do_promote(c, m, text, k, "rankPRE", "rankPRE", "المميز")

    # ═══════════════════════════════════════════════════════════════════════
    # ── أوامر التنزيل ──────────────────────────────────────────────────────
    # ═══════════════════════════════════════════════════════════════════════

    if re.match(r"^تنزيل Dev($| .+)", text):
        if not is_botowner(uid, cid):
            return await m.reply(f"{k} هذا الامر يخص ( Dev🎖️ ) بس")
        raw = _extract_raw_target(text)  # المشكلة 5: دالة مشتركة
        target_id, mention = await _resolve_target(c, m, raw)
        if target_id is None:
            return await m.reply(f"{k} حدد المستخدم برد أو يوزر/آيدي")
        if _dev_check(target_id): return await m.reply("ركز حبيبي كيف انزل نفسي")
        key = f"{target_id}:rankDEV2:{DEV_ID}"
        if not await ar.get(key):
            return await m.reply(f"「 {mention} 」\n{k} مو Dev²🎖\n☆")
        async with ar.pipeline(transaction=False) as pipe:
            pipe.delete(key)
            pipe.srem(f"{DEV_ID}:DEV2", target_id)
            await pipe.execute()
        rank_cache_invalidate(target_id, cid)
        return await m.reply(f"「 {mention} 」\n{k} نزلته من Dev²🎖\n☆")

    if re.match(r"^تنزيل MY($| .+)", text):
        if not is_dev2(uid, cid):
            return await m.reply(f"{k} هذا الامر يخص ( Dev²🎖️ وفوق ) بس")
        raw = _extract_raw_target(text)  # المشكلة 5: دالة مشتركة
        target_id, mention = await _resolve_target(c, m, raw)
        if target_id is None:
            return await m.reply(f"{k} حدد المستخدم برد أو يوزر/آيدي")
        if _dev_check(target_id): return await m.reply("ركز حبيبي كيف انزل نفسي")
        # المشكلة 3: get_rank للهدف مرة واحدة فقط
        target_rank = await get_rank(target_id, cid)
        if rank == target_rank: return await m.reply("نفس رتبتك ترا")
        key = f"{target_id}:rankDEV:{DEV_ID}"
        if not await ar.get(key):
            return await m.reply(f"「 {mention} 」\n{k} مو Myth🎖️ من قبل\n☆")
        async with ar.pipeline(transaction=False) as pipe:
            pipe.delete(key)
            pipe.srem(f"{DEV_ID}:DEV", target_id)
            await pipe.execute()
        rank_cache_invalidate(target_id, cid)
        return await m.reply(f"「 {mention} 」\n{k} نزلته من Myth🎖️\n☆")

    if re.match(r"^تنزيل مالك اساسي($| .+)", text):
        if not is_gowner(uid, cid):
            return await m.reply(f"{k} هذا الامر يخص ( المالك الاساسي وفوق ) بس")
        return await do_demote(c, m, text, k, rank, "rankGOWNER", "rankGOWNER", "المالك الاساسي")

    if re.match(r"^تنزيل مالك($| .+)", text):
        if not is_gowner(uid, cid):
            return await m.reply(f"{k} هذا الامر يخص ( المالك الاساسي ) بس")
        return await do_demote(c, m, text, k, rank, "rankOWNER", "rankOWNER", "المالك")

    if re.match(r"^تنزيل مدير($| .+)", text):
        if not is_owner(uid, cid):
            return await m.reply(f"{k} هذا الامر يخص ( المالك وفوق ) بس")
        return await do_demote(c, m, text, k, rank, "rankMOD", "rankMOD", "المدير")

    if re.match(r"^تنزيل ادمن($| .+)", text):
        if not is_mod(uid, cid):
            return await m.reply(f"{k} هذا الامر يخص ( المدير وفوق ) بس")
        return await do_demote(c, m, text, k, rank, "rankADMIN", "rankADMIN", "الادمن")

    if re.match(r"^تنزيل مميز($| .+)", text):
        if not is_admin(uid, cid):
            return await m.reply(f"{k} هذا الامر يخص ( الادمن وفوق ) بس")
        return await do_demote(c, m, text, k, rank, "rankPRE", "rankPRE", "المميز")

    # تنزيل الكل
    if re.match(r"^تنزيل الكل($| .+)", text):
        if not is_mod(uid, cid):
            return await m.reply(f"{k} هذا الامر يخص ( المدير وفوق ) بس")

        raw = _extract_raw_target(text)  # المشكلة 5: دالة مشتركة
        target_id, mention = await _resolve_target(c, m, raw)
        if target_id is None:
            return await m.reply(f"{k} حدد المستخدم برد أو يوزر/آيدي")
        if _dev_check(target_id):  return await m.reply("ركز حبيبي كيف انزل نفسي")
        if target_id == uid:       return await m.reply(f"{k} مافيك تنزل نفسك")

        # المشكلة 3: get_rank و _get_rank_level للهدف كل منهما مرة واحدة فقط
        target_rank  = await get_rank(target_id, cid)
        if rank == target_rank:
            return await m.reply("نفس رتبتك ترا")

        t_level  = _get_rank_level(target_id, cid)   # المشكلة 4: الـ import في الأعلى
        my_level = _get_rank_level(uid, cid)

        if t_level >= my_level:
            return await m.reply(f"{k} رتبته اعلى منك أو مساوية")

        rank_map = [
            (7, f"{target_id}:rankDEV2:{DEV_ID}",      f"{DEV_ID}:DEV2"),
            (6, f"{target_id}:rankDEV:{DEV_ID}",        f"{DEV_ID}:DEV"),
            (5, _key(cid, "rankGOWNER", target_id),     _list_key(cid, "rankGOWNER")),
            (4, _key(cid, "rankOWNER",  target_id),     _list_key(cid, "rankOWNER")),
            (3, _key(cid, "rankMOD",    target_id),     _list_key(cid, "rankMOD")),
            (2, _key(cid, "rankADMIN",  target_id),     _list_key(cid, "rankADMIN")),
            (1, _key(cid, "rankPRE",    target_id),     _list_key(cid, "rankPRE")),
        ]
        async with ar.pipeline(transaction=False) as pipe:
            for lvl, rkey, lkey in rank_map:
                if lvl < my_level:
                    pipe.delete(rkey)
                    pipe.srem(lkey, target_id)
            await pipe.execute()

        rank_cache_invalidate(target_id, cid)
        return await m.reply(f"「 {mention} 」\n{k} نزلته من {target_rank}\n☆")
