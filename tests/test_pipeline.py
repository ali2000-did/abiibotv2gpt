"""تست آداپتور وب عمومی + پاکسازی + کیفیت + خروجی + دیتابیس."""
import json
from pathlib import Path

from abii_bot.config import AppConfig
from abii_bot.local import LocalFixtureFetcher
from abii_bot.models import Lead
from abii_bot.pipeline.cleaner import Deduper, normalize_lead
from abii_bot.pipeline.quality import dataset_report
from abii_bot.platforms import ScanSpec, build_adapter
from abii_bot.runner import DEMO_FIXTURES
from abii_bot.storage import LeadStore, export_leads

FIXTURES = Path(__file__).parent.parent / "examples" / "fixtures"


# ---------- web adapter ----------
def test_web_adapter_extracts_contact_info():
    fetcher = LocalFixtureFetcher(FIXTURES, DEMO_FIXTURES)
    adapter = build_adapter("web", fetcher, AppConfig())
    refs = list(adapter.discover(ScanSpec("web", urls=["https://example-seller.ir/contact"])))
    lead = adapter.parse_detail(adapter.fetch_detail(refs[0]), refs[0])

    assert lead.title == "فروشگاه ایران‌کالا"
    assert "09123456789" in lead.phones        # از ‎+۹۸۹۱۲... با ارقام فارسی
    assert "02188776655" in lead.phones        # ثابت با ارقام فارسی
    assert "sales@iran-kala.example.ir" in lead.emails
    assert lead.phones[0].startswith("09")     # موبایل اول


# ---------- cleaner / dedupe ----------
def _lead(**kw) -> Lead:
    base = dict(source="x", source_id="1", url="https://x/1", title="  تیتل   ", phones=[])
    base.update(kw)
    return Lead(**base)


def test_normalize_lead_scores_and_orders():
    lead = normalize_lead(_lead(phones=["02188776655", "09121112222"], city="تهران "))
    assert lead.phones == ["09121112222", "02188776655"]  # موبایل اول
    assert lead.title == "تیتل"
    assert lead.quality_score >= 55


def test_deduper_statuses(tmp_path):
    store = LeadStore(tmp_path / "t.db")
    dd = Deduper(store)

    l1 = normalize_lead(_lead(phones=["09121112222"]))
    assert dd.classify(l1) == "new"
    store.upsert(l1)

    l2 = normalize_lead(_lead(phones=["09121112222"]))
    assert dd.classify(l2) == "duplicate"

    l3 = normalize_lead(_lead(phones=["09121112222", "02188776655"]))
    assert dd.classify(l3) == "updated"
    store.upsert(l3)

    got = store.get("x", "1")
    assert set(got.phones) == {"09121112222", "02188776655"}


# ---------- export ----------
def test_export_csv_xlsx(tmp_path):
    leads = [normalize_lead(_lead(source_id=str(i), phones=[f"0912111222{i}"])) for i in range(3)]
    paths = export_leads(leads, tmp_path, ["csv", "xlsx"])
    csv_text = paths["csv"].read_text(encoding="utf-8-sig")
    assert "شماره تماس" in csv_text and "09121112221" in csv_text
    assert paths["xlsx"].exists()


def test_dataset_report():
    leads = [
        _lead(source_id="1", phones=["09121112222"]),
        _lead(source_id="2", phones=[]),
    ]
    rep = dataset_report(leads)
    assert rep["total"] == 2
    assert rep["with_phone_pct"] == 50.0
