"""قرارداد آداپتور پلتفرم — هر پلتفرمی (دیوار/ترب/سایت عمومی) این سه متد را پیاده می‌کند.

چرخه کار هر آداپتور:
    discover(spec)      → فهرست آگهی‌های حوزه هدف (ListingRef)
    fetch_detail(ref)   → دانلود جزئیات (JSON یا HTML خام)
    parse_detail(...)   → تبدیل به Lead (استخراج فیلدها + شماره تماس)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable, Union

from ..crawler.base import Fetcher
from ..models import ListingRef, Lead


class ScanSpec:
    """مشخصات یک اسکن: کدام پلتفرم، کدام حوزه، چه محدودیتی."""

    def __init__(
        self,
        platform: str,
        city: str | None = None,
        category: str | None = None,
        query: str | None = None,
        urls: list[str] | None = None,
        max_pages: int = 1,
        max_items: int | None = None,
    ):
        self.platform = platform
        self.city = city
        self.category = category
        self.query = query
        self.urls = urls or []
        self.max_pages = max_pages
        self.max_items = max_items

    def describe(self) -> str:
        bits = [self.platform]
        if self.city:
            bits.append(f"city={self.city}")
        if self.category:
            bits.append(f"category={self.category}")
        if self.query:
            bits.append(f"q={self.query}")
        if self.urls:
            bits.append(f"urls={len(self.urls)}")
        return " ".join(bits)


Payload = Union[dict, str]  # JSON پلتفرم یا HTML خام


class PlatformAdapter(ABC):
    name: str = "base"

    @abstractmethod
    def discover(self, spec: ScanSpec) -> Iterable[ListingRef]:  # pragma: no cover
        ...

    @abstractmethod
    def fetch_detail(self, ref: ListingRef) -> Payload:  # pragma: no cover
        ...

    @abstractmethod
    def parse_detail(self, payload: Payload, ref: ListingRef) -> Lead:  # pragma: no cover
        ...


# ---------- ابزارهای مشترک پارس مقاوم (Resilient Parsing) ----------
def dig(obj, path: str, default=None):
    """دسترسی امن به مسیر نقطه‌ای داخل JSON تودرتو: dig(data, 'post.city.name')"""
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur


# کلیدهایی که معمولاً شماره تماس در آن‌ها قرار می‌گیرد
PHONE_KEYS = {
    "phone", "phone_number", "contact_phone", "display_phone",
    "telephone", "mobile", "shop_phone", "phone_1", "phone_2",
    "contact_number", "seller_phone", "support_phone",
}


def walk_phone_values(node) -> Iterable[str]:
    """پیمایش بازگشتی JSON و برگرداندن مقادیر کلیدهای مرتبط با شماره تماس."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k.lower() in PHONE_KEYS and isinstance(v, (str, int)):
                yield str(v)
            else:
                yield from walk_phone_values(v)
    elif isinstance(node, list):
        for item in node:
            yield from walk_phone_values(item)


def json_text(payload: dict) -> str:
    """serialize کردن کل JSON برای اسکن کامل متن (fallback شماره تماس)."""
    import json

    return json.dumps(payload, ensure_ascii=False)
