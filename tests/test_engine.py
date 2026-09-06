"""تست‌های موتور ناهمگام ترب — روی سرور ماک API v4."""
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from abii_bot.config import AppConfig
from abii_bot.engine import TorobShopScanner, parse_shop_payload, run_torob_engine, walk_shop_ids
from abii_bot.extraction import extract_phone_numbers
from abii_bot.storage import LeadStore

REPO = Path(__file__).parent.parent

_DB_SEQ = 0


def mock_tmp_db(tag: str) -> Path:
    global _DB_SEQ
    _DB_SEQ += 1
    return Path(f"/tmp/abii_test_{tag}_{_DB_SEQ}.db")


@pytest.fixture(scope="module")
def mock_module():
    import sys

    sys.path.insert(0, str(REPO / "examples" / "mock_sites"))
    import mock_torob

    return mock_torob


@pytest.fixture(scope="module")
def mock_api(mock_module):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), mock_module.Handler)
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


# ---------------- robustness: کلاینت و fallback ----------------
def test_get_json_404_returns_none(mock_api, mock_module):
    """404 نباید retry بخورد و نباید استثنا بدهد — فقط None."""
    import asyncio

    from abii_bot.engine.http_async import AsyncPoliteClient

    cfg = AppConfig()
    cfg.politeness.min_delay = 0.01

    async def go():
        client = AsyncPoliteClient(cfg, min_delay=0.01)
        try:
            broken = mock_module.API_BROKEN_SHOPS[0]
            data = await client.get_json(f"{mock_api}/v4/shop/detail/?shop_id={broken}")
            assert data is None
            assert client.metrics.requests == 1, "404 نباید retry بخورد"
        finally:
            await client.aclose()

    asyncio.run(go())


def test_get_json_non_json_raises_connection_error(mock_api):
    """پاسخ 200 اما HTML → ConnectionError کنترل‌شده (نه JSONDecodeError خام)."""
    import asyncio

    from abii_bot.engine.http_async import AsyncPoliteClient

    cfg = AppConfig()
    cfg.politeness.max_retries = 1
    cfg.politeness.min_delay = 0.01

    async def go():
        client = AsyncPoliteClient(cfg, min_delay=0.01)
        try:
            with pytest.raises(ConnectionError):
                await client.get_json(f"{mock_api}/shop/shop-1/")  # HTML است نه JSON
        finally:
            await client.aclose()

    asyncio.run(go())


def test_web_fallback_recovers_phone_of_broken_api_shop(mock_api, mock_module):
    """فروشگاهی که APIاش 404 است → شماره از صفحه وب (HTML) بازیابی می‌شود."""
    import asyncio

    from abii_bot.engine.http_async import AsyncPoliteClient

    cfg = AppConfig(db_path=mock_tmp_db("fallback"))
    cfg.politeness.min_delay = 0.01
    store = LeadStore(cfg.db_path)
    scanner = TorobShopScanner(cfg, ["لپ تاپ"], store, api_base=mock_api)

    broken = mock_module.API_BROKEN_SHOPS[0]
    expected = extract_phone_numbers(mock_module.SHOPS[broken]["phone"])

    async def go():
        client = AsyncPoliteClient(cfg, min_delay=0.01)
        try:
            lead = await scanner._web_fallback(client, broken)
            assert lead is not None
            assert lead.phones == expected, "شماره از HTML بازیابی نشد"
            assert lead.seller_name == mock_module.SHOPS[broken]["name"]
        finally:
            await client.aclose()

    asyncio.run(go())


def test_web_fallback_cannot_see_button_only_phones(mock_api, mock_module):
    """شماره‌های JS-injected (پشت دکمه) در HTML خام نیستند → fallback آن‌ها را نمی‌گیرد."""
    import asyncio

    from abii_bot.engine.http_async import AsyncPoliteClient

    cfg = AppConfig(db_path=mock_tmp_db("behind"))
    cfg.politeness.min_delay = 0.01
    store = LeadStore(cfg.db_path)
    scanner = TorobShopScanner(cfg, ["لپ تاپ"], store, api_base=mock_api)

    behind = sorted(mock_module.PHONE_BEHIND_BUTTON)[0]

    async def go():
        client = AsyncPoliteClient(cfg, min_delay=0.01)
        try:
            lead = await scanner._web_fallback(client, behind)
            html_phone = extract_phone_numbers(mock_module.SHOPS[behind]["phone"])
            assert lead is not None and html_phone, "پیش‌شرط تست معتبر نیست"
            assert lead.phones == [], "نباید شماره JS-injected از HTML خام دربیاید"
        finally:
            await client.aclose()

    asyncio.run(go())
