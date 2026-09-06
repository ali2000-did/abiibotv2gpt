"""پاکسازی و اعتبارسنجی Lead + منطق تشخیص تکراری/به‌روزرسانی."""
from __future__ import annotations

from ..extraction.fields import clean_text
from ..models import Lead
from .quality import quality_score


def normalize_lead(lead: Lead) -> Lead:
    """پاکسازی همه فیلدها + مرتب‌سازی شماره‌ها (موبایل اول) + امتیاز کیفیت."""
    lead.title = clean_text(lead.title, 200)
    lead.seller_name = clean_text(lead.seller_name, 120)
    lead.city = clean_text(lead.city, 60)
    lead.category = clean_text(lead.category, 120)
    lead.price = clean_text(lead.price, 60)
    lead.description = clean_text(lead.description, 300)

    mobiles = [p for p in lead.phones if p.startswith("09")]
    landlines = [p for p in lead.phones if not p.startswith("09")]
    # حذف تکراری با حفظ ترتیب
    lead.phones = list(dict.fromkeys(mobiles + landlines))
    lead.emails = list(dict.fromkeys(lead.emails))
    if not lead.phones:
        lead.phones = []
    lead.quality_score = quality_score(lead)
    return lead


class Deduper:
    """وضعیت هر Lead را نسبت به دیتابیس تعیین می‌کند.

    new       → این source_id را قبلاً ندیده‌ایم
    updated   → دیده‌ایم ولی شماره‌هایش تغییر کرده
    duplicate → دقیقاً همان رکورد قبلی
    """

    def __init__(self, store):
        self.store = store

    def classify(self, lead: Lead) -> str:
        prev = self.store.get(lead.source, lead.source_id)
        if prev is None:
            return "new"
        prev_phones = set(prev.phones)
        cur_phones = set(lead.phones)
        if prev_phones == cur_phones:
            return "duplicate"
        if prev_phones and not cur_phones:
            # داده جدید ضعیف‌تر است؛ رکورد قبلی را خراب نکن
            return "duplicate"
        return "updated"
