"""
إدارة الكتم والحظر
أوامر:
  كتم (رد) / كتم @user / كتم عام (رد) / كتم عام @user
  الغاء الكتم (رد) / الغاء الكتم @user / الغاء الكتم العام (رد)
  حظر عام (رد) / حظر عام @user
  حظر عام من الالعاب (رد) / حظر عام من الالعاب @user
  الغاء الحظر العام (رد) / الغاء الحظر العام @user
  الغاء الحظر العام من الالعاب (رد) / الغاء الحظر العام من الالعاب @user
  مسح المكتومين / مسح المكتومين عام / مسح المحظورين عام
"""
import asyncio
import re
from pyrogram import Client, filters
from pyrogram.errors import FloodWait
from pyrogram.types import Message

from config import r, DEV_ID, botkey, ar
from helpers.ranks import (
    get_rank, is_admin, is_mod, is_dev, is_pre,
)
from helpers.utils import group_enabled, resolve_text, can_speak, is_gbanned, utils_cache_invalidate
from config import cache_invalidate_prefix


# ───────────────────────── مساعد استخراج المستخدم ─────────────────────────

async def _resolve_user(c: Client, m: Message, target: str):
    if target is None and m.reply_to_message and m.reply_to_message.from_user:
        u = m.reply_to_message.from_user
        return u.id, u.mention
    if target is None:
        return None, None
    try:
        uid = int(target)
    except ValueError:
        uid = target.lstrip("@")
    try:
        u = await c.get_users(uid)
        return u.id, u.mention
    except Exception:
        return None, None


# ─────────── مساعدات الكتم/الحظر — FIX #3: إلغاء تكرار الكود ──────────────

async def _do_mute(m: Message, target_id: int, target_mention: str,
                   cid: int, is_global: bool = False):
    """تنفيذ عملية الكتم (محلي أو عام) عبر pipeline واحد"""
    k = botkey()
    if is_global:
        key      = f"{target_id}:mute:{DEV_ID}"
        list_key = f"listMUTE:{DEV_ID}"
        already  = f"「 {target_mention} 」\n{k} مكتوم عاماً مسبقاً"
        success  = f"「 {target_mention} 」\n{k} تم كتمه عاماً ✅\n☆"
    else:
        key      = f"{target_id}:mute:{cid}:{DEV_ID}"
        list_key = f"{cid}:listMUTE:{DEV_ID}"
        already  = f"「 {target_mention} 」\n{k} مكتوم مسبقاً"
        success  = f"「 {target_mention} 」\n{k} تم كتمه ✅\n☆"

    if await ar.get(key):
        return await m.reply(already)
    async with ar.pipeline(transaction=False) as pipe:
        pipe.set(key, 1)
        pipe.sadd(list_key, target_id)
        await pipe.execute()
    utils_cache_invalidate(key)
    return await m.reply(success)


async def _do_unmute(m: Message, target_id: int, target_mention: str,
                     cid: int, is_global: bool = False):
    """تنفيذ عملية رفع الكتم (محلي أو عام) عبر pipeline واحد"""
    k = botkey()
    if is_global:
        key       = f"{target_id}:mute:{DEV_ID}"
        list_key  = f"listMUTE:{DEV_ID}"
        not_muted = f"「 {target_mention} 」\n{k} غير مكتوم عاماً"
        success   = f"「 {target_mention} 」\n{k} تم رفع الكتم العام ✅\n☆"
    else:
        key       = f"{target_id}:mute:{cid}:{DEV_ID}"
        list_key  = f"{cid}:listMUTE:{DEV_ID}"
        not_muted = f"「 {target_mention} 」\n{k} غير مكتوم"
        success   = f"「 {target_mention} 」\n{k} تم رفع الكتم ✅\n༄"

    if not await ar.get(key):
        return await m.reply(not_muted)
    async with ar.pipeline(transaction=False) as pipe:
        pipe.delete(key)
        pipe.srem(list_key, target_id)
        await pipe.execute()
    utils_cache_invalidate(key)
    return await m.reply(success)


async def _do_gban(m: Message, target_id: int, target_mention: str,
                   games: bool = False):
    """تنفيذ عملية الحظر العام (عادي أو من الألعاب) عبر pipeline واحد"""
    k = botkey()
    if games:
        key      = f"{target_id}:gbangames:{DEV_ID}"
        list_key = f"listGBANGAMES:{DEV_ID}"
        already  = f"「 {target_mention} 」\n{k} محظور من الالعاب مسبقاً"
        success  = f"「 {target_mention} 」\n{k} تم حظره من الالعاب عاماً 🔴\n☆"
    else:
        key      = f"{target_id}:gban:{DEV_ID}"
        list_key = f"listGBAN:{DEV_ID}"
        already  = f"「 {target_mention} 」\n{k} محظور عاماً مسبقاً"
        success  = f"「 {target_mention} 」\n{k} تم حظره عاماً 🔴\n☆"

    if await ar.get(key):
        return await m.reply(already)
    async with ar.pipeline(transaction=False) as pipe:
        pipe.set(key, 1)
        pipe.sadd(list_key, target_id)
        if games:
            pipe.delete(f"{target_id}:Floos")
            pipe.srem("BankList", target_id)
        await pipe.execute()
    utils_cache_invalidate(key)
    return await m.reply(success)


async def _do_ungban(m: Message, target_id: int, target_mention: str,
                     games: bool = False):
    """تنفيذ عملية رفع الحظر العام (عادي أو من الألعاب) عبر pipeline واحد"""
    k = botkey()
    if games:
        key        = f"{target_id}:gbangames:{DEV_ID}"
        list_key   = f"listGBANGAMES:{DEV_ID}"
        not_banned = f"「 {target_mention} 」\n{k} غير محظور من الالعاب عاماً"
        success    = f"「 {target_mention} 」\n{k} تم رفع حظره من الالعاب ✅\n☆"
    else:
        key        = f"{target_id}:gban:{DEV_ID}"
        list_key   = f"listGBAN:{DEV_ID}"
        not_banned = f"「 {target_mention} 」\n{k} غير محظور عاماً"
        success    = f"「 {target_mention} 」\n{k} تم رفع الحظر العام ✅\n☆"

    if not await ar.get(key):
        return await m.reply(not_banned)
    async with ar.pipeline(transaction=False) as pipe:
        pipe.delete(key)
        pipe.srem(list_key, target_id)
        await pipe.execute()
    utils_cache_invalidate(key)
    return await m.reply(success)


# ─────────────────── حذف رسائل المكتوم/المحظور ──────────────────────────
# FIX #2: أضفنا filters.incoming لتخطي رسائل الخدمة (انضمام/مغادرة إلخ)

@Client.on_message(filters.incoming & filters.group, group=15)
async def enforce_mute_gban(c: Client, m: Message):
    if not m.from_user:
        return
    uid = m.from_user.id
    cid = m.chat.id

    if not group_enabled(cid):
        return

    if is_gbanned(uid):
        try:
            await m.chat.ban_member(uid)
        except Exception:
            try:
                await m.delete()
            except Exception:
                pass
        return

    if not can_speak(uid, cid):
        try:
            await m.delete()
        except FloodWait as fw:
            await asyncio.sleep(fw.value)
        except Exception:
            pass


# ───────────────────────── معالج أوامر الكتم/الحظر ────────────────────────

@Client.on_message(filters.text & filters.group, group=14)
async def mute_handler(c: Client, m: Message):
    if not m.from_user:
        return
    cid, uid = m.chat.id, m.from_user.id
    if not group_enabled(cid):
        return
    if not can_speak(uid, cid):
        return

    text = resolve_text(m.text, cid)
    k    = botkey()

    if text == "كتم" and m.reply_to_message and m.reply_to_message.from_user:
        if not is_admin(uid, cid):
            return await m.reply(f"{k} هذا الأمر يخص الادمن وفوق فقط")
        target_id      = m.reply_to_message.from_user.id
        target_mention = m.reply_to_message.from_user.mention
        if target_id == uid:
            return await m.reply(f"{k} ما تقدر تكتم نفسك 😅")
        if is_pre(target_id, cid):
            _rk = await get_rank(target_id, cid)
            return await m.reply(f"{k} ما تقدر تكتم {_rk}")
        return await _do_mute(m, target_id, target_mention, cid)

    m_local = re.fullmatch(r"كتم\s+(@?\S+)", text)
    if m_local:
        if not is_admin(uid, cid):
            return await m.reply(f"{k} هذا الأمر يخص الادمن وفوق فقط")
        target_id, target_mention = await _resolve_user(c, m, m_local.group(1))
        if target_id is None:
            return await m.reply(f"{k} ما لقيت هذا المستخدم")
        if target_id == uid:
            return await m.reply(f"{k} ما تقدر تكتم نفسك 😅")
        if is_pre(target_id, cid):
            _rk = await get_rank(target_id, cid)
            return await m.reply(f"{k} ما تقدر تكتم {_rk}")
        return await _do_mute(m, target_id, target_mention, cid)

    if text == "كتم عام" and m.reply_to_message and m.reply_to_message.from_user:
        if not is_dev(uid, cid):
            return await m.reply(f"{k} هذا الأمر يخص المطور فقط")
        target_id      = m.reply_to_message.from_user.id
        target_mention = m.reply_to_message.from_user.mention
        if is_dev(target_id, cid):
            _rk = await get_rank(target_id, cid)
            return await m.reply(f"{k} ما تقدر تكتم {_rk}")
        return await _do_mute(m, target_id, target_mention, cid, is_global=True)

    m_gmute = re.fullmatch(r"كتم عام\s+(@?\S+)", text)
    if m_gmute:
        if not is_dev(uid, cid):
            return await m.reply(f"{k} هذا الأمر يخص المطور فقط")
        target_id, target_mention = await _resolve_user(c, m, m_gmute.group(1))
        if target_id is None:
            return await m.reply(f"{k} ما لقيت هذا المستخدم")
        if is_dev(target_id, cid):
            _rk = await get_rank(target_id, cid)
            return await m.reply(f"{k} ما تقدر تكتم {_rk}")
        return await _do_mute(m, target_id, target_mention, cid, is_global=True)

    if text == "الغاء الكتم" and m.reply_to_message and m.reply_to_message.from_user:
        if not is_admin(uid, cid):
            return await m.reply(f"{k} هذا الأمر يخص الادمن وفوق فقط")
        target_id      = m.reply_to_message.from_user.id
        target_mention = m.reply_to_message.from_user.mention
        return await _do_unmute(m, target_id, target_mention, cid)

    m_unmute = re.fullmatch(r"الغاء الكتم\s+(@?\S+)", text)
    if m_unmute:
        if not is_admin(uid, cid):
            return await m.reply(f"{k} هذا الأمر يخص الادمن وفوق فقط")
        target_id, target_mention = await _resolve_user(c, m, m_unmute.group(1))
        if target_id is None:
            return await m.reply(f"{k} ما لقيت هذا المستخدم")
        return await _do_unmute(m, target_id, target_mention, cid)

    if text == "الغاء الكتم العام" and m.reply_to_message and m.reply_to_message.from_user:
        if not is_dev(uid, cid):
            return await m.reply(f"{k} هذا الأمر يخص المطور فقط")
        target_id      = m.reply_to_message.from_user.id
        target_mention = m.reply_to_message.from_user.mention
        return await _do_unmute(m, target_id, target_mention, cid, is_global=True)

    m_ungmute = re.fullmatch(r"الغاء الكتم العام\s+(@?\S+)", text)
    if m_ungmute:
        if not is_dev(uid, cid):
            return await m.reply(f"{k} هذا الأمر يخص المطور فقط")
        target_id, target_mention = await _resolve_user(c, m, m_ungmute.group(1))
        if target_id is None:
            return await m.reply(f"{k} ما لقيت هذا المستخدم")
        return await _do_unmute(m, target_id, target_mention, cid, is_global=True)

    if text == "حظر عام" and m.reply_to_message and m.reply_to_message.from_user:
        if not is_dev(uid, cid):
            return await m.reply(f"{k} هذا الأمر يخص المطور فقط")
        target_id      = m.reply_to_message.from_user.id
        target_mention = m.reply_to_message.from_user.mention
        if is_dev(target_id, cid):
            _rk = await get_rank(target_id, cid)
            return await m.reply(f"{k} ما تقدر تحظر {_rk}")
        return await _do_gban(m, target_id, target_mention)

    m_gban = re.fullmatch(r"حظر عام\s+(@?\S+)", text)
    if m_gban:
        if not is_dev(uid, cid):
            return await m.reply(f"{k} هذا الأمر يخص المطور فقط")
        target_id, target_mention = await _resolve_user(c, m, m_gban.group(1))
        if target_id is None:
            return await m.reply(f"{k} ما لقيت هذا المستخدم")
        if is_dev(target_id, cid):
            _rk = await get_rank(target_id, cid)
            return await m.reply(f"{k} ما تقدر تحظر {_rk}")
        return await _do_gban(m, target_id, target_mention)

    if text == "حظر عام من الالعاب" and m.reply_to_message and m.reply_to_message.from_user:
        if not is_dev(uid, cid):
            return await m.reply(f"{k} هذا الأمر يخص المطور فقط")
        target_id      = m.reply_to_message.from_user.id
        target_mention = m.reply_to_message.from_user.mention
        if is_dev(target_id, cid):
            _rk = await get_rank(target_id, cid)
            return await m.reply(f"{k} ما تقدر تحظر {_rk}")
        return await _do_gban(m, target_id, target_mention, games=True)

    m_gbangames = re.fullmatch(r"حظر عام من الالعاب\s+(@?\S+)", text)
    if m_gbangames:
        if not is_dev(uid, cid):
            return await m.reply(f"{k} هذا الأمر يخص المطور فقط")
        target_id, target_mention = await _resolve_user(c, m, m_gbangames.group(1))
        if target_id is None:
            return await m.reply(f"{k} ما لقيت هذا المستخدم")
        if is_dev(target_id, cid):
            _rk = await get_rank(target_id, cid)
            return await m.reply(f"{k} ما تقدر تحظر {_rk}")
        return await _do_gban(m, target_id, target_mention, games=True)

    if text == "الغاء الحظر العام" and m.reply_to_message and m.reply_to_message.from_user:
        if not is_dev(uid, cid):
            return await m.reply(f"{k} هذا الأمر يخص المطور فقط")
        target_id      = m.reply_to_message.from_user.id
        target_mention = m.reply_to_message.from_user.mention
        return await _do_ungban(m, target_id, target_mention)

    m_ungban = re.fullmatch(r"الغاء الحظر العام\s+(@?\S+)", text)
    if m_ungban:
        if not is_dev(uid, cid):
            return await m.reply(f"{k} هذا الأمر يخص المطور فقط")
        target_id, target_mention = await _resolve_user(c, m, m_ungban.group(1))
        if target_id is None:
            return await m.reply(f"{k} ما لقيت هذا المستخدم")
        return await _do_ungban(m, target_id, target_mention)

    if text == "الغاء الحظر العام من الالعاب" and m.reply_to_message and m.reply_to_message.from_user:
        if not is_dev(uid, cid):
            return await m.reply(f"{k} هذا الأمر يخص المطور فقط")
        target_id      = m.reply_to_message.from_user.id
        target_mention = m.reply_to_message.from_user.mention
        return await _do_ungban(m, target_id, target_mention, games=True)

    m_ungbangames = re.fullmatch(r"الغاء الحظر العام من الالعاب\s+(@?\S+)", text)
    if m_ungbangames:
        if not is_dev(uid, cid):
            return await m.reply(f"{k} هذا الأمر يخص المطور فقط")
        target_id, target_mention = await _resolve_user(c, m, m_ungbangames.group(1))
        if target_id is None:
            return await m.reply(f"{k} ما لقيت هذا المستخدم")
        return await _do_ungban(m, target_id, target_mention, games=True)

    # ── مسح المكتومين — FIX #1: pipeline واحد بدلاً من N*2 طلب Redis ──────
    if text == "مسح المكتومين":
        if not is_mod(uid, cid):
            return await m.reply(f"{k} هذا الأمر يخص المدير وفوق فقط")
        muted = await ar.smembers(f"{cid}:listMUTE:{DEV_ID}")
        if not muted:
            return await m.reply(f"{k} لا يوجد مكتومون")
        async with ar.pipeline(transaction=False) as pipe:
            for mid in muted:
                pipe.delete(f"{mid}:mute:{cid}:{DEV_ID}")
                utils_cache_invalidate(f"{mid}:mute:{cid}:{DEV_ID}")
            pipe.delete(f"{cid}:listMUTE:{DEV_ID}")
            await pipe.execute()
        return await m.reply(f"{k} تم مسح ( {len(muted)} ) مكتوم\n☆")

    if text == "مسح المكتومين عام":
        if not is_dev(uid, cid):
            return await m.reply(f"{k} هذا الأمر يخص المطور فقط")
        muted = await ar.smembers(f"listMUTE:{DEV_ID}")
        if not muted:
            return await m.reply(f"{k} لا يوجد مكتومون عاماً")
        async with ar.pipeline(transaction=False) as pipe:
            for mid in muted:
                pipe.delete(f"{mid}:mute:{DEV_ID}")
                utils_cache_invalidate(f"{mid}:mute:{DEV_ID}")
            pipe.delete(f"listMUTE:{DEV_ID}")
            await pipe.execute()
        return await m.reply(f"{k} تم مسح ( {len(muted)} ) مكتوم عام\n☆")

    if text == "مسح المحظورين عام":
        if not is_dev(uid, cid):
            return await m.reply(f"{k} هذا الأمر يخص المطور فقط")
        gbanned = await ar.smembers(f"listGBAN:{DEV_ID}")
        if not gbanned:
            return await m.reply(f"{k} لا يوجد محظورون عاماً")
        async with ar.pipeline(transaction=False) as pipe:
            for gid in gbanned:
                pipe.delete(f"{gid}:gban:{DEV_ID}")
                utils_cache_invalidate(f"{gid}:gban:{DEV_ID}")
            pipe.delete(f"listGBAN:{DEV_ID}")
            await pipe.execute()
        return await m.reply(f"{k} تم مسح ( {len(gbanned)} ) محظور عام\n☆")

    if text == "قائمة المكتومين":
        if not is_admin(uid, cid):
            return await m.reply(f"{k} هذا الأمر يخص الادمن وفوق فقط")
        muted = await ar.smembers(f"{cid}:listMUTE:{DEV_ID}")
        if not muted:
            return await m.reply(f"{k} لا يوجد أحد مكتوم")
        lines = "\n".join(f"• `{mid}`" for mid in muted)
        return await m.reply(f"{k} المكتومون:\n{lines}")
