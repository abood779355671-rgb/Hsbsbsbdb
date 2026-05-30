"""
أوامر الإدارة العامة
  تفعيل / تعطيل          → تشغيل/إيقاف البوت في المجموعة
  كتم الكل / فتح الكل    → إسكات/فتح المجموعة لغير الإداريين
  اقفل [امر] [مستوى]     → قفل أمر على مستوى معين
  افتح [امر]             → فتح أمر مقفول
  الاقفال                → قائمة الأقفال
  تغيير مفتاح [نص]       → تغيير رمز البوت في الردود
  تغيير الاسم [اسم]      → تغيير اسم البوت
  /start / /help          → مساعدة خاصة
"""
import re
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from config import r, DEV_ID, botkey, botname, ar
from helpers.ranks import is_admin, is_mod, is_gowner, is_owner, is_dev
from helpers.utils import group_enabled, can_speak, resolve_text, utils_cache_invalidate


LOCK_LEVELS_AR = {
    "مالك اساسي": 0,
    "مالك":       1,
    "مدير":       2,
    "ادمن":       3,
    "مميز":       4,
}
LOCK_LEVELS_LABEL = {0: "مالك أساسي", 1: "مالك", 2: "مدير", 3: "ادمن", 4: "مميز"}


# ─────────────── /start في الخاص ────────────────────────────────────────

@Client.on_message(filters.command("start") & filters.private)
async def cmd_start(c: Client, m: Message):
    k    = botkey()
    name = botname()
    # ✅ إصلاح 2: رسالة واحدة تجمع النص والزر بدلاً من رسالتين منفصلتين
    _channel = await ar.get(str(DEV_ID) + ":BotChannel") or "telegram"
    await m.reply(
        f"أهلاً! أنا **{name}** 🤖\n\n"
        f"{k} بوت إدارة مجموعات متكامل\n\n"
        "**الميزات:**\n"
        "• نظام رتب (مطوّر، مالك، مدير، ادمن، مميز)\n"
        "• كتم وحظر (محلي وعام)\n"
        "• فلاتر مخصصة (نص، صور، فيديو ...)\n"
        "• أوامر مخصصة\n"
        "• ترحيب وقوانين مخصصة\n"
        "• همسة inline\n"
        "• فلتر الكلمات السيئة\n\n"
        f"لتفعيلي في مجموعتك: ارفعني مشرفاً ثم أرسل **تفعيل**",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("قناة البوت 📢", url=f"https://t.me/{_channel}"),
        ]])
    )


@Client.on_message(filters.command("help") & filters.private)
async def cmd_help(c: Client, m: Message):
    k = botkey()
    await m.reply(
        f"{k} **قائمة الأوامر الرئيسية:**\n\n"
        "**الإدارة:**\n`تفعيل` `تعطيل` `كتم الكل` `فتح الكل`\n\n"
        "**الرتب:**\n`رتبة` `ادمن @` `مدير @` `مالك @` `شيل ادمن @`\n\n"
        "**الكتم:**\n`كتم (ردّ)` `كتم @` `كتم عام @` `الغاء الكتم`\n\n"
        "**الحظر:**\n`حظر عام (ردّ/@ )` `الغاء الحظر العام`\n\n"
        "**الفلاتر:**\n`اضف فلتر [كلمة]` `حذف فلتر [كلمة]` `الفلاتر`\n\n"
        "**الترحيب:**\n`وضع الترحيب` `مسح الترحيب` `وضع قوانين` `القوانين`\n\n"
        "**الأوامر المخصصة:**\n`اضف امر` `حذف امر` `الاوامر المضافة`\n\n"
        "**فلتر الكلمات:**\n`اضف كلمة [كلمة]` `حذف كلمة [كلمة]` `الكلمات المحظورة`\n\n"
        "**الأقفال:**\n`اقفل [امر] [مستوى]` `افتح [امر]` `الاقفال`\n\n"
        "**الهمسة:**\n`@البوت همستك @username` (inline)"
    )


# ─────────────── تفعيل وتعطيل في المجموعة ───────────────────────────────

# الأوامر المعروفة في هذا الـ handler — للخروج السريع من الرسائل العادية
_KNOWN_COMMANDS = {
    "تفعيل", "تعطيل", "كتم الكل", "فتح الكل", "الاقفال", "مجموعاتي",
}
_KNOWN_PREFIXES = ("تغيير مفتاح ", "تغيير الاسم ", "اقفل ", "افتح ")

@Client.on_message(filters.text & filters.group, group=10)
async def admin_commands(c: Client, m: Message):
    if not m.from_user:
        return
    cid, uid = m.chat.id, m.from_user.id
    k = botkey()

    text_raw = m.text.strip() if m.text else ""
    if not text_raw:
        return

    # ✅ إصلاح 1: early return سريع — الرسائل العادية تخرج فوراً
    # بدون هذا الفحص كل رسالة نصية تمر عبر الـ regex الثقيلة أدناه
    if (text_raw not in _KNOWN_COMMANDS and
            not any(text_raw.startswith(p) for p in _KNOWN_PREFIXES)):
        # قد تكون تفعيل/تعطيل — هما الوحيدان اللذان يعملان قبل group_enabled
        if text_raw not in ("تفعيل", "تعطيل"):
            return

    # ── تفعيل ────────────────────────────────────────────────────────────
    if text_raw == "تفعيل":
        if not is_owner(uid, cid):
            return await m.reply(f"{k} هذا الأمر للمالك وفوق فقط")
        await ar.set(f"{cid}:enable:{DEV_ID}", 1)
        await ar.sadd(f"enablelist:{DEV_ID}", cid)
        utils_cache_invalidate(f"{cid}:enable:{DEV_ID}")
        return await m.reply(f"{k} تم تفعيل البوت في هذه المجموعة ✅")

    # ── تعطيل ────────────────────────────────────────────────────────────
    if text_raw == "تعطيل":
        if not is_owner(uid, cid):
            return await m.reply(f"{k} هذا الأمر للمالك وفوق فقط")
        await ar.delete(f"{cid}:enable:{DEV_ID}")
        await ar.srem(f"enablelist:{DEV_ID}", cid)
        utils_cache_invalidate(f"{cid}:enable:{DEV_ID}")
        return await m.reply(f"{k} تم تعطيل البوت في هذه المجموعة")

    if not group_enabled(cid):
        return
    if not can_speak(uid, cid):
        return

    text = resolve_text(text_raw, cid)

    # ── كتم الكل / فتح الكل ──────────────────────────────────────────────
    if text == "كتم الكل":
        if not is_mod(uid, cid):
            return await m.reply(f"{k} هذا الأمر للمدير وفوق فقط")
        await ar.set(f"{cid}:mute:{DEV_ID}", 1)
        return await m.reply(f"{k} تم إسكات المجموعة 🔇 (الإداريون فقط يتكلمون)")

    if text == "فتح الكل":
        if not is_mod(uid, cid):
            return await m.reply(f"{k} هذا الأمر للمدير وفوق فقط")
        await ar.delete(f"{cid}:mute:{DEV_ID}")
        return await m.reply(f"{k} تم فتح الكلام للجميع 🔊")

    # ── تغيير مفتاح (رمز البوت) ──────────────────────────────────────────
    m_key = re.fullmatch(r"تغيير مفتاح\s+(.+)", text)
    if m_key:
        if not is_dev(uid, cid):
            return await m.reply(f"{k} هذا الأمر للمطور فقط")
        new_key = m_key.group(1).strip()
        await ar.set(f"{DEV_ID}:botkey", new_key)
        return await m.reply(f"تم تغيير المفتاح إلى: {new_key} ✅")

    # ── تغيير اسم البوت ──────────────────────────────────────────────────
    m_name = re.fullmatch(r"تغيير الاسم\s+(.+)", text)
    if m_name:
        if not is_dev(uid, cid):
            return await m.reply(f"{k} هذا الأمر للمطور فقط")
        new_name = m_name.group(1).strip()
        await ar.set(f"{DEV_ID}:BotName", new_name)
        return await m.reply(f"{k} تم تغيير اسم البوت إلى: **{new_name}** ✅")

    # ── اقفل أمر ─────────────────────────────────────────────────────────
    m_lock = re.fullmatch(r"اقفل\s+(\S+)\s+(\S+)", text)
    if m_lock:
        if not is_gowner(uid, cid):
            return await m.reply(f"{k} هذا الأمر للمالك الأساسي وفوق فقط")
        cmd_name  = m_lock.group(1)
        level_str = m_lock.group(2)
        level     = LOCK_LEVELS_AR.get(level_str)
        if level is None:
            levels_list = " / ".join(LOCK_LEVELS_AR.keys())
            return await m.reply(f"{k} مستوى غير صحيح. الخيارات: {levels_list}")
        await ar.hset(f"{DEV_ID}:locks:{cid}", cmd_name, level)
        return await m.reply(
            f"{k} تم قفل أمر «{cmd_name}» على مستوى **{LOCK_LEVELS_LABEL[level]}** ✅"
        )

    # ── افتح أمر ─────────────────────────────────────────────────────────
    m_unlock = re.fullmatch(r"افتح\s+(\S+)", text)
    if m_unlock:
        if not is_gowner(uid, cid):
            return await m.reply(f"{k} هذا الأمر للمالك الأساسي وفوق فقط")
        cmd_name = m_unlock.group(1)
        await ar.hdel(f"{DEV_ID}:locks:{cid}", cmd_name)
        return await m.reply(f"{k} تم فتح أمر «{cmd_name}» ✅")

    # ── قائمة الأقفال ────────────────────────────────────────────────────
    if text == "الاقفال":
        if not is_admin(uid, cid):
            return await m.reply(f"{k} هذا الأمر للادمن وفوق فقط")
        locks = await ar.hgetall(f"{DEV_ID}:locks:{cid}")
        if not locks:
            return await m.reply(f"{k} لا توجد أقفال في هذه المجموعة")
        lines = [f"{k} الأوامر المقفولة:\n"]
        for cmd, lvl in locks.items():
            lines.append(f"• `{cmd}` — {LOCK_LEVELS_LABEL.get(int(lvl), '—')}")
        return await m.reply("\n".join(lines))

    # ── مجموعات البوت (للمطور) ───────────────────────────────────────────
    if text == "مجموعاتي":
        if not is_dev(uid, cid):
            return await m.reply(f"{k} هذا الأمر للمطور فقط")
        groups = await ar.smembers(f"enablelist:{DEV_ID}")
        count  = len(groups)
        # ✅ إصلاح 3: إرسال العدد فقط لتجنب تجاوز حد 4096 حرف عند كثرة المجموعات
        return await m.reply(
            f"{k} عدد المجموعات المفعّلة: **{count}**"
        )
