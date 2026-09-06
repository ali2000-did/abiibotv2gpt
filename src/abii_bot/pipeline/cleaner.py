"""پاکسازی و اعتبارسنجی Lead + منطق تشخیص تکراری/به‌روزرسانی."""
from __future__ import annotations

from ..extraction.fields import clean_text
from ..extraction.phone import split_real_phones
from ..models import Lead
from .quality import quality_score


def normalize_lead(lead: Lead) -> Lead:
    """پاکسازی همه فیلدها + مرتب‌سازی شماره‌ها (موبایل اول) + امتیاز کیفیت.

    گلوگاه کیفیت: شماره‌های «مشکوک» (الگوی نمایشی مثل 09123456789 یا همه‌صفر)
    همین‌جا حذف می‌شوند تا هیچ داده بی‌ارزشی وارد دیتابیس/خروجی نشود.
    """
    lead.title = clean_text(lead.title, 200)
    lead.seller_name = clean_text(lead.seller_name, 120)
    lead.city = clean_text(lead.city, 60)
    lead.category = clean_text(lead.category, 120)
    lead.price = clean_text(lead.price, 60)
    lead.description = clean_text(lead.description, 300)

    mobiles = [p for p in lead.phones if p.startswith("09")]
    landlines = [p for p in lead.phones if not p.startswith("09")]
    real, junk = split_real_phones(mobiles + landlines)
    if junk:
        import logging

        logging.getLogger(__name__).warning(
            "حذف %s شماره مشکوک/نمایشی از %s: %s", len(junk), lead.source_id, junk
        )
    lead.phones = real  # موبایل اول (ترتیب حفظ شده)
    lead.emails = list(dict.fromkeys(lead.emails))
    if not lead.phones:
        lead.phones = []
    lead.quality_score = quality_score(lead)
    return lead


def reconcile(prev: Lead, cur: Lead) -> Lead:
    """ادغام رکورد قبلی و جدید — داده‌ها فقط کامل‌تر می‌شوند، هرگز ضعیف‌تر نمی‌شوند.

    شماره‌ها اجتماع می‌شوند (موبایل اول)؛ فیلدهای خالیِ جدید از قبلی پر می‌شوند.
    """
    mobiles = [p for p in (*cur.phones, *prev.phones) if p.startswith("09")]
    landlines = [p for p in (*cur.phones, *prev.phones) if not p.startswith("09")]
    cur.phones = list(dict.fromkeys(mobiles + landlines))
    cur.emails = list(dict.fromkeys((*cur.emails, *prev.emails)))
    for field in ("title", "category", "city", "district", "price",
                  "seller_name", "description"):
        if not getattr(cur, field) and getattr(prev, field):
            setattr(cur, field, getattr(prev, field))
    return normalize_lead(cur)


def commit_lead(lead: Lead, store, deduper: "Deduper") -> str:
    """تعیین وضعیت + ذخیره امن یک لید (جلوگیری از بازنویسی داده قوی با ضعیف).

    duplicate → فقط touch (last_seen)؛ updated → ادغام با رکورد قبلی؛ new → درج.
    وضعیت نهایی را برمی‌گرداند.
    """
    status = deduper.classify(lead)
    lead.status = status
    if status == "duplicate":
        store.touch(lead.source, lead.source_id)
    else:
        if status == "updated":
            prev = store.get(lead.source, lead.source_id)
            if prev is not None:
                lead = reconcile(prev, lead)
                lead.status = "updated"
        store.upsert(lead)
    return status


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
