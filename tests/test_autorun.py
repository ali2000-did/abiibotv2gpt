"""تست‌های اتوران — حلقه خودکار، تنظیمات، فایل وضعیت، افزایشی‌بودن دورها."""
import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from abii_bot.autorun import (
    AutorunSettings,
    default_settings_path,
    parse_interval,
    run_forever,
    status_path,
)
from abii_bot.config import AppConfig
from abii_bot.storage import LeadStore

REPO = Path(__file__).parent.parent


# ---------------- parse_interval ----------------
@pytest.mark.parametrize("text,expected", [
    ("24h", 86400), ("6h", 21600), ("30m", 1800), ("45s", 45),
    ("86400", 86400), ("1d", 86400), (12, 12), ("2.5h", 9000),
])
def test_parse_interval(text, expected):
    assert parse_interval(text) == expected


# ---------------- settings round-trip ----------------
def test_settings_save_load(tmp_path):
    p = tmp_path / "autorun.yaml"
    s = AutorunSettings(
        queries=["مینی کولر شارژی", "کولر حمل‌پذیر"], every_seconds=3600, max_shops=55
    )
    saved = s.save(p)
    loaded = AutorunSettings.load(saved)
    assert loaded.queries == ["مینی کولر شارژی", "کولر حمل‌پذیر"]
    assert loaded.every_seconds == 3600 and loaded.max_shops == 55
    assert loaded.api_base is None  # تنظیم تستی ذخیره نمی‌شود


def test_settings_load_rejects_empty(tmp_path):
    p = tmp_path / "autorun.yaml"
    p.write_text("queries: []\n", encoding="utf-8")
    with pytest.raises(ValueError):
        AutorunSettings.load(p)


def test_default_settings_shipped_with_repo():
    """فایل پیش‌فرض ریپو باید محصول کارفرما را داشته باشد (مینی کولر شارژی)."""
    p = default_settings_path()
    assert p.exists(), "configs/autorun.yaml باید در ریپو باشد"
    s = AutorunSettings.load(p)
    assert "مینی کولر شارژی" in s.queries
    assert s.every_seconds == 86400  # روزانه


# ---------------- حلقه اجرا (روی ماک) ----------------
@pytest.fixture(scope="module")
def mock_api():
    import sys

    sys.path.insert(0, str(REPO / "examples" / "mock_sites"))
    import mock_torob

    srv = ThreadingHTTPServer(("127.0.0.1", 0), mock_torob.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_run_forever_once_writes_status(mock_api, tmp_path):
    cfg = AppConfig(db_path=tmp_path / "data" / "leads.db")
    cfg.politeness.min_delay = 0.01
    settings = AutorunSettings(
        queries=["مینی کولر شارژی"], every_seconds=5, max_shops=20,
        workers=4, min_delay=0.01, api_base=mock_api,
    )
    cycles = run_forever(settings, cfg, once=True)
    assert cycles == 1

    st = status_path(cfg)
    assert st.exists()
    data = json.loads(st.read_text(encoding="utf-8"))
    assert data["cycle"] == 1
    assert data["error"] is None
    assert data["leads_new"] >= 1
    assert data["next_run_at"] is None  # once → دور بعدی ندارد


def test_second_cycle_is_incremental(mock_api, tmp_path):
    """دور دوم: فروشگاه‌های دیده‌شده دوباره fetch نمی‌شوند."""
    cfg = AppConfig(db_path=tmp_path / "data" / "leads.db")
    cfg.politeness.min_delay = 0.01
    settings = AutorunSettings(
        queries=["مینی کولر شارژی"], every_seconds=5, max_shops=20,
        workers=4, min_delay=0.01, api_base=mock_api,
    )
    run_forever(settings, cfg, once=True)
    cycles = run_forever(settings, cfg, once=True)
    st = json.loads(status_path(cfg).read_text(encoding="utf-8"))
    assert cycles == 2 and st["cycle"] == 2
    assert st["shops_fetched"] == 0  # همه تازه‌اند → صفر برداشت
    assert st["leads_new"] == 0      # و صفر لید جدید


def test_cycle_error_does_not_crash(mock_api, tmp_path, monkeypatch):
    """خرابی یک دور (مثلاً خطای داخلی) → ثبت خطا در وضعیت، بدون کرش."""
    import abii_bot.autorun as ar

    def boom(queries, cfg, **kw):
        raise RuntimeError("شبکه قطع است")

    monkeypatch.setattr(ar, "run_torob_engine", boom)

    cfg = AppConfig(db_path=tmp_path / "data" / "leads.db")
    settings = AutorunSettings(queries=["مینی کولر شارژی"], api_base=mock_api)
    cycles = run_forever(settings, cfg, once=True)
    assert cycles == 1  # خطا خورد ولی چرخید و برگشت
    st = json.loads(status_path(cfg).read_text(encoding="utf-8"))
    assert st["error"] and "شبکه قطع است" in st["error"]


def test_unreachable_host_degrades_gracefully(tmp_path):
    """قطعی واقعی شبکه → موتور خروجی خالی می‌دهد (بدون کرش) و وضعیت ثبت می‌شود."""
    cfg = AppConfig(db_path=tmp_path / "data" / "leads.db")
    cfg.politeness.max_retries = 1
    cfg.politeness.timeout = 1.0
    settings = AutorunSettings(
        queries=["مینی کولر شارژی"], workers=2, min_delay=0.01,
        api_base="http://127.0.0.1:1",  # بندِ بسته
    )
    cycles = run_forever(settings, cfg, once=True)
    assert cycles == 1
    st = json.loads(status_path(cfg).read_text(encoding="utf-8"))
    assert st["shops_fetched"] == 0
