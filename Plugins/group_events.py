"""
أحداث المجموعة - تتبع الأحداث وإعلام المطور
"""
import asyncio
import time
from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus, ChatMembersFilter
from pyrogram.types import (
    Message, ChatMemberUpdated,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

from config import r, DEV_ID, botkey, botname as _botname, ar
from helpers.ranks import is_dev, get_rank, get_devs
from helpers.utils import group_enabled

_BOT_ID: int | None = None

# cache لعدد أعضاء المجموعة — TTL دقيقتان
_MEMBERS_COUNT_CACHE: dict[int, tuple[int, float]] = {}
_MEMBERS_COUNT_TTL = 120  # ثانية

def _members_count_cache_get(cid: int) -> int | None:
    entry = _MEMBERS_COUNT_CACHE.get(cid)
    if entry and time.monotonic() - entry[1] < _MEMBERS_COUNT_TTL:
        return entry[0]
    return None

def _members_count_cache_set(cid: int, count: int) -> None:
    _MEMBERS_COUNT_CACHE[cid] = (count, time.monotonic())


async def _get_bot_id(c) -> int:
    global _BOT_ID
    if _BOT_ID is None:
        me = await c.get_me()
        _BOT_ID = me.id
    return _BOT_ID


async def _dev_notify(c, text: str, reply_markup=None):
    """يُرسل رسالة للمطور أو مجموعة المطورين — بدون sleep بين الرسائل"""
    try:
        dev_group = await ar.get(f"DevGroup:{DEV_ID}")
    except Exception:
        dev_group = None

    if dev_group:
        try:
            await c.send_message(int(dev_group), text,
                           disable_web_page_preview=True,
                           reply_markup=reply_markup)
        except Exception:
            pass
    else:
        devs = await get_devs()
        # أرسل لكل المطورين بشكل متوازٍ — بدون sleep بينهم
        await asyncio.gather(*[
            c.send_message(int(dev), text,
                           disable_web_page_preview=True,
                           reply_markup=reply_markup)
            for dev in devs
        ], return_exceptions=True)


@Client.on_message(filters.left_chat_member, group=6)
async def on_left_member(c: Client, m: Message):
    cid = m.chat.id
    k = botkey()

    bot_id = await _get_bot_id(c)
    if m.left_chat_member.id == bot_id:
        uid  = m.from_user.id if m.from_user else 0
        usr  = m.from_user
        mention_str  = usr.mention if usr else str(uid)
        username_str = "@" + usr.username if (usr and usr.username) else "مافيه"
        group_user_str = "@" + m.chat.username if m.chat.username else "مافيه"
        text = (
            f"{k} من「 {mention_str} 」\n"
            f"{k} يوزره : {username_str}\n"
            f"{k} ايديه : `{uid}`\n\n"
            f"{k} قام بطرد البوت من المجموعة:\n\n"
            f"{k} اسم المجموعة : {m.chat.title}\n"
            f"{k} يوزر المجموعة : {group_user_str}\n"
            f"{k} ايدي المجموعة : `{cid}`\n"
            f"{k} تم مسح بيانات المجموعة\n\n☆"
        )
        try:
            await ar.srem(f"enablelist:{DEV_ID}", cid)
            await ar.delete(f"{cid}:enable:{DEV_ID}")
            groups_count = await ar.scard(f"enablelist:{DEV_ID}")
            if groups_count:
                text += f"\n{k} عدد المجموعات الآن: {groups_count}"
        except Exception:
            pass
        try:
            await _dev_notify(c, text)
        except Exception:
            pass
        return

    if not group_enabled(cid):
        return
    try:
        if not await ar.get(f"{cid}:trackLeave:{DEV_ID}"):
            return
    except Exception:
        return
    try:
        await m.reply(
            f"{k} غادر المجموعة: {m.left_chat_member.mention}",
            disable_web_page_preview=True,
        )
    except Exception:
        pass


@Client.on_message(filters.text & filters.group, group=8)
async def group_settings(c: Client, m: Message):
    if not m.from_user:
        return
    cid, uid = m.chat.id, m.from_user.id
    if not group_enabled(cid):
        return

    text = m.text.strip() if m.text else ""
    k    = botkey()

    if text == "تفعيل مغادرة":
        if not is_dev(uid, cid):
            return await m.reply(f"{k} هذا الأمر للمطور فقط")
        await ar.set(f"{cid}:trackLeave:{DEV_ID}", 1)
        return await m.reply(f"{k} سيتم الإعلان عن مغادرة الأعضاء ✅")

    if text == "تعطيل مغادرة":
        if not is_dev(uid, cid):
            return await m.reply(f"{k} هذا الأمر للمطور فقط")
        await ar.delete(f"{cid}:trackLeave:{DEV_ID}")
        return await m.reply(f"{k} تم تعطيل إعلان المغادرة")

    if text == "معلومات":
        rank = await get_rank(uid, cid)
        members_count = _members_count_cache_get(cid)
        if members_count is None:
            members_count = await c.get_chat_members_count(cid)
            _members_count_cache_set(cid, members_count)
        return await m.reply(
            f"{k} **معلومات المجموعة**\n\n"
            f"الاسم: **{m.chat.title}**\n"
            f"الأيدي: `{cid}`\n"
            f"عدد الأعضاء: **{members_count}**\n\n"
            f"{k} **معلوماتك**\n"
            f"الاسم: {m.from_user.mention}\n"
            f"الأيدي: `{uid}`\n"
            f"رتبتك: **{rank}**"
        )


@Client.on_chat_member_updated(filters.group, group=5)
async def chat_member_updated(c: Client, m: ChatMemberUpdated):
    k = botkey()
    try:
        if not m.new_chat_member:
            return
        bot_id = await _get_bot_id(c)
        if m.new_chat_member.user.id != bot_id:
            return

        cid = m.chat.id
        adder_id = m.from_user.id if m.from_user else 0
        adder_mention = m.from_user.mention if m.from_user else str(adder_id)
        status = m.new_chat_member.status

        if status == ChatMemberStatus.MEMBER:
            if await ar.get(f"{cid}:enable:{DEV_ID}"):
                await c.send_message(cid, f"{k} من「 {adder_mention} 」\n{k} تم تعطيل المجموعة تلقائياً\n☆")
                await ar.delete(f"{cid}:enable:{DEV_ID}")
                await ar.srem(f"enablelist:{DEV_ID}", cid)

        elif status == ChatMemberStatus.ADMINISTRATOR:
            priv = m.new_chat_member.privileges
            full_priv = (priv and priv.can_manage_chat and priv.can_delete_messages
                         and priv.can_restrict_members and priv.can_pin_messages
                         and priv.can_invite_users)

            if not full_priv:
                if await ar.get(f"{cid}:enable:{DEV_ID}"):
                    await c.send_message(cid, f"{k} من「 {adder_mention} 」\n{k} تم تعطيل المجموعة - الصلاحيات غير كاملة\n☆")
                    await ar.delete(f"{cid}:enable:{DEV_ID}")
                    await ar.srem(f"enablelist:{DEV_ID}", cid)
            else:
                if not await ar.get(f"{cid}:enable:{DEV_ID}"):
                    if await ar.get(f"DisableBot:{DEV_ID}"):
                        return await c.send_message(cid, f"{k} تم تعطيل البوت الخدمي من المطور")
                    async with ar.pipeline(transaction=False) as pipe:
                        pipe.set(f"{cid}:enable:{DEV_ID}", 1)
                        pipe.sadd(f"enablelist:{DEV_ID}", cid)
                        pipe.set(f"{cid}:rankOWNER:{adder_id}:{DEV_ID}", 1)
                        pipe.sadd(f"{cid}:rankOWNERs:{DEV_ID}", adder_id)
                        await pipe.execute()
                    from pyrogram.enums import ChatMembersFilter
                    async with ar.pipeline(transaction=False) as adm_pipe:
                        async for member in c.get_chat_members(cid, filter=ChatMembersFilter.ADMINISTRATORS):
                            if not member.user.is_bot and not member.user.is_deleted:
                                if member.status == ChatMemberStatus.OWNER:
                                    adm_pipe.set(f"{cid}:rankGOWNER:{member.user.id}:{DEV_ID}", 1)
                                    adm_pipe.sadd(f"{cid}:rankGOWNERs:{DEV_ID}", member.user.id)
                                elif member.status == ChatMemberStatus.ADMINISTRATOR:
                                    adm_pipe.set(f"{cid}:rankADMIN:{member.user.id}:{DEV_ID}", 1)
                                    adm_pipe.sadd(f"{cid}:rankADMINs:{DEV_ID}", member.user.id)
                        await adm_pipe.execute()

                    # _BOT_ID مضمون هنا — استخدم c.me مباشرة بدلاً من API call جديد
                    bot_username = (c.me.username if c.me else "") or ""
                    await c.send_message(
                        cid,
                        f"{k} من「 {adder_mention} 」\n{k} تم تفعيل المجموعة تلقائياً ✅\n☆",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("Commands", url=f"https://t.me/{bot_username}?start=Commands")
                        ]]) if bot_username else None,
                    )
                    chat = await c.get_chat(cid)
                    groups_count = await ar.scard(f"enablelist:{DEV_ID}")
                    notify_text = (
                        f"{k} من「 {adder_mention} 」\n"
                        f"{k} يوزره : {'@'+m.from_user.username if m.from_user and m.from_user.username else 'مافيه'}\n"
                        f"{k} ايديه : `{adder_id}`\n\n"
                        f"{k} تم تفعيل البوت بمجموعة جديدة:\n\n"
                        f"{k} اسم المجموعة : {m.chat.title}\n"
                        f"{k} يوزر المجموعة : {'@'+m.chat.username if m.chat.username else 'مافيه'}\n"
                        f"{k} ايدي المجموعة : `{cid}`\n"
                        f"{k} عدد المجموعات الآن : {groups_count}\n\n☆"
                    )
                    markup = None
                    if chat.invite_link:
                        markup = InlineKeyboardMarkup([[InlineKeyboardButton(m.chat.title, url=chat.invite_link)]])
                    await _dev_notify(c, notify_text, markup)
    except Exception:
        pass
