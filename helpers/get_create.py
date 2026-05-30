"""
helpers/get_create.py
تقدير تاريخ إنشاء حساب تيليغرام بناءً على الـ ID
يحاول أولاً API خارجي ويرجع للجدول المحلي عند الفشل
"""

import httpx
from config import ar

# جدول نقاط مرجعية (ID → تاريخ تقريبي)
_CHECKPOINTS = [
    (0,             "يناير 2013"),
    (100_000,       "فبراير 2013"),
    (1_000_000,     "أكتوبر 2013"),
    (5_000_000,     "مارس 2014"),
    (10_000_000,    "سبتمبر 2014"),
    (20_000_000,    "مايو 2015"),
    (50_000_000,    "ديسمبر 2015"),
    (100_000_000,   "أبريل 2016"),
    (200_000_000,   "أبريل 2017"),
    (300_000_000,   "ديسمبر 2017"),
    (400_000_000,   "يوليو 2018"),
    (500_000_000,   "مارس 2019"),
    (600_000_000,   "أغسطس 2019"),
    (700_000_000,   "فبراير 2020"),
    (800_000_000,   "يوليو 2020"),
    (900_000_000,   "يناير 2021"),
    (1_000_000_000, "أغسطس 2021"),
    (1_100_000_000, "يناير 2022"),
    (1_200_000_000, "يوليو 2022"),
    (1_300_000_000, "يناير 2023"),
    (1_400_000_000, "يوليو 2023"),
    (1_500_000_000, "ديسمبر 2023"),
    (1_600_000_000, "مايو 2024"),
    (1_700_000_000, "أكتوبر 2024"),
    (1_800_000_000, "مارس 2025"),
    (1_900_000_000, "أغسطس 2025"),
]

# ✅ إصلاح 3: client مشترك على مستوى الوحدة — يُعاد استخدامه بدلاً من إنشاء
# اتصال جديد في كل استدعاء (يوفر وقت TCP handshake وتكلفة SSL)
_http_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=5,
            # ✅ إصلاح 1: حُذف content-type من الـ headers هنا
            # كان يتعارض مع json= الذي يضبط content-type تلقائياً على application/json
            # التعارض كان يُسبب رفض الـ API للطلب أحياناً
            headers={
                "accept": "*/*",
                "user-agent": "Nicegram/92 CFNetwork/1390 Darwin/22.0.0",
                "x-api-key": "e758fb28-79be-4d1c-af6b-066633ded128",
                "accept-language": "en-US,en;q=0.9",
            },
        )
    return _http_client


async def close_client():
    """أغلق الـ client عند إيقاف البوت — استدعِها من main.py في finally"""
    global _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None


def _local_estimate(user_id: int) -> str:
    """تقدير محلي بناءً على الجدول."""
    uid = abs(int(user_id))
    label = _CHECKPOINTS[0][1]
    for threshold, date_label in _CHECKPOINTS:
        if uid >= threshold:
            label = date_label
        else:
            break
    return f"~ {label}"


async def get_creation_date(user_id: int) -> str:
    """
    يُرجع تاريخ إنشاء الحساب (async).
    يحاول API خارجي أولاً مع cache في Redis، ثم يرجع للتقدير المحلي.

    ✅ إصلاح 1: حُذف content-type المتعارض — json= يضبطه تلقائياً
    ✅ إصلاح 2: raise_for_status() لاكتشاف أخطاء HTTP (4xx/5xx) قبل json()
    ✅ إصلاح 3: client مشترك بدلاً من إنشاء جديد في كل استدعاء
    ✅ إصلاح 4: حُذف import r (sync) غير المستخدم — كان يُضيف dependency غير ضرورية
    """
    cache_key = f"{user_id}:CreateDate"
    cached = await ar.get(cache_key)
    if cached:
        return cached

    try:
        client = _get_client()
        res = await client.post(
            "https://restore-access.indream.app/regdate",
            json={"telegramId": user_id},
        )
        # ✅ إصلاح 2: تحقق من كود HTTP قبل محاولة قراءة JSON
        res.raise_for_status()
        data = res.json()
        date_str = data["data"]["date"].replace("-", "/")
        await ar.set(cache_key, date_str, ex=86400)
        return date_str
    except httpx.HTTPStatusError:
        return _local_estimate(user_id)
    except (KeyError, ValueError):
        # الـ API رجع JSON لكن البيانات مختلفة عن المتوقع
        return _local_estimate(user_id)
    except Exception:
        return _local_estimate(user_id)
