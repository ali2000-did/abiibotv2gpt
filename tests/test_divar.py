"""تست آداپتور دیوار روی فیکسچر — بدون شبکه."""
from pathlib import Path

from abii_bot.config import AppConfig
from abii_bot.local import LocalFixtureFetcher
from abii_bot.platforms import ScanSpec, build_adapter
from abii_bot.runner import DEMO_FIXTURES

FIXTURES = Path(__file__).parent.parent / "examples" / "fixtures"


def make_adapter():
    cfg = AppConfig()
    fetcher = LocalFixtureFetcher(FIXTURES, DEMO_FIXTURES)
    return build_adapter("divar", fetcher, cfg)


def test_discover_tokens():
    adapter = make_adapter()
    refs = list(adapter.discover(ScanSpec("divar", city="tehran", category="buy-apartment")))
    assert [r.source_id for r in refs] == ["wZJmF8xu", "gQ7kL2pA", "mNb3vRt9"]
    assert refs[0].url.startswith("https://divar.ir/v/")


def test_parse_detail_extracts_phone_and_fields():
    adapter = make_adapter()
    ref = list(adapter.discover(ScanSpec("divar", city="tehran")))[0]
    payload = adapter.fetch_detail(ref)
    lead = adapter.parse_detail(payload, ref)

    assert lead.source == "divar"
    assert lead.title == "آپارتمان ۸۵ متری، خیابان ولیعصر"
    assert "09127640915" in lead.phones
    assert lead.phones[0].startswith("09")  # موبایل اول
    assert lead.city == "تهران"
    assert "املاک" in (lead.category or "")
    assert lead.price == "8,500,000,000"
