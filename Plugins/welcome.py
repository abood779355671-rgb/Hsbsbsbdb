"""
الترحيب والقوانين
أوامر:
  وضع الترحيب / ضع الترحيب → تعيين رسالة ترحيب مخصصة
  الترحيب                   → عرض الترحيب الحالي
  مسح الترحيب               → حذف الترحيب المخصص
  وضع قوانين                → تعيين قوانين المجموعة
  مسح القوانين              → حذف القوانين
  القوانين                  → عرض القوانين

متغيرات الترحيب:
  {الاسم}     {اليوزر}    {المجموعه}
  {التاريخ}   {الوقت}     {القوانين}
"""

import asyncio
import time
import pytz
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery, ChatPermissions,
)

from config import r, DEV_ID, DEV_ID_INT, botkey, botname, ar
from helpers.ranks import is_mod, is_pre
from helpers.utils import group_enabled, can_speak, resolve_text  # المشكلة 4: import واحد هنا يكفي، لا يُكرَّر داخل الـ handlers

# المشكلة 3: timezone يُبنى مرة واحدة على مستوى الملف بدلاً من إعادة بنائه في كل دخول
_TZ = pytz.timezone("Asia/Riyadh")

# كاش التحقق من Captcha — على مستوى الوحدة لا على Class
_VERIFIED: dict = {}  # key: "{cid}:{uid}" → True

DEFAULT_WELCOME = (
    "لا تُسِئ اللفظ وإن ضَاق عليك الرَّد\n\n"
    "ɴᴀᴍᴇ ⌯ {الاسم}\n"
    "ᴜѕᴇʀɴᴀᴍᴇ ⌯ {اليوزر}\n"
    "𝖣𝖺𝗍𝖾 ⌯ {التاريخ}"
)

DEFAULT_RULES = (
    "📌 قوانين المجموعة:\n"
    "• ممنوع نشر الروابط\n"
    "• ممنوع التكلم أو نشر صور إباحية\n"
    "• ممنوع الإعادة التوجيه\n"
    "• ممنوع العنصرية بكل أنواعها\n"
    "• الرجاء احترام المدراء والأدمنية"
)

# rate limiting للترحيب — مرة واحدة كل 5 ثوانٍ لكل مجموعة لمنع FloodWait
_welcome_last: dict[int, float] = {}
_WELCOME_COOLDOWN = 5.0  # ثوانٍ
_WELCOME_LAST_MAX = 2000  # حد أقصى لمنع memory leak

# المشكلة 2: cache لصور البروفايل — {uid: (file_id_or_None, expires_at)}
_PHOTO_CACHE_TTL = 300  # 5 دقائق
_photo_cache: dict[int, tuple[str | None, float]] = {}


def _build_welcome(template: str, member, chat, rules_text: str) -> str:
    # المشكلة 3: استخدام _TZ الجاهز بدلاً من pytz.timezone(...) في كل استدعاء
    NOW      = datetime.now(_TZ)
    name     = member.first_name or "عضو"
    username = f"@{member.username}" if member.username else name
    title    = chat.title or ""
    clock    = NOW.strftime("%I:%M %p")
    date     = NOW.strftime("%d/%m/%Y")
    return (
        template
        .replace("{القوانين}", rules_text)
        .replace("{الاسم}",    name)
        .replace("{المجموعه}", title)
        .replace("{الوقت}",    clock)
        .replace("{التاريخ}",  date)
        .replace("{اليوزر}",   username)
    )


async def _get_profile_photo(c: Client, uid: int) -> str | None:
    """
    المشكلة 2: cache لصور البروفايل بـ TTL=5 دقائق.
    يتجنب استدعاء get_chat_photos لكل عضو يدخل من جديد.
    """
    entry = _photo_cache.get(uid)
    if entry and time.monotonic() < entry[1]:
        return entry[0]
    # Cache انتهى → اطلب من Telegram
    photo = None
    try:
        async for p in c.get_chat_photos(uid, limit=1):
            photo = p.file_id
            break
    except Exception:
        pass
    _photo_cache[uid] = (photo, time.monotonic() + _PHOTO_CACHE_TTL)
    return photo


# المشكلة 1: الدالة مُعرَّفة هنا على مستوى الملف مرة واحدة — لا داخل حلقة for
async def _kick_if_unverified(bot: Client, chat_id: int, user_id: int, msg_id: int):
    """تنتظر 60 ثانية ثم تطرد العضو إذا لم يتحقق."""
    await asyncio.sleep(60)
    if not _VERIFIED.get(f"{chat_id}:{user_id}"):
        try:
            await bot.ban_chat_member(chat_id, user_id)
            await bot.unban_chat_member(chat_id, user_id)
            await bot.delete_messages(chat_id, msg_id)
        except Exception:
            pass
    # تنظيف الكاش بعد انتهاء المهلة
    _VERIFIED.pop(f"{chat_id}:{user_id}", None)


# ─────────────────────────────────────────────────────────────────────────
# معالج ضبط الترحيب والقوانين (نصوص)
# ─────────────────────────────────────────────────────────────────────────

@Client.on_message(filters.group & filters.text, group=29)
async def welcome_settings_handler(c: Client, m: Message):
    if not m.from_user:
        return
    cid, uid = m.chat.id, m.from_user.id
    if not group_enabled(cid):
        return
    if not can_speak(uid, cid):
        return

    text = resolve_text(m.text, cid)
    k    = botkey()

    # إلغاء وضع الترحيب
    if text == "الغاء":
        if await ar.get(f"{cid}:setWelcome:{uid}:{DEV_ID}"):
            await ar.delete(f"{cid}:setWelcome:{uid}:{DEV_ID}")
            return await m.reply(f"{k} ابشر لغيت وضع الترحيب")
        if await ar.get(f"{cid}:setRules:{uid}:{DEV_ID}"):
            await ar.delete(f"{cid}:setRules:{uid}:{DEV_ID}")
            return await m.reply(f"{k} ابشر لغيت وضع القوانين")

    # استلام القوانين
    if await ar.get(f"{cid}:setRules:{uid}:{DEV_ID}") and is_mod(uid, cid):
        await ar.set(f"{cid}:CustomRules:{DEV_ID}", m.text.html)
        await ar.delete(f"{cid}:setRules:{uid}:{DEV_ID}")
        return await m.reply(f"{k} تم حطيتها")

    # استلام الترحيب
    if await ar.get(f"{cid}:setWelcome:{uid}:{DEV_ID}") and is_mod(uid, cid):
        await ar.set(f"{cid}:CustomWelcome:{DEV_ID}", m.text.html)
        await ar.delete(f"{cid}:setWelcome:{uid}:{DEV_ID}")
        return await m.reply(f"{k} تم وسوينا الترحيب ياعيني")

    # مسح القوانين
    if text == "مسح القوانين":
        if not is_mod(uid, cid):
            return await m.reply(f"{k} هذا الامر يخص ( المدير وفوق ) بس")
        await ar.delete(f"{cid}:CustomRules:{DEV_ID}")
        return await m.reply(f"{k} من عيوني مسحت القوانين")

    # وضع قوانين
    if text == "وضع قوانين":
        if not is_mod(uid, cid):
            return await m.reply(f"{k} هذا الامر يخص ( المدير وفوق ) بس")
        await ar.set(f"{cid}:setRules:{uid}:{DEV_ID}", 1)
        return await m.reply(f"{k} ارسل القوانين الحين")

    # القوانين (عرض)
    if text == "القوانين":
        rules = await ar.get(f"{cid}:CustomRules:{DEV_ID}") or DEFAULT_RULES
        return await m.reply(rules, disable_web_page_preview=True)

    # عرض الترحيب الحالي
    if text == "الترحيب":
        if not is_mod(uid, cid):
            return await m.reply(f"{k} هذا الامر يخص ( المدير وفوق ) بس")
        w = await ar.get(f"{cid}:CustomWelcome:{DEV_ID}") or DEFAULT_WELCOME
        return await m.reply(f"`{w}`")

    # مسح الترحيب
    if text == "مسح الترحيب":
        if not is_mod(uid, cid):
            return await m.reply(f"{k} هذا الامر يخص ( المدير وفوق ) بس")
        await ar.delete(f"{cid}:CustomWelcome:{DEV_ID}")
        return await m.reply(f"{k} مسحت الترحيب")

    # وضع / ضع الترحيب
    if text in ("وضع الترحيب", "ضع الترحيب"):
        if not is_mod(uid, cid):
            return await m.reply(f"{k} هذا الامر يخص ( المدير وفوق ) بس")
        await ar.set(f"{cid}:setWelcome:{uid}:{DEV_ID}", 1)
        return await m.reply(
            "⇜ تمام عيني\n"
            "⇜ ارسل رسالة الترحيب الحين\n\n"
            "⇜ ملاحظة تقدر تضيف دوال للترحيب مثلا:\n"
            "⇜ اظهار قوانين المجموعه  ⇠ {القوانين}\n"
            "⇜ اظهار اسم العضو ⇠ {الاسم}\n"
            "⇜ اظهار اليوزر العضو ⇠ {اليوزر}\n"
            "⇜ اظهار اسم المجموعه ⇠ {المجموعه}\n"
            "⇜ اظهار تاريخ دخول العضو ⇠ {التاريخ}\n"
            "⇜ اظهار وقت دخول العضو ⇠ {الوقت}\n☆"
        )

    # تعطيل / تفعيل الترحيب
    if text == "تعطيل الترحيب":
        if not is_mod(uid, cid):
            return await m.reply(f"{k} هذا الامر يخص ( المدير وفوق ) بس")
        await ar.set(f"{cid}:disableWelcome:{DEV_ID}", 1)
        return await m.reply(f"{k} تم تعطيل الترحيب")

    if text == "تفعيل الترحيب":
        if not is_mod(uid, cid):
            return await m.reply(f"{k} هذا الامر يخص ( المدير وفوق ) بس")
        await ar.delete(f"{cid}:disableWelcome:{DEV_ID}")
        return await m.reply(f"{k} تم تفعيل الترحيب")


# ─────────────────────────────────────────────────────────────────────────
# إرسال رسالة الترحيب عند دخول عضو جديد
# ─────────────────────────────────────────────────────────────────────────

@Client.on_message(filters.new_chat_members, group=4)
async def welcome_new_member(c: Client, m: Message):
    cid = m.chat.id
    if not group_enabled(cid):
        return
    _w_keys = [
        f"{cid}:disableWelcome:{DEV_ID}",
        f"{DEV_ID}:BotChannel",
        f"{cid}:CustomWelcome:{DEV_ID}",
        f"{cid}:CustomRules:{DEV_ID}",
        f"{cid}:enableVerify:{DEV_ID}",
    ]
    _w_vals = await ar.mget(_w_keys)
    _disable_welcome, _ch_raw, _template_raw, _rules_raw, _enable_verify = _w_vals
    if _disable_welcome:
        return
    k        = botkey()
    ch       = _ch_raw or "yqyqy66"
    template = _template_raw or DEFAULT_WELCOME
    rules    = _rules_raw or DEFAULT_RULES

    for member in m.new_chat_members:
        if member.is_bot:
            continue
        if member.id == DEV_ID_INT:
            continue

        # التحقق من الفيريفاي
        if _enable_verify and not is_pre(member.id, cid):
            try:
                await c.restrict_chat_member(
                    cid, member.id,
                    permissions=ChatPermissions(can_send_messages=False),
                )
            except Exception:
                pass
            kb = InlineKeyboardMarkup([[InlineKeyboardButton(
                "✅ أنا لست روبوت — اضغط هنا",
                callback_data=f"verify:{cid}:{member.id}",
            )]])
            pending_msg = await m.reply(
                f"{k} مرحباً {member.mention}\n"
                "اضغط الزر خلال 60 ثانية وإلا سيتم طردك 👇",
                reply_markup=kb,
            )
            # المشكلة 1: استدعاء الدالة المعرَّفة مسبقاً على مستوى الملف — لا تعريف داخل الحلقة
            asyncio.get_running_loop().create_task(
                _kick_if_unverified(c, cid, member.id, pending_msg.id)
            )
            continue

        text = _build_welcome(template, member, m.chat, rules)

        # rate limiting — تجنب FloodWait عند دخول عدة أشخاص معاً
        now  = time.monotonic()
        last = _welcome_last.get(cid, 0)
        if now - last < _WELCOME_COOLDOWN:
            continue
        if len(_welcome_last) > _WELCOME_LAST_MAX:
            oldest = sorted(_welcome_last, key=_welcome_last.get)[: len(_welcome_last) // 2]
            for _wk in oldest:
                _welcome_last.pop(_wk, None)
        _welcome_last[cid] = time.monotonic()

        # المشكلة 2: صورة البروفايل من cache بدلاً من get_chat_photos لكل عضو
        photo = None
        if not await ar.get(f"{cid}:disableWelcomep:{DEV_ID}") and member.photo:
            photo = await _get_profile_photo(c, member.id)

        try:
            if photo:
                await m.reply_photo(photo, caption=text)
            else:
                await m.reply(text, disable_web_page_preview=True)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────
# Captcha: زر التحقق callback
# ─────────────────────────────────────────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^verify:"))
async def captcha_verify_callback(c: Client, cb: CallbackQuery):
    parts  = cb.data.split(":")
    cid_cb = int(parts[1])
    uid_cb = int(parts[2])

    if cb.from_user.id != uid_cb:
        return await cb.answer("هذا الزر مو لك 😅", show_alert=True)

    try:
        await c.restrict_chat_member(cid_cb, uid_cb, ChatPermissions(
            can_send_messages=True,
            can_send_media_messages=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
        ))
    except Exception:
        pass

    _VERIFIED[f"{cid_cb}:{uid_cb}"] = True
    try:
        await cb.message.delete()
    except Exception:
        pass
    await cb.answer("✅ تم التحقق، أهلاً بك!", show_alert=True)


# ─────────────────────────────────────────────────────────────────────────
# أوامر تفعيل / تعطيل الفيريفاي (Captcha)
# ─────────────────────────────────────────────────────────────────────────

@Client.on_message(filters.group & filters.text, group=41)
async def captcha_settings_handler(c: Client, m: Message):
    if not m.from_user:
        return
    cid, uid = m.chat.id, m.from_user.id
    # المشكلة 4: الـ import محذوف من هنا — موجود بالفعل أعلى الملف
    if not group_enabled(cid):
        return
    if not can_speak(uid, cid):
        return

    text = resolve_text(m.text, cid)
    k    = botkey()

    if text == "تفعيل الفيريفاي":
        if not is_mod(uid, cid):
            return await m.reply(f"{k} هذا الامر يخص ( المدير وفوق ) بس")
        await ar.set(f"{cid}:enableVerify:{DEV_ID}", 1)
        return await m.reply(f"{k} تم تفعيل نظام التحقق (Captcha) ✅")

    if text == "تعطيل الفيريفاي":
        if not is_mod(uid, cid):
            return await m.reply(f"{k} هذا الامر يخص ( المدير وفوق ) بس")
        await ar.delete(f"{cid}:enableVerify:{DEV_ID}")
        return await m.reply(f"{k} تم تعطيل نظام التحقق (Captcha) ❌")
