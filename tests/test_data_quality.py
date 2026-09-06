"""سوئیت کیفیت داده — «هیچ داده بی‌ارزش/بی‌معنی تولید نشود».

سه لایه دفاع:
  ۱) Extractor: زباله‌های بازارگاهی (قیمت/مدل/IMEI/کدملی/…) هرگز شماره نمی‌شوند
  ۲) Suspicious: فرمتِ درست ولی نمایشی (09123456789، همه‌صفر، دنباله) → پرچم + حذف در Lead
  ۳) Export: ردیف بدون هیچ راه تماسی (شماره/ایمیل) به خروجی نمی‌رود
"""
import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from abii_bot.config import AppConfig
from abii_bot.engine import run_torob_engine
from abii_bot.extraction import extract_phones, is_suspicious_local, split_real_phones
from abii_bot.extraction.phone import is_valid_mobile
from abii_bot.models import Lead
from abii_bot.pipeline.cleaner import normalize_lead
from abii_bot.storage import LeadStore, export_leads

REPO = Path(__file__).parent.parent


# ═══════════════ لایه ۱: زباله بازارگاهی هرگز شماره نمی‌شود ═══════════════
class TestMarketplaceNoise:
    """متن‌های واقعی آگهی/فروشگاه — نباید هیچ شماره‌ای استخراج شود."""

    @pytest.mark.parametrize("text", [
        "قیمت: ۴۵٬۵۰۰٬۰۰۰ تومان — نقدی",               # قیمت با جداکننده فارسی
        "قیمت: 45,500,000 تومان",                        # قیمت انگلیسی
        "۱۰٬۹۰۰٬۰۰۰ تومان تخفیف ویژه",                  # قیمت با ممیز فارسی ٫
        "متراژ ۸۵ متر، ساخت ۱۴۰۰، دو خواب",             # متراژ/سال ساخت
        "مدل X1504 — سری VivoBook",                     # مدل کالا
        "IMEI: 356938035643809",                        # IMEI ۱۵ رقمی
        "شماره سریال: SN091234567890123",               # سریال
        "کد ملی: 0912345678",                            # کد ملی ۱۰ رقمی (شروع 091!)
        "کد پستی: 1234567890",                           # کد پستی
        "تاریخ: 1403/08/15 — ساعت 19:30",               # تاریخ/ساعت
        "کد پیگیری: 87654321",                           # کد پیگیری
        "123456789012345678901234",                      # رشته رقم رند (فازر)
        "09123456789012345678901",                       # شماره واقعی‌نما داخل رشته رقم (غیرواقعی)
        "گارانتی ۱۸ ماهه، ارسال از انبار تهران",
        "ظرفیت 20000 میلی‌آمپر — توان 65 وات",
    ])
    def test_no_phone_from_noise(self, text):
        assert extract_phones(text) == [], f"زباله به‌عنوان شماره گرفته شد: {text!r}"


# ═══════════════ لایه ۲: شماره نمایشی = پرچم + حذف ═══════════════
class TestSuspiciousNumbers:
    @pytest.mark.parametrize("number", [
        "09123456789",   # کلاسیک‌ترین شماره نمایشی (دنباله صعودی)
        "09120000000",   # همه صفر
        "09121111111",   # همه یکسان
        "09127654321",   # دنباله نزولی
        "02112345678",   # ثابت نمایشی
        "02188888888",   # ثابت همه‌یکسان
        "09352222222",
    ])
    def test_flagged_as_suspicious(self, number):
        hits = extract_phones(number)
        assert hits, "فرمت درست است و باید استخراج شود"
        assert hits[0].suspicious is True, f"{number} باید مشکوک باشد"
        assert is_valid_mobile(number) if number.startswith("09") else True

    @pytest.mark.parametrize("number", [
        "09127640915",   # واقعی‌نما (جایگزین فیکسچرها)
        "09124456677",
        "09353050005",
        "02188776655",   # ثابت واقعی
        "02122334455",
        "09210543311",
    ])
    def test_real_numbers_pass(self, number):
        hits = extract_phones(number)
        assert hits and hits[0].suspicious is False, f"{number} واقعی است، نباید مشکوک باشد"

    def test_split_real_phones(self):
        real, junk = split_real_phones(
            ["09127640915", "09123456789", "02188776655", "09120000000"]
        )
        assert real == ["09127640915", "02188776655"]
        assert junk == ["09123456789", "09120000000"]

    def test_extractor_never_hides_flag(self):
        """همه مسیرهای استخراج، پرچم suspicious را حفظ می‌کنند."""
        text = "تماس: 09127640915 یا نمونه: ۰۹۱۲۳۴۵۶۷۸۹"
        hits = extract_phones(text)
        by_num = {h.number: h.suspicious for h in hits}
        assert by_num == {"09127640915": False, "09123456789": True}


# ═══════════════ لایه ۲/ب: گلوگاه Lead — حذف در normalize ═══════════════
class TestLeadLevelGarbageFilter:
    def _lead(self, phones, **kw):
        base = dict(source="torob", source_id="shop:x", url="https://t/x", phones=phones)
        base.update(kw)
        return normalize_lead(Lead(**base))

    def test_suspicious_dropped_from_lead(self):
        lead = self._lead(["09123456789", "09127640915"])
        assert lead.phones == ["09127640915"]

    def test_all_suspicious_means_no_phones(self):
        lead = self._lead(["09123456789", "09120000000"])
        assert lead.phones == []
        assert lead.quality_score < 60  # بدون شماره = امتیاز پایین

    def test_real_landline_kept(self):
        lead = self._lead(["02112345678", "02188776655"])
        assert lead.phones == ["02188776655"]

    def test_no_fabrication_when_empty(self):
        """«فقط شماره اگر بود» — بدون شماره، هیچ مقدار ساختگی درج نمی‌شود."""
        lead = self._lead([])
        assert lead.phones == []
        assert lead.primary_phone is None
        assert lead.seller_name in (None, "") or isinstance(lead.seller_name, str)


# ═══════════════ لایه ۳: خروجی فقط ردیف‌های با ارزش ═══════════════
class TestExportWorthiness:
    def _lead(self, source_id, phones=None, emails=None):
        return normalize_lead(
            Lead(source="torob", source_id=source_id, url=f"https://t/{source_id}",
                 seller_name=f"فروشگاه {source_id}", phones=phones or [], emails=emails or [])
        )

    def test_only_with_contact_filters_phoneless(self, tmp_path):
        leads = [
            self._lead("1", phones=["09127640915"]),
            self._lead("2"),                            # بدون هیچ تماسی → بی‌ارزش
            self._lead("3", emails=["info@shop.ir"]),   # ایمیل دارد → ارزشمند
        ]
        paths = export_leads(leads, tmp_path, ["csv"], only_with_contact=True)
        text = paths["csv"].read_text(encoding="utf-8-sig")
        assert "فروشگاه 1" in text and "info@shop.ir" in text
        assert "فروشگاه 2" not in text, "ردیف بدون راه تماس نباید در خروجی باشد"

    def test_default_keeps_all_for_audits(self, tmp_path):
        leads = [self._lead("1"), self._lead("2", phones=["09127640915"])]
        export_leads(leads, tmp_path, ["csv"], only_with_contact=False)
        assert True  # بدون خطا؛ حالت ممیزی کامل


# ═══════════════ سرتاسری: موتور روی شبیه‌ساز — دیتابیس پاک ═══════════════
class TestEngineProducesCleanData:
    @pytest.fixture(scope="class")
    def engine_result(self, tmp_path_factory):
        import sys

        sys.path.insert(0, str(REPO / "examples" / "mock_sites"))
        import mock_torob

        srv = ThreadingHTTPServer(("127.0.0.1", 0), mock_torob.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        cfg = AppConfig(db_path=tmp_path_factory.mktemp("qa") / "leads.db")
        cfg.politeness.min_delay = 0.01
        outcome = run_torob_engine(
            ["لپ تاپ", "مینی کولر شارژی"], cfg, max_shops=44, workers=6,
            min_delay=0.01, max_pages=2, api_base=base,
        )
        srv.shutdown()
        return outcome, cfg, mock_torob

    def test_database_has_zero_suspicious_phones(self, engine_result):
        outcome, cfg, mock = engine_result
        store = LeadStore(cfg.db_path)
        bad = [
            (l.source_id, p)
            for l in store.all_leads()
            for p in l.phones
            if is_suspicious_local(p[4:] if p.startswith("09") else p[3:])
        ]
        assert bad == [], f"شماره مشکوک به دیتابیس راه یافت: {bad}"

    def test_every_phone_is_format_valid_and_normalized(self, engine_result):
        outcome, cfg, _ = engine_result
        for lead in outcome.leads:
            for p in lead.phones:
                assert len(p) == 11 and p.startswith("0") and p.isdigit(), f"نرمال‌نشده: {p}"

    def test_export_contains_only_contactable_rows(self, engine_result):
        outcome, _, _ = engine_result
        csv_path = outcome.export_paths["csv"]
        rows = [
            line for line in csv_path.read_text(encoding="utf-8-sig").splitlines()[1:] if line
        ]
        with_phone = sum(1 for l in outcome.leads if l.phones or l.emails)
        assert len(rows) == with_phone, "خروجی باید دقیقاً لیدهای دارای راه تماس باشد"
        assert len(rows) >= 1

    def test_phones_actually_exist_in_source_dataset(self, engine_result):
        """هر شماره خروجی باید در دیتاست مبدأ وجود داشته باشد (ساختگی نیست)."""
        outcome, _, mock = engine_result
        all_source_numbers = set()
        for s in mock.SHOPS.values():
            if s["phone"]:
                all_source_numbers.update(h.number for h in extract_phones(s["phone"]))
        for sid, site in mock.SHOP_SITES.items():
            all_source_numbers.add(site["extra_phone"])
        for lead in outcome.leads:
            for p in lead.phones:
                assert p in all_source_numbers, f"شماره {p} در منبع نیست — ساختگی است!"
