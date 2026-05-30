"""
ملف guards_locks.py - نظام الأقفال والحماية
الأوامر المتاحة:
  تفعيل الحماية / تعطيل الحماية     → حزمة حماية شاملة (مالك+)
  قفل الكل / فتح الكل               → قفل/فتح جميع الأنواع (مدير+)
  قفل/فتح الدردشة (الشات)           → منع الكتابة للكل (مدير+)
  قفل/فتح التعديل                   → منع تعديل الرسائل (مدير+)
  قفل/فتح تعديل الميديا             → منع تعديل الوسائط (مدير+)
  قفل/فتح الفويسات (البصمات)        → منع رسائل الصوت (مدير+)
  قفل/فتح الفيديو (الفيديوهات)       → منع الفيديو (مدير+)
  قفل/فتح الاشعارات                 → حذف إشعارات الخدمة (مدير+)
  قفل/فتح الصور                     → منع الصور (مدير+)
  قفل/فتح الملصقات                  → منع الستيكرات (مدير+)
  قفل/فتح الفارسيه                  → منع الكتابة الفارسية (مدير+)
  قفل/فتح الملفات                   → منع الملفات (مدير+)
  قفل/فتح المتحركات (المتحركه)       → منع الـ GIF (مدير+)
  قفل/فتح الروابط                   → منع الروابط (مدير+)
  قفل/فتح الهشتاق (الهاشتاق)         → منع الهاشتاقات (مدير+)
  قفل/فتح البوتات                   → منع دخول البوتات (مدير+)
  قفل/فتح اليوزرات (المنشن)          → منع المنشنات (مدير+)
  قفل/فتح الكفر (الشيعه/الشيعة)      → منع كلمات الكفر (مدير+)
  قفل/فتح الإباحي (الاباحي)          → فلتر NSFW (مدير+)
  قفل/فتح الكلام الكثير (الكلايش)    → منع الرسائل الطويلة +150 حرف (مدير+)
  قفل/فتح التكرار                   → منع التكرار السريع (مدير+)
  قفل/فتح التوجيه                   → منع التوجيه (مدير+)
  قفل/فتح الانلاين                  → منع الرسائل المضمّنة (مدير+)
  قفل/فتح السب                      → منع الكلمات البذيئة (مدير+)
  قفل/فتح الاضافه (الجهات)           → منع إضافة جهات الاتصال (مدير+)
  قفل/فتح دخول البوتات (الوهمي/الايراني) → حظر البوتات فور دخولها (مدير+)
  قفل/فتح الصوت                     → منع رسائل الصوت (مدير+)
  قفل/فتح القنوات                   → منع رسائل القنوات (مدير+)
  قفل/فتح الدخول                    → طرد من يدخل (مدير+)
  تعطيل/تفعيل التحذير               → إيقاف/تشغيل رسائل التحذير (مدير+)
  منع (رد على ميديا)                → منع ملف بعينه (مدير+)
  الغاء منع (رد على ميديا)          → إلغاء منع ملف (مدير+)
  منع (رد على نص)                   → منع كلمة بعينها (مدير+)
  قائمة المنع / مسح قائمة المنع     → إدارة قائمة المنع
"""

import re
import time

from pyrogram import Client, filters
from pyrogram.errors import FloodWait
from pyrogram.types import Message

from config import r, DEV_ID, botkey, cached_smembers, ar
from helpers.ranks import is_admin, is_mod, is_owner, is_gowner, is_dev, is_pre, rank_cache_invalidate
from helpers.utils import group_enabled, resolve_text, utils_cache_invalidate

# ────────────────────────────────────────────────────────────
# cache مفاتيح الأقفال في الذاكرة — TTL 8 ثوانٍ
# يمنع 27 طلب Redis لكل رسالة واردة
# ────────────────────────────────────────────────────────────
_LOCKS_CACHE: dict[int, tuple[list, float]] = {}
_LOCKS_TTL = 8  # ثوانٍ

def _locks_cache_get(cid: int) -> list | None:
    entry = _LOCKS_CACHE.get(cid)
    if entry and time.monotonic() - entry[1] < _LOCKS_TTL:
        return entry[0]
    return None

def _locks_cache_set(cid: int, vals: list) -> None:
    if len(_LOCKS_CACHE) >= 300:
        oldest = min(_LOCKS_CACHE, key=lambda k: _LOCKS_CACHE[k][1])
        _LOCKS_CACHE.pop(oldest, None)
    _LOCKS_CACHE[cid] = (vals, time.monotonic())

def _locks_cache_invalidate(cid: int) -> None:
    """استدعِها بعد أي تغيير في إعدادات القفل لهذه المجموعة"""
    _LOCKS_CACHE.pop(cid, None)

# ────────────────────────────────────────────────────────────
# قوائم الكلمات المحظورة
# ────────────────────────────────────────────────────────────

LIST_SUB = frozenset([
    "كس", "كسمك", "كسختك", "عير", "كسخالتك", "خرا بالله", "عير بالله",
    "كسخواتكم", "كحاب", "مناويج", "كحبه", "ابن الكحبه", "فرخ", "فروخ",
    "طيزك", "طيزختك", "يا ابن الخول", "المتناك", "شرموط", "شرموطه",
    "ابن الشرموطه", "ابن الخول", "ابن العرص", "منايك", "متناك",
    "ابن المتناكه", "زبك", "عرص", "زبي", "خول", "لبوه", "لباوي",
    "ابن اللبوه", "منيوك", "كسمكك", "متناكه", "يا عرص", "يا خول",
    "قحبه", "القحبه", "شراميط", "العلق", "العلوق", "العلقه",
])

# كلمات الكفر والشتائم الدينية
LIST_KFR = frozenset([
    "يلعن دينك", "يلعن ربك", "العن الله", "كفر بالله", "اكفر بالله",
    "العن دينك", "يلعن الدين", "لعنة الله على الاسلام", "اكفر",
    "الله وسخ", "ربي وسخ", "الاسلام وسخ", "الدين وسخ",
    "يلعن ابو الاسلام", "يلعن ابو الدين", "شيعي", "رافضي", "صفوي",
    "ناصبي", "يا رافضي", "يا شيعي", "يا صفوي",
])

# كلمات إباحية / NSFW
LIST_NSFW = frozenset([
    "سكس", "بورن", "porn", "sex", "xxx", "نيك", "ناكه", "مناكه",
    "nude", "naked", "نودز", "اباحي", "إباحي", "بورنو", "هنتاي",
    "hentai", "xnxx", "xvideos", "pornhub", "onlyfans",
])

# ────────────────────────────────────────────────────────────
# مساعدات
# ────────────────────────────────────────────────────────────

def _find_urls(text: str) -> list:
    """يجد الروابط في النص"""
    pattern = r'(https?://[^\s]+|t\.me/[^\s]+|@[A-Za-z0-9_]{5,})'
    return re.findall(pattern, text)


def _k() -> str:
    return botkey()


async def _safe_delete(m) -> bool:
    """حذف آمن مع معالجة FloodWait"""
    import asyncio
    try:
        await m.delete()
        return True
    except FloodWait as fw:
        await asyncio.sleep(fw.value)
        try:
            await m.delete()
            return True
        except Exception:
            return False
    except Exception:
        return False


def _warn_msg(mention: str, key: str, reason: str) -> str:
    return f"「 {mention} 」\n{key} ممنوع {reason}\n☆"


async def _cooldown_warn(uid: int, cid: int) -> bool:
    """يمنع إرسال أكثر من تحذير في 60 ثانية للمستخدم — SET NX ذري (طلب واحد بدلاً من 2)"""
    key = f"{DEV_ID}:inWARN:{uid}{cid}"
    # SET NX EX: يُعيد True إذا نجح الضبط (أول مرة) → لا يوجد cooldown
    # يُعيد None إذا كان المفتاح موجوداً → cooldown نشط
    return await ar.set(key, 1, nx=True, ex=60) is None


# ────────────────────────────────────────────────────────────
# معالج القفل الرئيسي - async بدل Thread
# ────────────────────────────────────────────────────────────

@Client.on_message(filters.group, group=27)
async def guard_handler(c: Client, m: Message):
    await _guard_sync(c, m)


@Client.on_edited_message(filters.group, group=27)
async def guard_edit_handler(c: Client, m: Message):
    await _guard_edit_sync(c, m)


async def _guard_edit_sync(c: Client, m: Message):
    """معالجة الرسائل المعدّلة"""
    if not group_enabled(m.chat.id):
        return

    k = _k()

    if m.sender_chat:
        uid = m.sender_chat.id
        mention = m.sender_chat.title
    elif m.from_user:
        uid = m.from_user.id
        mention = m.from_user.mention
    else:
        return

    # جلب إعدادات التعديل مرة واحدة من Redis
    edit_keys = [
        f"{m.chat.id}:lockEdit:{DEV_ID}",
        f"{m.chat.id}:lockEditM:{DEV_ID}",
        f"{m.chat.id}:disableWarn:{DEV_ID}",
    ]
    lock_edit, lock_edit_m, disable_warn = await ar.mget(edit_keys)

    # قفل التعديل النصي
    if lock_edit and m.text and not is_admin(uid, m.chat.id):
        await _safe_delete(m)
        if not disable_warn and not await _cooldown_warn(uid, m.chat.id):
            await m.reply(_warn_msg(mention, k, "التعديل"), disable_web_page_preview=True)

    # قفل تعديل الميديا
    if lock_edit_m and m.media and not is_admin(uid, m.chat.id):
        await _safe_delete(m)
        if not disable_warn and not await _cooldown_warn(uid, m.chat.id):
            await m.reply(_warn_msg(mention, k, "تعديل الميديا"), disable_web_page_preview=True)


async def _guard_sync(c: Client, m: Message):
    """المعالج الرئيسي لجميع الأقفال - يجلب كل مفاتيح Redis دفعة واحدة"""
    if not group_enabled(m.chat.id):
        return

    k = _k()
    cid = m.chat.id

    if m.sender_chat:
        uid = m.sender_chat.id
        mention = m.sender_chat.title
    elif m.from_user:
        uid = m.from_user.id
        mention = m.from_user.mention
    else:
        return

    # ── جلب مفاتيح الأقفال الخاصة بالمجموعة من cache أو Redis ──
    # مفاتيح uid (2,3) لا تُخزَّن في الـ cache لأنها تختلف بين المستخدمين
    lk = _locks_cache_get(cid)
    if lk is None:
        group_keys = [
            f"{cid}:lockNot:{DEV_ID}",         # 0
            f"{cid}:lockaddContacts:{DEV_ID}",  # 1
            None,                               # 2 — placeholder لـ uid:mute
            None,                               # 3 — placeholder لـ uid:mute global
            f"{cid}:mute:{DEV_ID}",             # 4
            f"{cid}:lockBots:{DEV_ID}",         # 5
            f"{cid}:lockJoin:{DEV_ID}",         # 6
            f"{cid}:lockChannels:{DEV_ID}",     # 7
            f"{cid}:lockSpam:{DEV_ID}",         # 8
            f"{cid}:lockInline:{DEV_ID}",       # 9
            f"{cid}:lockForward:{DEV_ID}",      # 10
            f"{cid}:lockAudios:{DEV_ID}",       # 11
            f"{cid}:lockVideo:{DEV_ID}",        # 12
            f"{cid}:lockPhoto:{DEV_ID}",        # 13
            f"{cid}:lockStickers:{DEV_ID}",     # 14
            f"{cid}:lockAnimations:{DEV_ID}",   # 15
            f"{cid}:lockFiles:{DEV_ID}",        # 16
            f"{cid}:lockPersian:{DEV_ID}",      # 17
            f"{cid}:lockUrls:{DEV_ID}",         # 18
            f"{cid}:lockHashtags:{DEV_ID}",     # 19
            f"{cid}:lockMessages:{DEV_ID}",     # 20
            f"{cid}:lockVoice:{DEV_ID}",        # 21
            f"{cid}:lockTags:{DEV_ID}",         # 22
            f"{cid}:lockSHTM:{DEV_ID}",         # 23
            f"{cid}:disableWarn:{DEV_ID}",      # 24
            f"{cid}:lockKFR:{DEV_ID}",          # 25
            f"{cid}:lockNSFW:{DEV_ID}",         # 26
        ]
        cacheable = [k for k in group_keys if k is not None]
        raw = await ar.mget(cacheable)
        # أعِد بناء القائمة مع None في موضعَي uid
        val_iter = iter(raw)
        lk = [None] * 27
        for i, key in enumerate(group_keys):
            lk[i] = next(val_iter) if key is not None else None
        _locks_cache_set(cid, lk)

    # مفاتيح uid تُجلب دائماً طازجة (لا تُخزَّن في الـ cache)
    uid_mute_local, uid_mute_global = await ar.mget([
        f"{uid}:mute:{cid}:{DEV_ID}",
        f"{uid}:mute:{DEV_ID}",
    ])
    lk = list(lk)
    lk[2] = uid_mute_local
    lk[3] = uid_mute_global
    # lk[i] = القيمة أو None

    # حذف إشعارات الخدمة
    if lk[0] and m.service:
        await _safe_delete(m)
        return

    # منع إضافة جهات الاتصال
    if lk[1] and m.from_user and m.new_chat_members:
        if not is_admin(m.from_user.id, cid):
            for mem in m.new_chat_members:
                if mem.id != m.from_user.id:
                    await m.chat.ban_member(mem.id)
                    await _safe_delete(m)
                    if not lk[24]:
                        await m.reply(_warn_msg(m.from_user.mention, k, "تضيف حد هنا"), disable_web_page_preview=True)
                    return

    # فحص مكتوم / صمت عام
    if lk[2] or lk[3]:
        return
    if lk[4] and not is_admin(uid, cid):
        await _safe_delete(m)
        return

    # ── نحسب رتبة المستخدم مرة واحدة فقط — تُستخدم في كل الفحوصات اللاحقة ──
    # is_pre يشمل is_admin، لذا استدعاء واحد يكفي لكلاهما
    _uid_is_pre   = is_pre(uid, cid)    # مميز وفوق → يتخطى كل الأقفال
    _uid_is_admin = _uid_is_pre or is_admin(uid, cid)  # نتجنب استدعاء ثانٍ إذا كان pre

    # المميز وفوق يتخطى كل الأقفال
    if _uid_is_pre:
        return

    # فحص الملفات المحظورة بعينها
    if m.media:
        file_id = None
        if m.sticker:     file_id = m.sticker.file_id
        elif m.animation: file_id = m.animation.file_id
        elif m.photo:     file_id = m.photo.file_id
        elif m.video:     file_id = m.video.file_id
        elif m.voice:     file_id = m.voice.file_id
        elif m.audio:     file_id = m.audio.file_id
        elif m.document:  file_id = m.document.file_id
        if file_id:
            idd = file_id[-6:]
            if await ar.get(f"{idd}:NotAllow:{cid}:{DEV_ID}"):
                if not _uid_is_admin:
                    await _safe_delete(m)
                    return

    # فحص الكلمات المحظورة في النص
    if m.text:
        banned_words = cached_smembers(f"{cid}:NotAllowedListText:{DEV_ID}")
        if banned_words and not _uid_is_admin:
            for word in banned_words:
                if word in m.text:
                    await _safe_delete(m)
                    return

    # حظر دخول البوتات
    if lk[5] and m.new_chat_members:
        for mem in m.new_chat_members:
            if mem.is_bot:
                await m.chat.ban_member(mem.id)
        return

    # منع دخول الكل
    if lk[6] and m.new_chat_members:
        for mem in m.new_chat_members:
            if not is_admin(mem.id, cid):
                await m.chat.ban_member(mem.id)
                await m.chat.unban_member(mem.id)
        return

    # منع رسائل القنوات
    if lk[7] and m.sender_chat:
        if m.sender_chat.id != cid:
            await m.chat.ban_member(m.sender_chat.id)
            return

    # منع التكرار السريع
    if lk[8] and m.from_user:
        spam_key = f"{uid}:in_spam:{cid}:{DEV_ID}"
        count = await ar.get(spam_key)
        if not count:
            await ar.set(spam_key, 1, ex=10)
        else:
            count = int(count)
            if count >= 10:
                await ar.set(f"{uid}:mute:{cid}:{DEV_ID}", 1)
                await ar.sadd(f"{cid}:listMUTE:{DEV_ID}", uid)
                await ar.delete(spam_key)
                utils_cache_invalidate(f"{uid}:mute:{cid}:{DEV_ID}")
                rank_cache_invalidate(uid, cid)
                await m.reply(f"「 {mention} 」\n{k} كتمتك يالبثر عشان تتعلم تكرر\n☆")
                return
            else:
                await ar.set(spam_key, count + 1, ex=10)

    # قفل الانلاين (رسائل مضمّنة)
    if lk[9] and m.via_bot:
        await _safe_delete(m)
        if not lk[24] and not await _cooldown_warn(uid, cid):
            await m.reply(_warn_msg(mention, k, "ترسل انلاين"), disable_web_page_preview=True)
        return

    # قفل التوجيه
    if lk[10] and m.forward_date:
        await _safe_delete(m)
        if not lk[24] and not await _cooldown_warn(uid, cid):
            await m.reply(_warn_msg(mention, k, "ترسل توجيه"), disable_web_page_preview=True)
        return

    # قفل الصوت (Audio)
    if lk[11] and m.audio:
        await _safe_delete(m)
        if not lk[24] and not await _cooldown_warn(uid, cid):
            await m.reply(_warn_msg(mention, k, "ترسل صوت"), disable_web_page_preview=True)
        return

    # قفل الفيديو
    if lk[12] and m.video:
        await _safe_delete(m)
        if not lk[24] and not await _cooldown_warn(uid, cid):
            await m.reply(_warn_msg(mention, k, "ترسل فيديوهات"), disable_web_page_preview=True)
        return

    # قفل الصور
    if lk[13] and m.photo:
        await _safe_delete(m)
        if not lk[24] and not await _cooldown_warn(uid, cid):
            await m.reply(_warn_msg(mention, k, "ترسل صور"), disable_web_page_preview=True)
        return

    # قفل الملصقات
    if lk[14] and m.sticker:
        await _safe_delete(m)
        if not lk[24] and not await _cooldown_warn(uid, cid):
            await m.reply(_warn_msg(mention, k, "ترسل ملصقات"), disable_web_page_preview=True)
        return

    # قفل المتحركات GIF
    if lk[15] and m.animation:
        await _safe_delete(m)
        if not lk[24] and not await _cooldown_warn(uid, cid):
            await m.reply(_warn_msg(mention, k, "ترسل متحركات"), disable_web_page_preview=True)
        return

    # قفل الملفات
    if lk[16] and m.document:
        await _safe_delete(m)
        if not lk[24] and not await _cooldown_warn(uid, cid):
            await m.reply(_warn_msg(mention, k, "ترسل ملفات"), disable_web_page_preview=True)
        return

    # قفل الفارسي
    # أحرف فارسية حصرية لا توجد في لوحات عربية — ی و ک شائعتان خليجياً
    PERSIAN_CHARS = ("پ", "گ", "ژ", "چ")
    if lk[17]:
        txt = m.text or m.caption or ""
        if any(c in txt for c in PERSIAN_CHARS):
            await _safe_delete(m)
            if not lk[24]:
                await m.reply(_warn_msg(mention, k, "ترسل فارسي"), disable_web_page_preview=True)
            return

    # قفل الروابط
    if lk[18] and m.text:
        if len(_find_urls(m.text)) > 0:
            await _safe_delete(m)
            if not lk[24] and not await _cooldown_warn(uid, cid):
                await m.reply(_warn_msg(mention, k, "ترسل روابط"), disable_web_page_preview=True)
            return

    # قفل الهاشتاق
    if lk[19] and m.text:
        if len(re.findall(r"#(\w+)", m.text)) > 0:
            await _safe_delete(m)
            if not lk[24] and not await _cooldown_warn(uid, cid):
                await m.reply(_warn_msg(mention, k, "ترسل هاشتاق"), disable_web_page_preview=True)
            return

    # قفل الكلام الكثير (+150 حرف)
    if lk[20] and m.text and len(m.text) > 150:
        await _safe_delete(m)
        if not lk[24] and not await _cooldown_warn(uid, cid):
            await m.reply(_warn_msg(mention, k, "ترسل كلام كثير"), disable_web_page_preview=True)
        return

    # قفل الفويس (Voice)
    if lk[21] and m.voice:
        await _safe_delete(m)
        if not lk[24] and not await _cooldown_warn(uid, cid):
            await m.reply(_warn_msg(mention, k, "ترسل فويس"), disable_web_page_preview=True)
        return

    # قفل المنشنات
    if lk[22] and m.text:
        if re.search(r"@[A-Za-z0-9_]{5,}", m.text):
            await _safe_delete(m)
            if not lk[24] and not await _cooldown_warn(uid, cid):
                await m.reply(_warn_msg(mention, k, "ترسل منشنات"), disable_web_page_preview=True)
            return

    # قفل السب
    if lk[23]:
        txt = m.caption or m.text or ""
        for word in LIST_SUB:
            if word in txt:
                await _safe_delete(m)
                if not lk[24] and not await _cooldown_warn(uid, cid):
                    await m.reply(_warn_msg(mention, k, "السب هنا"), disable_web_page_preview=True)
                return

    # قفل الكفر
    if lk[25]:
        txt = (m.caption or m.text or "").lower()
        for word in LIST_KFR:
            if word in txt:
                await _safe_delete(m)
                if not lk[24] and not await _cooldown_warn(uid, cid):
                    await m.reply(_warn_msg(mention, k, "الكلام هذا"), disable_web_page_preview=True)
                return

    # قفل الإباحي (NSFW)
    if lk[26]:
        txt = (m.caption or m.text or "").lower()
        for word in LIST_NSFW:
            if word in txt:
                await _safe_delete(m)
                if not lk[24] and not await _cooldown_warn(uid, cid):
                    await m.reply(_warn_msg(mention, k, "المحتوى الإباحي"), disable_web_page_preview=True)
                return


# ────────────────────────────────────────────────────────────
# معالج الأوامر (group=25)
# ────────────────────────────────────────────────────────────

@Client.on_message(filters.group & filters.text, group=28)
async def lock_commands_handler(c: Client, m: Message):
    if not m.from_user:
        return
    if not group_enabled(m.chat.id):
        return

    text = resolve_text(m.text, m.chat.id)
    k = _k()
    uid = m.from_user.id
    cid = m.chat.id
    mention = m.from_user.mention

    async def reply(msg):
        return await m.reply(msg, disable_web_page_preview=True)

    async def need_mod():
        if not is_mod(uid, cid):
            await m.reply(f"{k} هذا الأمر يخص ( المدير وفوق ) بس")
            return True
        return False

    async def need_owner():
        if not is_owner(uid, cid):
            await m.reply(f"{k} هذا الأمر يخص ( المالك وفوق ) بس")
            return True
        return False

    # ──── قفل الكل ────
    if text == "قفل الكل":
        if await need_mod(): return
        ALL_LOCKS = [
            "mute", "lockEdit", "lockEditM", "lockVoice", "lockVideo",
            "lockNot", "lockPhoto", "lockPersian", "lockStickers", "lockFiles",
            "lockAnimations", "lockUrls", "lockHashtags", "lockBots", "lockTags",
            "lockMessages", "lockSpam", "lockForward", "lockSHTM",
            "lockaddContacts", "lockAudios", "lockChannels", "lockJoin",
            "lockInline", "lockNSFW",
        ]
        keys = [f"{cid}:{lk}:{DEV_ID}" for lk in ALL_LOCKS]
        vals = await ar.mget(keys)
        if all(vals):
            return await reply(f"{k} من 「 {mention} 」\n{k} كل شي مقفل يالطيب!\n☆")
        async with ar.pipeline(transaction=False) as pipe:
            for key in keys:
                pipe.set(key, 1)
            await pipe.execute()
        _locks_cache_invalidate(cid)
        return await reply(f"{k} من 「 {mention} 」\n{k} ابشر قفلت كل شي\n☆")

    # ──── فتح الكل ────
    if text == "فتح الكل":
        if await need_mod(): return
        ALL_LOCKS = [
            "mute", "lockEdit", "lockEditM", "lockVoice", "lockVideo",
            "lockNot", "lockPhoto", "lockPersian", "lockStickers", "lockFiles",
            "lockAnimations", "lockUrls", "lockHashtags", "lockBots", "lockTags",
            "lockMessages", "lockSpam", "lockForward", "lockSHTM",
            "lockaddContacts", "lockAudios", "lockChannels", "lockJoin",
            "lockInline", "lockNSFW", "lockKFR",
        ]
        keys = [f"{cid}:{lk}:{DEV_ID}" for lk in ALL_LOCKS]
        vals = await ar.mget(keys)
        if not any(vals):
            return await reply(f"{k} من 「 {mention} 」\n{k} كل شي مفتوح يالطيب!\n☆")
        async with ar.pipeline(transaction=False) as pipe:
            for key in keys:
                pipe.delete(key)
            await pipe.execute()
        _locks_cache_invalidate(cid)
        return await reply(f"{k} من 「 {mention} 」\n{k} ابشر فتحت كل شي\n☆")

    # ──── تفعيل الحماية ────
    PROT_LOCKS = [
        "lockEditM", "lockVoice", "lockVideo", "lockPhoto", "lockPersian",
        "lockStickers", "lockFiles", "lockAnimations", "lockUrls", "lockTags",
        "lockMessages", "lockSpam", "lockForward", "lockSHTM", "lockAudios",
        "lockChannels", "lockNSFW",
    ]
    if text in ("تفعيل الحماية", "تفعيل الحمايه"):
        if await need_owner(): return
        keys = [f"{cid}:{lk}:{DEV_ID}" for lk in PROT_LOCKS]
        vals = await ar.mget(keys)
        if all(vals):
            return await reply(f"{k} من 「 {mention} 」\n{k} الحماية مفعلة من قبل\n☆")
        await ar.delete(f"{cid}:disableWarn:{DEV_ID}")
        async with ar.pipeline(transaction=False) as pipe:
            for key in keys:
                pipe.set(key, 1)
            await pipe.execute()
        _locks_cache_invalidate(cid)
        return await reply(f"{k} من 「 {mention} 」\n{k} ابشر فعّلت الحماية\n☆")

    # ──── تعطيل الحماية ────
    if text in ("تعطيل الحماية", "تعطيل الحمايه"):
        if await need_owner(): return
        keys = [f"{cid}:{lk}:{DEV_ID}" for lk in PROT_LOCKS]
        vals = await ar.mget(keys)
        if not any(vals):
            return await reply(f"{k} من 「 {mention} 」\n{k} الحماية معطلة من قبل\n☆")
        async with ar.pipeline(transaction=False) as pipe:
            for key in keys:
                pipe.delete(key)
            await pipe.execute()
        _locks_cache_invalidate(cid)
        return await reply(f"{k} من 「 {mention} 」\n{k} ابشر عطّلت الحماية\n☆")

    # ──── أوامر قفل/فتح فردية ────
    SINGLE_LOCKS = {
        "قفل الدردشة":      ("mute",              ""),
        "قفل الدردشه":      ("mute",              ""),
        "قفل الشات":        ("mute",              ""),
        "فتح الدردشة":      ("mute",              ""),
        "فتح الدردشه":      ("mute",              ""),
        "فتح الشات":        ("mute",              ""),
        "قفل التعديل":      ("lockEdit",          ""),
        "فتح التعديل":      ("lockEdit",          ""),
        "قفل تعديل الميديا":("lockEditM",         ""),
        "فتح تعديل الميديا":("lockEditM",         ""),
        "قفل الفويسات":     ("lockVoice",         ""),
        "قفل البصمات":      ("lockVoice",         ""),
        "فتح الفويسات":     ("lockVoice",         ""),
        "فتح البصمات":      ("lockVoice",         ""),
        "قفل الفيديو":      ("lockVideo",         ""),
        "قفل الفيديوهات":   ("lockVideo",         ""),
        "فتح الفيديو":      ("lockVideo",         ""),
        "فتح الفيديوهات":   ("lockVideo",         ""),
        "قفل الاشعارات":    ("lockNot",           ""),
        "فتح الاشعارات":    ("lockNot",           ""),
        "قفل الصور":        ("lockPhoto",         ""),
        "فتح الصور":        ("lockPhoto",         ""),
        "قفل الملصقات":     ("lockStickers",      ""),
        "فتح الملصقات":     ("lockStickers",      ""),
        "قفل الفارسيه":     ("lockPersian",       ""),
        "فتح الفارسيه":     ("lockPersian",       ""),
        "قفل الملفات":      ("lockFiles",         ""),
        "فتح الملفات":      ("lockFiles",         ""),
        "قفل المتحركات":    ("lockAnimations",    ""),
        "قفل المتحركه":     ("lockAnimations",    ""),
        "فتح المتحركات":    ("lockAnimations",    ""),
        "فتح المتحركه":     ("lockAnimations",    ""),
        "قفل الروابط":      ("lockUrls",          ""),
        "فتح الروابط":      ("lockUrls",          ""),
        "قفل الهشتاق":      ("lockHashtags",      ""),
        "قفل الهاشتاق":     ("lockHashtags",      ""),
        "فتح الهشتاق":      ("lockHashtags",      ""),
        "فتح الهاشتاق":     ("lockHashtags",      ""),
        "قفل البوتات":      ("lockBots",          ""),
        "فتح البوتات":      ("lockBots",          ""),
        "قفل اليوزرات":     ("lockTags",          ""),
        "قفل المنشن":       ("lockTags",          ""),
        "فتح اليوزرات":     ("lockTags",          ""),
        "فتح المنشن":       ("lockTags",          ""),
        "قفل الكفر":        ("lockKFR",           ""),
        "قفل الشيعه":       ("lockKFR",           ""),
        "قفل الشيعة":       ("lockKFR",           ""),
        "فتح الكفر":        ("lockKFR",           ""),
        "فتح الشيعه":       ("lockKFR",           ""),
        "فتح الشيعة":       ("lockKFR",           ""),
        "قفل الإباحي":      ("lockNSFW",          ""),
        "قفل الاباحي":      ("lockNSFW",          ""),
        "فتح الإباحي":      ("lockNSFW",          ""),
        "فتح الاباحي":      ("lockNSFW",          ""),
        "قفل الكلام الكثير": ("lockMessages",     ""),
        "قفل الكلايش":      ("lockMessages",      ""),
        "فتح الكلام الكثير": ("lockMessages",     ""),
        "فتح الكلايش":      ("lockMessages",      ""),
        "قفل التكرار":      ("lockSpam",          ""),
        "فتح التكرار":      ("lockSpam",          ""),
        "قفل التوجيه":      ("lockForward",       ""),
        "فتح التوجيه":      ("lockForward",       ""),
        "قفل الانلاين":     ("lockInline",        ""),
        "فتح الانلاين":     ("lockInline",        ""),
        "قفل السب":         ("lockSHTM",          ""),
        "فتح السب":         ("lockSHTM",          ""),
        "قفل الاضافه":      ("lockaddContacts",   ""),
        "قفل الاضافة":      ("lockaddContacts",   ""),
        "قفل الجهات":       ("lockaddContacts",   ""),
        "فتح الاضافه":      ("lockaddContacts",   ""),
        "فتح الاضافة":      ("lockaddContacts",   ""),
        "فتح الجهات":       ("lockaddContacts",   ""),
        "قفل دخول البوتات": ("lockBots",          ""),
        "قفل الوهمي":       ("lockBots",          ""),
        "قفل الايراني":     ("lockBots",          ""),
        "فتح دخول البوتات": ("lockBots",          ""),
        "فتح الوهمي":       ("lockBots",          ""),
        "فتح الايراني":     ("lockBots",          ""),
        "قفل الصوت":        ("lockVoice",         ""),
        "فتح الصوت":        ("lockVoice",         ""),
        "قفل القنوات":      ("lockChannels",      ""),
        "فتح القنوات":      ("lockChannels",      ""),
        "قفل الدخول":       ("lockJoin",          ""),
        "فتح الدخول":       ("lockJoin",          ""),
    }

    if text in SINGLE_LOCKS:
        if await need_mod(): return
        lock_key, _ = SINGLE_LOCKS[text]
        redis_key = f"{cid}:{lock_key}:{DEV_ID}"
        is_lock = text.startswith("قفل")
        if is_lock:
            # SET NX — ذري يمنع race condition بين مديرين
            if not await ar.set(redis_key, 1, nx=True):
                return await reply(f"{k} من 「 {mention} 」\n{k} {text} مفعّل من قبل\n☆")
            _locks_cache_invalidate(cid)
            return await reply(f"{k} من 「 {mention} 」\n{k} ابشر {text}\n☆")
        else:
            if not await ar.get(redis_key):
                return await reply(f"{k} من 「 {mention} 」\n{k} {text} معطّل من قبل\n☆")
            await ar.delete(redis_key)
            _locks_cache_invalidate(cid)
            return await reply(f"{k} من 「 {mention} 」\n{k} ابشر {text}\n☆")

    # ──── تعطيل/تفعيل التحذير ────
    if text == "تعطيل التحذير":
        if await need_mod(): return
        if await ar.get(f"{cid}:disableWarn:{DEV_ID}"):
            return await reply(f"{k} من 「 {mention} 」\n{k} التحذير معطّل من قبل\n☆")
        await ar.set(f"{cid}:disableWarn:{DEV_ID}", 1)
        return await reply(f"{k} من 「 {mention} 」\n{k} ابشر عطّلت التحذير\n☆")

    if text == "تفعيل التحذير":
        if await need_mod(): return
        if not await ar.get(f"{cid}:disableWarn:{DEV_ID}"):
            return await reply(f"{k} من 「 {mention} 」\n{k} التحذير مفعّل من قبل\n☆")
        await ar.delete(f"{cid}:disableWarn:{DEV_ID}")
        return await reply(f"{k} من 「 {mention} 」\n{k} ابشر فعّلت التحذير\n☆")

    # ──── منع / الغاء منع ميديا ────
    if text == "منع" and m.reply_to_message and m.reply_to_message.media:
        if await need_mod(): return
        rep = m.reply_to_message
        file_id = None
        if rep.sticker:     file_id = rep.sticker.file_id
        elif rep.animation: file_id = rep.animation.file_id
        elif rep.photo:     file_id = rep.photo.file_id
        elif rep.video:     file_id = rep.video.file_id
        elif rep.voice:     file_id = rep.voice.file_id
        elif rep.audio:     file_id = rep.audio.file_id
        elif rep.document:  file_id = rep.document.file_id
        if file_id:
            idd = file_id[-6:]
            if await ar.get(f"{idd}:NotAllow:{cid}:{DEV_ID}"):
                return await reply(f"{k} هذا الملف محظور من قبل")
            await ar.set(f"{idd}:NotAllow:{cid}:{DEV_ID}", 1)
            await ar.sadd(f"{cid}:NotAllowedList:{DEV_ID}", idd)
            return await reply(f"{k} من 「 {mention} 」\n{k} ابشر منعت هذا الملف\n☆")

    if text == "الغاء منع" and m.reply_to_message and m.reply_to_message.media:
        if await need_mod(): return
        rep = m.reply_to_message
        file_id = None
        if rep.sticker:     file_id = rep.sticker.file_id
        elif rep.animation: file_id = rep.animation.file_id
        elif rep.photo:     file_id = rep.photo.file_id
        elif rep.video:     file_id = rep.video.file_id
        elif rep.voice:     file_id = rep.voice.file_id
        elif rep.audio:     file_id = rep.audio.file_id
        elif rep.document:  file_id = rep.document.file_id
        if file_id:
            idd = file_id[-6:]
            if not await ar.get(f"{idd}:NotAllow:{cid}:{DEV_ID}"):
                return await reply(f"{k} هذا الملف مو محظور")
            await ar.delete(f"{idd}:NotAllow:{cid}:{DEV_ID}")
            await ar.srem(f"{cid}:NotAllowedList:{DEV_ID}", idd)
            return await reply(f"{k} من 「 {mention} 」\n{k} ابشر رفعت المنع\n☆")

    # ──── منع كلمة نصية ────
    if text == "منع" and m.reply_to_message and not m.reply_to_message.media:
        if await need_mod(): return
        word = m.reply_to_message.text
        if not word:
            return await reply(f"{k} الرسالة ما تحتوي نص")
        await ar.sadd(f"{cid}:NotAllowedListText:{DEV_ID}", word)
        return await reply(f"{k} من 「 {mention} 」\n{k} ابشر منعت: `{word}`\n☆")

    # ──── قائمة المنع ────
    if text in ("قائمه المنع", "قائمة المنع"):
        if await need_mod(): return
        files = await ar.smembers(f"{cid}:NotAllowedList:{DEV_ID}")
        words = await ar.smembers(f"{cid}:NotAllowedListText:{DEV_ID}")
        if not files and not words:
            return await reply(f"{k} قائمة المنع فارغة")
        msg = f"{k} قائمة المنع:\n\n"
        if files:
            msg += "**الملفات:**\n" + "\n".join(f"• `{f}`" for f in files) + "\n\n"
        if words:
            msg += "**الكلمات:**\n" + "\n".join(f"• `{w}`" for w in words)
        return await reply(msg)

    # ──── مسح قائمة المنع ────
    if text in ("مسح قائمه المنع", "مسح قائمة المنع"):
        if await need_mod(): return
        files = await ar.smembers(f"{cid}:NotAllowedList:{DEV_ID}")
        async with ar.pipeline(transaction=False) as pipe:
            for f in files:
                pipe.delete(f"{f}:NotAllow:{cid}:{DEV_ID}")
            pipe.delete(f"{cid}:NotAllowedList:{DEV_ID}")
            pipe.delete(f"{cid}:NotAllowedListText:{DEV_ID}")
            await pipe.execute()
        return await reply(f"{k} ابشر مسحت قائمة المنع")
