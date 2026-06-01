"""
نظام الإنذارات والتحذيرات
أوامر:
  تحذير (رد) / تحذير @user     → إضافة تحذير للعضو (ادمن وفوق)
  مسح تحذير (رد) / مسح تحذير @user → مسح آخر تحذير (ادمن وفوق)
  مسح تحذيراته (رد) / مسح تحذيراته @user → مسح كل تحذيرات العضو (مدير وفوق)
  التحذيرات (رد) / التحذيرات @user → عرض عدد تحذيرات العضو
  التحذيرات               → عرض قائمة المحذَّرين في المجموعة
  الحد الأقصى [رقم]       → تعيين الحد الأقصى للتحذيرات (مالك وفوق)
  الحد الأقصى             → عرض الحد الحالي

مفاتيح Redis:
  warn:{uid}:{cid}:{DEV_ID}     → عدد التحذيرات (int)
  warnMax:{cid}:{DEV_ID}        → الحد الأقصى (افتراضي 3)
  listWARN:{cid}:{DEV_ID}       → set بـ uid المحذَّرين
"""
import re
import time
from collections import OrderedDict as _OD

from pyrogram import Client, filters
from pyrogram.types import Message

from config import ar, DEV_ID, botkey
from helpers.ranks import is_admin, is_mod, is_owner, is_pre, get_rank
from helpers.utils import group_enabled, can_speak, resolve_text


# ─────────────────────────── كاش التحذيرات ───────────────────────────────
_warn_cache: _OD = _OD()
_WARN_TTL        = 15          # ثانية
_MAX_WARN_CACHE  = 5000


def _warn_cache_cleanup():
    if len(_warn_cache) < _MAX_WARN_CACHE:
        return
    now = time.monotonic()
    expired = [k for k, (_, t) in list(_warn_cache.items()) if now - t > _WARN_TTL]
    for k in expired:
        _warn_cache.pop(k, None)
    while len(_warn_cache) > int(_MAX_WARN_CACHE * 0.8):
        _warn_cache.popitem(last=False)


def _warn_cache_invalidate(uid: int, cid: int):
    _warn_cache.pop(f"warn:{uid}:{cid}", None)
    _warn_cache.pop(f"warnMax:{cid}", None)


# ─────────────────────────── مفاتيح Redis ────────────────────────────────

def _warn_key(uid: int, cid: int) -> str:
    return f"warn:{uid}:{cid}:{DEV_ID}"

def _warn_max_key(cid: int) -> str:
    return f"warnMax:{cid}:{DEV_ID}"

def _warn_list_key(cid: int) -> str:
    return f"listWARN:{cid}:{DEV_ID}"


# ─────────────────────────── دوال مساعدة ─────────────────────────────────

async def _get_warn_count(uid: int, cid: int) -> int:
    """يجلب عدد تحذيرات العضو مع كاش."""
    cache_key = f"warn:{uid}:{cid}"
    now = time.monotonic()
    entry = _warn_cache.get(cache_key)
    if entry and now - entry[1] < _WARN_TTL:
        return entry[0]
    val = await ar.get(_warn_key(uid, cid))
    count = int(val) if val else 0
    _warn_cache_cleanup()
    _warn_cache[cache_key] = (count, now)
    return count


async def _get_warn_max(cid: int) -> int:
    """يجلب الحد الأقصى للتحذيرات مع كاش (افتراضي 3)."""
    cache_key = f"warnMax:{cid}"
    now = time.monotonic()
    entry = _warn_cache.get(cache_key)
    if entry and now - entry[1] < _WARN_TTL:
        return entry[0]
    val = await ar.get(_warn_max_key(cid))
    mx = int(val) if val else 3
    _warn_cache_cleanup()
    _warn_cache[cache_key] = (mx, now)
    return mx


async def _resolve_target(c: Client, m: Message, raw: str | None):
    """يُرجع (user_id, mention) من رد أو يوزر/آيدي."""
    if raw is None:
        if m.reply_to_message and m.reply_to_message.from_user:
            u = m.reply_to_message.from_user
            return u.id, u.mention
        return None, None
    try:
        uid = int(raw)
    except ValueError:
        uid = raw.lstrip("@")
    try:
        u = await c.get_users(uid)
        return u.id, u.mention
    except Exception:
        return None, None


def _extract_target(text: str) -> str | None:
    """يستخرج آخر كلمة إذا كانت يوزر أو آيدي."""
    parts = text.split()
    if len(parts) > 1:
        last = parts[-1]
        if last.startswith("@") or last.lstrip("-").isdigit():
            return last
    return None


# ─────────────────────────── معالج الأوامر ───────────────────────────────

@Client.on_message(filters.text & filters.group, group=13)
async def warnings_handler(c: Client, m: Message):
    if not m.from_user:
        return

    cid = m.chat.id
    uid = m.from_user.id

    if not group_enabled(cid):
        return
    if not can_speak(uid, cid):
        return

    text = resolve_text(m.text, cid)
    k    = botkey()

    # ══════════════════════════════════════════════════════════════════
    # تحذير
    # ══════════════════════════════════════════════════════════════════
    if re.match(r"^تحذير($| .+)", text):
        if not is_admin(uid, cid):
            return await m.reply(f"{k} هذا الأمر يخص الادمن وفوق فقط")

        raw = _extract_target(text)
        target_id, mention = await _resolve_target(c, m, raw)
        if target_id is None:
            return await m.reply(f"{k} حدد المستخدم برد أو يوزر/آيدي")
        if target_id == uid:
            return await m.reply(f"{k} ما تقدر تحذر نفسك 😅")
        if is_pre(target_id, cid):
            rk = await get_rank(target_id, cid)
            return await m.reply(f"{k} ما تقدر تحذر {rk}")

        warn_key  = _warn_key(target_id, cid)
        list_key  = _warn_list_key(cid)
        max_warns = await _get_warn_max(cid)

        # زيادة العداد بـ pipeline
        async with ar.pipeline(transaction=False) as pipe:
            pipe.incr(warn_key)
            pipe.sadd(list_key, target_id)
            results = await pipe.execute()

        current = results[0]
        _warn_cache_invalidate(target_id, cid)

        if current >= max_warns:
            # وصل الحد — كتم تلقائي
            mute_key      = f"{target_id}:mute:{cid}:{DEV_ID}"
            mute_list_key = f"{cid}:listMUTEs:{DEV_ID}"
            async with ar.pipeline(transaction=False) as pipe:
                pipe.set(mute_key, 1)
                pipe.sadd(mute_list_key, target_id)
                pipe.delete(warn_key)
                pipe.srem(list_key, target_id)
                await pipe.execute()
            _warn_cache_invalidate(target_id, cid)
            return await m.reply(
                f"「 {mention} 」\n"
                f"{k} وصل الحد الأقصى ({max_warns}) تحذيرات\n"
                f"{k} تم كتمه تلقائياً 🔇\n☆"
            )

        return await m.reply(
            f"「 {mention} 」\n"
            f"{k} تحذير {current}/{max_warns} ⚠️\n☆"
        )

    # ══════════════════════════════════════════════════════════════════
    # مسح تحذير (آخر تحذير واحد)
    # ══════════════════════════════════════════════════════════════════
    if re.match(r"^مسح تحذير($| .+)", text):
        if not is_admin(uid, cid):
            return await m.reply(f"{k} هذا الأمر يخص الادمن وفوق فقط")

        raw = _extract_target(text)
        target_id, mention = await _resolve_target(c, m, raw)
        if target_id is None:
            return await m.reply(f"{k} حدد المستخدم برد أو يوزر/آيدي")

        warn_key = _warn_key(target_id, cid)
        current  = await _get_warn_count(target_id, cid)

        if current <= 0:
            return await m.reply(f"「 {mention} 」\n{k} ما عنده تحذيرات")

        new_count = current - 1
        if new_count == 0:
            async with ar.pipeline(transaction=False) as pipe:
                pipe.delete(warn_key)
                pipe.srem(_warn_list_key(cid), target_id)
                await pipe.execute()
        else:
            await ar.set(warn_key, new_count)

        _warn_cache_invalidate(target_id, cid)
        max_warns = await _get_warn_max(cid)
        return await m.reply(
            f"「 {mention} 」\n"
            f"{k} تم مسح تحذير ✅\n"
            f"{k} التحذيرات الآن: {new_count}/{max_warns}\n☆"
        )

    # ══════════════════════════════════════════════════════════════════
    # مسح تحذيراته (كل التحذيرات)
    # ══════════════════════════════════════════════════════════════════
    if re.match(r"^مسح تحذيراته($| .+)", text):
        if not is_mod(uid, cid):
            return await m.reply(f"{k} هذا الأمر يخص المدير وفوق فقط")

        raw = _extract_target(text)
        target_id, mention = await _resolve_target(c, m, raw)
        if target_id is None:
            return await m.reply(f"{k} حدد المستخدم برد أو يوزر/آيدي")

        current = await _get_warn_count(target_id, cid)
        if current <= 0:
            return await m.reply(f"「 {mention} 」\n{k} ما عنده تحذيرات")

        async with ar.pipeline(transaction=False) as pipe:
            pipe.delete(_warn_key(target_id, cid))
            pipe.srem(_warn_list_key(cid), target_id)
            await pipe.execute()

        _warn_cache_invalidate(target_id, cid)
        return await m.reply(
            f"「 {mention} 」\n"
            f"{k} تم مسح كل تحذيراته ({current}) ✅\n☆"
        )

    # ══════════════════════════════════════════════════════════════════
    # التحذيرات — عرض تحذيرات عضو معين أو قائمة المجموعة
    # ══════════════════════════════════════════════════════════════════
    if re.match(r"^التحذيرات($| .+)", text):

        raw = _extract_target(text)

        # إذا فيه رد أو يوزر → عرض تحذيرات عضو معين
        if raw or (m.reply_to_message and m.reply_to_message.from_user):
            target_id, mention = await _resolve_target(c, m, raw)
            if target_id is None:
                return await m.reply(f"{k} ما لقيت هذا المستخدم")
            current   = await _get_warn_count(target_id, cid)
            max_warns = await _get_warn_max(cid)
            if current == 0:
                return await m.reply(f"「 {mention} 」\n{k} ما عنده تحذيرات ✅")
            return await m.reply(
                f"「 {mention} 」\n"
                f"{k} التحذيرات: {current}/{max_warns} ⚠️"
            )

        # بدون رد أو يوزر → قائمة كل المحذَّرين
        warned_ids = await ar.smembers(_warn_list_key(cid))
        if not warned_ids:
            return await m.reply(f"{k} لا يوجد أعضاء محذَّرون في هذه المجموعة ✅")

        max_warns = await _get_warn_max(cid)
        lines = [f"{k} **قائمة المحذَّرين** ⚠️\n"]
        for i, wid in enumerate(warned_ids, 1):
            count = await _get_warn_count(int(wid), cid)
            try:
                u = await c.get_users(int(wid))
                name = u.mention
            except Exception:
                name = f"`{wid}`"
            lines.append(f"{i}. {name} — {count}/{max_warns}")

        return await m.reply("\n".join(lines))

    # ══════════════════════════════════════════════════════════════════
    # الحد الأقصى [رقم] — تعيين أو عرض الحد
    # ══════════════════════════════════════════════════════════════════
    m_max = re.match(r"^الحد الأقصى(?:\s+(\d+))?$", text)
    if m_max:
        current_max = await _get_warn_max(cid)

        if not m_max.group(1):
            # عرض الحد الحالي فقط
            return await m.reply(
                f"{k} الحد الأقصى الحالي للتحذيرات: **{current_max}** ⚠️"
            )

        # تعيين حد جديد — يحتاج مالك وفوق
        if not is_owner(uid, cid):
            return await m.reply(f"{k} هذا الأمر يخص المالك وفوق فقط")

        new_max = int(m_max.group(1))
        if new_max < 1 or new_max > 20:
            return await m.reply(f"{k} الحد يجب أن يكون بين 1 و 20")

        await ar.set(_warn_max_key(cid), new_max)
        _warn_cache.pop(f"warnMax:{cid}", None)
        return await m.reply(
            f"{k} تم تعيين الحد الأقصى للتحذيرات: **{new_max}** ✅\n☆"
        )
