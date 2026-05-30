"""
الفلاتر المخصصة
أوامر:
  اضف فلتر [الكلمة]   → إضافة فلتر (يطلب الرد بعدها)
  حذف فلتر [الكلمة]   → حذف فلتر
  الفلاتر             → قائمة الفلاتر
"""
import re
import random
import pytz
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import Message

from config import r, DEV_ID, botkey, cached_smembers, ar
from helpers.ranks import is_mod
from helpers.utils import group_enabled, can_speak, resolve_text

# ── cache محلي لتسريع الفحص المبكر في quick_reply_input ──────────────────
# يمنع 4-6 طلبات Redis لكل رسالة إذا لم يكن المستخدم في أي خطوة
# {uid}: أي uid ينتظر إدخالاً في أي خطوة من 4 خطوات
_WAITING_QR: set[int] = set()


def _date_now() -> str:
    tz  = pytz.timezone("Asia/Riyadh")
    now = datetime.now(tz)
    return now.strftime("%d/%m/%Y %I:%M:%S %p")


# ── إرسال ردّ الفلتر ─────────────────────────────────────────────────────

async def _send_filter(m: Message, data: str):
    """يُحلّل بيانات الفلتر ويُرسل الرد المناسب"""
    try:
        # ✅ إصلاح: نقسم على أول & فقط لاستخراج type، والباقي هو القيمة
        # صيغة التخزين: type=text&text=... أو type=photo&photo=FILE_ID&caption=...
        parts = {}
        # استخراج type أولاً
        if data.startswith("type="):
            type_end = data.index("&") if "&" in data else len(data)
            parts["type"] = data[5:type_end]
            rest = data[type_end+1:] if "&" in data else ""
            # استخراج الحقل الثاني (file_id أو text)
            ftype = parts["type"]
            if ftype == "text":
                # text=... كل الباقي هو النص
                if rest.startswith("text="):
                    parts["text"] = rest[5:]
            elif ftype in ("photo", "video", "animation", "audio", "voice", "doc"):
                # TYPE=FILE_ID&caption=...
                if rest.startswith(f"{ftype}="):
                    cap_idx = rest.find("&caption=")
                    if cap_idx != -1:
                        parts[ftype] = rest[len(ftype)+1:cap_idx]
                        parts["caption"] = rest[cap_idx+9:]
                    else:
                        parts[ftype] = rest[len(ftype)+1:]
            elif ftype == "sticker":
                if rest.startswith("sticker="):
                    parts["sticker"] = rest[8:]
        else:
            # fallback للبيانات القديمة
            parts = dict(p.split("=", 1) for p in data.split("&") if "=" in p)
    except Exception:
        return

    ftype = parts.get("type", "text")

    if ftype == "text":
        txt = parts.get("text", "")
        await m.reply(txt, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    elif ftype == "photo":
        fid     = parts.get("photo", "")
        caption = parts.get("caption", "")
        if caption == "None": caption = None
        await m.reply_photo(fid, caption=caption, parse_mode=ParseMode.HTML)

    elif ftype == "video":
        fid     = parts.get("video", "")
        caption = parts.get("caption", "")
        if caption == "None": caption = None
        await m.reply_video(fid, caption=caption, parse_mode=ParseMode.HTML)

    elif ftype == "animation":
        fid     = parts.get("animation", "")
        caption = parts.get("caption", "")
        if caption == "None": caption = None
        await m.reply_animation(fid, caption=caption, parse_mode=ParseMode.HTML)

    elif ftype == "audio":
        fid     = parts.get("audio", "")
        caption = parts.get("caption", "")
        if caption == "None": caption = None
        await m.reply_audio(fid, caption=caption, parse_mode=ParseMode.HTML)

    elif ftype == "voice":
        fid     = parts.get("voice", "")
        caption = parts.get("caption", "")
        if caption == "None": caption = None
        await m.reply_voice(fid, caption=caption, parse_mode=ParseMode.HTML)

    elif ftype == "doc":
        fid     = parts.get("doc", "")
        caption = parts.get("caption", "")
        if caption == "None": caption = None
        await m.reply_document(fid, caption=caption, parse_mode=ParseMode.HTML)

    elif ftype == "sticker":
        fid = parts.get("sticker", "")
        await m.reply_sticker(fid)


# ── مرحلة إضافة الفلتر (استقبال الرد) ───────────────────────────────────

@Client.on_message(filters.group, group=21)
async def filter_input_handler(c: Client, m: Message):
    if not m.from_user:
        return
    cid, uid = m.chat.id, m.from_user.id
    if not group_enabled(cid):
        return
    if not can_speak(uid, cid):
        return

    key_wait = f"{cid}:addFilter2:{uid}:{DEV_ID}"
    if not await ar.get(key_wait) or not is_mod(uid, cid):
        return

    filter_word = await ar.get(key_wait)
    date        = _date_now()
    k           = botkey()

    async def _save(data: str, ftype_label: str):
        await ar.set(f"{filter_word}:filter:{DEV_ID}:{cid}", data)
        await ar.set(f"{filter_word}:filtertype:{cid}:{DEV_ID}", ftype_label)
        await ar.set(f"{filter_word}:filterInfo:{cid}:{DEV_ID}", f"by={uid}&date={date}")
        await ar.sadd(f"{cid}:FiltersList:{DEV_ID}", filter_word)
        await ar.delete(key_wait)
        await m.reply(f"({filter_word})\n{k} تم حفظ الفلتر ✅", parse_mode=ParseMode.HTML)

    if m.text and m.text != "الغاء":
        await _save(f"type=text&text={m.text.html}", "نص")
        return

    if m.text == "الغاء":
        await ar.delete(key_wait)
        await m.reply(f"{k} تم إلغاء إضافة الفلتر")
        return

    cap = m.caption.html if m.caption else "None"

    if m.photo:
        await _save(f"type=photo&photo={m.photo.file_id}&caption={cap}", "صورة")
    elif m.video:
        await _save(f"type=video&video={m.video.file_id}&caption={cap}", "فيديو")
    elif m.animation:
        await _save(f"type=animation&animation={m.animation.file_id}&caption={cap}", "GIF")
    elif m.audio:
        await _save(f"type=audio&audio={m.audio.file_id}&caption={cap}", "صوت")
    elif m.voice:
        await _save(f"type=voice&voice={m.voice.file_id}&caption={cap}", "بصمة")
    elif m.document:
        await _save(f"type=doc&doc={m.document.file_id}&caption={cap}", "ملف")
    elif m.sticker:
        await _save(f"type=sticker&sticker={m.sticker.file_id}", "ستيكر")


# ── أوامر الفلاتر الرئيسية ────────────────────────────────────────────────

@Client.on_message(filters.text & filters.group, group=22)
async def filters_commands(c: Client, m: Message):
    if not m.from_user:
        return
    cid, uid = m.chat.id, m.from_user.id
    if not group_enabled(cid):
        return
    if not can_speak(uid, cid):
        return

    text = resolve_text(m.text, cid)
    k    = botkey()

    # اضف فلتر [كلمة]
    add_m = re.fullmatch(r"اضف فلتر\s+(.+)", text)
    if add_m:
        if not is_mod(uid, cid):
            return await m.reply(f"{k} هذا الأمر للمدير وفوق فقط")
        word = add_m.group(1).strip().lower()
        await ar.set(f"{cid}:addFilter2:{uid}:{DEV_ID}", word, ex=300)
        return await m.reply(
            f"{k} أرسل الرد للكلمة «{word}» الآن\n"
            "(نص، صورة، فيديو، ستيكر ...)\n"
            "أرسل **الغاء** للتراجع"
        )

    # حذف فلتر [كلمة]
    del_m = re.fullmatch(r"حذف فلتر\s+(.+)", text)
    if del_m:
        if not is_mod(uid, cid):
            return await m.reply(f"{k} هذا الأمر للمدير وفوق فقط")
        word = del_m.group(1).strip().lower()
        fkey = f"{word}:filter:{DEV_ID}:{cid}"
        if not await ar.get(fkey):
            return await m.reply(f"{k} لا يوجد فلتر بهذه الكلمة")
        await ar.delete(fkey)
        await ar.delete(f"{word}:filtertype:{cid}:{DEV_ID}")
        await ar.delete(f"{word}:filterInfo:{cid}:{DEV_ID}")
        await ar.srem(f"{cid}:FiltersList:{DEV_ID}", word)
        return await m.reply(f"{k} تم حذف فلتر «{word}» ✅")

    # قائمة الفلاتر
    if text == "الفلاتر":
        fl = cached_smembers(f"{cid}:FiltersList:{DEV_ID}")
        if not fl:
            return await m.reply(f"{k} لا توجد فلاتر في هذه المجموعة")
        sorted_fl = sorted(fl)
        ftype_vals = await ar.mget([f"{w}:filtertype:{cid}:{DEV_ID}" for w in sorted_fl])
        lines = [f"{k} الفلاتر المضافة:\n"]
        for i, (word, ftype) in enumerate(zip(sorted_fl, ftype_vals), 1):
            lines.append(f"{i}. `{word}` — {ftype or '—'}")
        return await m.reply("\n".join(lines))


# ── تطبيق الفلاتر على كل رسالة ───────────────────────────────────────────

@Client.on_message(filters.text & filters.group, group=23)
async def apply_filters(c: Client, m: Message):
    if not m.from_user or not m.text:
        return
    cid, uid = m.chat.id, m.from_user.id
    if not group_enabled(cid):
        return
    if not can_speak(uid, cid):
        return
    # لا نطبّق الفلاتر إذا المستخدم في وضع إضافة فلتر
    if await ar.get(f"{cid}:addFilter2:{uid}:{DEV_ID}"):
        return

    fl = cached_smembers(f"{cid}:FiltersList:{DEV_ID}")
    if not fl:
        return

    # ✅ إصلاح: نمرر النص عبر resolve_text لدعم الأوامر المخصصة
    msg_text = resolve_text(m.text, cid).lower()
    for word in fl:
        if word in msg_text:
            data = await ar.get(f"{word}:filter:{DEV_ID}:{cid}")
            if data:
                try:
                    await _send_filter(m, data)
                except Exception:
                    pass
            break


# ─────────────────────────────────────────────────────────────────────────────
# الردود المميزة (المتعددة/العشوائية) - group=23B
# ─────────────────────────────────────────────────────────────────────────────

@Client.on_message(filters.group & filters.text, group=34)
async def random_filters_handler(c: Client, m: Message):
    if not m.from_user:
        return
    cid, uid = m.chat.id, m.from_user.id
    if not group_enabled(cid):
        return
    if not can_speak(uid, cid):
        return

    text = resolve_text(m.text, cid)
    k    = botkey()


    # ── إلغاء ────────────────────────────────────────────────────────────
    if text == "الغاء":
        if await ar.delete(f"{cid}:addFilterR:{uid}:{DEV_ID}"):
            return await m.reply(f"{k} تم إلغاء إضافة الرد المميز")
        _afr2_key = f"{cid}:addFilterR2:{uid}:{DEV_ID}"
        _afr2_val = await ar.get(_afr2_key)
        if _afr2_val:
            rep = _afr2_val
            await ar.delete(f"{cid}:addFilterR2:{uid}:{DEV_ID}")
            await ar.delete(f"{rep}:randomfilter:{cid}:{DEV_ID}")
            return await m.reply(f"{k} تم إلغاء إضافة الرد المميز")
        if await ar.delete(f"{cid}:delFilterR:{uid}:{DEV_ID}"):
            return await m.reply(f"{k} تم إلغاء مسح الرد المميز")
        return

    # ── تم (حفظ الرد المميز) ─────────────────────────────────────────────
    _key_afr2 = f"{cid}:addFilterR2:{uid}:{DEV_ID}"
    _val_afr2 = await ar.get(_key_afr2)
    if text == "تم" and _val_afr2:
        word  = _val_afr2
        count = len(cached_smembers(f"{word}:randomfilter:{cid}:{DEV_ID}"))  # cached بدلاً من ar.smembers مباشرة
        await ar.set(f"{word}:randomFilter:{cid}:{DEV_ID}", 1)
        await ar.sadd(f"{cid}:RFiltersList:{DEV_ID}", word)
        await ar.delete(f"{cid}:addFilterR2:{uid}:{DEV_ID}")
        return await m.reply(f"{k} تم إضافة الرد المميز ( {word} )\n{k} بـ ( {count} ) جواب رد\n☆")

    # ── مرحلة إضافة الأجوبة ──────────────────────────────────────────────
    if _val_afr2 and is_mod(uid, cid):
        word = _val_afr2
        await ar.sadd(f"{word}:randomfilter:{cid}:{DEV_ID}", m.text.html if hasattr(m.text, "html") else m.text)
        return await m.reply(f"{k} تم إضافة هذا الجواب\n{k} بس تخلص أرسل **تم**")

    # ── مرحلة تلقّي اسم الرد المميز الجديد ──────────────────────────────
    if await ar.get(f"{cid}:addFilterR:{uid}:{DEV_ID}") and is_mod(uid, cid):
        await ar.delete(f"{cid}:addFilterR:{uid}:{DEV_ID}")
        await ar.set(f"{cid}:addFilterR2:{uid}:{DEV_ID}", text, ex=300)
        return await m.reply(f"{k} الآن أرسل أجوبة الرد\n{k} بس تخلص أرسل **تم**")

    # ── حذف رد مميز (مرحلة تلقّي الاسم) ─────────────────────────────────
    if await ar.get(f"{cid}:delFilterR:{uid}:{DEV_ID}") and is_mod(uid, cid):
        if not await ar.get(f"{text}:randomFilter:{cid}:{DEV_ID}"):
            await ar.delete(f"{cid}:delFilterR:{uid}:{DEV_ID}")
            return await m.reply(f"{k} هذا الرد غير مضاف")
        await ar.delete(f"{text}:randomFilter:{cid}:{DEV_ID}")
        await ar.delete(f"{text}:randomfilter:{cid}:{DEV_ID}")
        await ar.delete(f"{cid}:delFilterR:{uid}:{DEV_ID}")
        await ar.srem(f"{cid}:RFiltersList:{DEV_ID}", text)
        return await m.reply(f"{k} تم مسح الرد المميز ✅")

    # ── أوامر الردود المميزة ─────────────────────────────────────────────
    if text == "اضف رد مميز":
        if not is_mod(uid, cid):
            return await m.reply(f"{k} هذا الأمر للمدير وفوق فقط")
        await ar.set(f"{cid}:addFilterR:{uid}:{DEV_ID}", 1, ex=300)
        return await m.reply(f"{k} أرسل الكلمة التي تريدها")

    if text == "مسح رد مميز":
        if not is_mod(uid, cid):
            return await m.reply(f"{k} هذا الأمر للمدير وفوق فقط")
        await ar.set(f"{cid}:delFilterR:{uid}:{DEV_ID}", 1, ex=300)
        return await m.reply(f"{k} أرسل الرد الذي تريد مسحه")

    if text == "الردود المميزه":
        if not is_mod(uid, cid):
            return await m.reply(f"{k} هذا الأمر للمدير وفوق فقط")
        rfl = cached_smembers(f"{cid}:RFiltersList:{DEV_ID}")
        if not rfl:
            return await m.reply(f"{k} مافيه ردود مميزة مضافة")
        txt = "الردود المميزة:\n"
        for i, word in enumerate(rfl, 1):
            count = len(cached_smembers(f"{word}:randomfilter:{cid}:{DEV_ID}"))  # cached بدلاً من ar.smembers مباشرة
            txt += f"\n{i} - ( {word} ) ☆ ( {count} )"
        txt += "\n☆"
        return await m.reply(txt)

    if text == "مسح الردود المميزه":
        if not is_mod(uid, cid):
            return await m.reply(f"{k} هذا الأمر للمدير وفوق فقط")
        rfl = cached_smembers(f"{cid}:RFiltersList:{DEV_ID}")
        if not rfl:
            return await m.reply(f"{k} مافيه ردود مميزة مضافة")
        count = 0
        for word in list(rfl):
            await ar.delete(f"{word}:randomFilter:{cid}:{DEV_ID}")
            await ar.delete(f"{word}:randomfilter:{cid}:{DEV_ID}")
            await ar.srem(f"{cid}:RFiltersList:{DEV_ID}", word)
            count += 1
        return await m.reply(f"{k} تم مسح ( {count} ) رد مميز ✅")


@Client.on_message(filters.text & filters.group, group=26)
async def apply_random_filters(c: Client, m: Message):
    """تطبيق الردود المميزة العشوائية."""
    if not m.from_user or not m.text:
        return
    cid, uid = m.chat.id, m.from_user.id
    if not group_enabled(cid):
        return
    # ✅ إصلاح: تحقق من can_speak
    if not can_speak(uid, cid):
        return

    text = resolve_text(m.text, cid)

    rfl = cached_smembers(f"{cid}:RFiltersList:{DEV_ID}")
    if not rfl:
        return

    for word in rfl:
        if text == word:
            options = cached_smembers(f"{word}:randomfilter:{cid}:{DEV_ID}")
            if options:
                chosen = random.choice(list(options))
                try:
                    await m.reply(chosen, disable_web_page_preview=True)
                except Exception:
                    pass
            return


# ─────────────────────────────────────────────────────────────────────────────
# اضف رد / حذف رد / اضف ردي
# اضف رد   → فلتر نصي سريع (مدير+): يطلب الكلمة ثم الرد
# حذف رد   → حذف فلتر سريع (مدير+)
# اضف ردي  → رد شخصي لـ uid المستخدم فقط (عضو عادي يضيف لنفسه)
# ─────────────────────────────────────────────────────────────────────────────

@Client.on_message(filters.group, group=38)
async def quick_reply_input(c: Client, m: Message):
    """مرحلة استقبال الرد بعد 'اضف رد' أو 'اضف ردي'"""
    if not m.from_user:
        return
    uid = m.from_user.id

    # الفحص المبكر — صفر Redis لـ 99.99% من الرسائل
    if uid not in _WAITING_QR:
        return

    cid = m.chat.id
    if not group_enabled(cid):
        return

    k = botkey()

    # جلب الـ 4 مفاتيح دفعةً واحدة بدلاً من 4-6 طلبات منفصلة
    s1, s2, ms1, ms2 = await ar.mget([
        f"{cid}:qr_step1:{uid}:{DEV_ID}",
        f"{cid}:qr_step2:{uid}:{DEV_ID}",
        f"{cid}:myreply_step1:{uid}:{DEV_ID}",
        f"{cid}:myreply_step2:{uid}:{DEV_ID}",
    ])

    # ─── اضف رد: مرحلة 2 — استقبال الكلمة المحفزة ────────────────────────
    if s1:
        if not is_mod(uid, cid):
            await ar.delete(f"{cid}:qr_step1:{uid}:{DEV_ID}")
            _WAITING_QR.discard(uid)
            return
        if not m.text:
            return
        if m.text.strip() == "الغاء":
            await ar.delete(f"{cid}:qr_step1:{uid}:{DEV_ID}")
            _WAITING_QR.discard(uid)
            return await m.reply(f"{k} تم الإلغاء")
        word = m.text.strip().lower()
        await ar.set(f"{cid}:qr_step2:{uid}:{DEV_ID}", word, ex=300)
        await ar.delete(f"{cid}:qr_step1:{uid}:{DEV_ID}")
        # uid ينتقل من step1 إلى step2 — يبقى في _WAITING_QR
        return await m.reply(
            f"{k} ممتاز! الكلمة: `{word}`\n"
            "الآن أرسل الرد (نص، صورة، فيديو، ستيكر ...)\n"
            "أرسل **الغاء** للتراجع"
        )

    # ─── اضف رد: مرحلة 3 — استقبال الرد ─────────────────────────────────
    if s2:
        if not is_mod(uid, cid):
            await ar.delete(f"{cid}:qr_step2:{uid}:{DEV_ID}")
            _WAITING_QR.discard(uid)
            return
        word = s2  # القيمة من mget مباشرة — بدون استدعاء مزدوج
        if m.text and m.text.strip() == "الغاء":
            await ar.delete(f"{cid}:qr_step2:{uid}:{DEV_ID}")
            _WAITING_QR.discard(uid)
            return await m.reply(f"{k} تم الإلغاء")

        cap = m.caption.html if m.caption else "None"
        if m.text:
            data = f"type=text&text={m.text.html}"
        elif m.photo:
            data = f"type=photo&photo={m.photo.file_id}&caption={cap}"
        elif m.video:
            data = f"type=video&video={m.video.file_id}&caption={cap}"
        elif m.animation:
            data = f"type=animation&animation={m.animation.file_id}&caption={cap}"
        elif m.audio:
            data = f"type=audio&audio={m.audio.file_id}&caption={cap}"
        elif m.voice:
            data = f"type=voice&voice={m.voice.file_id}&caption={cap}"
        elif m.document:
            data = f"type=doc&doc={m.document.file_id}&caption={cap}"
        elif m.sticker:
            data = f"type=sticker&sticker={m.sticker.file_id}"
        else:
            return await m.reply(f"{k} نوع الرسالة غير مدعوم")

        await ar.set(f"{word}:filter:{DEV_ID}:{cid}", data)
        await ar.set(f"{word}:filtertype:{cid}:{DEV_ID}", "رد سريع")
        await ar.sadd(f"{cid}:FiltersList:{DEV_ID}", word)
        await ar.delete(f"{cid}:qr_step2:{uid}:{DEV_ID}")
        _WAITING_QR.discard(uid)
        return await m.reply(f"{k} تم إضافة الرد ✅\nالكلمة: `{word}`")

    # ─── اضف ردي: مرحلة 2 — استقبال الكلمة ──────────────────────────────
    if ms1:
        if not m.text:
            return
        if m.text.strip() == "الغاء":
            await ar.delete(f"{cid}:myreply_step1:{uid}:{DEV_ID}")
            _WAITING_QR.discard(uid)
            return await m.reply(f"{k} تم الإلغاء")
        word = m.text.strip().lower()
        await ar.set(f"{cid}:myreply_step2:{uid}:{DEV_ID}", word, ex=300)
        await ar.delete(f"{cid}:myreply_step1:{uid}:{DEV_ID}")
        # uid ينتقل من myreply_step1 إلى myreply_step2 — يبقى في _WAITING_QR
        return await m.reply(
            f"{k} الكلمة: `{word}`\n"
            "الآن أرسل الرد الشخصي (يظهر فقط لك)\n"
            "أرسل **الغاء** للتراجع"
        )

    # ─── اضف ردي: مرحلة 3 — استقبال الرد الشخصي ─────────────────────────
    if ms2:
        word = ms2  # القيمة من mget مباشرة — بدون استدعاء مزدوج
        if m.text and m.text.strip() == "الغاء":
            await ar.delete(f"{cid}:myreply_step2:{uid}:{DEV_ID}")
            _WAITING_QR.discard(uid)
            return await m.reply(f"{k} تم الإلغاء")
        if not m.text:
            return await m.reply(f"{k} الردود الشخصية نصية فقط")
        reply_text = m.text.html if hasattr(m.text, "html") else m.text
        await ar.set(f"myreply:{cid}:{uid}:{word}:{DEV_ID}", reply_text, ex=86400 * 30)
        await ar.sadd(f"myreplyList:{cid}:{uid}:{DEV_ID}", word)
        await ar.delete(f"{cid}:myreply_step2:{uid}:{DEV_ID}")
        _WAITING_QR.discard(uid)
        return await m.reply(f"{k} تم إضافة ردك الشخصي ✅\nالكلمة: `{word}`")

    # إذا وصلنا هنا فالـ uid في _WAITING_QR لكن مفاتيح Redis انتهت (TTL)
    _WAITING_QR.discard(uid)


@Client.on_message(filters.text & filters.group, group=39)
async def quick_reply_commands(c: Client, m: Message):
    """أوامر: اضف رد / حذف رد / اضف ردي / ردودي / حذف ردي"""
    if not m.from_user:
        return
    cid, uid = m.chat.id, m.from_user.id
    if not group_enabled(cid):
        return
    if not can_speak(uid, cid):
        return

    text = resolve_text(m.text, cid)
    k    = botkey()

    # ── اضف رد ───────────────────────────────────────────────────────────
    if text == "اضف رد":
        if not is_mod(uid, cid):
            return await m.reply(f"{k} هذا الأمر للمدير وفوق فقط")
        await ar.set(f"{cid}:qr_step1:{uid}:{DEV_ID}", 1, ex=300)
        _WAITING_QR.add(uid)
        return await m.reply(
            f"{k} أرسل الكلمة التي تريد البوت يرد عليها\n"
            "أرسل **الغاء** للتراجع"
        )

    # ── حذف رد [كلمة] ────────────────────────────────────────────────────
    del_m = re.fullmatch(r"حذف رد\s+(.+)", text)
    if del_m:
        if not is_mod(uid, cid):
            return await m.reply(f"{k} هذا الأمر للمدير وفوق فقط")
        word = del_m.group(1).strip().lower()
        fkey = f"{word}:filter:{DEV_ID}:{cid}"
        if not await ar.get(fkey):
            return await m.reply(f"{k} لا يوجد رد بهذه الكلمة")
        await ar.delete(fkey)
        await ar.delete(f"{word}:filtertype:{cid}:{DEV_ID}")
        await ar.delete(f"{word}:filterInfo:{cid}:{DEV_ID}")
        await ar.srem(f"{cid}:FiltersList:{DEV_ID}", word)
        return await m.reply(f"{k} تم حذف الرد «{word}» ✅")

    # ── اضف ردي ──────────────────────────────────────────────────────────
    if text == "اضف ردي":
        await ar.set(f"{cid}:myreply_step1:{uid}:{DEV_ID}", 1, ex=300)
        _WAITING_QR.add(uid)
        return await m.reply(
            f"{k} أرسل الكلمة التي تريد البوت يرد عليها شخصياً لك\n"
            "أرسل **الغاء** للتراجع"
        )

    # ── ردودي ────────────────────────────────────────────────────────────
    if text == "ردودي":
        words = cached_smembers(f"myreplyList:{cid}:{uid}:{DEV_ID}")
        if not words:
            return await m.reply(f"{k} ما عندك ردود شخصية مضافة")
        lines = [f"{k} ردودك الشخصية:\n"]
        for i, w in enumerate(sorted(words), 1):
            lines.append(f"{i}. `{w}`")
        return await m.reply("\n".join(lines))

    # ── حذف ردي [كلمة] ───────────────────────────────────────────────────
    del_my = re.fullmatch(r"حذف ردي\s+(.+)", text)
    if del_my:
        word = del_my.group(1).strip().lower()
        key  = f"myreply:{cid}:{uid}:{word}:{DEV_ID}"
        if not await ar.get(key):
            return await m.reply(f"{k} ما عندك رد شخصي بهذه الكلمة")
        await ar.delete(key)
        await ar.srem(f"myreplyList:{cid}:{uid}:{DEV_ID}", word)
        return await m.reply(f"{k} تم حذف ردك الشخصي «{word}» ✅")


@Client.on_message(filters.text & filters.group, group=40)
async def apply_personal_replies(c: Client, m: Message):
    """تطبيق الردود الشخصية (اضف ردي)"""
    if not m.from_user or not m.text:
        return
    cid, uid = m.chat.id, m.from_user.id
    if not group_enabled(cid):
        return
    if not can_speak(uid, cid):
        return

    text  = resolve_text(m.text, cid).lower()
    words = cached_smembers(f"myreplyList:{cid}:{uid}:{DEV_ID}")
    if not words:
        return

    for word in words:
        if word in text:
            reply = await ar.get(f"myreply:{cid}:{uid}:{word}:{DEV_ID}")
            if reply:
                try:
                    await m.reply(reply, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
                except Exception:
                    pass
            return
