"""
الأوامر المخصصة - تغيير اسم الأوامر
أوامر:
  اضف امر         → تعيين اسم بديل لأمر موجود
  حذف امر [امر]   → حذف أمر مخصص
  الاوامر المضافة → قائمة الأوامر المخصصة
"""
import re
from pyrogram import Client, filters
from pyrogram.types import Message

from config import r, DEV_ID, botkey, ar, cached_smembers
from helpers.ranks import is_owner, is_admin
from helpers.utils import group_enabled, can_speak, resolve_text, utils_cache_invalidate

# ── cache محلي لتخطي Redis لكل رسالة في group=999 ─────────────────────────
# يُضاف عند بدء عملية إضافة أمر، يُمسح عند الإنهاء أو الإلغاء
_WAITING_CUSTOM: set[int] = set()  # uid


@Client.on_message(filters.text & filters.group, group=999)
async def custom_commands(c: Client, m: Message):
    if not m.from_user:
        return
    uid = m.from_user.id
    cid = m.chat.id

    text = resolve_text(m.text, cid)

    # ── إلغاء في منتصف العملية (يُفحص قبل أي شيء) ───────────────────────
    if text == "الغاء" and uid in _WAITING_CUSTOM:
        k = botkey()
        if await ar.delete(f"{cid}:addCustom:{uid}:{DEV_ID}"):
            _WAITING_CUSTOM.discard(uid)
            return await m.reply(f"{k} تم إلغاء إضافة الأمر")
        if await ar.delete(f"{cid}:addCustom2:{uid}:{DEV_ID}"):
            _WAITING_CUSTOM.discard(uid)
            return await m.reply(f"{k} تم إلغاء إضافة الأمر")
        return

    # ── الفحص المبكر للمراحل — صفر Redis لـ 99% من الرسائل ──────────────
    if uid in _WAITING_CUSTOM:
        if not group_enabled(cid):
            return
        if not can_speak(uid, cid):
            return
        k = botkey()

        # جلب المفتاحين دفعةً واحدة — بدون استدعاء مزدوج لنفس المفتاح
        c2_val, c1_val = await ar.mget([
            f"{cid}:addCustom2:{uid}:{DEV_ID}",
            f"{cid}:addCustom:{uid}:{DEV_ID}",
        ])

        # ── مرحلة 2: استقبال الاسم الجديد ───────────────────────────────
        if c2_val and is_admin(uid, cid) and len(text) < 60:
            old_cmd = c2_val  # القيمة من mget مباشرة — بدون استدعاء مزدوج
            new_cmd = text
            await ar.delete(f"{cid}:addCustom2:{uid}:{DEV_ID}")
            await ar.set(f"{cid}:Custom:{cid}:{DEV_ID}&text={new_cmd}", old_cmd)
            await ar.sadd(f"{cid}:listCustom:{cid}:{DEV_ID}", new_cmd)
            utils_cache_invalidate(f"rtxt:l:{cid}:{new_cmd}")
            _WAITING_CUSTOM.discard(uid)
            return await m.reply(
                f"{k} تم إضافة الأمر:\n"
                f"الاسم الجديد: `{new_cmd}`\n"
                f"يُحوَّل إلى: `{old_cmd}` ✅"
            )

        # ── مرحلة 1: استقبال الأمر الأصلي ──────────────────────────────
        if c1_val and is_admin(uid, cid) and len(text) < 60:
            await ar.delete(f"{cid}:addCustom:{uid}:{DEV_ID}")
            await ar.set(f"{cid}:addCustom2:{uid}:{DEV_ID}", text, ex=300)
            # uid ينتقل من step1 إلى step2 — يبقى في _WAITING_CUSTOM
            return await m.reply(
                f"{k} ممتاز! الأمر الأصلي هو: `{text}`\n"
                f"الآن أرسل الاسم البديل الذي تريده\n"
                "أرسل **الغاء** للتراجع"
            )

        # TTL انتهى أو المفاتيح لا تتطابق — نظّف الـ set
        _WAITING_CUSTOM.discard(uid)
        return

    # من هنا: uid ليس في وضع انتظار — الأوامر العامة فقط
    if not group_enabled(cid):
        return
    if not can_speak(uid, cid):
        return
    k = botkey()

    # ── قائمة الأوامر المضافة ─────────────────────────────────────────────
    if text in ("الاوامر المضافه", "الاوامر المضافة"):
        if not is_owner(uid, cid):
            return await m.reply(f"{k} هذا الأمر للمالك وفوق فقط")
        # cached_smembers بدلاً من ar.smembers المباشرة
        cmds = cached_smembers(f"{cid}:listCustom:{cid}:{DEV_ID}")
        if not cmds:
            return await m.reply(f"{k} لا توجد أوامر مخصصة بعد")
        sorted_cmds = sorted(cmds)
        # mget بدلاً من loop بـ N استدعاء منفصل
        originals = await ar.mget([f"{cid}:Custom:{cid}:{DEV_ID}&text={a}" for a in sorted_cmds])
        lines = [f"{k} الأوامر المخصصة:\n"]
        for i, (alias, original) in enumerate(zip(sorted_cmds, originals), 1):
            lines.append(f"{i}. `{alias}` ← `{original or '؟'}`")
        return await m.reply("\n".join(lines))

    # ── اضف امر ──────────────────────────────────────────────────────────
    if text in ("اضف امر", "تغيير امر"):
        if not is_owner(uid, cid):
            return await m.reply(f"{k} هذا الأمر للمالك وفوق فقط")
        if uid in _WAITING_CUSTOM:
            return await m.reply(f"{k} أنت في منتصف إضافة أمر بالفعل، أرسل **الغاء** أولاً")
        await ar.set(f"{cid}:addCustom:{uid}:{DEV_ID}", 1, ex=300)
        _WAITING_CUSTOM.add(uid)
        return await m.reply(
            f"{k} أرسل الأمر الأصلي (الموجود مسبقاً) الآن\n"
            "أرسل **الغاء** للتراجع"
        )

    # ── حذف امر ──────────────────────────────────────────────────────────
    del_m = re.fullmatch(r"حذف امر\s+(.+)", text)
    if del_m:
        if not is_owner(uid, cid):
            return await m.reply(f"{k} هذا الأمر للمالك وفوق فقط")
        alias = del_m.group(1).strip()
        key   = f"{cid}:Custom:{cid}:{DEV_ID}&text={alias}"
        if not await ar.get(key):
            return await m.reply(f"{k} لا يوجد أمر مخصص بهذا الاسم")
        await ar.delete(key)
        await ar.srem(f"{cid}:listCustom:{cid}:{DEV_ID}", alias)
        utils_cache_invalidate(f"rtxt:l:{cid}:{alias}")
        return await m.reply(f"{k} تم حذف الأمر المخصص «{alias}» ✅")
