"""
ملف id.py - معلومات المستخدمين والمجموعات
الأوامر المتاحة:
  ايدي / id           → عرض الايدي مع الشكل المخصص
  معلوماتي            → إحصائيات المستخدم كاملة
  كشف (رد/يوزر/ايدي)  → كشف معلومات أي مستخدم
  رسايلي / رسائلي      → عدد الرسائل
  تكليجاتي            → عدد التعديلات
  ترتيبي / تفاعلي     → ترتيبي بين المتفاعلين
  المتفاعلين           → توب 20 متفاعل
  القروبات             → توب 20 قروب متفاعل
  افتاري / افتار       → صورة الافتار
  بايو                 → عرض البايو
  المجموعه             → معلومات المجموعة
  صلاحياتي/ه          → عرض صلاحيات المشرف
  رتبته               → رتبة عضو بالرد
  لقبي                → اللقب المخصص
  مسح رسائلي          → إعادة تعيين عداد الرسائل
  مسح تكليجاتي        → إعادة تعيين عداد التعديلات
  مسح المتفاعلين       → تصفير الجميع (للمالك)
  جهاتي               → عدد جهات الاتصال المُضافة
  مجموعاتي            → عدد المجموعات المشترك فيها
  انشائي / الانشاء    → تاريخ إنشاء الحساب
  تعيين الايدي        → تخصيص شكل الايدي (للمدير+)
  تغيير الايدي        → اختيار شكل عشوائي
  مسح الايدي          → إزالة الشكل المخصص
  تفعيل/تعطيل الايدي  → تشغيل/إيقاف أمر ايدي
  تفعيل/تعطيل افتاري  → تشغيل/إيقاف الافتار
  تفعيل/تعطيل الايدي بالصوره → تشغيل/إيقاف الصورة في الايدي
"""

import asyncio
import random
import logging
import re
import os
from io import BytesIO

from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus, ChatMembersFilter
from pyrogram.types import Message
from pyrogram.raw.functions.users import GetFullUser
from pyrogram.raw.functions.channels import GetFullChannel
from pyrogram.file_id import FileId, FileType, ThumbnailSource

from config import r, DEV_ID, botkey, ar
logger = logging.getLogger("id")

# ─────────────────────────────────────────────────────────────────────────
# cache بسيط في الذاكرة لتفادي تكرار طلبات get_chat/GetFullChannel
# TTL = 5 دقائق  |  الحجم الأقصى = 500 مدخل
# ─────────────────────────────────────────────────────────────────────────
_CHAT_CACHE: dict[int, tuple[object, float]] = {}
_CHAT_CACHE_TTL = 300  # ثواني

def _cache_get(chat_id: int):
    import time
    entry = _CHAT_CACHE.get(chat_id)
    if entry and time.monotonic() - entry[1] < _CHAT_CACHE_TTL:
        return entry[0]
    return None

def _cache_set(chat_id: int, obj):
    import time
    if len(_CHAT_CACHE) >= 500:
        oldest = min(_CHAT_CACHE, key=lambda k: _CHAT_CACHE[k][1])
        _CHAT_CACHE.pop(oldest, None)
    _CHAT_CACHE[chat_id] = (obj, time.monotonic())

from helpers.ranks import (
    get_rank, is_admin, is_mod, is_owner, is_gowner, is_dev, is_locked,
)
from helpers.utils import group_enabled, can_speak, resolve_text
from helpers.get_create import get_creation_date  # async

# ─────────────────────────────────────────────────────────────────────────
# مساعدات داخلية
# ─────────────────────────────────────────────────────────────────────────

def _get_top(users: list[dict]) -> list[dict]:
    """ترتيب المستخدمين تنازلياً حسب عدد الرسائل"""
    return sorted(users, key=lambda i: i.get("msgs", 0), reverse=True)


def _emoji_bank(rank: int) -> str:
    emojis = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    return emojis[rank - 1] if 1 <= rank <= 10 else f"{rank}. "


def _tfa3l_label(msgs: int) -> str:
    if msgs > 10000: return "اسطورة التلي"
    if msgs > 5000:  return "اسطورة التفاعل"
    if msgs > 2500:  return "متفاعل"
    if msgs > 750:   return "تفاعل متوسط"
    if msgs > 500:   return "يجي منك"
    if msgs > 50:    return "شد حيلك"
    return "تفاعل صفر"


# ─────────────────────────────────────────────────────────────────────────
# أشكال الايدي الافتراضية
# ─────────────────────────────────────────────────────────────────────────

DEFAULT_ID_TEMPLATE = """\
𖡋 𝐔𝐒𝐄 ⌯  {اليوزر}
𖡋 𝐌𝐒𝐆 ⌯  {الرسائل}
𖡋 𝐒𝐓𝐀 ⌯  {الرتبه}
𖡋 𝐈𝐃 ⌯  {الايدي}
𖡋 𝐄𝐃𝐈𝐓 ⌯  {التعديل}
𖡋 𝐂𝐑  ⌯  {الانشاء}
{البايو}"""

CUSTOM_ID_TEMPLATES = [
    """\
- ᴜѕᴇʀɴᴀᴍᴇ ➣ {اليوزر} .
- ᴍѕɢѕ ➣ {الرسائل} .
- ѕᴛᴀᴛѕ ➣ {الرتبه} .
- ʏᴏᴜʀ ɪᴅ ➣ {الايدي} .
- ᴇᴅɪᴛ ᴍsɢ ➣ {التعديل} .
{البايو}""",
    """\
• USE 𖦹 {اليوزر}
• MSG 𖥳 {الرسائل}
• STA 𖦹 {الرتبه}
• iD 𖥳 {الايدي}
{البايو}""",
    """\
➞: 𝒔𝒕𝒂𓂅 {اليوزر} 𓍯
➞: 𝒖𝒔𝒆𝒓𓂅 {اليوزر} 𓍯
➞: 𝒎𝒔𝒈𝒆𓂅 {الرسائل} 𓍯
➞: 𝒊𝒅 𓂅 {الايدي} 𓍯
{البايو}""",
    """\
♡ : 𝐈𝐃 𖠀 {الايدي} .
♡ : 𝐔𝐒𝐄𝐑 𖠀 {اليوزر} .
♡ : 𝐌𝐒𝐆𝐒 𖠀 {الرسائل} .
♡ : 𝐒𝐓𝐀𝐓𝐒 𖠀 {الرتبه} .
♡ : 𝐄𝐃𝐈𝐓  𖠀 {التعديل} .
{البايو}""",
    """\
⌁ NaMe ⇨ {الاسم}
⌁ Use ⇨ {اليوزر}
⌁ Msg ⇨ {الرسائل}
⌁ Sta ⇨ {الرتبه}
⌁ iD ⇨ {الايدي}
{البايو}""",
    """\
✾ 𝐔𝐒𝐄 ⤷ {اليوزر}
✾ 𝐌𝐒𝐆 ⤷ {الرسائل}
✾ 𝐒𝐓𝐀 ⤷ {الرتبه}
✾ 𝐈𝐃 ⤷ {الايدي}
✾ 𝐁𝐈𝐎 ⤷ {البايو}""",
]

COMMENTS = [
    "تيكفه لاتكتب ايدي",
    "يع",
    "جبر",
    "احلى من يكتب ايدي",
    "افخم ايدي",
    "لحد يرسل ايدي من بعده",
    "يلبييه اطلق ايدي",
    "ازق ايدي",
    "لعد تكتب ايدي",
    "للاسف ايديك تلوث بصري ):",
    "جابك الله انت وأيديك على شكل جبر خاطر لقلبّي",
]


# ─────────────────────────────────────────────────────────────────────────
# عدادات الرسائل والتعديلات
# ─────────────────────────────────────────────────────────────────────────

@Client.on_message(filters.group, group=9)
async def add_msg_count(c: Client, m: Message):
    if not m.from_user:
        return
    uid, cid = str(m.from_user.id), str(m.chat.id)
    # لا نعدّ رسائل المجموعات المعطّلة — يوفّر ضربة Redis كاملة
    if not group_enabled(int(cid)):
        return
    if await ar.get(f"{uid}:mute:{cid}:{DEV_ID}"):
        return
    # pipeline async — كتابات في رحلة واحدة بدون تجميد event loop
    async with ar.pipeline(transaction=False) as pipe:
        pipe.incr(f"{DEV_ID}{cid}:TotalMsgs:{uid}")
        pipe.incr(f"{DEV_ID}:TotalGroupMsgs:{cid}")
        pipe.sadd(f"{DEV_ID}{cid}:members", uid)
        results = await pipe.execute()
    # تحديث الاسم كل 50 رسالة فقط بدلاً من كل رسالة
    current_msgs = results[0] if results else 0
    if current_msgs == 1 or current_msgs % 50 == 0:
        await ar.set(f"{uid}:bankName", m.from_user.first_name[:25])


@Client.on_edited_message(filters.group, group=10)
async def add_edited_msg_count(c: Client, m: Message):
    if not m.from_user:
        return
    uid, cid = str(m.from_user.id), str(m.chat.id)
    await ar.incr(f"{cid}:TotalEDMsgs:{uid}:{DEV_ID}")


# ─────────────────────────────────────────────────────────────────────────
# معالج الأوامر الرئيسي
# ─────────────────────────────────────────────────────────────────────────

@Client.on_message(filters.text & filters.group, group=11)
async def id_handler(c: Client, m: Message):
    if not m.from_user:
        return
    cid, uid = m.chat.id, m.from_user.id
    if not group_enabled(cid):
        return
    if not can_speak(uid, cid):
        return

    text = resolve_text(m.text, cid)
    k    = botkey()

    # ── جهات الاتصال ──────────────────────────────────────────────────────
    if text == "جهاتي":
        contacts = int(await ar.get(f"{cid}TotalContacts{uid}:{DEV_ID}") or 0)
        return await m.reply(f"{k} عدد جهاتك ↢ {contacts}")

    # ── مجموعاتي ──────────────────────────────────────────────────────────
    if text == "مجموعاتي":
        groups = await ar.smembers(f"{uid}:groups")
        if not groups:
            return await m.reply(f"{k} ماعندك مجموعات")
        return await m.reply(f"{k} عدد مجموعاتك ↼ ( {len(groups)} )")

    # ── تاريخ الإنشاء ─────────────────────────────────────────────────────
    if text in ("انشائي", "الانشاء") and not m.reply_to_message:
        return await m.reply(f"{k} الانشاء ( {await get_creation_date(uid)} )")

    if text in ("الانشاء", "انشائه") and m.reply_to_message and m.reply_to_message.from_user:
        return await m.reply(f"{k} الانشاء ( {await get_creation_date(m.reply_to_message.from_user.id)} )")

    # ── اسمي ──────────────────────────────────────────────────────────────
    if text == "اسمي":
        return await m.reply(m.from_user.first_name, disable_web_page_preview=True)

    # ── معلوماتي ──────────────────────────────────────────────────────────
    if text == "معلوماتي":
        msgs  = int(await ar.get(f"{DEV_ID}{cid}:TotalMsgs:{uid}") or 0)
        edits = int(await ar.get(f"{cid}:TotalEDMsgs:{uid}:{DEV_ID}") or 0)
        tfa3l = _tfa3l_label(msgs)
        username = _get_username(m.from_user)
        rank = await get_rank(uid, cid)
        txt = f"""
⚘ المعلومات
❁ الاسم ↼ {m.from_user.mention}
❁ اليوزر ↼ {username}
❁ الايدي  ↼ `{uid}`
❁ الرتبه ↼ {rank}
┄─┅═ـ═┅─┄
⚘ احصائيات الرسايل
❁ الرسايل ↼ {msgs:,}
❁ التعديل ↼ {edits:,}
❁ التفاعل ↼ {tfa3l}
"""
        return await m.reply(txt)

    # ── بايو ──────────────────────────────────────────────────────────────
    if text == "بايو":
        if await ar.get(f"{cid}:disableBio:{DEV_ID}"):
            return
        target_id = m.reply_to_message.from_user.id if (m.reply_to_message and m.reply_to_message.from_user) else uid
        chat_info = _cache_get(target_id)
        if chat_info is None:
            chat_info = await c.get_chat(target_id)
            _cache_set(target_id, chat_info)
        if not chat_info.bio:
            who = "ماعنده بايو" if m.reply_to_message else "ماعندك بايو"
            return await m.reply(f"{k} {who}")
        return await m.reply(f"`{chat_info.bio}`")

    # ── معلومات المجموعة ──────────────────────────────────────────────────
    if text in ("المجموعه", "المجموعة"):
        cached_full = _cache_get(cid)
        if cached_full is None:
            cached_full = await c.invoke(GetFullChannel(channel=await c.resolve_peer(cid)))
            _cache_set(cid, cached_full)
        get  = cached_full
        link = get.full_chat.exported_invite.link if get.full_chat.exported_invite else "مافي رابط"
        txt  = (
            f"معلومات المجموعة:\n\n"
            f"{k} الاسم ↢ {m.chat.title}\n"
            f"{k} الايدي ↢ `{cid}`\n"
            f"{k} عدد الاعضاء ↢ ( {get.full_chat.participants_count} )\n"
            f"{k} عدد المشرفين ↢ ( {get.full_chat.admins_count} )\n"
            f"{k} عدد المحظورين ↢ ( {get.full_chat.kicked_count} )\n"
            f"{k} الرابط ↢ {link}"
        )
        if m.chat.photo:
            if m.chat.username:
                return await m.reply_photo(f"https://t.me/{m.chat.username}", caption=txt)
            else:
                buf = BytesIO()
                await c.download_media(m.chat.photo.big_file_id, in_memory=True, file_name=buf)
                buf.seek(0)
                buf.name = "chat_photo.jpg"
                await m.reply_photo(buf, caption=txt)
                return
        return await m.reply(txt, disable_web_page_preview=True)

    # ── افتاري ────────────────────────────────────────────────────────────
    if text == "افتاري":
        if await ar.get(f"{cid}:disableAV:{DEV_ID}"):
            return
        return await _send_avatar(c, m, uid)

    # ── افتار (بالرد) ─────────────────────────────────────────────────────
    if text == "افتار" and m.reply_to_message and m.reply_to_message.from_user:
        if await ar.get(f"{cid}:disableAV:{DEV_ID}"):
            return
        return await _send_avatar(c, m, m.reply_to_message.from_user.id)

    # ── افتار (بالايدي/يوزر) ──────────────────────────────────────────────
    parts = text.split()
    if parts[0] == "افتار" and len(parts) == 2:
        if await ar.get(f"{cid}:disableAV:{DEV_ID}"):
            return
        try:    target_id = int(parts[1])
        except ValueError: target_id = parts[1]
        return await _send_avatar(c, m, target_id)

    # ── ايديي ─────────────────────────────────────────────────────────────
    if text == "ايديي":
        return await m.reply(f"( `{uid}` )")

    # ── ايدي (بالرد) ──────────────────────────────────────────────────────
    if text in ("ايدي", "id") and m.reply_to_message and m.reply_to_message.from_user:
        return await m.reply(f"الايدي ↢ ( `{m.reply_to_message.from_user.id}` )")

    # ── ايدي (عام - الأمر الرئيسي) ────────────────────────────────────────
    if text in ("ايدي", "id") and not m.reply_to_message:
        if await ar.get(f"{cid}:disableID:{DEV_ID}"):
            return
        return await _send_id_card(c, m)

    # ── رتبتي ─────────────────────────────────────────────────────────────
    if text == "رتبتي":
        rank = await get_rank(uid, cid)
        return await m.reply(f"{k} رتبتك ↢ {rank}")

    # ── رتبته (بالرد) ─────────────────────────────────────────────────────
    if text == "رتبته" and m.reply_to_message and m.reply_to_message.from_user:
        target = m.reply_to_message.from_user
        rank_bot  = await get_rank(target.id, cid)
        try:
            status    = (await m.chat.get_member(target.id)).status
            rank_chat = _chat_status_label(status)
        except Exception as e:
            logger.error("get_member failed for %s: %s", target.id, e)
            rank_chat = "غير معروف"
        return await m.reply(
            f"رتبته:\n{k} في البوت ( {rank_bot} )\n{k} في المجموعة ( {rank_chat} )\n-"
        )

    # ── رسايلي ────────────────────────────────────────────────────────────
    if text in ("رسايلي", "رسائلي"):
        msgs = int(await ar.get(f"{DEV_ID}{cid}:TotalMsgs:{uid}") or 0)
        return await m.reply(f"{k} عدد رسايلك ↢ {msgs:,}")

    # ── رسايله (بالرد) ────────────────────────────────────────────────────
    if text in ("رسايله", "رسائلة") and m.reply_to_message and m.reply_to_message.from_user:
        msgs = int(await ar.get(f"{DEV_ID}{cid}:TotalMsgs:{m.reply_to_message.from_user.id}") or 0)
        return await m.reply(f"{k} عدد رسايله ↢ {msgs:,}")

    # ── تكليجاتي / تعديلاتي ───────────────────────────────────────────────
    if text in ("تكليجاتي", "تعديلاتي"):
        edits = int(await ar.get(f"{cid}:TotalEDMsgs:{uid}:{DEV_ID}") or 0)
        return await m.reply(f"{k} عدد تكليجاتك ↢ {edits:,}")

    # ── مسح رسائلي ────────────────────────────────────────────────────────
    if text in ("مسح رسائلي", "مسح رسايلي"):
        msgs = int(await ar.get(f"{DEV_ID}{cid}:TotalMsgs:{uid}") or 0)
        await ar.delete(f"{DEV_ID}{cid}:TotalMsgs:{uid}")
        return await m.reply(f"{k} ابشر مسحت ( {msgs:,} ) من رسائلك")

    # ── مسح تكليجاتي ──────────────────────────────────────────────────────
    if text == "مسح تكليجاتي":
        edits = int(await ar.get(f"{cid}:TotalEDMsgs:{uid}:{DEV_ID}") or 0)
        await ar.delete(f"{cid}:TotalEDMsgs:{uid}:{DEV_ID}")
        return await m.reply(f"{k} ابشر مسحت ( {edits:,} ) من تكليجاتك")

    # ── مسح المتفاعلين ────────────────────────────────────────────────────
    if text in ("مسح المتفاعلين", "تصفير المتفاعلين"):
        if not is_owner(uid, cid):
            return await m.reply(f"{k} عذراً الامر يخص ↤〖 المالك 〗فقط .")
        # استخدم set التتبع بدلاً من scan_iter O(N)
        uids_raw = await ar.smembers(f"{DEV_ID}{cid}:members")
        keys = [f"{DEV_ID}{cid}:TotalMsgs:{u}" for u in uids_raw]
        if keys:
            async with ar.pipeline(transaction=False) as pipe:
                for key in keys:
                    pipe.delete(key)
                await pipe.execute()
        return await m.reply(f"{k} ابشر مسحت كل المتفاعلين")

    # ── ترتيبي / تفاعلي ───────────────────────────────────────────────────
    if text in ("ترتيبي", "تفاعلي"):
        # استخدم set التتبع بدلاً من scan_iter O(N)
        uids_raw = await ar.smembers(f"{DEV_ID}{cid}:members")
        users_keys = [f"{DEV_ID}{cid}:TotalMsgs:{u}" for u in uids_raw]
        top = _build_top_list(users_keys)
        ids = [i["id"] for i in top]
        if uid not in ids:
            return await m.reply(f"{k} مافي إحصائيات لك بعد")
        rank_pos = ids.index(uid) + 1
        msgs = int(await ar.get(f"{DEV_ID}{cid}:TotalMsgs:{uid}") or 0)
        return await m.reply(
            f"{k} ترتيبك بالمتفاعلين ↢ {rank_pos}\n"
            f"{k} رسائلك بالتفاعل ↢ {msgs:,}\n-"
        )

    # ── توب المتفاعلين ────────────────────────────────────────────────────
    if text in ("المتفاعلين", "توب المتفاعلين"):
        # استخدم set التتبع بدلاً من scan_iter O(N)
        uids_raw = await ar.smembers(f"{DEV_ID}{cid}:members")
        users_keys = [f"{DEV_ID}{cid}:TotalMsgs:{u}" for u in uids_raw]
        top = _build_top_list(users_keys, with_name=True)
        txt = "- توب اكثر 20 متفاعل :\n━━━━━━━━━\n"
        for i, item in enumerate(top[:20], 1):
            emoji = _emoji_bank(i)
            txt += f"{emoji}{item['msgs']:,} | [{item['name']}](tg://user?id={item['id']})\n"
        return await c.send_message(cid, txt, disable_web_page_preview=True, reply_to_message_id=m.id)

    # ── توب القروبات ──────────────────────────────────────────────────────
    if text in ("القروبات", "توب القروبات"):
        if not is_dev(uid, cid):
            return
        # استخدم enablelist بدلاً من scan_iter O(N)
        group_ids = await ar.smembers(f"enablelist:{DEV_ID}")
        groups_keys = [f"{DEV_ID}:TotalGroupMsgs:{gid}" for gid in group_ids]
        if not groups_keys:
            return await m.reply(f"{botkey()} ما في إحصائيات قروبات بعد")
        # جلب عدادات الرسائل بـ mget واحد
        msg_vals = await ar.mget(groups_keys)
        chat_ids = []
        msgs_map = {}
        for i, gkey in enumerate(groups_keys):
            try:
                chat_id = int(gkey.split("TotalGroupMsgs:")[1])
                chat_ids.append(chat_id)
                msgs_map[chat_id] = int(msg_vals[i] or 0)
            except (ValueError, IndexError) as e:
                logger.error("Failed to parse TotalGroupMsgs key '%s': %s", gkey, e)
                pass
        # جلب عناوين القروبات بالتوازي
        async def _safe_get_title(chat_id):
            try:
                return chat_id, (await c.get_chat(chat_id)).title
            except Exception as e:
                logger.error("get_chat failed for %s: %s", chat_id, e)
                return chat_id, str(chat_id)
        titles = await asyncio.gather(*[_safe_get_title(cid_) for cid_ in chat_ids])
        result = [{"title": t, "id": cid_, "msgs": msgs_map[cid_]} for cid_, t in titles]
        result = sorted(result, key=lambda x: x["msgs"], reverse=True)
        txt = "- توب اكثر 20 قروب متفاعل:\n━━━━━━━━━\n"
        for i, item in enumerate(result[:20], 1):
            txt += f"{_emoji_bank(i)}{item['msgs']:,} | {item['title']}\n"
        return await c.send_message(cid, txt, disable_web_page_preview=True, reply_to_message_id=m.id)

    # ── كشف ───────────────────────────────────────────────────────────────
    # بالرد
    if text == "كشف" and m.reply_to_message and m.reply_to_message.from_user:
        return await _send_kashf(c, m, m.reply_to_message.from_user.id, "بالرد")

    # بالمنشن
    if text.startswith("كشف") and len(text.split()) > 1 and "tg://user?id=" in (m.text.html or ""):
        user_id = int(re.search(r'href="([^"]+)', m.text.html).group(1).split("=")[1])
        return await _send_kashf(c, m, user_id, "بالمنشن")

    # بالايدي أو يوزر
    if text.startswith("كشف") and len(text.split()) == 2:
        raw = text.split()[1]
        try:
            target_id = int(raw); ks = "بالايدي"
        except ValueError:
            target_id = raw.lstrip("@"); ks = "باليوزر"
        return await _send_kashf(c, m, target_id, ks)

    # ── صلاحياتي ──────────────────────────────────────────────────────────
    if text == "صلاحياتي":
        return await _send_permissions(c, m, uid)

    # ── صلاحياته (بالرد) ──────────────────────────────────────────────────
    if text == "صلاحياته" and m.reply_to_message and m.reply_to_message.from_user:
        return await _send_permissions(c, m, m.reply_to_message.from_user.id)

    # ── لقبي ──────────────────────────────────────────────────────────────
    if text == "لقبي":
        member = await m.chat.get_member(uid)
        title  = member.custom_title
        if not title:
            return await m.reply(f"{k} ماعندك لقب")
        return await m.reply(f"{k} لقبك ↢ ( {title} )")

    # ───────────────────────────────────────────────────────────────────────
    # أوامر إدارة شكل الايدي
    # ───────────────────────────────────────────────────────────────────────

    # إلغاء وضع الانتظار
    if await ar.get(f"{cid}:addCustomID:{uid}:{DEV_ID}") and text == "الغاء":
        await ar.delete(f"{cid}:addCustomID:{uid}:{DEV_ID}")
        return await m.reply(f"{k} ابشر تم الغاء تعيين الايدي")

    if await ar.get(f"{cid}:addCustomIDG:{uid}:{DEV_ID}") and text == "الغاء":
        await ar.delete(f"{cid}:addCustomIDG:{uid}:{DEV_ID}")
        return await m.reply(f"{k} ابشر تم الغاء تعيين الايدي عام")

    # استقبال الايدي المخصص (للقروب)
    if await ar.get(f"{cid}:addCustomID:{uid}:{DEV_ID}") and is_mod(uid, cid):
        await ar.set(f"{cid}:customID:{DEV_ID}", m.text)
        await ar.delete(f"{cid}:addCustomID:{uid}:{DEV_ID}")
        return await m.reply(f"{k} وسوينا الايدي\n{k} يمديك تجرب شكل الايدي الجديد الحين")

    # استقبال الايدي المخصص العام
    if await ar.get(f"{cid}:addCustomIDG:{uid}:{DEV_ID}") and is_dev(uid, cid):
        await ar.set(f"customID:{DEV_ID}", m.text)
        await ar.delete(f"{cid}:addCustomIDG:{uid}:{DEV_ID}")
        return await m.reply(f"{k} وسوينا الايدي العام\n{k} يمديك تجرب شكل الايدي الجديد الحين")

    # مسح الايدي
    if text == "مسح الايدي":
        if not is_mod(uid, cid):
            return await m.reply(f"{k} عذراً الامر يخص ↤〖 المدير 〗فقط .")
        if not await ar.get(f"{cid}:customID:{DEV_ID}"):
            return await m.reply(f"{k} الايدي مو معدل")
        await ar.delete(f"{cid}:customID:{DEV_ID}")
        return await m.reply(f"{k} ابشر مسحت الايدي")

    if text in ("مسح الايدي العام", "مسح الايدي عام"):
        if not is_dev(uid, cid):
            return await m.reply(f"{k} عذراً الامر يخص ↤〖 Dev 〗فقط .")
        if not await ar.get(f"customID:{DEV_ID}"):
            return await m.reply(f"{k} الايدي العام مو معدل")
        await ar.delete(f"customID:{DEV_ID}")
        return await m.reply(f"{k} ابشر مسحت الايدي العام")

    # تغيير الايدي (شكل عشوائي)
    if text == "تغيير الايدي":
        if not is_mod(uid, cid):
            return await m.reply(f"{k} عذراً الامر يخص ↤〖 المدير 〗فقط .")
        template = random.choice(CUSTOM_ID_TEMPLATES)
        await ar.set(f"{cid}:customID:{DEV_ID}", template)
        return await m.reply(f"{k} وسوينا الايدي\n{k} يمديك تجرب شكل الايدي الجديد الحين")

    # تعيين الايدي
    if text == "تعيين الايدي":
        if not is_mod(uid, cid):
            return await m.reply(f"{k} عذراً الامر يخص ↤〖 المدير 〗فقط .")
        guide = _id_guide_text()
        await m.reply(guide)
        await ar.set(f"{cid}:addCustomID:{uid}:{DEV_ID}", 1, ex=300)
        return

    if text == "تعيين الايدي عام":
        if not is_dev(uid, cid):
            return await m.reply(f"{k} عذراً الامر يخص ↤〖 Dev 〗فقط .")
        guide = _id_guide_text()
        await m.reply(guide)
        await ar.set(f"{cid}:addCustomIDG:{uid}:{DEV_ID}", 1, ex=300)
        return

    # تفعيل / تعطيل الايدي
    if text == "تفعيل الايدي":
        if not is_admin(uid, cid):
            return await m.reply(f"{k} عذراً الامر يخص ↤〖 الادمن 〗فقط .")
        if not await ar.get(f"{cid}:disableID:{DEV_ID}"):
            return await m.reply(f"{k} بواسطة ↤ {m.from_user.mention}\n{k} الايدي مفعل من قبل")
        await ar.delete(f"{cid}:disableID:{DEV_ID}")
        return await m.reply(f"{k} بواسطة ↤ {m.from_user.mention}\n{k} ابشر فعلت الايدي")

    if text == "تعطيل الايدي":
        if not is_admin(uid, cid):
            return await m.reply(f"{k} عذراً الامر يخص ↤〖 الادمن 〗فقط .")
        if await ar.get(f"{cid}:disableID:{DEV_ID}"):
            return await m.reply(f"{k} بواسطة ↤ {m.from_user.mention}\n{k} الايدي معطل من قبل")
        await ar.set(f"{cid}:disableID:{DEV_ID}", 1)
        return await m.reply(f"{k} بواسطة ↤ {m.from_user.mention}\n{k} ابشر عطلت الايدي")

    # تفعيل / تعطيل الافتار
    if text == "تفعيل افتاري":
        if not is_admin(uid, cid):
            return await m.reply(f"{k} عذراً الامر يخص ↤〖 الادمن 〗فقط .")
        if not await ar.get(f"{cid}:disableAV:{DEV_ID}"):
            return await m.reply(f"{k} بواسطة ↤ {m.from_user.mention}\n{k} افتار مفعل من قبل")
        await ar.delete(f"{cid}:disableAV:{DEV_ID}")
        return await m.reply(f"{k} بواسطة ↤ {m.from_user.mention}\n{k} ابشر فعلت افتار")

    if text == "تعطيل افتاري":
        if not is_admin(uid, cid):
            return await m.reply(f"{k} عذراً الامر يخص ↤〖 الادمن 〗فقط .")
        if await ar.get(f"{cid}:disableAV:{DEV_ID}"):
            return await m.reply(f"{k} بواسطة ↤ {m.from_user.mention}\n{k} افتار معطل من قبل")
        await ar.set(f"{cid}:disableAV:{DEV_ID}", 1)
        return await m.reply(f"{k} بواسطة ↤ {m.from_user.mention}\n{k} ابشر عطلت افتار")

    # تفعيل / تعطيل الايدي بالصوره
    if text == "تفعيل الايدي بالصوره":
        if not is_admin(uid, cid):
            return await m.reply(f"{k} عذراً الامر يخص ↤〖 الادمن 〗فقط .")
        if not await ar.get(f"{cid}:disableIDPHOTO:{DEV_ID}"):
            return await m.reply(f"{k} بواسطة ↤ {m.from_user.mention}\n{k} الايدي بالصوره مفعل من قبل")
        await ar.delete(f"{cid}:disableIDPHOTO:{DEV_ID}")
        return await m.reply(f"{k} بواسطة ↤ {m.from_user.mention}\n{k} ابشر فعلت الايدي بالصوره")

    if text == "تعطيل الايدي بالصوره":
        if not is_admin(uid, cid):
            return await m.reply(f"{k} عذراً الامر يخص ↤〖 الادمن 〗فقط .")
        if await ar.get(f"{cid}:disableIDPHOTO:{DEV_ID}"):
            return await m.reply(f"{k} بواسطة ↤ {m.from_user.mention}\n{k} الايدي بالصوره معطل من قبل")
        await ar.set(f"{cid}:disableIDPHOTO:{DEV_ID}", 1)
        return await m.reply(f"{k} بواسطة ↤ {m.from_user.mention}\n{k} ابشر عطلت الايدي بالصوره")


# ─────────────────────────────────────────────────────────────────────────
# عداد جهات الاتصال عند إضافة عضو
# ─────────────────────────────────────────────────────────────────────────

@Client.on_message(filters.new_chat_members, group=2)
async def add_contact_count(c: Client, m: Message):
    if not m.from_user:
        return
    for member in m.new_chat_members:
        if m.from_user.id != member.id:  # من أضاف شخصاً آخر
            await ar.incr(f"{m.chat.id}TotalContacts{m.from_user.id}:{DEV_ID}")


# ─────────────────────────────────────────────────────────────────────────
# دوال مساعدة
# ─────────────────────────────────────────────────────────────────────────

def _get_username(user) -> str:
    if getattr(user, "usernames", None):
        return " ".join(f"@{u.username}" for u in user.usernames)
    if user.username:
        return f"@{user.username}"
    return "مافي يوزر"


def _chat_status_label(status) -> str:
    return {
        ChatMemberStatus.OWNER:         "المالك",
        ChatMemberStatus.ADMINISTRATOR: "مشرف",
        ChatMemberStatus.RESTRICTED:    "مقيد",
        ChatMemberStatus.LEFT:          "طالع",
        ChatMemberStatus.MEMBER:        "عضو",
        ChatMemberStatus.BANNED:        "لاقم حظر",
    }.get(status, "غير معروف")


def _build_top_list(keys, with_name: bool = False) -> list[dict]:
    if not keys:
        return []
    # جلب عدادات الرسائل بطلب mget واحد
    msg_vals = r.mget(keys)
    # جلب الأسماء بطلب mget واحد إذا احتجناها
    uids = []
    for key in keys:
        try:
            uids.append(int(key.split("TotalMsgs:")[1]))
        except (ValueError, IndexError) as e:
            logger.error("Failed to parse TotalMsgs key '%s': %s", key, e)
            uids.append(None)
    name_vals = None
    if with_name:
        name_keys = [f"{uid}:bankName" if uid else "" for uid in uids]
        name_vals = r.mget(name_keys) if name_keys else []
    result = []
    for i, key in enumerate(keys):
        try:
            uid  = uids[i]
            if uid is None:
                continue
            msgs = int(msg_vals[i] or 0)
            item = {"id": uid, "msgs": msgs}
            if with_name:
                item["name"] = (name_vals[i] if name_vals else None) or str(uid)
            result.append(item)
        except Exception as e:
            logger.error("Failed to build result item at index %d: %s", i, e)
            pass
    return sorted(result, key=lambda x: x["msgs"], reverse=True)


async def _send_avatar(c: Client, m: Message, target_id):
    k = botkey()
    try:
        target = _cache_get(target_id)
        if target is None:
            target = await c.get_chat(target_id)
            _cache_set(target_id, target)
        if not target.photo:
            msg = "مقدر اجيب افتاره يمكن حاظرني" if target_id != m.from_user.id else "ماقدر اجيب افتارك ارسل نقطه خاص وارجع جرب"
            return await m.reply(f"{k} {msg}")
        if target.username:
            photo = f"http://t.me/{target.username}"
        else:
            async for p in c.get_chat_photos(target.id, limit=1):
                photo = p.file_id
        bio     = target.bio  # استخدام الكائن المحفوظ بدل استدعاء get_chat مرة ثانية
        caption = f"`{bio}`" if bio else None
        return await m.reply_photo(photo, caption=caption)
    except Exception as e:
        logger.warning("%s", e)
        return await m.reply(f"{k} ما قدرت اجيب الافتار")


async def _send_kashf(c: Client, m: Message, target_id, method: str):
    k   = botkey()
    cid = m.chat.id
    try:
        member   = await m.chat.get_member(target_id)
        user     = member.user
        rank_bot = await get_rank(user.id, cid)
        msgs     = int(await ar.get(f"{DEV_ID}{cid}:TotalMsgs:{user.id}") or 0)
        username = _get_username(user)
        status   = _chat_status_label(member.status)
        txt = (
            f"\n{k} الاسم ↢ {user.first_name}\n"
            f"{k} الايدي ↢ `{user.id}`\n"
            f"{k} اليوزر : ( {username} )\n"
            f"{k} الرتبه ↢ ( {rank_bot} )\n"
            f"{k} الرسائل ↢ ( {msgs:,} )\n"
            f"{k} بالمجموعة ↢ ( {status} )\n"
            f"{k} نوع الكشف ↢ {method}\n-\n"
        )
        return await m.reply(txt, disable_web_page_preview=True)
    except Exception as e:
        logger.error("_send_kashf failed for target %s: %s", target_id, e)
        return await m.reply(f"{k} العضو مو بالمجموعة")


async def _send_permissions(c: Client, m: Message, target_id: int):
    k   = botkey()
    cid = m.chat.id
    try:
        member = await m.chat.get_member(target_id)
    except Exception as e:
        logger.error("get_member failed for %s: %s", target_id, e)
        return await m.reply(f"{k} ما قدرت جيب معلومات العضو")

    is_self = (target_id == m.from_user.id)
    prefix  = "انت" if is_self else "هو"

    if member.status == ChatMemberStatus.OWNER:
        return await m.reply(f"{k} {prefix} المالك وعنده كل الصلاحيات")
    if member.status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
        return await m.reply(f"{k} {prefix} العضو وماعنده صلاحيات")

    p  = member.privileges
    t  = lambda v: "✔️" if v else "✖️"
    txt = f"""
{k} {'انت مشرف' if is_self else 'هو مشرف'} وهذي صلاحياته{'ك' if is_self else ''}:

1) - ادارة المجموعة ↼ ( {t(p.can_manage_chat)} )
2) - مسح الرسائل ↼ ( {t(p.can_delete_messages)} )
3) - ادارة مكالمات ↼ ( {t(p.can_manage_video_chats)} )
4) - تقييد الأعضاء وحظرهم ↼ ( {t(p.can_restrict_members)} )
5) - رفع المشرفين ↼ ( {t(p.can_promote_members)} )
6) - تعديل معلومات المجموعة ↼ ( {t(p.can_change_info)} )
7) - تثبيت الرسايل ↼ ( {t(p.can_pin_messages)} )
"""
    return await m.reply(txt)


async def _send_id_card(c: Client, m: Message):
    k   = botkey()
    cid = m.chat.id
    uid = m.from_user.id

    # جلب القالب
    template = (
        await ar.get(f"{cid}:customID:{DEV_ID}") or
        await ar.get(f"customID:{DEV_ID}") or
        DEFAULT_ID_TEMPLATE
    )

    username = _get_username(m.from_user)
    rank     = await get_rank(uid, cid)   # كانت ناقصة await — bug إصلاح
    msgs     = int(await ar.get(f"{DEV_ID}{cid}:TotalMsgs:{uid}") or 0)
    edits    = int(await ar.get(f"{cid}:TotalEDMsgs:{uid}:{DEV_ID}") or 0)
    name     = m.from_user.first_name
    create   = await get_creation_date(uid)
    chat_inf = _cache_get(uid)
    if chat_inf is None:
        chat_inf = await c.get_chat(uid)
        _cache_set(uid, chat_inf)
    bio      = chat_inf.bio or "مافي بايو"
    tfa3l    = _tfa3l_label(msgs)
    comment  = random.choice(COMMENTS)

    text = (template
        .replace("{الاسم}",    name)
        .replace("{اليوزر}",   username)
        .replace("{الرسائل}",  f"{msgs:,}")
        .replace("{التعديل}",  f"{edits:,}")
        .replace("{الانشاء}",  create)
        .replace("{البايو}",   bio)
        .replace("{الايدي}",   f"`{uid}`")
        .replace("{الرتبه}",   rank)
        .replace("{التفاعل}",  tfa3l)
        .replace("{تعليق}",    comment)
    )

    # إذا الايدي بدون صورة
    if await ar.get(f"{cid}:disableIDPHOTO:{DEV_ID}") or not m.from_user.photo:
        return await m.reply(text, disable_web_page_preview=True)

    # إرسال مع الصورة / الفيديو
    try:
        full_user = await c.invoke(GetFullUser(id=(await c.resolve_peer(uid))))
        photo     = full_user.full_user.profile_photo
        video     = photo.video_sizes if photo else None

        if video:
            v = video[-2] if len(video) == 3 else video[-1]
            cache_key = f"{photo.access_hash}:{uid}"
            if await ar.get(cache_key):
                return await m.reply_animation(await ar.get(cache_key), caption=text)
            file_id_obj = FileId(
                file_type=FileType.PHOTO, dc_id=photo.dc_id,
                media_id=photo.id, access_hash=photo.access_hash,
                file_reference=photo.file_reference,
                thumbnail_source=ThumbnailSource.THUMBNAIL,
                thumbnail_file_type=FileType.PHOTO,
                thumbnail_size=v.type, volume_id=0, local_id=0
            ).encode()
            buf = await c.download_media(file_id_obj, in_memory=True)
            if not isinstance(buf, BytesIO):
                buf = BytesIO(buf)
            buf.name = f"{uid}vid{cid}.mp4"
            sent = await m.reply_animation(buf, caption=text)
            await ar.set(cache_key, sent.animation.file_id, ex=3600)
            return

        if photo:
            fid = FileId(
                file_type=FileType.PHOTO, dc_id=photo.dc_id,
                media_id=photo.id, access_hash=photo.access_hash,
                file_reference=photo.file_reference,
                thumbnail_source=ThumbnailSource.THUMBNAIL,
                thumbnail_file_type=FileType.PHOTO,
                thumbnail_size=photo.sizes[0].type,
                volume_id=0, local_id=0
            ).encode()
            return await m.reply_photo(fid, caption=text)
    except Exception as e:
        logger.warning("%s", e)

    return await m.reply(text, disable_web_page_preview=True)


def _id_guide_text() -> str:
    return """
تمام , الحين ارسل شكل الايدي الجديد

- الاختصارات:

{الاسم} ↼ يطلع اسم الشخص
{الايدي} ↼ يطلع ايدي الشخص
{اليوزر} ↼ يطلع يوزر الشخص
{الرتبه} ↼ يطلع رتبه الشخص
{التفاعل} ↼ يطلع تفاعل الشخص
{الرسائل} ↼ يطلع كم رسالة عند الشخص
{التعديل} ↼ يطلع كم مره عدل الشخص
{البايو} ↼ يطلع البايو اللي كاتبه
{تعليق} ↼ يطلع تعليق عشوائي
{الانشاء} ↼ يطلع انشاء الحساب
"""
