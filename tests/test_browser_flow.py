"""تست یکپارچه جریان مرورگری ترب — کل رفتار کاربر روی سرور ماک.

نیازمندی: کرومیوم (نصب استاندارد playwright یا fallback در ~/.cache/abii-browsers).
اگر مرورگر موجود نباشد، تست skip می‌شود (نه fail).
"""
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from abii_bot.browser import run_torob_browser
from abii_bot.browser.setup import find_chromium
from abii_bot.config import AppConfig

REPO = Path(__file__).parent.parent
HAS_BROWSER = find_chromium() is not None or pytest.importorskip(
    "playwright", reason="playwright نصب نیست"
) is None

pytestmark = pytest.mark.skipif(not HAS_BROWSER, reason="کرومیوم در دسترس نیست")


@pytest.fixture(scope="module")
def mock_server():
    """سرور ترب ماک روی پورت تصادفی."""
    import sys

    sys.path.insert(0, str(REPO / "examples" / "mock_sites"))
    import mock_torob

    srv = ThreadingHTTPServer(("127.0.0.1", 0), mock_torob.Handler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture(scope="module")
def scan_result(mock_server, tmp_path_factory):
    cfg = AppConfig(db_path=tmp_path_factory.mktemp("db") / "t.db")
    cfg.politeness.min_delay = 0.05  # تست سریع
    result = run_torob_browser(
        query="لپ تاپ", cfg=cfg, max_products=5, headless=True,
        min_delay=0.05, base_url=mock_server,
    )
    return result


def test_flow_visits_all_products(scan_result):
    assert scan_result.pages_visited >= 9  # ۵ محصول + ۴ فروشگاه
    assert len(scan_result.leads) == 9


def test_shop_phones_extracted_from_show_phone_button(scan_result):
    """شماره‌ها پشت دکمه «نمایش شماره» بودند — فقط با کلیک واقعی ظاهر می‌شوند."""
    by_id = {l.source_id: l for l in scan_result.leads}
    assert "09123456789" in by_id["shop:shop-1"].phones      # ارقام فارسی ۰۹۱۲-۳۴۵-۶۷۸۹
    assert "09352223344" in by_id["shop:shop-2"].phones      # فرمت +98 935 ...
    assert "02188776655" in by_id["shop:shop-3"].phones      # ثابت ۰۲۱-...


def test_phone_in_product_description(scan_result):
    by_id = {l.source_id: l for l in scan_result.leads}
    assert "09124456677" in by_id["p:prk-3"].phones


def test_chat_only_shop_has_no_phone(scan_result):
    by_id = {l.source_id: l for l in scan_result.leads}
    assert by_id["shop:shop-4"].phones == []
    assert "p:prk-5" in by_id  # محصول بدون فروشنده → فقط لید محصول


def test_seller_names(scan_result):
    by_id = {l.source_id: l for l in scan_result.leads}
    assert by_id["shop:shop-1"].seller_name == "فروشگاه رایان تک"


def test_all_leads_stored_and_normalized(scan_result):
    for lead in scan_result.leads:
        for p in lead.phones:
            assert p.startswith("0") and p.isdigit()
        assert lead.status in {"new", "updated", "duplicate"}
