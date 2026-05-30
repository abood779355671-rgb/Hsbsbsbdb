"""
ألعاب المجموعة
─────────────────────────────────────────────────────
الأوامر:
  العاب            → قائمة الألعاب
  لعبة [اسم]       → بدء لعبة محددة
  انهاء            → إنهاء اللعبة الجارية

الألعاب المتاحة:
  ارقام     → خمّن الرقم
  كلمات     → خمّن الكلمة المقلوبة
  جملة      → رتّب الجملة
  ايموجي    → خمّن الإيموجي
  دول       → عاصمة الدولة
  اعلام     → خمّن العلم
  سيارات    → شعار السيارة
  انمي      → خمّن شخصية الأنمي
  صور       → خمّن الصورة
  تشفير     → فك التشفير
  كرة       → خمّن لاعب كرة القدم
  دين       → أسئلة دينية
  سؤال      → أسئلة عامة (كت كت)
  معاني     → خمّن معنى الإيموجي
  مثل       → خمّن المثل
  تركيب     → جمع الكلمة العربية
  انجليزي   → ترجمة الكلمة
  عربي      → جمع الكلمة العربية
  حساب      → احسب العملية الرياضية
  ترتيب     → رتّب الكلمة المقلوبة
"""

import asyncio
import random
import re
import time

from pyrogram import Client, filters
from pyrogram.types import Message

from config import r, DEV_ID, botkey, botname, ar
from helpers.ranks import is_admin, is_mod, is_dev
from helpers.utils import group_enabled, can_speak, resolve_text
from helpers.games_data_lazy import (   # lazy load — لا يُحمَّل عند الإقلاع
    Maths, words, Arab, gomal, trteep, emojis, english,
    m3any, countries, mthal, countries_, cut, deen,
    cars, anime, emojis_pics, pics, jobs, knzs,
    tashfeer, football, tarkeeb,
)

# ─── ثوابت ──────────────────────────────────────────────────────────────────
GAME_TTL      = 90
SCORE_TTL     = 86400 * 30

GAME_NAMES = {
    "ارقام":    "🔢 خمّن الرقم",
    "كلمات":    "🔤 الكلمة المقلوبة",
    "جملة":     "📝 رتّب الجملة",
    "ايموجي":   "🎭 خمّن الإيموجي",
    "دول":      "🌍 عواصم الدول",
    "اعلام":    "🚩 خمّن العلم",
    "سيارات":   "🚗 شعار السيارة",
    "انمي":     "🎌 خمّن الأنمي",
    "صور":      "🖼️ خمّن الصورة",
    "تشفير":    "🔐 فك التشفير",
    "كرة":      "⚽ خمّن اللاعب",
    "دين":      "🕌 أسئلة دينية",
    "سؤال":     "💬 أسئلة عامة",
    "معاني":    "😀 معاني الإيموجي",
    "مثل":      "📖 الأمثال",
    "تركيب":    "🔡 التركيب",
    "انجليزي":  "🇬🇧 إنجليزي/عربي",
    "عربي":     "🔡 جمع الكلمة",
    "حساب":     "🧮 العمليات الحسابية",
    "ترتيب":    "🔀 رتّب الكلمة",
}

# ─── مساعدات Redis ────────────────────────────────────────────────────────────

def _gkey(cid: int, field: str) -> str:
    return f"game:{DEV_ID}:{cid}:{field}"


async def _get_active(cid: int) -> dict | None:
    # ✅ إصلاح 1: mget واحد بدلاً من استدعاءين منفصلين
    gtype, answer = await ar.mget([_gkey(cid, "type"), _gkey(cid, "answer")])
    if not gtype or not answer:
        return None
    return {"type": gtype, "answer": answer}


async def _set_active(cid: int, gtype: str, answer: str):
    # ✅ إصلاح 1: pipeline واحد بدلاً من استدعاءين منفصلين
    async with ar.pipeline(transaction=False) as pipe:
        pipe.set(_gkey(cid, "type"),   gtype,  ex=GAME_TTL)
        pipe.set(_gkey(cid, "answer"), answer, ex=GAME_TTL)
        await pipe.execute()


async def _clear_active(cid: int):
    # ✅ إصلاح 1: delete مع مفتاحين في استدعاء واحد بدلاً من اثنين
    await ar.delete(_gkey(cid, "type"), _gkey(cid, "answer"))


async def _add_score(uid: int, cid: int, points: int = 1) -> int:
    # ✅ إصلاح 2: pipeline واحد بدلاً من استدعاءين منفصلين
    # ✅ إصلاح إضافي: إعادة النقاط الجديدة مباشرة لتجنب استدعاء _get_user_score
    async with ar.pipeline(transaction=False) as pipe:
        pipe.zincrby(f"game_score:{DEV_ID}:{cid}", points, str(uid))
        pipe.zincrby(f"game_score_global:{DEV_ID}", points, str(uid))
        results = await pipe.execute()
    return int(results[0])  # النقاط الجديدة للمجموعة المحلية


async def _get_top(cid: int, n: int = 10):
    return await ar.zrevrange(f"game_score:{DEV_ID}:{cid}", 0, n - 1, withscores=True)


async def _get_user_score(uid: int, cid: int) -> int:
    s = await ar.zscore(f"game_score:{DEV_ID}:{cid}", str(uid))
    return int(s) if s else 0

# ─── توليد السؤال ────────────────────────────────────────────────────────────

async def _start_game(c: Client, m: Message, gtype: str, k: str):
    cid = m.chat.id

    if gtype == "ارقام":
        ans = random.choice(Maths)
        await m.reply(f"🔢 {k} خمّن الرقم:\n**{_scramble_num(ans)}**\n\n_لديك {GAME_TTL} ثانية_")
        await _set_active(cid, gtype, ans)

    elif gtype == "كلمات":
        ans = random.choice(words)
        scr = _scramble(ans)
        await m.reply(f"🔤 {k} رتّب الحروف لتكوّن كلمة:\n**{scr}**\n\n_لديك {GAME_TTL} ثانية_")
        await _set_active(cid, gtype, ans)

    elif gtype == "جملة":
        raw = random.choice(gomal)
        parts = [p.strip() for p in raw.split("'") if p.strip()]
        ans = " ".join(parts)
        shuffled = parts[:]
        random.shuffle(shuffled)
        await m.reply(f"📝 {k} رتّب الكلمات لتكوّن جملة:\n**{' | '.join(shuffled)}**\n\n_لديك {GAME_TTL} ثانية_")
        await _set_active(cid, gtype, ans)

    elif gtype == "ايموجي":
        ans = random.choice(emojis)
        fake = random.sample([e for e in emojis if e != ans], 3)
        options = fake + [ans]
        random.shuffle(options)
        opts_text = "  ".join(options)
        await m.reply(f"🎭 {k} خمّن الإيموجي الصح:\n{opts_text}\n\n_أرسل الإيموجي مباشرة_\n_لديك {GAME_TTL} ثانية_")
        await _set_active(cid, gtype, ans)

    elif gtype == "دول":
        item = random.choice(countries)
        ans  = item["name"]
        await m.reply(f"🌍 {k} ما اسم الدولة التي عاصمتها:\n**{item['capital']}**\n\n_لديك {GAME_TTL} ثانية_")
        await _set_active(cid, gtype, ans)

    elif gtype == "اعلام":
        item = random.choice(countries_)
        ans  = item["name"]
        await m.reply_photo(item["flag"], caption=f"🚩 {k} خمّن اسم الدولة صاحبة هذا العلم\n\n_لديك {GAME_TTL} ثانية_")
        await _set_active(cid, gtype, ans)

    elif gtype == "سيارات":
        item = random.choice(cars)
        ans  = item["brand"]
        await m.reply_photo(item["photo"], caption=f"🚗 {k} خمّن اسم شركة السيارة\n\n_لديك {GAME_TTL} ثانية_")
        await _set_active(cid, gtype, ans)

    elif gtype == "انمي":
        item = random.choice(anime)
        ans  = item["anime"]
        await m.reply_photo(item["photo"], caption=f"🎌 {k} خمّن اسم الشخصية\n\n_لديك {GAME_TTL} ثانية_")
        await _set_active(cid, gtype, ans)

    elif gtype == "صور":
        item = random.choice(pics)
        ans  = item["answer"]
        cap  = item.get("caption") or "خمّن الصورة"
        await m.reply_photo(item["photo"], caption=f"🖼️ {k} {cap}\n\n_لديك {GAME_TTL} ثانية_")
        await _set_active(cid, gtype, ans)

    elif gtype == "تشفير":
        item = random.choice(tashfeer)
        ans  = item["answer"]
        cap  = item.get("caption") or "فك التشفير"
        await m.reply_photo(item["photo"], caption=f"🔐 {k} {cap}\n\n_لديك {GAME_TTL} ثانية_")
        await _set_active(cid, gtype, ans)

    elif gtype == "كرة":
        item = random.choice(football)
        ans  = item["answer"]
        cap  = item.get("caption") or "خمّن اللاعب"
        await m.reply_photo(item["photo"], caption=f"⚽ {k} {cap}\n\n_لديك {GAME_TTL} ثانية_")
        await _set_active(cid, gtype, ans)

    elif gtype == "دين":
        item = random.choice(deen)
        ans  = item["answer"]
        await m.reply(f"🕌 {k} **{item['question']}**\n\n_لديك {GAME_TTL} ثانية_")
        await _set_active(cid, gtype, ans)

    elif gtype == "سؤال":
        q = random.choice(cut)
        await m.reply(f"💬 {k} **{q}**\n\n_أجب بحرية — لا إجابة صح أو غلط!_")
        await _set_active(cid, gtype, "free")

    elif gtype == "معاني":
        item = random.choice(emojis_pics)
        ans  = item["emoji"]
        await m.reply_photo(item["photo"], caption=f"😀 {k} خمّن الإيموجي المعبّر عن الصورة\n\n_لديك {GAME_TTL} ثانية_")
        await _set_active(cid, gtype, ans)

    elif gtype == "مثل":
        ans = random.choice(mthal)
        scr = _scramble(ans)
        await m.reply(f"📖 {k} خمّن المثل من الحروف المقلوبة:\n**{scr}**\n\n_لديك {GAME_TTL} ثانية_")
        await _set_active(cid, gtype, ans)

    elif gtype == "تركيب":
        ans = random.choice(tarkeeb)
        scr = _scramble(ans)
        await m.reply(f"🔡 {k} رتّب الحروف:\n**{scr}**\n\n_لديك {GAME_TTL} ثانية_")
        await _set_active(cid, gtype, ans)

    elif gtype == "انجليزي":
        ans = random.choice(english)
        await m.reply(f"🇬🇧 {k} ما ترجمة الكلمة:\n**{_to_english_hint(ans)}**\n\n_لديك {GAME_TTL} ثانية_")
        await _set_active(cid, gtype, ans)

    elif gtype == "عربي":
        ans = random.choice(Arab)
        scr = _scramble(ans)
        await m.reply(f"🔡 {k} رتّب الحروف لتكوّن الجمع العربي:\n**{scr}**\n\n_لديك {GAME_TTL} ثانية_")
        await _set_active(cid, gtype, ans)

    elif gtype == "حساب":
        q, ans = _make_math()
        await m.reply(f"🧮 {k} احسب:\n**{q}**\n\n_لديك {GAME_TTL} ثانية_")
        await _set_active(cid, gtype, ans)

    elif gtype == "ترتيب":
        ans = random.choice(trteep)
        scr = _scramble(ans)
        await m.reply(f"🔀 {k} رتّب الحروف:\n**{scr}**\n\n_لديك {GAME_TTL} ثانية_")
        await _set_active(cid, gtype, ans)

# ─── دوال مساعدة ─────────────────────────────────────────────────────────────

def _scramble(word: str) -> str:
    chars = list(word)
    random.shuffle(chars)
    return " ".join(chars)

def _scramble_num(num: str) -> str:
    digits = list(num)
    random.shuffle(digits)
    return "".join(digits)

def _to_english_hint(arabic: str) -> str:
    mapping = {
        "معلومات": "Information",  "قنوات": "Channels",
        "مجموعات": "Groups",       "كتاب": "Book",
        "تفاحه": "Apple",          "مختلف": "Different",
        "مصر": "Egypt",            "فلوس": "Money",
        "اعلم": "I know",          "ذئب": "Wolf",
        "تمساح": "Crocodile",      "ذكي": "Smart",
        "كلب": "Dog",              "صقر": "Falcon",
        "مشكله": "Problem",        "كمبيوتر": "Computer",
        "اصدقاء": "Friends",       "منضده": "Desk",
    }
    return mapping.get(arabic, arabic)

def _make_math() -> tuple[str, str]:
    ops = ["+", "-", "×", "÷"]
    op  = random.choice(ops)
    if op == "+":
        a, b = random.randint(1, 500), random.randint(1, 500)
        return f"{a} + {b}", str(a + b)
    elif op == "-":
        a, b = random.randint(10, 500), random.randint(1, 9)
        return f"{a} - {b}", str(a - b)
    elif op == "×":
        a, b = random.randint(2, 50), random.randint(2, 20)
        return f"{a} × {b}", str(a * b)
    else:
        b = random.randint(2, 20)
        a = b * random.randint(2, 30)
        return f"{a} ÷ {b}", str(a // b)

def _normalize(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[أإآا]", "ا", text)
    text = re.sub(r"[ةه]", "ه", text)
    text = re.sub(r"[يى]", "ي", text)
    text = re.sub(r"\s+", " ", text)
    return text

# ─── معالجات الأوامر ──────────────────────────────────────────────────────────

@Client.on_message(filters.text & filters.group, group=60)
async def games_handler(c: Client, m: Message):
    if not m.from_user:
        return
    cid, uid = m.chat.id, m.from_user.id
    if not group_enabled(cid):
        return

    text = resolve_text(m.text, cid)
    k    = botkey()

    # ── قائمة الألعاب ────────────────────────────────────────────────────
    if text in ("العاب", "الالعاب", "ألعاب"):
        lines = [f"{k} **الألعاب المتاحة:**\n"]
        for cmd, desc in GAME_NAMES.items():
            lines.append(f"  `لعبة {cmd}` ← {desc}")
        lines.append(f"\n{k} لبدء لعبة: `لعبة [اسم]`")
        lines.append(f"{k} لإنهاء اللعبة: `انهاء`")
        return await m.reply("\n".join(lines))

    # ── نقاطي ────────────────────────────────────────────────────────────
    if text in ("نقاطي", "نقطتي", "درجاتي"):
        score = await _get_user_score(uid, cid)
        return await m.reply(f"{k} {m.from_user.mention} نقاطك: **{score}** 🏆")

    # ── ترتيب المجموعة ───────────────────────────────────────────────────
    if text in ("الترتيب", "ترتيب الالعاب", "المتصدرين"):
        top = await _get_top(cid)
        if not top:
            return await m.reply(f"{k} لا توجد نقاط بعد!")
        medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7
        lines  = [f"{k} **ترتيب المجموعة:**\n"]
        uid_list = [int(uid_s) for uid_s, _ in top]
        name_map: dict[int, str] = {}
        try:
            users_bulk = await c.get_users(uid_list)
            if not isinstance(users_bulk, list):
                users_bulk = [users_bulk]
            for u in users_bulk:
                name_map[u.id] = u.first_name[:20]
        except Exception:
            pass
        for i, (uid_s, score) in enumerate(top):
            name = name_map.get(int(uid_s), str(uid_s))
            lines.append(f"{medals[i]} {name} — **{int(score)}** نقطة")
        return await m.reply("\n".join(lines))

    # ── مسح النقاط ───────────────────────────────────────────────────────
    if text == "مسح النقاط":
        if not is_mod(uid, cid):
            return await m.reply(f"{k} هذا الأمر للمدير وفوق فقط")
        await ar.delete(f"game_score:{DEV_ID}:{cid}")
        return await m.reply(f"{k} تم مسح جميع النقاط ✅")

    # ── إنهاء اللعبة ─────────────────────────────────────────────────────
    if text == "انهاء":
        active = await _get_active(cid)
        if not active:
            return await m.reply(f"{k} لا توجد لعبة جارية")
        if not is_admin(uid, cid):
            return await m.reply(f"{k} هذا الأمر للادمن وفوق فقط")
        ans = active["answer"]
        await _clear_active(cid)
        return await m.reply(f"{k} تم إنهاء اللعبة\nالإجابة كانت: **{ans}**")

    # ── بدء لعبة ─────────────────────────────────────────────────────────
    m_start = re.fullmatch(r"لعبة\s+(\S+)", text)
    if m_start:
        gtype = m_start.group(1)
        if gtype not in GAME_NAMES:
            avail = "، ".join(GAME_NAMES.keys())
            return await m.reply(f"{k} لعبة غير موجودة!\nالألعاب: {avail}")
        if await _get_active(cid):
            return await m.reply(f"{k} يوجد لعبة جارية! أرسل **انهاء** أولاً")
        _gban_vals = await ar.mget([f"game_gbangames:{DEV_ID}:{uid}", f"{uid}:gbangames:{DEV_ID}"])
        if any(_gban_vals):
            return await m.reply(f"{k} أنت محظور من الألعاب")
        await _start_game(c, m, gtype, k)
        return

    # ── التحقق من الإجابة ────────────────────────────────────────────────
    active = await _get_active(cid)
    if not active:
        return

    if not can_speak(uid, cid):
        return

    gtype  = active["type"]
    answer = active["answer"]

    if gtype == "سؤال" and answer == "free":
        return

    user_ans = _normalize(text)
    correct  = _normalize(answer)

    if user_ans == correct:
        await _clear_active(cid)
        # ✅ إصلاح 2: _add_score تُعيد النقاط الجديدة مباشرة — لا حاجة لـ _get_user_score
        score = await _add_score(uid, cid)
        await m.reply(
            f"✅ {m.from_user.mention} أجاب صح!\n"
            f"{k} الإجابة: **{answer}**\n"
            f"🏆 نقاطك الآن: **{score}**"
        )


# ─── انتهاء مهلة الجلسة تلقائياً ────────────────────────────────────────────
# (يعتمد على TTL في Redis — لا يحتاج scheduler منفصل)
