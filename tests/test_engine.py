"""تست‌های موتور ناهمگام ترب — روی سرور ماک API v4."""
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from abii_bot.config import AppConfig
from abii_bot.engine import parse_shop_payload, run_torob_engine, walk_shop_ids
from abii_bot.storage import LeadStore

REPO = Path(__file__).parent.parent


@pytest.fixture(scope="module")
def mock_api():
    import sys

    sys.path.insert(0, str(REPO / "examples" / "mock_sites"))
    import mock_torob

    srv = ThreadingHTTPServer(("127.0.0.1", 0), mock_torob.Handler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture(scope="module")
def first_scan(mock_api, tmp_path_factory):
    cfg = AppConfig(db_path=tmp_path_factory.mktemp("db1") / "t.db")
    cfg.politeness.min_delay = 0.01
    outcome = run_torob_engine(
        ["لپ تاپ", "گوشی موبایل"], cfg, max_shops=40, workers=6,
        min_delay=0.01, max_pages=2, api_base=mock_api,
    )
    return outcome, cfg


# ----------------单元 unit: پارسر مقاوم ----------------
def test_walk_shop_ids_flat_and_nested():
    flat = {"shop_id": "s1", "shop_name": "فروشگاه الف", "other": {"shop_id": "s2", "name": "ب"}}
    assert walk_shop_ids(flat) == {"s1": "فروشگاه الف", "s2": "ب"}

    nested = {"result": {"offer_list": [{"shop": {"id": "s3", "name": "پ"}}, {"seller_id": "s4"}]}}
    assert set(walk_shop_ids(nested)) == {"s3", "s4"}


def test_parse_shop_payload_variants():
    # شکل ۱: کلیدهای تخت
    l1 = parse_shop_payload({"shop_name": "الف", "city": "تهران", "phone": "09121112222"}, "1", "http://x/1")
    assert l1.seller_name == "الف" and l1.phones == ["09121112222"] and l1.city == "تهران"

    # شکل ۲: تودرتو + شماره فارسی با فاصله
    l2 = parse_shop_payload(
        {"data": {"name": "ب", "city_name": "مشهد", "contact": {"phone": "۰۹۳۵ ۳۳۳ ۱۲۳۴"}}},
        "2", "http://x/2",
    )
    assert l2.seller_name == "ب" and l2.phones == ["09353331234"]

    # شکل ۳: بدون شماره → لید بدون شماره با کیفیت پایین‌تر
    l3 = parse_shop_payload({"name": "پ", "city": "شیراز"}, "3", "http://x/3")
    assert l3.phones == [] and l3.quality_score < 60


# ---------------- integration: موتور روی ماک ----------------
def test_engine_finds_shops_with_normalized_phones(first_scan):
    outcome, _ = first_scan
    m = outcome.metrics
    assert m.shops_found >= 30, "باید دهها فروشگاه یکتا پیدا شود"
    assert m.shops_fetched == min(40, m.shops_found)
    assert m.phones_found >= 15, "بیشتر فروشگاه‌ها شماره دارند"
    for lead in outcome.leads:
        assert lead.source_id.startswith("shop:")
        for p in lead.phones:
            assert len(p) == 11 and p.startswith("0"), f"نرمال‌نشده: {p}"
        assert lead.seller_name  # نام فروشگاه همیشه هست


def test_engine_dedupes_shops_across_products(first_scan):
    """فروشگاه‌ها بین محصولات مشترک‌اند — هیچ فروشگاهی دو بار fetch نشده است."""
    outcome, cfg = first_scan
    ids = [l.source_id for l in outcome.leads]
    assert len(ids) == len(set(ids))
    assert outcome.metrics.shops_fetched == len(ids)


def test_incremental_second_run_skips_fresh(first_scan, mock_api, tmp_path):
    outcome, cfg = first_scan
    # اجرای دوم با همان کوئری‌ها روی همان دیتابیس: همه فروشگاه‌ها تازه‌اند → هیچ fetch نباید انجام شود
    out2 = run_torob_engine(
        ["لپ تاپ", "گوشی موبایل"], cfg, max_shops=40, workers=4, min_delay=0.01,
        max_pages=2, api_base=mock_api,
    )
    assert out2.metrics.shops_fetched == 0
    assert out2.metrics.shops_skipped_fresh >= outcome.metrics.shops_fetched * 0.7
    assert out2.leads == []


def test_engine_throughput(first_scan):
    """اسموک پرفورمنس: موتور باید روی ماک حداقل ~۲ فروشگاه/ثانیه بدهد (workers=6)."""
    outcome, _ = first_scan
    rate = outcome.metrics.shops_fetched / max(outcome.metrics.duration_sec, 0.001)
    assert rate > 1.0, f"throughput خیلی کم: {rate:.1f}/s"


def test_export_files_created(first_scan):
    outcome, _ = first_scan
    assert set(outcome.export_paths) >= {"csv", "xlsx"}
    csv_text = outcome.export_paths["csv"].read_text(encoding="utf-8-sig")
    assert "فروشگاه رایان تک" in csv_text and "09123456789" in csv_text
