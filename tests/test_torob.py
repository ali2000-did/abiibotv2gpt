"""تست آداپتور ترب روی فیکسچر — بدون شبکه."""
from pathlib import Path

from abii_bot.config import AppConfig
from abii_bot.local import LocalFixtureFetcher
from abii_bot.platforms import ScanSpec, build_adapter
from abii_bot.runner import DEMO_FIXTURES

FIXTURES = Path(__file__).parent.parent / "examples" / "fixtures"


def make_adapter():
    cfg = AppConfig()
    fetcher = LocalFixtureFetcher(FIXTURES, DEMO_FIXTURES)
    return build_adapter("torob", fetcher, cfg)


def test_discover_products():
    adapter = make_adapter()
    refs = list(adapter.discover(ScanSpec("torob", query="لپتاپ")))
    assert [r.source_id for r in refs] == ["prk-laptop-asus-001", "prk-laptop-lenovo-002"]


def test_parse_detail_seller_info():
    adapter = make_adapter()
    ref = list(adapter.discover(ScanSpec("torob", query="لپتاپ")))[0]
    payload = adapter.fetch_detail(ref)
    lead = adapter.parse_detail(payload, ref)

    assert lead.title == "لپ تاپ ۱۵ اینچی ایسوس سری VivoBook"
    assert "02188997766" in lead.phones
    assert lead.seller_name == "فروشگاه رایان تک"
    assert lead.city == "تهران"
