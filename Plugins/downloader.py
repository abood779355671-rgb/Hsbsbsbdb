"""
تحميل من يوتيوب / تيك توك / ساوند كلاود + شازام
أوامر:
  بحث [كلمة] / yt [كلمة]     → بحث يوتيوب وتحميل صوت أول نتيجة
  يوت [كلمة]                  → بحث يوتيوب مع قائمة نتائج
  تيك [رابط]                  → تحميل فيديو تيك توك
  ساوند [كلمة]                → بحث ساوند كلاود
  شازام                       → التعرف على صوت (رد على رسالة)
  شازام [كلمة]                → بحث كلمات أغنية
"""
import os
import re
import time
import random
import asyncio
import logging

import aiohttp        # ✅ إصلاح 3: نُقل من داخل الدوال إلى أعلى الملف
import yt_dlp
import httpx

from pyrogram import Client, filters
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
    InlineQueryResultArticle, InputTextMessageContent,
)

from config import r, DEV_ID, botkey, ar

logger = logging.getLogger("downloader")
from helpers.ranks import is_admin
from helpers.utils import group_enabled, can_speak, resolve_text

RAPIDAPI_KEY  = os.getenv("RAPIDAPI_KEY", "")
RAPIDAPI_HOST = "yt-search-and-download-mp3.p.rapidapi.com"
YTSEARCH_OK   = bool(RAPIDAPI_KEY)

# ── helpers للـ Redis ──────────────────────────────────────────────────────

_channel_cache: tuple[str, float] = ("S_B_8", 0.0)
_CHANNEL_TTL = 60.0

async def _get_channel() -> str:
    global _channel_cache
    now = time.monotonic()
    if now - _channel_cache[1] < _CHANNEL_TTL:
        return _channel_cache[0]
    val = await ar.get(f"{DEV_ID}:BotChannel") or "S_B_8"
    _channel_cache = (val, now)
    return val

async def _is_disabled(cid: int, feature: str) -> bool:
    group_k, global_k = await ar.mget(
        [f"{cid}:{feature}:{DEV_ID}", f":{feature}:{DEV_ID}"]
    )
    return bool(group_k or global_k)

async def _yt_cache_get(media_type: str, vid_id: str) -> tuple[str, str] | None:
    val = await ar.get(f"yt{media_type}:{vid_id}")
    if val and ":" in val:
        file_id, dur_str = val.split(":", 1)
        return file_id, dur_str
    return None

async def _yt_cache_set(media_type: str, vid_id: str, file_id: str, dur_str: str):
    await ar.set(f"yt{media_type}:{vid_id}", f"{file_id}:{dur_str}")


async def _yt_search(query: str, limit: int = 4) -> list:
    """بحث يوتيوب عبر RapidAPI"""
    # ✅ إصلاح 3: حُذف import aiohttp من هنا — مستورد أعلى الملف
    headers = {
        "x-rapidapi-key":  RAPIDAPI_KEY,
        "x-rapidapi-host": RAPIDAPI_HOST,
        "Content-Type":    "application/json",
    }
    try:
        session = await _get_aio_session()
        async with session.get(
            f"https://{RAPIDAPI_HOST}/search",
            params={"query": query, "limit": limit},
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as r:
            logger.info("[_yt_search] status=%s", r.status)
            if r.status == 200:
                data    = await r.json()
                results = []
                items   = data if isinstance(data, list) else data.get("results", data.get("items", []))
                for item in items[:limit]:
                    vid_id = item.get("videoId") or item.get("id") or item.get("video_id", "")
                    title  = item.get("title", "")
                    dur    = item.get("duration") or item.get("lengthSeconds", 0)
                    if isinstance(dur, str):
                        parts = dur.split(":")
                        try:
                            dur = int(parts[-1]) + int(parts[-2]) * 60 + (int(parts[-3]) * 3600 if len(parts) > 2 else 0)
                        except Exception:
                            dur = 0
                    if vid_id:
                        results.append({"id": vid_id, "title": title, "duration": dur, "channel": item.get("channelTitle", "")})
                logger.info("[_yt_search] results=%d", len(results))
                return results
            else:
                text = await r.text()
                logger.warning("[_yt_search] failed status=%s body=%s", r.status, text[:200])
    except Exception as e:
        logger.error("[_yt_search] exception: %s", e)
    return []


async def _yt_download(vid_id: str, audio_only: bool = True) -> str | None:
    """تحميل MP3 من يوتيوب عبر RapidAPI"""
    # ✅ إصلاح 3: حُذف import aiohttp من هنا — مستورد أعلى الملف
    headers = {
        "x-rapidapi-key":  RAPIDAPI_KEY,
        "x-rapidapi-host": RAPIDAPI_HOST,
        "Content-Type":    "application/json",
    }
    try:
        session = await _get_aio_session()
        async with session.get(
            f"https://{RAPIDAPI_HOST}/mp3",
            params={"videoId": vid_id},
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=60),
        ) as r:
            logger.info("[_yt_download] mp3 status=%s", r.status)
            if r.status != 200:
                logger.warning("[_yt_download] failed: %s", await r.text())
                return None
            data   = await r.json()
            dl_url = (
                data.get("link") or data.get("url") or
                data.get("downloadUrl") or data.get("download_url") or
                data.get("audio") or ""
            )
            if not dl_url:
                logger.warning("[_yt_download] no url in response: %s", data)
                return None

        filename = f"/tmp/{vid_id}.mp3"
        async with session.get(dl_url, timeout=aiohttp.ClientTimeout(total=120)) as r:
            if r.status == 200:
                with open(filename, "wb") as f:
                    async for chunk in r.content.iter_chunked(1024 * 64):
                        f.write(chunk)
                logger.info("[_yt_download] saved %s", filename)
                return filename
    except Exception as e:
        logger.error("[_yt_download] exception: %s", e)
    return None


try:
    from shazamio import Shazam
    shazam  = Shazam()
    SHAZAM_OK = True
except Exception:
    SHAZAM_OK = False

# client مشترك — يُعاد استخدامه بدلاً من إنشاء client جديد لكل طلب
_http = httpx.AsyncClient(http2=True, timeout=httpx.Timeout(30, pool=None))

# ✅ إصلاح 4: _aio_session معرَّف كـ None على مستوى الوحدة
# main.py يُغلقه في finally عند إيقاف البوت
_aio_session: aiohttp.ClientSession | None = None

async def _get_aio_session() -> aiohttp.ClientSession:
    global _aio_session
    # ✅ إصلاح 3: aiohttp مستورد أعلى الملف — لا NameError هنا
    if _aio_session is None or _aio_session.closed:
        connector  = aiohttp.TCPConnector(limit=10, ttl_dns_cache=300)
        _aio_session = aiohttp.ClientSession(connector=connector)
    return _aio_session


# ── helpers ───────────────────────────────────────────────────────────────

async def _run_ydl(opts: dict, url: str, download: bool = True) -> tuple:
    """تشغيل yt_dlp في thread منفصل لتجنب تجميد event loop"""
    if os.path.exists("cookies.txt"):
        opts["cookiefile"] = "cookies.txt"
    loop = asyncio.get_running_loop()
    def _extract():
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=download), ydl
    info, ydl = await loop.run_in_executor(None, _extract)
    return info, ydl

async def _download_thumbnail(url: str) -> str | None:
    if not url:
        return None
    try:
        resp = await _http.get(url, follow_redirects=True)
        if resp.status_code == 200:
            ext = url.split(".")[-1].split("?")[0] or "jpg"
            if ext not in ("jpg", "jpeg", "png", "webp"):
                ext = "jpg"
            filename = f"thumb_{random.randint(1000, 9999)}.{ext}"
            with open(filename, "wb") as f:
                f.write(resp.content)
            return filename
    except Exception:
        return None
    return None

def _find_urls(text: str):
    pat = r"(?i)\b((?:https?://|www\d{0,3}[.]|[a-z0-9.\-]+[.][a-z]{2,4}/)(?:[^\s()<>]+|\(([^\s()<>]+|(\([^\s()<>]+\)))*\))+(?:\(([^\s()<>]+|(\([^\s()<>]+\)))*\)|[^\s!()\[\]{};:'\".,<>?«»""'']))"
    return [x[0] for x in re.findall(pat, text)]

def _seconds_to_str(seconds: int) -> str:
    return time.strftime("%M:%S", time.gmtime(seconds))

def _channel_markup(channel: str):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🧚‍♀️", url=f"https://t.me/{channel}")]])

def _sanitize_filename(filename: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', '_', filename)


# ── يوتيوب: بحث مع قائمة نتائج ──────────────────────────────────────────

@Client.on_message(filters.text & filters.group, group=32)
async def downloader_handler(c: Client, m: Message):
    if not m.from_user:
        return
    cid, uid = m.chat.id, m.from_user.id
    if not group_enabled(cid):
        return
    if not can_speak(uid, cid):
        return

    text = resolve_text(m.text, cid)
    k    = botkey()

    # ── يوت [بحث] → قائمة نتائج ─────────────────────────────────────────
    if text.startswith("يوت ") and YTSEARCH_OK:
        logger.info("[يوت] cid=%s uid=%s text=%r", cid, uid, text)
        if await _is_disabled(cid, "disableYT"):
            return
        channel = await _get_channel()
        query   = text.split(None, 1)[1]
        try:
            results = await _yt_search(query, limit=4)
        except Exception as e:
            logger.error("[يوت] search error: %s", e)
            return await m.reply(f"فشل البحث: {e}")
        keyboard = []
        for res in results:
            keyboard.append([InlineKeyboardButton(
                (res.get("title") or "")[:60],
                callback_data=f"{uid}GET{res['id']}"
            )])
        sent = await m.reply(
            f"{k} البحث ~ {query}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True,
        )
        await ar.set(f"{sent.id}:one_minute:{uid}", 1, ex=60)
        return

    # ── بحث [كلمة] / yt [كلمة] → أول نتيجة صوت ──────────────────────────
    if (text.startswith("بحث ") or text.startswith("yt ")) and YTSEARCH_OK:
        logger.info("[بحث] cid=%s uid=%s text=%r", cid, uid, text)
        if await _is_disabled(cid, "disableYT"):
            return
        channel = await _get_channel()
        query   = text.split(None, 1)[1]
        try:
            results = await _yt_search(query, limit=1)
        except Exception as e:
            logger.error("[بحث] search error: %s", e)
            return await m.reply(f"فشل البحث: {e}")
        if not results:
            return await m.reply(f"{k} ما لقيت نتائج")
        res    = results[0]
        vid_id = res["id"]
        url    = f"https://youtu.be/{vid_id}"

        cached = await _yt_cache_get("audio", vid_id)
        if cached:
            file_id, dur_str = cached
            return await m.reply_audio(
                file_id,
                caption=f"@{channel} ~ ⏳ {dur_str}",
                reply_markup=_channel_markup(channel),
            )

        if int(res.get("duration", 0)) > 1500:
            return await m.reply(f"{k} الصوت أكثر من 25 دقيقة ما أقدر أنزله")

        audio_file = await _yt_download(vid_id, audio_only=True)
        if not audio_file or not os.path.exists(audio_file):
            return await m.reply(f"{k} فشل تحميل الصوت")

        mp3_file  = audio_file
        dur_str   = _seconds_to_str(int(res.get("duration", 0)))
        thumb_url = f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg"
        thumb     = await _download_thumbnail(thumb_url)

        try:
            sent = await m.reply_audio(
                mp3_file,
                title=res.get("title", ""),
                thumb=thumb,
                duration=int(res.get("duration", 0)),
                performer=res.get("channel", ""),
                caption=f"@{channel} ~ ⏳ {dur_str}",
                reply_markup=_channel_markup(channel),
            )
        except Exception:
            return await m.reply(f"{k} فشل إرسال الملف الصوتي")

        await _yt_cache_set("audio", vid_id, sent.audio.file_id, dur_str)
        for tmp in [mp3_file, thumb]:
            if tmp:
                try:
                    os.remove(tmp)
                except Exception as e:
                    logger.error("فشل حذف الملف المؤقت '%s': %s", tmp, e)
        return

    # ── تيك [رابط] → فيديو تيك توك ──────────────────────────────────────
    if text.startswith("تيك "):
        if await _is_disabled(cid, "disableTik"):
            return
        urls = _find_urls(text)
        if not urls:
            return
        url = urls[0]
        try:
            vid_data, _ = await _run_ydl({}, url, download=False)
        except Exception:
            return await m.reply(f"{k} فشل التحميل")
        channel  = await _get_channel()
        title    = vid_data.get("fulltitle", "")
        duration = int(vid_data.get("duration", 0))
        dur_str  = _seconds_to_str(duration)
        file_url = vid_data.get("url", "")
        views    = vid_data.get("view_count", 0)
        likes    = vid_data.get("like_count", 0)
        comments = vid_data.get("comment_count", 0)
        reposts  = vid_data.get("repost_count", 0)
        uploader = vid_data.get("uploader", "")
        creator  = vid_data.get("creator", uploader)
        uploader_url = vid_data.get("uploader_url", "")
        caption = (
            f"`{title}`\n{k} الطول: {dur_str}\n{k} المشاهدات: {views:,}\n"
            f"{k} اللايكات: {likes:,}\n{k} الكومنت: {comments:,}\n"
            f"{k} الاكسبلور: {reposts:,}\n\n~ @{channel}"
        )
        reply_markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton(f"{creator} - @{uploader}", url=uploader_url)]]
        ) if uploader_url else None
        try:
            await m.reply_video(file_url, caption=caption, reply_markup=reply_markup)
        except Exception:
            try:
                vid_data2, ytdl = await _run_ydl({"outtmpl": "%(id)s.%(ext)s"}, url, download=True)
                fn = ytdl.prepare_filename(vid_data2)
                await m.reply_video(fn, caption=caption, reply_markup=reply_markup)
                try:
                    os.remove(fn)
                except Exception as e:
                    logger.error("فشل حذف ملف الفيديو المؤقت '%s': %s", fn, e)
            except Exception:
                await m.reply(f"{k} فشل تحميل الفيديو")
        return

    # ── ساوند [كلمة] → بحث ساوند كلاود ─────────────────────────────────
    if text.startswith("ساوند "):
        if await _is_disabled(cid, "disableSound"):
            return
        query = text.split(None, 1)[1]
        try:
            sc_opts = {"quiet": True, "skip_download": True, "noplaylist": True, "extract_flat": True}
            info, _ = await _run_ydl(sc_opts, f"scsearch5:{query}", download=False)
            entries = (info.get("entries") or [])[:5]
        except Exception:
            return await m.reply(f"{k} فشل البحث في ساوند كلاود")
        if not entries:
            return await m.reply(f"{k} ما لقيت نتائج")
        buttons = []
        for entry in entries:
            page_url = entry.get("url") or entry.get("webpage_url", "")
            title    = (entry.get("title") or page_url)[:60]
            sc_key   = page_url.split("soundcloud.com")[1] if "soundcloud.com" in page_url else page_url
            buttons.append([InlineKeyboardButton(
                title,
                switch_inline_query_current_chat=f"{sc_key}#SOUND",
            )])
        await m.reply(f"{k} بحث الساوند ~ {query}", reply_markup=InlineKeyboardMarkup(buttons))
        return

    # ── رابط ساوند كلاود مباشر ───────────────────────────────────────────
    found = _find_urls(text)
    if found and "soundcloud" in found[0]:
        if await _is_disabled(cid, "disableSound"):
            return
        channel = await _get_channel()
        sc_id = found[0].split("soundcloud.com")[1]
        return await m.reply(
            f"@{channel} - ☁️",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "اضغط هنا لاختيار صيغة التحميل",
                    switch_inline_query_current_chat=f"{sc_id}#SOUND",
                )],
                [InlineKeyboardButton("☁️", url=f"t.me/{channel}")],
            ]),
        )

    # ── تحميل صوت / بصمة ساوند كلاود (#AUDIO / #VOICE) ─────────────────
    if text.endswith("#AUDIO") or text.endswith("#VOICE"):
        found = _find_urls(text)
        if found and "soundcloud" in found[0]:
            if await _is_disabled(cid, "disableSound"):
                return
            is_voice = text.endswith("#VOICE")
            url      = found[0]
            sc_key   = url.split("soundcloud.com/")[1] if "soundcloud.com/" in url else url
            cache_k  = f"{sc_key}:soundVoice" if is_voice else f"{sc_key}:sound"
            channel  = await _get_channel()

            cached = await ar.get(cache_k)
            if cached:
                if is_voice:
                    return await m.reply_voice(cached)
                return await m.reply_audio(cached)

            try:
                info, _ = await _run_ydl({}, url, download=False)
            except Exception:
                return await m.reply(f"{k} فشل جلب معلومات الصوت")

            if int(info.get("duration", 0)) > 1500:
                return await m.reply(f"{k} مقطع أكثر من 25 دقيقة ما أقدر أنزله")

            try:
                info, ytdl2 = await _run_ydl({"outtmpl": "%(id)s.%(ext)s"}, url, download=True)
                fn = ytdl2.prepare_filename(info)
            except Exception:
                return await m.reply(f"{k} فشل تحميل الصوت")

            if is_voice:
                rid = random.randint(1, 100000)
                ogg = f"voice{rid}.ogg"
                try:
                    proc = await asyncio.create_subprocess_exec(
                        "ffmpeg", "-i", _sanitize_filename(fn),
                        "-ac", "1", "-strict", "-2",
                        "-codec:a", "libopus",
                        "-b:a", "128k", "-vbr", "off",
                        "-ar", "24000", ogg, "-y", "-loglevel", "quiet",
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    await proc.communicate()
                    sent = await m.reply_voice(ogg)
                    await ar.set(cache_k, sent.voice.file_id)
                except Exception as e:
                    logger.error("فشل تحويل الصوت: %s", e)
                    return await m.reply(f"{k} فشل معالجة الصوت")
                finally:
                    for f in [fn, ogg]:
                        try:
                            if os.path.exists(f):
                                os.remove(f)
                        except Exception as e:
                            logger.error("فشل حذف الملف المؤقت '%s': %s", f, e)
            else:
                title = info.get("title", "صوت")
                dur   = int(info.get("duration", 0))
                try:
                    sent  = await m.reply_audio(fn, title=title, performer=f"@{channel}", duration=dur)
                    await ar.set(cache_k, sent.audio.file_id)
                except Exception:
                    await m.reply(f"{k} فشل إرسال الصوت")
                finally:
                    try:
                        if os.path.exists(fn):
                            os.remove(fn)
                    except Exception as e:
                        logger.error("فشل حذف الملف المؤقت '%s': %s", fn, e)
            return


# ── ساوند كلاود Inline ───────────────────────────────────────────────────

@Client.on_inline_query(filters.regex("SOUND"))
async def soundcloud_inline(c: Client, query):
    url_part = query.query.split("#SOUND")[0]
    channel  = await _get_channel()
    prefix   = "https://soundcloud.com" if url_part.count("/") > 1 else "https://on.soundcloud.com"
    full_url = f"{prefix}{url_part}"
    await query.answer(
        results=[
            InlineQueryResultArticle(
                title="اضغط للتحميل - صوت",
                description="~ ساوند كلاود",
                url=f"https://t.me/{channel}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🧚‍♀️", url=f"t.me/{channel}")]]),
                input_message_content=InputTextMessageContent(f"{full_url} #AUDIO", disable_web_page_preview=True),
            ),
            InlineQueryResultArticle(
                title="اضغط للتحميل - بصمة",
                description="~ ساوند كلاود",
                url=f"https://t.me/{channel}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🧚‍♀️", url=f"t.me/{channel}")]]),
                input_message_content=InputTextMessageContent(f"{full_url} #VOICE", disable_web_page_preview=True),
            ),
        ],
        cache_time=1,
    )


# ── يوتيوب Callback: قائمة نتائج → اختيار نوع ───────────────────────────

@Client.on_callback_query(filters.regex("GET"))
async def yt_get_info(c: Client, query):
    user_id, vid_id = query.data.split("GET")
    if str(query.from_user.id) != user_id:
        await query.answer("هذا الزر ليس لك", show_alert=True)
        return
    if not await ar.get(f"{query.message.id}:one_minute:{user_id}"):
        k = botkey()
        await query.answer(f"{k} مرّت أكثر من دقيقة، ابحث مرة أخرى", show_alert=True)
        try:
            await query.message.delete()
        except Exception:
            pass
        return
    if await ar.get(f"{query.message.chat.id}:disableYT:{DEV_ID}"):
        await query.answer("الميزة معطلة", show_alert=True)
        return
    try:
        await query.message.delete()
    except Exception:
        pass
    channel = await _get_channel()
    url = f"https://youtu.be/{vid_id}"
    try:
        ydl_info_opts = {"skip_download": True, "quiet": True}
        info, _ = await _run_ydl(ydl_info_opts, url, download=False)
        thumbnail = info.get("thumbnail", f"https://img.youtube.com/vi/{vid_id}/hqdefault.jpg")
    except Exception:
        thumbnail = f"https://img.youtube.com/vi/{vid_id}/hqdefault.jpg"
    await query.message.reply_to_message.reply_photo(
        thumbnail,
        caption=f"@{channel} ~ {url}",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("♫ صوت",  callback_data=f"{user_id}AUDIO{vid_id}"),
                InlineKeyboardButton("❖ فيديو", callback_data=f"{user_id}VIDEO{vid_id}"),
            ],
            [InlineKeyboardButton("🧚‍♀️", url=f"https://t.me/{channel}")],
        ]),
    )


@Client.on_callback_query(filters.regex("^[0-9]+AUDIO"))
async def yt_audio_download(c: Client, query):
    user_id, vid_id = query.data.split("AUDIO")
    if str(query.from_user.id) != user_id:
        await query.answer("هذا الزر ليس لك", show_alert=True)
        return
    if await ar.get(f"{query.message.chat.id}:disableYT:{DEV_ID}"):
        await query.answer("الميزة معطلة", show_alert=True)
        return
    channel = await _get_channel()
    rep = _channel_markup(channel)
    url = f"https://youtu.be/{vid_id}"

    cached = await _yt_cache_get("audio", vid_id)
    if cached:
        file_id, dur_str = cached
        try:
            await query.edit_message_caption(f"@{channel} :)", reply_markup=rep)
        except Exception:
            pass
        await query.answer("تم الإرسال من الكاش", show_alert=False)
        return await query.message.reply_audio(file_id, caption=f"@{channel} ~ ⏳ {dur_str}")

    try:
        await query.edit_message_caption("جاري التحميل ..", reply_markup=rep)
    except Exception:
        pass

    ydl_ops = {"format": "bestaudio[ext=m4a]", "forceduration": True, "outtmpl": "%(id)s.%(ext)s"}
    try:
        info, ydl = await _run_ydl(ydl_ops, url, download=True)
    except Exception:
        await query.answer("فشل التحميل", show_alert=True)
        return

    audio_file = ydl.prepare_filename(info)
    mp3_file   = audio_file.replace(".m4a", ".mp3")

    if not os.path.exists(audio_file):
        await query.answer("فشل التحميل", show_alert=True)
        return

    os.rename(audio_file, mp3_file)
    dur     = int(info["duration"])
    dur_str = _seconds_to_str(dur)

    try:
        await query.edit_message_caption("✈️✈️✈️✈️✈️", reply_markup=rep)
    except Exception:
        pass

    try:
        sent = await query.message.reply_audio(
            mp3_file,
            title=info["title"],
            duration=dur,
            performer=info.get("channel", ""),
            caption=f"@{channel} ~ ⏳ {dur_str}",
        )
    except Exception:
        await query.answer("فشل إرسال الصوت", show_alert=True)
        try:
            os.remove(mp3_file)
        except Exception:
            pass
        return

    try:
        await query.edit_message_caption(f"@{channel} :)", reply_markup=rep)
    except Exception:
        pass

    await _yt_cache_set("audio", vid_id, sent.audio.file_id, dur_str)
    try:
        os.remove(mp3_file)
    except Exception as e:
        logger.error("فشل حذف الملف المؤقت '%s': %s", mp3_file, e)


@Client.on_callback_query(filters.regex("^[0-9]+VIDEO"))
async def yt_video_download(c: Client, query):
    user_id, vid_id = query.data.split("VIDEO")
    if str(query.from_user.id) != user_id:
        await query.answer("هذا الزر ليس لك", show_alert=True)
        return
    if await ar.get(f"{query.message.chat.id}:disableYT:{DEV_ID}"):
        await query.answer("الميزة معطلة", show_alert=True)
        return
    channel = await _get_channel()
    rep = _channel_markup(channel)
    url = f"https://youtu.be/{vid_id}"

    cached = await _yt_cache_get("video", vid_id)
    if cached:
        file_id, dur_str = cached
        try:
            await query.edit_message_caption(f"@{channel} :)", reply_markup=rep)
        except Exception:
            pass
        await query.answer("تم الإرسال من الكاش", show_alert=False)
        return await query.message.reply_video(file_id, caption=f"@{channel} ~ ⏳ {dur_str}")

    try:
        await query.edit_message_caption("جاري التحميل ..", reply_markup=rep)
    except Exception:
        pass

    ydl_opts = {"format": "best", "outtmpl": "%(id)s.%(ext)s", "geo_bypass": True}

    try:
        info, ydl = await _run_ydl(ydl_opts, url, download=False)
    except Exception:
        await query.answer("فشل جلب معلومات الفيديو", show_alert=True)
        return

    if int(info["duration"]) > 1500:
        try:
            await query.edit_message_caption("فيديو أكثر من 25 دقيقة ما أقدر أنزله", reply_markup=rep)
        except Exception:
            pass
        await query.answer("الفيديو طويل جداً", show_alert=True)
        return

    try:
        info, ydl = await _run_ydl(ydl_opts, url, download=True)
    except Exception:
        await query.answer("فشل تحميل الفيديو", show_alert=True)
        return

    fn      = ydl.prepare_filename(info)
    dur     = int(info["duration"])
    dur_str = _seconds_to_str(dur)

    try:
        await query.edit_message_caption("✈️✈️✈️✈️✈️", reply_markup=rep)
    except Exception:
        pass

    try:
        sent = await query.message.reply_video(
            fn,
            duration=dur,
            caption=f"@{channel} ~ ⏳ {dur_str}",
        )
    except Exception:
        await query.answer("فشل إرسال الفيديو", show_alert=True)
        try:
            os.remove(fn)
        except Exception:
            pass
        return

    try:
        await query.edit_message_caption(f"@{channel} :)", reply_markup=rep)
    except Exception:
        pass

    await _yt_cache_set("video", vid_id, sent.video.file_id, dur_str)
    try:
        os.remove(fn)
    except Exception as e:
        logger.error("فشل حذف ملف الفيديو المؤقت '%s': %s", fn, e)


# ── شازام ─────────────────────────────────────────────────────────────────

@Client.on_message(filters.regex("^شازام$") & filters.group)
async def shazam_identify(c: Client, m: Message):
    if not SHAZAM_OK:
        return await m.reply("🧚‍♀️ خدمة الشازام غير متاحة حالياً")
    if await ar.get(f"{m.chat.id}:disableShazam:{DEV_ID}"):
        return
    if not m.reply_to_message:
        return await m.reply("🧚‍♀️ ردّ على رسالة صوت / صوتية / فيديو")
    rep   = m.reply_to_message
    media = rep.audio or rep.voice or rep.video
    if not media:
        return await m.reply("🧚‍♀️ ردّ على رسالة صوت / صوتية / فيديو")
    if media.duration and media.duration > 300:
        return await m.reply("🧚‍♀️ مدة المقطع أكثر من 5 دقائق")
    if media.file_size and media.file_size > 26214400:
        return await m.reply("🧚‍♀️ حجم المقطع أكثر من 25 ميجابايت")

    rid = random.randint(1, 100000)
    fn  = f"shazam{rid}.ogg"
    msg = await m.reply("جاري المعالجة ...")
    try:
        await rep.download(fn)
    except Exception:
        await msg.delete()
        return await m.reply("فشل تحميل المقطع")
    try:
        out = await shazam.recognize_song(fn)
    except Exception:
        out = None
    try:
        os.remove(fn)
    except Exception as e:
        logger.error("فشل حذف ملف الشازام '%s': %s", fn, e)
    try:
        await msg.delete()
    except Exception:
        pass

    if not out or not out.get("matches"):
        return await m.reply("فشل التعرف على الصوت")

    k       = botkey()
    channel = await _get_channel()
    title   = out["track"]["title"]
    author  = out["track"]["subtitle"]
    url     = out["track"]["url"]
    try:
        photo = out["track"]["images"]["background"]
    except Exception:
        photo = None

    text = f"{k} اسم الصوت: [{title}]({url})\n{k} الفنان: {author}"
    key  = InlineKeyboardMarkup([[InlineKeyboardButton("🧚‍♀️", url=f"t.me/{channel}")]])
    if photo:
        await m.reply_photo(photo, caption=text, reply_markup=key)
    else:
        await m.reply(text, reply_markup=key)


@Client.on_message(filters.regex("^شازام .+") & filters.group)
async def shazam_lyrics(c: Client, m: Message):
    if not SHAZAM_OK:
        return
    if await ar.get(f"{m.chat.id}:disableShazam:{DEV_ID}"):
        return
    query = m.text.split(None, 1)[1]
    try:
        out = await shazam.search_track(query=query, limit=1)
    except Exception:
        return await m.reply("فشل العثور")
    if not out:
        return await m.reply("فشل العثور")
    try:
        key     = int(out["tracks"]["hits"][0]["key"])
        title   = out["tracks"]["hits"][0]["heading"]["title"][:35]
        author  = out["tracks"]["hits"][0]["heading"]["subtitle"]
        url     = out["tracks"]["hits"][0]["url"]
        about   = await shazam.track_about(track_id=key)
        texts   = about["sections"][1]["text"]
        lyrics  = "\n".join(texts)
        await m.reply(
            lyrics[:4096],
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(f"{title} - {author}", url=url)]]
            ),
        )
    except Exception:
        await m.reply("فشل العثور")
