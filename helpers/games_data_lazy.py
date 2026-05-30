"""
Lazy loader لبيانات الألعاب — يُحمَّل عند أول استخدام فقط
بدلاً من تحميل 191KB عند الإقلاع
"""
import importlib
import logging
from typing import Any

logger = logging.getLogger("games_data_lazy")

_module = None
# ✅ إصلاح 2: تتبع فشل التحميل لمنع إعادة المحاولة في كل وصول
_load_failed = False

# قائمة المتغيرات القابلة للاستيراد من games_data
_EXPORTED_VARS = frozenset({
    "Maths", "words", "Arab", "gomal", "trteep", "emojis", "english",
    "m3any", "countries", "mthal", "countries_", "cut", "deen",
    "cars", "anime", "emojis_pics", "pics", "jobs", "knzs",
    "tashfeer", "football", "tarkeeb",
})


def _load() -> Any:
    """
    يُحمِّل helpers.games_data عند أول استدعاء ويُخزّنه.
    ✅ إصلاح 2: عند فشل التحميل يُسجّل الخطأ ولا يُعيد المحاولة
    (بدلاً من إلقاء ImportError في كل وصول وإبطاء كل الألعاب)
    """
    global _module, _load_failed
    if _module is not None:
        return _module
    if _load_failed:
        raise ImportError("helpers.games_data فشل تحميله سابقاً — راجع السجلات")
    try:
        _module = importlib.import_module("helpers.games_data")
        return _module
    except Exception as e:
        _load_failed = True
        logger.error("فشل تحميل helpers.games_data: %s", e)
        raise ImportError(f"helpers.games_data غير متاح: {e}") from e


# ✅ إصلاح 1: حُذفت _LazyProxy و _proxy — كانتا غير مستخدمتين خارجياً
# __getattr__ على مستوى الوحدة يؤدي نفس الوظيفة بشكل أنظف
# (Python يستدعي __getattr__ تلقائياً عند import X from games_data_lazy)

def __getattr__(name: str):
    """
    ✅ يُؤجّل تحميل games_data حتى أول وصول فعلي لأي متغير.
    يُستدعى تلقائياً عند: from helpers.games_data_lazy import Maths
    """
    if name in _EXPORTED_VARS:
        return getattr(_load(), name)
    raise AttributeError(f"module 'helpers.games_data_lazy' has no attribute {name!r}")
