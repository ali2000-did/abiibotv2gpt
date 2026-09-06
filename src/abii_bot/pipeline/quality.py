"""امتیاز کیفیت هر Lead (0 تا 100) — معیار Completeness/Accuracy.

وزن‌ها:
  موبایل +45 | فقط ثابت +30 | عنوان +10 | شهر +10 | دسته +5
  قیمت +10 | نام فروشنده +10 | ایمیل +5 | توضیحات +5
"""
from __future__ import annotations

from ..models import Lead


def quality_score(lead: Lead) -> int:
    score = 0
    if any(p.startswith("09") for p in lead.phones):
        score += 45
    elif lead.phones:  # فقط ثابت
        score += 30
    if lead.title:
        score += 10
    if lead.city:
        score += 10
    if lead.category:
        score += 5
    if lead.price:
        score += 10
    if lead.seller_name:
        score += 10
    if lead.emails:
        score += 5
    if lead.description:
        score += 5
    return min(score, 100)


def dataset_report(leads: list[Lead]) -> dict:
    """گزارش کیفیت کل دیتاست — مطابق چارچوب QA Engineer."""
    total = len(leads)
    with_phone = sum(1 for l in leads if l.phones)
    with_mobile = sum(1 for l in leads if any(p.startswith("09") for p in l.phones))
    return {
        "total": total,
        "with_phone_pct": round(100 * with_phone / total, 1) if total else 0.0,
        "with_mobile_pct": round(100 * with_mobile / total, 1) if total else 0.0,
        "avg_quality": round(sum(l.quality_score for l in leads) / total, 1) if total else 0.0,
        "by_status": {
            s: sum(1 for l in leads if l.status == s) for s in {"new", "updated", "duplicate"}
        },
    }
