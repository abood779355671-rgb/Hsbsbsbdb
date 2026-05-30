"""
فلتر الكلمات السيئة
أوامر:
  اضف كلمة [كلمة]        → إضافة كلمة محظورة
  حذف كلمة [كلمة]        → حذف كلمة من القائمة
  الكلمات المحظورة        → عرض القائمة
  تفعيل فلتر الكلمات      → تشغيل الفلتر
  تعطيل فلتر الكلمات      → إيقاف الفلتر
"""
import re
import asyncio
import time
from pyrogram import Client, filters
from pyrogram.types import Message

from config import r, DEV_ID, botkey, cached_smembers, ar
from helpers.ranks import is_mod, is_pre
from helpers.utils import group_enabled, resolve_text

# ── Cache محلي في الذاكرة ────────────────────────────────────────────────────
_FILTER_TTL = 10

# {cid: (enabled: bool, expires_at: float)}
_filter_enabled_cache: dict[int, tuple[bool, float]] = {}

# {cid: (pattern: re.Pattern | None, expires_at: float)}
_filter_pattern_cache: dict[int, tuple[re.Pattern | None, float]] = {}


# ✅ إصلاح 2: تحويل _is_filter_enabled إلى async مع stale-while-revalidate
# بدلاً من r.get() المتزامن الذي يُجمّد event loop لكل رسالة

async def _refresh_filter_enabled(cid: int):
    """يُحدِّث كاش حالة الفلتر من Redis async — يُستدعى في الخلفية فقط"""
    try:
        enabled = bool(await ar.get(f"{cid}:wordfilter:{DEV_ID}"))
        _filter_enabled_cache[cid] = (enabled, time.monotonic() + _FILTER_TTL)
    except Exception:
        pass


async def _is_filter_enabled(cid: int) -> bool:
    """
    ✅ إصلاح 2: async مع stale-while-revalidate — لا blocking Redis.
    - الكاش حديث → إرجاع فوري بدون I/O.
    - الكاش منتهٍ → أعد القيمة القديمة + جدول async refresh في الخلفية.
    - أول مرة → await ar.get() مرة واحدة فقط ثم يُخزَّن.
    """
    entry = _filter_enabled_cache.get(cid)
    now = time.monotonic()
    if entry:
        enabled, expires = entry
        if now < expires:
            return enabled
        # الكاش انتهى — stale-while-revalidate
        try:
            asyncio.get_running_loop().create_task(_refresh_filter_enabled(cid))
        except RuntimeError:
            pass
        return enabled
    # أول مرة — async fetch مباشر (مقبول لأنه مرة واحدة لكل مجموعة)
    try:
        enabled = bool(await ar.get(f"{cid}:wordfilter:{DEV_ID}"))
    except Exception:
        enabled = False
    _filter_enabled_cache[cid] = (enabled, now + _FILTER_TTL)
    return enabled


def _invalidate_filter_enabled(cid: int) -> None:
    """امسح cache الحالة فور تغييرها (تفعيل/تعطيل)."""
    _filter_enabled_cache.pop(cid, None)


def _get_compiled_pattern(cid: int) -> re.Pattern | None:
    """
    يُرجع Regex مجمّع لكل الكلمات المحظورة في المجموعة.
    cache محلي يتجنب استدعاء cached_smembers في كل رسالة.
    """
    entry = _filter_pattern_cache.get(cid)
    if entry and time.monotonic() < entry[1]:
        return entry[0]
    words = cached_smembers(f"{cid}:badwords:{DEV_ID}")
    if words:
        pattern = re.compile(
            "|".join(re.escape(w) for w in words),
            re.IGNORECASE,
        )
    else:
        pattern = None
    _filter_pattern_cache[cid] = (pattern, time.monotonic() + _FILTER_TTL)
    return pattern


def _invalidate_pattern(cid: int) -> None:
    """امسح cache الـ Pattern فور إضافة/حذف كلمة."""
    _filter_pattern_cache.pop(cid, None)


# ── معالج الأوامر (group=17) ─────────────────────────────────────────────────
@Client.on_message(filters.text & filters.group, group=17)
async def word_filter_commands(c: Client, m: Message):
    if not m.from_user:
        return
    cid, uid = m.chat.id, m.from_user.id
    if not group_enabled(cid):
        return
    text = resolve_text(m.text, cid)
    k    = botkey()

    add_m = re.fullmatch(r"اضف كلمة\s+(.+)", text)
    if add_m:
        if not is_mod(uid, cid):
            return await m.reply(f"{k} هذا الأمر للمدير وفوق فقط")
        word = add_m.group(1).strip().lower()
        await ar.sadd(f"{cid}:badwords:{DEV_ID}", word)
        _invalidate_pattern(cid)
        return await m.reply(f"{k} تم إضافة الكلمة المحظورة: `{word}` ✅")

    del_m = re.fullmatch(r"حذف كلمة\s+(.+)", text)
    if del_m:
        if not is_mod(uid, cid):
            return await m.reply(f"{k} هذا الأمر للمدير وفوق فقط")
        word = del_m.group(1).strip().lower()
        await ar.srem(f"{cid}:badwords:{DEV_ID}", word)
        _invalidate_pattern(cid)
        return await m.reply(f"{k} تم حذف الكلمة: `{word}` ✅")

    if text == "الكلمات المحظورة":
        if not is_mod(uid, cid):
            return await m.reply(f"{k} هذا الأمر للمدير وفوق فقط")
        words = cached_smembers(f"{cid}:badwords:{DEV_ID}")
        if not words:
            return await m.reply(f"{k} لا توجد كلمات محظورة")
        return await m.reply(
            f"{k} الكلمات المحظورة:\n" +
            "\n".join(f"• `{w}`" for w in sorted(words))
        )

    if text == "تفعيل فلتر الكلمات":
        if not is_mod(uid, cid):
            return await m.reply(f"{k} هذا الأمر للمدير وفوق فقط")
        await ar.set(f"{cid}:wordfilter:{DEV_ID}", 1)
        _invalidate_filter_enabled(cid)
        return await m.reply(f"{k} تم تفعيل فلتر الكلمات ✅")

    if text == "تعطيل فلتر الكلمات":
        if not is_mod(uid, cid):
            return await m.reply(f"{k} هذا الأمر للمدير وفوق فقط")
        await ar.delete(f"{cid}:wordfilter:{DEV_ID}")
        _invalidate_filter_enabled(cid)
        return await m.reply(f"{k} تم تعطيل فلتر الكلمات")


# ── معالج الفلترة الفعلية (group=16) ─────────────────────────────────────────
@Client.on_message(filters.text & filters.group, group=16)
async def apply_word_filter(c: Client, m: Message):
    """يحذف الرسائل التي تحتوي كلمات محظورة"""
    if not m.from_user or not m.text:
        return
    cid, uid = m.chat.id, m.from_user.id
    if not group_enabled(cid):
        return

    # ✅ إصلاح 2: await على الدالة async — لا blocking Redis
    if not await _is_filter_enabled(cid):
        return

    if is_pre(uid, cid):
        return

    pattern = _get_compiled_pattern(cid)
    if pattern is None:
        return

    if pattern.search(m.text.lower()):
        k       = botkey()
        mention = m.from_user.mention
        deleted = False
        try:
            await m.delete()
            deleted = True
        except Exception:
            pass
        if deleted:
            try:
                await c.send_message(cid, f"{k} {mention}، رسالتك تحتوي كلمة محظورة 🚫")
            except Exception:
                pass
