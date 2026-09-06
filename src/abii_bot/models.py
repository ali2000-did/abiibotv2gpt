"""مدل داده اصلی پروژه.

`Lead` واحد مرکزی داده است: هر رکورد = یک فرصت تماس (عمدتاً شماره تماس فروشنده)
که از یک آگهی/محصول/صفحه وب استخراج شده است.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ListingRef:
    """ارجاع به یک آگهی/محصول/صفحه قبل از دانلود جزئیات."""

    source: str  # divar | torob | web
    source_id: str  # token / random_key / hash(URL)
    url: str

    def key(self) -> tuple[str, str]:
        return (self.source, self.source_id)


@dataclass
class Lead:
    """رکورد نهایی استخراج‌شده."""

    source: str
    source_id: str
    url: str
    title: Optional[str] = None
    category: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    price: Optional[str] = None
    seller_name: Optional[str] = None
    phones: list[str] = field(default_factory=list)  # ملی: 09xxxxxxxxx / 021xxxxxxxx
    emails: list[str] = field(default_factory=list)
    site: Optional[str] = None  # وب‌سایت اختصاصی فروشنده (اگر داشته باشد)
    description: Optional[str] = None  # قطعه‌ای کوتاه از توضیحات (اختیاری)
    quality_score: int = 0  # 0..100
    status: str = "new"  # new | updated | duplicate
    first_seen: datetime = field(default_factory=utcnow)
    last_seen: datetime = field(default_factory=utcnow)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["first_seen"] = self.first_seen.isoformat()
        d["last_seen"] = self.last_seen.isoformat()
        d["phones"] = "; ".join(self.phones)
        d["emails"] = "; ".join(self.emails)
        return d

    @property
    def primary_phone(self) -> Optional[str]:
        return self.phones[0] if self.phones else None

    def __str__(self) -> str:  # pragma: no cover
        phone = self.primary_phone or "—"
        return f"[{self.source}] {self.title or self.url} | {phone}"
