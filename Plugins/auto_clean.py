"""
ملف auto_clean.py - نظام التنظيف التلقائي للوسائط
الأوامر المتاحة:
  تفعيل التنظيف              → تفعيل حذف الوسائط تلقائياً بعد المدة المحددة (مالك أساسي+)
  تعطيل التنظيف              → إيقاف التنظيف التلقائي (مالك أساسي+)
  وضع وقت التنظيف [ثواني]   → تحديد مدة الانتظار قبل الحذف (60-3600 ثانية) (مالك أساسي+)
  وقت التنظيف                → عرض المدة الحالية المضبوطة (مالك أساسي+)

إصلاح: الرسائل المعلقة تُحفظ في Redis وتُستعاد عند إعادة التشغيل
"""

import asyncio
import logging
import re
import time as _time
from datetime import datetime, timedelta

from pyrogram import Client, filters
from pyrogram.errors import FloodWait
from pyrogram.types import Message

from config import r, DEV_ID, botkey, ar
from helpers.ranks import is_gowner
from helpers.utils import group_enabled, resolve_text


# ────────────────────────────────────────────────────────────
# مساعدات Redis للرسائل المعلقة
# نستخدم Sorted Set: key="{DEV_ID}:{chat_id}:pending-clean"
#   score = unix timestamp وقت الحذف
#   member = message_id
# ────────────────────────────────────────────────────────────

def _pending_key(chat_id: int) -> str:
    return f"{DEV_ID}:{chat_id}:pending-clean"


async def _schedule_delete(chat_id: int, msg_id: int, delete_at: datetime):
    """جدولة رسالة للحذف - تُحفظ في Redis (async)"""
    score = delete_at.timestamp()
    # ✅ إصلاح 1: pipeline() ليست coroutine — لا تحتاج await عند الإنشاء
    pipe = ar.pipeline()
    pipe.zadd(_pending_key(chat_id), {str(msg_id): score})
    pipe.sadd(f"{DEV_ID}:clean-active-chats", chat_id)
    ttl = int(score - _time.time()) + 3600
    if ttl > 0:
        pipe.expire(_pending_key(chat_id), ttl)
    await pipe.execute()


async def _get_due_messages(chat_id: int) -> list[int]:
    """جلب رسائل حان وقت حذفها (async)"""
    now = _time.time()
    members = await ar.zrangebyscore(_pending_key(chat_id), 0, now)
    if members:
        await ar.zremrangebyscore(_pending_key(chat_id), 0, now)
    return [int(m) for m in members]


def _active_chats_key() -> str:
    return f"{DEV_ID}:clean-active-chats"


async def _get_all_pending_chats(client_ar) -> list[int]:
    """جلب كل chat_ids التي فيها رسائل معلقة — async بدلاً من sync Redis"""
    members = await client_ar.smembers(_active_chats_key())
    return [int(m) for m in members if m]


# ────────────────────────────────────────────────────────────
# كاش media_group_id لتجنب معالجة نفس الألبوم أكثر من مرة
# ────────────────────────────────────────────────────────────

# ✅ إصلاح 2: كاش بسيط في الذاكرة للـ media_group_id
# TTL = 60 ثانية — كافٍ لاستقبال كل صور الألبوم الواحد
_processed_albums: dict[str, float] = {}
_ALBUM_TTL = 60.0


def _is_album_processed(media_group_id: str) -> bool:
    now = _time.time()
    ts = _processed_albums.get(media_group_id)
    if ts and now - ts < _ALBUM_TTL:
        return True
    # تنظيف المدخلات القديمة
    expired = [k for k, t in list(_processed_albums.items()) if now - t >= _ALBUM_TTL]
    for k in expired:
        _processed_albums.pop(k, None)
    return False


def _mark_album_processed(media_group_id: str):
    _processed_albums[media_group_id] = _time.time()


# ────────────────────────────────────────────────────────────
# جمع الرسائل الواردة
# ────────────────────────────────────────────────────────────

@Client.on_message(filters.group & filters.media, group=1)
async def _collect_media(c: Client, m: Message):
    if not group_enabled(m.chat.id):
        return

    # تخطي الصوت والفويس والألعاب
    if m.audio or m.voice or m.game:
        return

    # mget واحد بدلاً من طلبين منفصلين
    _clean_vals = await ar.mget([f"{DEV_ID}:{m.chat.id}:ena-clean", f"{DEV_ID}:{m.chat.id}:clean-secs"])
    if not _clean_vals[0]:
        return
    secs = int(_clean_vals[1] or "60")
    delete_at = datetime.now() + timedelta(seconds=secs)

    if m.media_group_id:
        # ✅ إصلاح 2: تجاهل الرسالة إذا سبق معالجة ألبومها
        if _is_album_processed(m.media_group_id):
            return
        _mark_album_processed(m.media_group_id)
        try:
            group_msgs = await c.get_media_group(m.chat.id, m.id)
            for gm in group_msgs:
                await _schedule_delete(m.chat.id, gm.id, delete_at)
        except Exception:
            await _schedule_delete(m.chat.id, m.id, delete_at)
    else:
        await _schedule_delete(m.chat.id, m.id, delete_at)


# ────────────────────────────────────────────────────────────
# حلقة الحذف التلقائي
# ────────────────────────────────────────────────────────────

logger = logging.getLogger("auto_clean")

async def _process_chat(client: Client, chat_id: int):
    """معالجة مجموعة واحدة — تُستدعى بشكل متوازٍ عبر asyncio.gather"""
    to_delete = await _get_due_messages(chat_id)
    if not to_delete:
        return
    try:
        await client.delete_messages(chat_id, to_delete)
        logger.debug("حذف %d رسالة من %s", len(to_delete), chat_id)
    except FloodWait as fw:
        await asyncio.sleep(fw.value)
        try:
            await client.delete_messages(chat_id, to_delete)
        except Exception:
            pass
    except Exception as e:
        logger.warning("خطأ حذف: %s", e)
    # إذا لم تعد هناك رسائل معلقة — أزل من active set
    if await ar.zcard(_pending_key(chat_id)) == 0:
        await ar.srem(f"{DEV_ID}:clean-active-chats", chat_id)


async def _auto_clean_loop(client: Client):
    """
    تدور كل 10 ثوانٍ وتحذف الرسائل التي حان وقتها.
    البيانات محفوظة في Redis — لا تُفقد عند إعادة التشغيل.
    المجموعات تُعالَج بشكل متوازٍ عبر asyncio.gather لتجنب تجميد event loop.
    """
    logger.info("الحلقة تعمل")
    while True:
        try:
            # ✅ إصلاح 3: رُفع sleep من 5 إلى 10 ثوانٍ لتقليل استعلامات Redis الزائدة
            await asyncio.sleep(10)
            chats = await _get_all_pending_chats(ar)
            if not chats:
                continue

            # معالجة كل المجموعات في نفس الوقت بدلاً من واحدة واحدة
            await asyncio.gather(
                *[_process_chat(client, chat_id) for chat_id in chats],
                return_exceptions=True,
            )

        except Exception as e:
            logger.error("خطأ عام: %s", e)


# ────────────────────────────────────────────────────────────
# أوامر التحكم
# ────────────────────────────────────────────────────────────

@Client.on_message(filters.group & filters.text, group=37)
async def clean_commands(c: Client, m: Message):
    if not m.from_user:
        return
    if not group_enabled(m.chat.id):
        return

    text = resolve_text(m.text, m.chat.id)
    k = botkey()
    uid = m.from_user.id
    cid = m.chat.id
    mention = m.from_user.mention

    async def need_gowner():
        if not is_gowner(uid, cid):
            await m.reply(f"{k} هذا الأمر يخص ( المالك الأساسي وفوق ) بس")
            return True
        return False

    # ── تعطيل التنظيف ──
    if text == "تعطيل التنظيف":
        if await need_gowner(): return
        if not await ar.get(f"{DEV_ID}:{cid}:ena-clean"):
            return await m.reply(f"{k} من 「 {mention} 」\n{k} التنظيف معطّل من قبل\n☆")
        await ar.delete(f"{DEV_ID}:{cid}:ena-clean")
        # مسح الرسائل المعلقة من Redis
        await ar.delete(_pending_key(cid))
        return await m.reply(f"{k} من 「 {mention} 」\n{k} ابشر عطّلت التنظيف\n☆")

    # ── تفعيل التنظيف ──
    if text == "تفعيل التنظيف":
        if await need_gowner(): return
        if await ar.get(f"{DEV_ID}:{cid}:ena-clean"):
            return await m.reply(f"{k} من 「 {mention} 」\n{k} التنظيف مفعّل من قبل\n☆")
        await ar.set(f"{DEV_ID}:{cid}:ena-clean", 1)
        return await m.reply(f"{k} من 「 {mention} 」\n{k} ابشر فعّلت التنظيف\n☆")

    # ── وضع وقت التنظيف [ثواني] ──
    if re.search(r"^وضع وقت التنظيف \d+$", text):
        if await need_gowner(): return
        secs = int(text.split()[-1])
        if secs < 60 or secs > 3600:
            return await m.reply(f"{k} عليك تحديد وقت التنظيف بالثواني من 60 إلى 3600 ثانية")
        await ar.set(f"{DEV_ID}:{cid}:clean-secs", secs)
        return await m.reply(f"{k} تم تعيين وقت التنظيف ( {secs} ) ثانية")

    # ── وقت التنظيف ──
    if text == "وقت التنظيف":
        if await need_gowner(): return
        # ✅ إصلاح 4: mget بدلاً من استعلامين منفصلين
        vals = await ar.mget([f"{DEV_ID}:{cid}:clean-secs", f"{DEV_ID}:{cid}:ena-clean"])
        secs   = vals[0] or "60"
        status = "مفعّل ✅" if vals[1] else "معطّل ❌"
        pending_count = await ar.zcard(_pending_key(cid)) or 0
        return await m.reply(
            f"{k} إعدادات التنظيف:\n"
            f"الحالة: {status}\n"
            f"مدة الانتظار: `{secs}` ثانية\n"
            f"رسائل معلقة: `{pending_count}`"
        )
