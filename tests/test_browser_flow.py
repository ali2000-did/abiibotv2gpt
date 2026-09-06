"""تست یکپارچه جریان مرورگری ترب — کل رفتار کاربر روی سرور ماک.

تست‌ها data-driven هستند: انتظارها مستقیماً از دیتاست ماک محاسبه می‌شوند تا
با بزرگ/کوچک شدن دیتاست همیشه معتبر بمانند.

نیازمندی: کرومیوم (نصب استاندارد playwright یا fallback در ~/.cache/abii-browsers).
"""
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from abii_bot.browser import run_torob_browser
from abii_bot.browser.setup import find_chromium
from abii_bot.config import AppConfig
from abii_bot.extraction import extract_phone_numbers

REPO = Path(__file__).parent.parent
HAS_BROWSER = find_chromium() is not None or pytest.importorskip(
    "playwright", reason="playwright نصب نیست"
) is None

pytestmark = pytest.mark.skipif(not HAS_BROWSER, reason="کرومیوم در دسترس نیست")

MAX_PRODUCTS = 5
QUERY = "لپ تاپ"


@pytest.fixture(scope="module")
def mock_module():
    sys.path.insert(0, str(REPO / "examples" / "mock_sites"))
    import mock_torob

    return mock_torob


@pytest.fixture(scope="module")
def mock_server(mock_module):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), mock_module.Handler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture(scope="module")
def scan_result(mock_server, mock_module, tmp_path_factory):
    cfg = AppConfig(db_path=tmp_path_factory.mktemp("db") / "t.db")
    cfg.politeness.min_delay = 0.05  # تست سریع
    result = run_torob_browser(
        query=QUERY, cfg=cfg, max_products=MAX_PRODUCTS, headless=True,
        min_delay=0.05, base_url=mock_server,
    )
    return result


def _expected_visits(mock_module):
    """محصولات mabarbazi اولین نتایج جستجو + فروشنده اصلی هر کدام."""
    visited = mock_module.match_prks(QUERY)[:MAX_PRODUCTS]
    shops = [
        mock_module.PRODUCTS[prk]["shops"][0]
        for prk in visited
        if mock_module.PRODUCTS[prk]["shops"]
    ]
    return visited, shops


def test_flow_visits_all_products_and_shops(scan_result, mock_module):
    visited, shops = _expected_visits(mock_module)
    assert len(visited) == MAX_PRODUCTS
    assert scan_result.pages_visited >= len(visited) + len(shops)
    assert scan_result.leads and len(scan_result.leads) == len(visited) + len(shops)


def test_shop_phones_match_dataset(scan_result, mock_module):
    """شماره هر فروشگاه = نرمال‌شدهی همان شماره در دیتاست (حتی پشت دکمه «نمایش شماره»)."""
    _, shops = _expected_visits(mock_module)
    by_id = {l.source_id: l for l in scan_result.leads}
    for sid in shops:
        assert f"shop:{sid}" in by_id, f"فروشگاه {sid} کلیک نشده است"
        phone = mock_module.SHOPS[sid]["phone"]
        expected = extract_phone_numbers(phone) if phone else []
        assert by_id[f"shop:{sid}"].phones == expected, f"شماره {sid} درست نیست"


def test_chat_only_shop_has_no_phone(scan_result, mock_module):
    """هر فروشگاه بدون شماره در دیتاست، بدون شماره در لید هم هست."""
    _, shops = _expected_visits(mock_module)
    by_id = {l.source_id: l for l in scan_result.leads}
    phoneless = [sid for sid in shops if not mock_module.SHOPS[sid]["phone"]]
    for sid in phoneless:
        assert by_id[f"shop:{sid}"].phones == []


def test_phone_in_product_description(scan_result):
    by_id = {l.source_id: l for l in scan_result.leads}
    assert "09124456677" in by_id["p:prk-3"].phones


def test_seller_name_from_shop_page(scan_result, mock_module):
    by_id = {l.source_id: l for l in scan_result.leads}
    lead = by_id["shop:shop-1"]
    assert lead.seller_name == mock_module.SHOPS["shop-1"]["name"]


def test_all_leads_stored_and_normalized(scan_result):
    for lead in scan_result.leads:
        for p in lead.phones:
            assert p.startswith("0") and p.isdigit()
        assert lead.status in {"new", "updated", "duplicate"}
