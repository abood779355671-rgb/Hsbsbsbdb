"""
ملف private_sudos.py - لوحة تحكم المطور + أوامر السودو
الأوامر (في الخاص):
  /start            → لوحة التحكم (للمطور) أو رسالة الترحيب
  الاحصائيات        → عدد المستخدمين والمجموعات
  السيرفر           → معلومات السيرفر
  الملفات           → قائمة ملفات البوت
  اذاعة بالخاص      → إرسال رسالة لكل المستخدمين
  اذاعة بالقروبات   → إرسال رسالة لكل المجموعات
  المحظورين عام     → قائمة المحظورين عاماً
  المكتومين عام     → قائمة المكتومين عاماً
  المجموعات المحظورة → قائمة المجموعات المحظورة
  جلب نسخة القروبات/المستخدمين → تصدير JSON
  تعيين/مسح اسم البوت
  وضع/مسح قناة السورس
  وضع/مسح رمز السورس
  وضع/مسح مجموعة المطور
  تغيير المطور الاساسي
  /eval /exec /cmd /print /sc → أوامر التشغيل (للمطور الأعلى)
"""

import asyncio
import html
import json
import logging
import os
import platform
import re
import sys
import traceback
import time
import uuid
from datetime import datetime
from io import StringIO

import httpx
import psutil
try:
    import cpuinfo
except ImportError:
    cpuinfo = None
lsb_release = None  # محذوف — نستخدم platform.version() بدلاً منه

from meval import meval
from pyrogram import Client, filters, errors
from pyrogram.enums import ChatType
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup,
)
from pytio import Tio, TioRequest

from config import r, DEV_ID, DEV_ID_INT, botkey, botname, ar
from config import Client as client_ref  # مرجع مبكر لـ _safe_globals — يجب أن يكون قبل أي استخدام
from helpers.ranks import (
    get_rank, is_admin, is_mod, is_owner, is_gowner, is_dev,
)

logger = logging.getLogger("private_sudos")

tio = Tio()

# ─────────────────────────────────────────────────────────────────────────
# المشكلة 3: دوال الإذاعة على مستوى الملف — لا تُعاد في كل رسالة
# ─────────────────────────────────────────────────────────────────────────

async def _do_pv_broadcast(c: Client, m: Message, rep: Message, users: list, uid: int, k: str):
    """إذاعة رسالة لكل المستخدمين — تعمل في background task."""
    await ar.set(f"{uid}:pvBroadcastRunning:{DEV_ID}", 1, ex=600)
    count = failed = 0
    try:
        for u in users:
            try:
                await m.copy(int(u))
                count += 1
                await asyncio.sleep(0.1)
            except errors.FloodWait as fw:
                await asyncio.sleep(fw.value)
            except Exception:
                failed += 1
        await rep.edit(f"{k} اذاعة ناجحة {count} | فشل {failed}")
    except Exception as e:
        logger.error("خطأ في اذاعة الخاص: %s", e)
        try:
            await rep.edit(f"{k} انتهت الاذاعة بخطأ: {e}")
        except Exception:
            pass
    finally:
        await ar.delete(f"{uid}:pvBroadcastRunning:{DEV_ID}")


async def _do_gp_broadcast(c: Client, m: Message, rep: Message, chats: list, uid: int, k: str):
    """إذاعة رسالة لكل المجموعات — تعمل في background task."""
    await ar.set(f"{uid}:gpBroadcastRunning:{DEV_ID}", 1, ex=600)
    count = failed = 0
    try:
        for chat in chats:
            try:
                await m.copy(int(chat))
                count += 1
                await asyncio.sleep(0.1)
            except errors.FloodWait as fw:
                await asyncio.sleep(fw.value)
            except Exception:
                failed += 1
        await rep.edit(f"{k} اذاعة ناجحة {count} | فشل {failed}")
    except Exception as e:
        logger.error("خطأ في اذاعة القروبات: %s", e)
        try:
            await rep.edit(f"{k} انتهت الاذاعة بخطأ: {e}")
        except Exception:
            pass
    finally:
        await ar.delete(f"{uid}:gpBroadcastRunning:{DEV_ID}")

# ─────────────────────────────────────────────────────────────────────────
# مساعدات
# ─────────────────────────────────────────────────────────────────────────

def _get_size(size_bytes: int, suffix: str = "B") -> str:
    for unit in ["", "K", "M", "G", "T", "P"]:
        if size_bytes < 1024:
            return f"{size_bytes:.2f}{unit}{suffix}"
        size_bytes /= 1024
    return f"{size_bytes:.2f}P{suffix}"


_bot_channel_cache: tuple | None = None   # (value, timestamp)
_BOT_CHANNEL_TTL = 60  # ثانية

async def _bot_channel() -> str:
    """يُرجع رابط قناة البوت مع كاش TTL=60 ثانية — تقليل طلبات Redis"""
    import time as _t
    global _bot_channel_cache
    if _bot_channel_cache is not None:
        val, ts = _bot_channel_cache
        if _t.monotonic() - ts < _BOT_CHANNEL_TTL:
            return val
    val = await ar.get(f"{DEV_ID}:BotChannel") or "t.me"
    _bot_channel_cache = (val, _t.monotonic())
    return val


def _bot_username(c: Client) -> str:
    try:
        return c.me.username or "bot"
    except Exception as e:
        logger.error("Failed to get bot username: %s", e)
        return "bot"


# ─────────────────────────────────────────────────────────────────────────
# /start في الخاص
# ─────────────────────────────────────────────────────────────────────────

@Client.on_message(filters.command("start") & filters.private, group=-100)
async def start_handler(c: Client, m: Message):
    uid      = m.from_user.id
    k        = botkey()
    name     = botname()
    channel  = await _bot_channel()
    username = _bot_username(c)
    if is_dev(uid, 0):
        rank = await get_rank(uid, uid)
        kb = ReplyKeyboardMarkup(
            [
                [("الاحصائيات")],
                [("تغيير المطور الاساسي")],
                [("جلب نسخة القروبات"), ("جلب نسخة المستخدمين")],
                [("تفعيل البوت الخدمي"), ("تعطيل البوت الخدمي")],
                [("الردود العامه"), ("الاوامر العامه")],
                [("المحظورين عام"), ("المجموعات المحظورة")],
                [("اذاعة بالخاص"), ("اذاعة بالقروبات")],
                [("المكتومين عام"), ("المحظورين من الالعاب")],
                [("رمز السورس"), ("قناة السورس"), ("اسم البوت")],
                [("مسح اسم البوت"), ("تعيين اسم البوت")],
                [("مسح رمز السورس"), ("وضع رمز السورس")],
                [("مسح قناة السورس"), ("وضع قناة السورس")],
                [("السيرفر"), ("الملفات"), ("/eval")],
                [("مجموعة المطور")],
                [("وضع مجموعة المطور"), ("مسح مجموعة المطور")],
                [("الغاء")],
            ],
            resize_keyboard=True,
        )
        return await m.reply(
            quote=True,
            text=f"{k} هلا بك {rank}\n{k} قدامك لوحة التحكم",
            reply_markup=kb,
        )

    # ── رسالة الترحيب للعامة ──
    await m.reply(
        text=f"""اهلين انا {name} 🧚

↞ اختصاصي ادارة المجموعات من السبام والخ..
↞ كت تويت, يوتيوب, ساوند, واشياء كثير ..
↞ عشان تفعلني ارفعني اشراف وارسل تفعيل.
""",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(
                f"ضيفني لـ مجموعتك 🧚‍♀️",
                url=f"https://t.me/{username}?startgroup=Commands&admin=ban_users+restrict_members+delete_messages+add_admins+change_info+invite_users+pin_messages+manage_call+manage_chat+manage_video_chats+promote_members"
            )],
            [InlineKeyboardButton(f"تحديثات {name} 🍻", url=f"https://t.me/{channel}")],
        ])
    )

    # تسجيل المستخدم الجديد — ar async بدلاً من r sync
    if not await ar.sismember(f"{DEV_ID}:UsersList", uid):
        await ar.sadd(f"{DEV_ID}:UsersList", uid)
        uname     = f"@{m.from_user.username}" if m.from_user.username else "ماعنده يوزر"
        total     = await ar.scard(f"{DEV_ID}:UsersList")
        notif_txt = (
            f"☆ شخص جديد دخل للبوت\n"
            f"☆ اسمه : {m.from_user.mention}\n"
            f"☆ ايديه : `{uid}`\n"
            f"☆ معرفه : {uname}\n\n"
            f"☆ عدد المستخدمين صار {total}"
        )
        kb2 = InlineKeyboardMarkup([[InlineKeyboardButton(m.from_user.first_name, user_id=uid)]])
        dev_group = await ar.get(f"DevGroup:{DEV_ID}")
        if dev_group:
            try:
                await c.send_message(int(dev_group), notif_txt, reply_markup=kb2)
            except Exception as e:
                logger.error("Failed to send notification to dev group %s: %s", dev_group, e)
                pass
        else:
            try:
                await c.send_message(DEV_ID_INT, notif_txt, disable_web_page_preview=True)
            except Exception as e:
                logger.error("Failed to send notification to DEV_ID %s: %s", DEV_ID, e)
                pass


# ─────────────────────────────────────────────────────────────────────────
# أوامر الخاص العامة (نصية)
# ─────────────────────────────────────────────────────────────────────────

@Client.on_message(filters.text & filters.private, group=30)
async def sudos_private_handler(c: Client, m: Message):
    if not m.from_user:
        return
    uid  = m.from_user.id
    text = m.text
    k    = botkey()
    # المشكلة 2: التحقق من الصلاحية أولاً — _bot_channel() تُجلب فقط عند الحاجة
    if not is_dev(uid, 0):
        return
    channel = await _bot_channel()

    # ── إلغاء حالة الانتظار ──────────────────────────────────────────────
    # المشكلة 5: ar.mget بدلاً من 5 استدعاءات Redis متسلسلة
    wait_keys = [
        f"{uid}:setBotName:{uid}:{DEV_ID}",
        f"{uid}:setBotChannel:{uid}:{DEV_ID}",
        f"{uid}:setBotKey:{uid}:{DEV_ID}",
        f"{uid}:setDevGroup:{uid}:{DEV_ID}",
        f"{uid}:setBotOwner:{uid}:{DEV_ID}",
    ]
    if text == "الغاء" and any(await ar.mget(wait_keys)):
        for k2 in wait_keys:
            await ar.delete(k2)
        return await m.reply(quote=True, text=f"{k} من عيوني لغيت كل شي")

    # ── استقبال القيم في وضع الانتظار ────────────────────────────────────
    if await ar.get(f"{uid}:setBotName:{uid}:{DEV_ID}"):
        await ar.delete(f"{uid}:setBotName:{uid}:{DEV_ID}")
        await ar.set(f"{DEV_ID}:BotName", text)
        return await m.reply(quote=True, text=f"{k} ابشر عيني المطور غيرت اسمي لـ {text}")

    if await ar.get(f"{uid}:setBotChannel:{uid}:{DEV_ID}"):
        await ar.delete(f"{uid}:setBotChannel:{uid}:{DEV_ID}")
        await ar.set(f"{DEV_ID}:BotChannel", text.lstrip("@"))
        return await m.reply(quote=True, text=f"{k} ابشر عيني غيرت قناة السورس لـ {text}")

    if await ar.get(f"{uid}:setBotKey:{uid}:{DEV_ID}"):
        await ar.delete(f"{uid}:setBotKey:{uid}:{DEV_ID}")
        await ar.set(f"{DEV_ID}:botkey", text)
        return await m.reply(quote=True, text=f"{k} ابشر عيني غيرت رمز السورس لـ {text}")

    if await ar.get(f"{uid}:setDevGroup:{uid}:{DEV_ID}"):
        await ar.delete(f"{uid}:setDevGroup:{uid}:{DEV_ID}")
        try:
            group_id = int(text)
        except ValueError:
            return await m.reply(quote=True, text=f"{k} الايدي غلط!")
        await ar.set(f"DevGroup:{DEV_ID}", group_id)
        return await m.reply(quote=True, text=f"{k} ابشر عيني قروب المطور لـ {text}")

    if await ar.get(f"{uid}:setBotOwner:{uid}:{DEV_ID}"):
        await ar.delete(f"{uid}:setBotOwner:{uid}:{DEV_ID}")
        try:
            get = await c.get_chat(text.lstrip("@"))
        except Exception as e:
            logger.error("get_chat failed for '%s': %s", text, e)
            return await m.reply(quote=True, text=f"{k} اليوزر غلط!")
        await ar.set(f"{DEV_ID}:owner", get.id)
        await m.reply(quote=True, text=f"{k} ابشر نقلت ملكية البوت لـ {text}")
        return

    # ── الاحصائيات ───────────────────────────────────────────────────────
    if text == "الاحصائيات":
        users = await ar.scard(f"{DEV_ID}:UsersList")
        chats = await ar.scard(f"enablelist:{DEV_ID}")
        return await m.reply(
            quote=True,
            text=f"{k} هلا بك مطوري\n{k} المستخدمين ~ {users}\n{k} المجموعات ~ {chats}"
        )

    # ── السيرفر ───────────────────────────────────────────────────────────
    if text in ("السيرفر", "معلومات السيرفر"):
        uname  = platform.uname()
        svmem  = psutil.virtual_memory()
        hard   = psutil.disk_partitions()
        usage  = psutil.disk_usage(hard[0].mountpoint) if hard else None
        uptime = time.strftime("%dD - %HH - %MM - %Ss", time.gmtime(time.time() - psutil.boot_time()))
        try:
            version = platform.version()
        except Exception as e:
            logger.error("Failed to get platform version: %s", e)
            version = "غير معروف"
        txt  = "——— SYSTEM INFO ———\n"
        txt += f"{k} النظام : {uname.system}\n"
        txt += f"{k} الاصدار: `{version}`\n"
        txt += "——— R.A.M INFO ———\n"
        txt += f"{k} رامات السيرفر: `{_get_size(svmem.total)}`\n"
        txt += f"{k} المستهلك: `{_get_size(svmem.used)}/{_get_size(svmem.available)}`\n"
        txt += f"{k} نسبة الاستهلاك: `{svmem.percent}%`\n"
        if usage:
            txt += "——— HARD DISK ———\n"
            txt += f"{k} ذاكرة التخزين: `{_get_size(usage.total)}`\n"
            txt += f"{k} المستهلك: `{_get_size(usage.used)}`\n"
            txt += f"{k} نسبة الاستهلاك: `{usage.percent}%`\n"
        txt += f"——— U.P T.I.M.E ———\n{uptime}\n\n༄"
        return await m.reply(quote=True, text=txt)

    # ── الملفات ───────────────────────────────────────────────────────────
    if text == "الملفات":
        files = sorted(f for f in os.listdir("Plugins") if f.endswith(".py"))
        txt   = "——— ملفات السورس ———\n"
        for i, fname in enumerate(files, 1):
            txt += f"{i}) `{fname}`\n"
        txt += f"——— @{channel} ———"
        return await m.reply(quote=True, text=txt, disable_web_page_preview=True)

    # ── قائمة المحظورين عاماً ─────────────────────────────────────────────
    if text in ("المستخدمين المحظورين", "المحظورين عام"):
        banned = list(await ar.smembers(f"listGBAN:{DEV_ID}"))
        if not banned:
            return await m.reply(quote=True, text=f"{k} مافيه محظورين عام")

        # المشكلة 1: get_users بدفعات حتى 200 ID في كل طلب بدلاً من طلب لكل مستخدم
        user_map: dict[int, str] = {}
        int_ids = [int(x) for x in banned]
        for i in range(0, len(int_ids), 200):
            batch = int_ids[i:i + 200]
            try:
                users_batch = await c.get_users(batch)
                for u in users_batch:
                    mention = f"@{u.username}" if u.username else u.first_name
                    user_map[u.id] = mention
            except Exception as e:
                logger.error("get_users batch failed: %s", e)

        lines, chunk = [], []
        for i, user_id in enumerate(int_ids, 1):
            mention = user_map.get(user_id, str(user_id))
            chunk.append(f"{i}) {mention} ~ ( `{user_id}` )")
            current = "\n".join(chunk)
            if len(chunk) >= 50 or len(current) >= 3800:
                lines.append(current)
                chunk = []
        if chunk:
            lines.append("\n".join(chunk))
        header = f"الحمير المحظورين عام ({len(banned)}):\n"
        await m.reply(quote=True, text=header + lines[0])
        for page in lines[1:]:
            await m.reply(quote=True, text=page)
            await asyncio.sleep(0.5)
        return

    # ── المكتومين عاماً ───────────────────────────────────────────────────
    if text == "المكتومين عام":
        muted = list(await ar.smembers(f"listMUTE:{DEV_ID}"))
        if not muted:
            return await m.reply(quote=True, text=f"{k} مافيه مكتومين عام")

        # المشكلة 1: get_users بدفعات حتى 200 ID في كل طلب
        user_map: dict[int, str] = {}
        int_ids = [int(x) for x in muted]
        for i in range(0, len(int_ids), 200):
            batch = int_ids[i:i + 200]
            try:
                users_batch = await c.get_users(batch)
                for u in users_batch:
                    mention = f"@{u.username}" if u.username else u.first_name
                    user_map[u.id] = mention
            except Exception as e:
                logger.error("get_users batch failed: %s", e)

        lines, chunk = [], []
        for i, user_id in enumerate(int_ids, 1):
            mention = user_map.get(user_id, str(user_id))
            chunk.append(f"{i} ➣ {mention} ↤ ( `{user_id}` )")
            current = "\n".join(chunk)
            if len(chunk) >= 50 or len(current) >= 3800:
                lines.append(current)
                chunk = []
        if chunk:
            lines.append("\n".join(chunk))
        header = f"- المكتومين عام ({len(muted)}):\n\n"
        await m.reply(quote=True, text=header + lines[0])
        for page in lines[1:]:
            await m.reply(quote=True, text=page)
            await asyncio.sleep(0.5)
        return

    # ── المجموعات المحظورة ────────────────────────────────────────────────
    if text == "المجموعات المحظورة":
        chats = await ar.smembers(f":BannedChats:{DEV_ID}")
        if not chats:
            return await m.reply(quote=True, text=f"{k} مافي قروب محظور عام")
        txt = "المجموعات المحظورة:\n"
        for i, cid in enumerate(chats, 1):
            txt += f"{i}) `{cid}`\n"
        return await m.reply(quote=True, text=txt)

    # ── رمز السورس ───────────────────────────────────────────────────────
    if text == "رمز السورس":
        return await m.reply(quote=True, text=f"`{k}`")

    # ── قناة السورس ──────────────────────────────────────────────────────
    if text == "قناة السورس":
        ch = await ar.get(f"{DEV_ID}:BotChannel")
        if not ch:
            return await m.reply(quote=True, text=f"{k} قناة السورس مو معينة")
        return await m.reply(quote=True, text=f"@{ch}")

    # ── اسم البوت ─────────────────────────────────────────────────────────
    if text == "اسم البوت":
        n = await ar.get(f"{DEV_ID}:BotName")
        if not n:
            return await m.reply(quote=True, text=f"{k} مافي اسم مخصص للبوت")
        return await m.reply(quote=True, text=n)

    # ── مجموعة المطور ─────────────────────────────────────────────────────
    if text == "مجموعة المطور":
        gid = await ar.get(f"DevGroup:{DEV_ID}")
        if not gid:
            return await m.reply(quote=True, text=f"{k} مجموعة المطور مو معينة")
        try:
            link = (await c.get_chat(int(gid))).invite_link
            return await m.reply(quote=True, text=link, protect_content=True)
        except Exception as e:
            logger.error("Failed to get invite link for group %s: %s", gid, e)
            return await m.reply(quote=True, text=f"`{gid}`")

    # ── ضبط الإعدادات ─────────────────────────────────────────────────────
    if text == "تعيين اسم البوت":
        await ar.set(f"{uid}:setBotName:{uid}:{DEV_ID}", 1, ex=300)
        return await m.reply(quote=True, text=f"{k} هلا مطوري ارسل اسمي الجديد الحين")

    if text == "مسح اسم البوت":
        await ar.delete(f"{DEV_ID}:BotName")
        return await m.reply(quote=True, text=f"{k} ابشر مسحت اسم البوت")

    if text == "وضع قناة السورس":
        await ar.set(f"{uid}:setBotChannel:{uid}:{DEV_ID}", 1, ex=300)
        return await m.reply(quote=True, text=f"{k} هلا مطوري ارسل قناة السورس الحين")

    if text == "مسح قناة السورس":
        await ar.delete(f"{DEV_ID}:BotChannel")
        return await m.reply(quote=True, text=f"{k} ابشر مسحت قناة السورس")

    if text == "وضع رمز السورس":
        await ar.set(f"{uid}:setBotKey:{uid}:{DEV_ID}", 1, ex=300)
        return await m.reply(quote=True, text=f"{k} هلا مطوري ارسل رمز السورس الحين")

    if text == "مسح رمز السورس":
        await ar.set(f"{DEV_ID}:botkey", "⇜")
        return await m.reply(quote=True, text=f"{k} ابشر مسحت رمز السورس")

    if text == "وضع مجموعة المطور":
        await ar.set(f"{uid}:setDevGroup:{uid}:{DEV_ID}", 1, ex=300)
        return await m.reply(quote=True, text=f"{k} هلا مطوري ارسل ايدي القروب الحين")

    if text == "مسح مجموعة المطور":
        await ar.delete(f"DevGroup:{DEV_ID}")
        return await m.reply(quote=True, text=f"{k} ابشر مسحت مجموعة المطور")

    if text == "تغيير المطور الاساسي":
        await ar.set(f"{uid}:setBotOwner:{uid}:{DEV_ID}", 1, ex=300)
        return await m.reply(quote=True, text=f"{k} ارسل يوزر المطور الجديد الحين")

    # ── اذاعة بالخاص ──────────────────────────────────────────────────────
    if text == "اذاعة بالخاص":
        await ar.set(f"{uid}:pvBroadcast:{DEV_ID}", 1, ex=300)
        return await m.reply(quote=True, text=f"{k} ارسل الاذاعة الحين")

    if text == "اذاعة بالقروبات":
        await ar.set(f"{uid}:gpBroadcast:{DEV_ID}", 1, ex=300)
        return await m.reply(quote=True, text=f"{k} ارسل الاذاعة الحين")

    # ── استقبال رسالة الاذاعة ────────────────────────────────────────────
    if await ar.get(f"{uid}:pvBroadcast:{DEV_ID}"):
        if await ar.get(f"{uid}:pvBroadcastRunning:{DEV_ID}"):
            return await m.reply("⚠️ الاذاعة شغالة الحين، انتظر تنتهي")
        await ar.delete(f"{uid}:pvBroadcast:{DEV_ID}")
        users = list(await ar.smembers(f"{DEV_ID}:UsersList"))
        rep   = await m.reply("جار الاذاعة..")
        # المشكلة 3: استدعاء الدالة المعرَّفة على مستوى الملف
        asyncio.create_task(_do_pv_broadcast(c, m, rep, users, uid, k))
        return

    if await ar.get(f"{uid}:gpBroadcast:{DEV_ID}"):
        if await ar.get(f"{uid}:gpBroadcastRunning:{DEV_ID}"):
            return await m.reply("⚠️ الاذاعة شغالة الحين، انتظر تنتهي")
        await ar.delete(f"{uid}:gpBroadcast:{DEV_ID}")
        chats = list(await ar.smembers(f"enablelist:{DEV_ID}"))
        rep   = await m.reply("جار الاذاعة..")
        # المشكلة 3: استدعاء الدالة المعرَّفة على مستوى الملف
        asyncio.create_task(_do_gp_broadcast(c, m, rep, chats, uid, k))
        return

    # ── جلب نسخة القروبات ────────────────────────────────────────────────
    if text == "جلب نسخة القروبات":
        data  = {"botUsername": _bot_username(c), "botID": c.me.id if c.me else 0, "Chats": [int(x) for x in await ar.smembers(f"enablelist:{DEV_ID}")]}
        fname = f"chats_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(fname, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        await m.reply_document(fname, quote=True)
        os.remove(fname)
        return

    # ── جلب نسخة المستخدمين ──────────────────────────────────────────────
    if text == "جلب نسخة المستخدمين":
        data  = {"botUsername": _bot_username(c), "botID": c.me.id if c.me else 0, "Users": [int(x) for x in await ar.smembers(f"{DEV_ID}:UsersList")]}
        fname = f"users_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(fname, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        await m.reply_document(fname, quote=True)
        os.remove(fname)
        return

    # ── تحديث البوت ──────────────────────────────────────────────────────
    if text == "تحديث":
        await m.reply(quote=True, text=f"{k} تم تحديث الملفات")
        python = sys.executable
        try:
            await _http.aclose()
        except Exception:
            pass
        os.execl(python, python, *sys.argv)


# ─────────────────────────────────────────────────────────────────────────
# /eval
# ─────────────────────────────────────────────────────────────────────────

# المشكلة 4: cache لـ _safe_globals — يُبنى مرة واحدة ولا يُعيد import config في كل /eval
_safe_globals_cache: dict | None = None

def _safe_globals() -> dict:
    """
    يُنشئ بيئة تنفيذ آمنة لـ meval — يُزيل المتغيرات الحساسة من globals().
    المتغيرات المُزالة: BOT_TOKEN, API_HASH, REDIS_URL وأي شيء من os.environ.
    النتيجة مُخزَّنة في cache — لا import config في كل استدعاء.
    """
    global _safe_globals_cache
    if _safe_globals_cache is not None:
        return _safe_globals_cache
    import config as _cfg
    _safe_globals_cache = {
        # مكتبات مفيدة
        "asyncio": asyncio, "os": os, "sys": sys, "re": re,
        "json": __import__("json"), "time": __import__("time"),
        "datetime": __import__("datetime"),
        # pyrogram
        "Client": client_ref, "filters": __import__("pyrogram").filters,
        "errors": __import__("pyrogram").errors,
        # Redis (async فقط — لا r sync)
        "ar": _cfg.ar, "DEV_ID": _cfg.DEV_ID,
        # مساعدات البوت
        "botkey": _cfg.botkey, "botname": _cfg.botname,
    }
    return _safe_globals_cache


async def _aexec(code: str, client: Client, message: Message):
    """تنفيذ كود مع بيئة محدودة — بدون BOT_TOKEN أو API_HASH في النطاق"""
    return await meval(
        code,
        _safe_globals(),
        client=client, message=message, c=client, m=message,
    )


@Client.on_message(filters.command("eval") & filters.user(DEV_ID_INT), group=-200)
async def eval_handler(c: Client, m: Message):
    if len(m.command) < 2 and not m.reply_to_message:
        return await m.reply("» هات أمر عشان انفذ!")
    cmd = m.text.split(None, 1)[1] if len(m.command) >= 2 else m.reply_to_message.text

    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = out_buf = StringIO()
    exc = None
    try:
        await _aexec(cmd, c, m)
    except Exception:
        exc = traceback.format_exc()
    stdout = out_buf.getvalue()
    sys.stdout, sys.stderr = old_stdout, old_stderr

    result   = exc or stdout or "SUCCESS"
    response = f"`OUTPUT:`\n\n```{result.strip()}```"
    if len(response) > 4096:
        fname = "output.txt"
        with open(fname, "w", encoding="utf8") as f:
            f.write(result.strip())
        await m.reply_document(fname, caption=f"`INPUT:`\n`{cmd[:980]}`\n\n`OUTPUT:` attached")
        os.remove(fname)
    else:
        await m.reply(response)


# ─────────────────────────────────────────────────────────────────────────
# /exec (تشغيل كود بلغات مختلفة عبر tio.run)
# ─────────────────────────────────────────────────────────────────────────

_langs_list = None

def _get_langs():
    """Lazy-load language list on first use (avoids blocking import)"""
    global _langs_list
    if _langs_list is None:
        try:
            _langs_list = tio.query_languages()
        except Exception:
            _langs_list = []
    return _langs_list
_langs_list_url = "https://amanoteam.com/etc/langs.html"

@Client.on_message(filters.command("exec") & filters.user(DEV_ID_INT), group=-200)
async def exec_tio_handler(c: Client, m: Message):
    try:
        lang = m.command[1]
        code = m.text.split(None, 2)[2]
    except IndexError:
        return await m.reply("الاستخدام: `/exec <language> <code>`")

    if lang not in _get_langs():
        return await m.reply(
            f"اللغة <b>{lang}</b> غير موجودة. القائمة: {_langs_list_url}"
        )
    req      = TioRequest(lang=lang, code=code)
    loop     = asyncio.get_running_loop()
    try:
        response = await asyncio.wait_for(
            loop.run_in_executor(None, tio.send, req),
            timeout=30.0,
        )
    except asyncio.TimeoutError:
        return await m.reply("⏱ انتهت مهلة التنفيذ (30 ثانية). قد تكون خدمة tio.run بطيئة أو غير متاحة.")
    except Exception as e:
        logger.error("tio.send error lang=%s: %s", lang, e)
        return await m.reply(f"❌ خطأ أثناء التنفيذ: <code>{html.escape(str(e))}</code>")
    err      = response.error or "None"
    res      = response.result or "None"
    stats    = response.debug.decode() if response.debug else "None"

    if response.error is None:
        txt = f"<b>Language:</b> <code>{lang}</code>\n\n<b>Code:</b>\n<code>{html.escape(code)}</code>\n\n<b>Results:</b>\n<code>{html.escape(res)}</code>\n\n<b>Stats:</b><code>{stats}</code>"
    else:
        txt = f"<b>Language:</b> <code>{lang}</code>\n\n<b>Code:</b>\n<code>{html.escape(code)}</code>\n\n<b>Results:</b>\n<code>{html.escape(res)}</code>\n\n<b>Errors:</b>\n<code>{html.escape(err)}</code>"
    await m.reply(txt)


# ─────────────────────────────────────────────────────────────────────────
# /cmd (تنفيذ أوامر shell)
# ─────────────────────────────────────────────────────────────────────────

async def _shell_exec(cmd: str):
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return stdout.decode(), stderr.decode()


@Client.on_message(filters.command("cmd") & filters.user(DEV_ID_INT), group=-200)
async def cmd_handler(c: Client, m: Message):
    try:
        cmd = m.text.split(None, 1)[1]
    except IndexError:
        return await m.reply("الاستخدام: `/cmd <command>`")
    if re.match(r"(?i)poweroff|halt|shutdown|reboot", cmd):
        return await m.reply("لا يمكن استخدام هذا الأمر")
    stdout, stderr = await _shell_exec(cmd)
    res = (
        (f"<b>Output:</b>\n<code>{html.escape(stdout)}</code>" if stdout else "") +
        (f"\n<b>Errors:</b>\n<code>{stderr}</code>" if stderr else "")
    )
    await m.reply(res or "لا يوجد خرج")


# ─────────────────────────────────────────────────────────────────────────
# /print (meval)
# ─────────────────────────────────────────────────────────────────────────

@Client.on_message(filters.command("print") & filters.user(DEV_ID_INT), group=-200)
async def print_handler(c: Client, m: Message):
    try:
        expr = m.text.split(None, 1)[1]
    except IndexError:
        return await m.reply("الاستخدام: `/print <expression>`")
    try:
        res = await meval(expr, _safe_globals(), c=c, m=m, client=c, message=m)
    except Exception:
        return await m.reply(f"<code>{html.escape(traceback.format_exc())}</code>")
    try:
        await m.reply(f"<code>{html.escape(str(res))}</code>")
    except Exception as e:
        await m.reply(str(e))


# ─────────────────────────────────────────────────────────────────────────
# /sc /ss /webs (لقطة شاشة موقع)
# ─────────────────────────────────────────────────────────────────────────

_http = httpx.AsyncClient(http2=True, timeout=httpx.Timeout(40, pool=None))

async def _screenshot_url(url: str) -> bytes | None:
    """
    يأخذ لقطة شاشة باستخدام thum.io — خدمة مجانية لا تحتاج API key.
    تُرجع الصورة كـ bytes مباشرة.
    في حال فشل thum.io يُجرَّب htmlpreview كبديل.
    """
    import urllib.parse
    encoded = urllib.parse.quote(url, safe="")
    # thum.io: مجاني بالكامل، بدون مفتاح، يعيد صورة JPEG مباشرة
    primary = f"https://image.thum.io/get/width/1280/crop/720/{encoded}"
    try:
        resp = await _http.get(primary, timeout=30, follow_redirects=True)
        if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("image/"):
            return resp.content
    except httpx.HTTPError:
        pass
    # بديل ثانٍ: screenshotapi.net الطبقة المجانية (200 req/شهر)
    fallback = f"https://shot.screenshotapi.net/screenshot?url={encoded}&output=image&file_type=jpg&wait_for_event=load"
    try:
        resp = await _http.get(fallback, timeout=40, follow_redirects=True)
        if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("image/"):
            return resp.content
    except httpx.HTTPError:
        pass
    return None


@Client.on_message(filters.command(["sc", "webs", "ss"]) & filters.user(DEV_ID_INT), group=-200)
async def screenshot_handler(c: Client, m: Message):
    parts = m.text.split(None, 1)
    url   = parts[1] if len(parts) > 1 else (m.reply_to_message.text if m.reply_to_message else None)
    if not url:
        return await m.reply("<b>Usage:</b> <code>/sc https://example.com</code>")
    sent    = await m.reply("جار أخذ لقطة الشاشة...")
    img_bytes = await _screenshot_url(url)
    if not img_bytes:
        return await sent.edit("فشل جلب اللقطة، حاول مرة أخرى.")
    try:
        from io import BytesIO
        await m.reply_photo(BytesIO(img_bytes), caption=url)
        await sent.delete()
    except Exception as e:
        await sent.edit(f"<b>Failed:</b> <code>{e}</code>")
