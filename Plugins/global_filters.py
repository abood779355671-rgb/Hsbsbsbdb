"""
الردود العامة - فلاتر تسري على جميع المجموعات
أوامر (للمطور):
  اضف فلتر عام [كلمة]  → إضافة فلتر عام
  حذف فلتر عام [كلمة]  → حذف فلتر عام
  الفلاتر العامة        → قائمة الفلاتر العامة
"""
import re
from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import Message

from config import r, DEV_ID, botkey, cached_smembers, ar
# ✅ إصلاح 2: نقل imports من داخل handlers إلى أعلى الملف
from helpers.ranks import is_dev, is_mod, is_owner
from helpers.utils import group_enabled, can_speak, resolve_text

# ✅ إصلاح 1: مجموعة in-memory لتتبع المستخدمين المنتظرين لإضافة فلتر عام
# بدلاً من استعلام Redis لكل رسالة في كل المجموعات
# 99.99% من الرسائل تخرج مجاناً بدون أي I/O
_pending_global_add: set[int] = set()


async def _send_data(m: Message, data: str):
    """
    Parse filter data — same robust logic as custom_filters._send_filter.
    صيغة التخزين: type=TYPE&TYPE=VALUE&caption=CAP
    النص يأتي كاملاً بعد 'text=' لتجنب قطع النص الذي يحتوي '&'.
    """
    try:
        parts = {}
        if not data.startswith("type="):
            parts = dict(p.split("=", 1) for p in data.split("&") if "=" in p)
        else:
            type_end = data.index("&") if "&" in data else len(data)
            parts["type"] = data[5:type_end]
            rest = data[type_end + 1:] if "&" in data else ""
            ftype = parts["type"]
            if ftype == "text":
                parts["text"] = rest[5:] if rest.startswith("text=") else rest
            elif ftype in ("photo", "video", "animation", "audio", "voice", "doc"):
                cap_idx = rest.find("&caption=")
                prefix  = f"{ftype}="
                if rest.startswith(prefix):
                    if cap_idx != -1:
                        parts[ftype]     = rest[len(prefix):cap_idx]
                        parts["caption"] = rest[cap_idx + 9:]
                    else:
                        parts[ftype] = rest[len(prefix):]
            elif ftype == "sticker":
                parts["sticker"] = rest[8:] if rest.startswith("sticker=") else rest
    except Exception:
        return
    ftype = parts.get("type", "text")
    cap   = parts.get("caption", None)
    if cap == "None": cap = None

    if ftype == "text":
        await m.reply(parts.get("text", ""), parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    elif ftype == "photo":
        await m.reply_photo(parts["photo"], caption=cap, parse_mode=ParseMode.HTML)
    elif ftype == "video":
        await m.reply_video(parts["video"], caption=cap, parse_mode=ParseMode.HTML)
    elif ftype == "animation":
        await m.reply_animation(parts["animation"], caption=cap, parse_mode=ParseMode.HTML)
    elif ftype == "sticker":
        await m.reply_sticker(parts["sticker"])
    elif ftype == "audio":
        await m.reply_audio(parts["audio"], caption=cap, parse_mode=ParseMode.HTML)
    elif ftype == "voice":
        await m.reply_voice(parts["voice"], caption=cap, parse_mode=ParseMode.HTML)
    elif ftype == "doc":
        await m.reply_document(parts["doc"], caption=cap, parse_mode=ParseMode.HTML)


# ── استقبال محتوى الفلتر العام الجديد ────────────────────────────────────

@Client.on_message(filters.group, group=31)
async def global_filter_input(c: Client, m: Message):
    if not m.from_user:
        return
    cid, uid = m.chat.id, m.from_user.id

    # ✅ إصلاح 1: فحص in-memory أولاً — لا Redis إذا لا أحد ينتظر
    # كل رسائل المجموعات تخرج هنا مجاناً في الحالة العادية
    if uid not in _pending_global_add:
        return
    if not is_dev(uid, cid):
        return

    key_wait = f"addGlobalFilter2:{uid}:{DEV_ID}"
    word = await ar.get(key_wait)
    if not word:
        # الـ TTL انتهى — نظّف المجموعة المحلية
        _pending_global_add.discard(uid)
        return

    if not group_enabled(cid):
        return

    k = botkey()

    async def _save(data: str):
        await ar.set(f"GlobalFilter:{DEV_ID}:{word}", data)
        await ar.sadd(f"GlobalFiltersList:{DEV_ID}", word)
        await ar.delete(key_wait)
        _pending_global_add.discard(uid)
        await m.reply(f"{k} تم إضافة الفلتر العام «{word}» ✅")

    if m.text and m.text != "الغاء":
        await _save(f"type=text&text={m.text.html}")
        return
    if m.text == "الغاء":
        await ar.delete(key_wait)
        _pending_global_add.discard(uid)
        await m.reply(f"{k} تم الإلغاء")
        return

    cap = m.caption.html if m.caption else "None"
    if m.photo:
        await _save(f"type=photo&photo={m.photo.file_id}&caption={cap}")
    elif m.video:
        await _save(f"type=video&video={m.video.file_id}&caption={cap}")
    elif m.animation:
        await _save(f"type=animation&animation={m.animation.file_id}&caption={cap}")
    elif m.sticker:
        await _save(f"type=sticker&sticker={m.sticker.file_id}")
    elif m.audio:
        await _save(f"type=audio&audio={m.audio.file_id}&caption={cap}")
    elif m.voice:
        await _save(f"type=voice&voice={m.voice.file_id}&caption={cap}")
    elif m.document:
        await _save(f"type=doc&doc={m.document.file_id}&caption={cap}")


# ── أوامر الفلاتر العامة ─────────────────────────────────────────────────

@Client.on_message(filters.text & filters.group, group=35)
async def global_filter_commands(c: Client, m: Message):
    if not m.from_user:
        return
    cid, uid = m.chat.id, m.from_user.id
    if not group_enabled(cid):
        return
    if not can_speak(uid, cid):
        return

    text = resolve_text(m.text, cid)
    k    = botkey()

    add_m = re.fullmatch(r"اضف فلتر عام\s+(.+)", text)
    if add_m:
        if not is_dev(uid, cid):
            return await m.reply(f"{k} هذا الأمر للمطور فقط")
        word = add_m.group(1).strip().lower()
        await ar.set(f"addGlobalFilter2:{uid}:{DEV_ID}", word, ex=300)
        # ✅ إصلاح 1: سجّل المستخدم محلياً لتجنب Redis في كل رسالة لاحقة
        _pending_global_add.add(uid)
        return await m.reply(
            f"{k} أرسل الرد للكلمة العامة «{word}» الآن\nأرسل **الغاء** للتراجع"
        )

    del_m = re.fullmatch(r"حذف فلتر عام\s+(.+)", text)
    if del_m:
        if not is_dev(uid, cid):
            return await m.reply(f"{k} هذا الأمر للمطور فقط")
        word = del_m.group(1).strip().lower()
        await ar.delete(f"GlobalFilter:{DEV_ID}:{word}")
        await ar.srem(f"GlobalFiltersList:{DEV_ID}", word)
        return await m.reply(f"{k} تم حذف الفلتر العام «{word}» ✅")

    if text == "الفلاتر العامة":
        if not is_mod(uid, cid):
            return await m.reply(f"{k} هذا الأمر للمدير وفوق فقط")
        fl = cached_smembers(f"GlobalFiltersList:{DEV_ID}")
        if not fl:
            return await m.reply(f"{k} لا توجد فلاتر عامة")
        return await m.reply(
            f"{k} الفلاتر العامة:\n" +
            "\n".join(f"• `{w}`" for w in sorted(fl))
        )


# ── تطبيق الفلاتر العامة ─────────────────────────────────────────────────

@Client.on_message(filters.text & filters.group, group=33)
async def apply_global_filters(c: Client, m: Message):
    if not m.from_user or not m.text:
        return
    cid = m.chat.id
    if not group_enabled(cid):
        return

    # ✅ إصلاح 1: استخدام المجموعة المحلية بدلاً من Redis
    if m.from_user.id in _pending_global_add:
        return

    fl = cached_smembers(f"GlobalFiltersList:{DEV_ID}")
    if not fl:
        return

    msg_lower = m.text.lower()
    fl_list   = list(fl)
    matching  = [w for w in fl_list if w in msg_lower]
    if matching:
        data_vals = await ar.mget([f"GlobalFilter:{DEV_ID}:{w}" for w in matching])
        for word, data in zip(matching, data_vals):
            if data:
                try:
                    await _send_data(m, data)
                except Exception:
                    pass
                break


# ─────────────────────────────────────────────────────────────────────────────
# ميزات إضافية: تعطيل/تفعيل ردود المطور، مسح الردود العامة
# ─────────────────────────────────────────────────────────────────────────────

@Client.on_message(filters.text & filters.group, group=24)
async def global_filter_extra(c: Client, m: Message):
    if not m.from_user:
        return
    cid, uid = m.chat.id, m.from_user.id
    if not group_enabled(cid):
        return
    if not can_speak(uid, cid):
        return

    # ✅ إصلاح 2: حُذف import داخل handler — is_owner و is_dev مستوردتان أعلى الملف
    text = resolve_text(m.text, cid)
    k    = botkey()

    # ── تعطيل / تفعيل ردود المطور ───────────────────────────────────────
    if text == "تعطيل ردود المطور":
        if not is_owner(uid, cid):
            return await m.reply(f"{k} هذا الأمر للمالك وفوق فقط")
        if await ar.get(f"{cid}:lock_global:{DEV_ID}"):
            return await m.reply(f"{k} ردود المطور معطلة مسبقاً")
        await ar.set(f"{cid}:lock_global:{DEV_ID}", 1)
        return await m.reply(f"{k} من「 {m.from_user.mention} 」\n{k} تم تعطيل ردود المطور\n☆")

    if text == "تفعيل ردود المطور":
        if not is_owner(uid, cid):
            return await m.reply(f"{k} هذا الأمر للمالك وفوق فقط")
        if not await ar.get(f"{cid}:lock_global:{DEV_ID}"):
            return await m.reply(f"{k} ردود المطور مفعلة مسبقاً")
        await ar.delete(f"{cid}:lock_global:{DEV_ID}")
        return await m.reply(f"{k} من「 {m.from_user.mention} 」\n{k} تم تفعيل ردود المطور\n☆")

    # ── الردود العامه (قائمة مع النوع) ──────────────────────────────────
    if text in ("الردود العامه", "الردود العامة"):
        if not is_dev(uid, cid):
            return await m.reply(f"{k} هذا الأمر للمطور فقط")
        fl = list(await ar.smembers(f"GlobalFiltersList:{DEV_ID}"))
        if not fl:
            return await m.reply(f"{k} مافيه ردود عامة مضافة")
        # mget واحد بدلاً من r.get لكل كلمة
        data_vals = await ar.mget([f"GlobalFilter:{DEV_ID}:{w}" for w in fl])
        _type_map = {"text":"نص","photo":"صورة","video":"فيديو","animation":"متحركة",
                     "audio":"صوت","voice":"بصمة","doc":"ملف","sticker":"ملصق"}
        txt = "ردود البوت:\n"
        for i, (word, data) in enumerate(zip(fl, data_vals), 1):
            ftype = "نص"
            if data:
                m_type = re.search(r"type=([^&]+)", data)
                if m_type:
                    ftype = _type_map.get(m_type.group(1), m_type.group(1))
            txt += f"\n{i} - ( {word} ) ࿓ ( {ftype} )"
        txt += "\n☆"
        return await m.reply(txt)

    # ── مسح الردود العامه ───────────────────────────────────────────────
    if text in ("مسح الردود العامه", "مسح الردود العامة"):
        if not is_dev(uid, cid):
            return await m.reply(f"{k} هذا الأمر للمطور فقط")
        fl = await ar.smembers(f"GlobalFiltersList:{DEV_ID}")
        if not fl:
            return await m.reply(f"{k} مافيه ردود عامة مضافة")
        count = len(fl)
        # ✅ إصلاح pipeline: لا await على أوامر الـ pipeline الفردية
        async with ar.pipeline(transaction=False) as pipe:
            for word in fl:
                pipe.delete(f"GlobalFilter:{DEV_ID}:{word}")
                pipe.srem(f"GlobalFiltersList:{DEV_ID}", word)
            await pipe.execute()
        return await m.reply(f"{k} ابشر مسحت ( {count} ) من الردود العامة")
