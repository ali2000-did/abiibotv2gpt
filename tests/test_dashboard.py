"""تست داشبورد زنده — احراز توکن، API وضعیت/لاگ، استنتاج فعالیت."""
import json
import os
import threading
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

from abii_bot.config import AppConfig
from abii_bot.dashboard import (
    derive_activity,
    get_token,
    make_handler,
    snapshot,
    tail_logs,
)
from abii_bot.models import Lead
from abii_bot.pipeline.cleaner import normalize_lead
from abii_bot.storage import LeadStore


def _cfg(tmp_path: Path) -> AppConfig:
    return AppConfig(db_path=tmp_path / "data" / "leads.db", export_dir=tmp_path / "exports")


def _serve(cfg: AppConfig):
    tok = get_token(cfg)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cfg, tok))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}", tok


def _get(url: str):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read().decode()


# ═══════════════ احراز توکن ═══════════════
def test_token_stable_and_required(tmp_path):
    cfg = _cfg(tmp_path)
    t1, t2 = get_token(cfg), get_token(cfg)
    assert t1 == t2 and len(t1) == 8  # یک بار ساخته می‌شود و پایدار است

    srv, base, tok = _serve(cfg)
    try:
        # بدون توکن → 401
        try:
            _get(base + "/api/status")
            raised = False
        except urllib.error.HTTPError as e:
            raised = e.code == 401
        assert raised, "بدون توکن باید 401 بدهد"

        # با توکن → 200
        code, body = _get(base + f"/api/status?t={tok}")
        assert code == 200
        assert "activity" in json.loads(body)
    finally:
        srv.shutdown()


# ═══════════════ API وضعیت ═══════════════
def test_status_endpoint_reflects_db_and_status_file(tmp_path):
    cfg = _cfg(tmp_path)
    # دو لید: یکی با شماره، یکی بدون
    store = LeadStore(cfg.db_path)
    for i, phones in ((1, ["09127640915"]), (2, [])):
        lead = normalize_lead(Lead(
            source="torob", source_id=f"s{i}", url=f"https://t/{i}",
            seller_name=f"فروشگاه {i}", phones=phones,
        ))
        store.upsert(lead)
    # فایل وضعیت: خواب تا دور بعد (۱ ساعت دیگر)
    cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
    (cfg.db_path.parent / "autorun_status.json").write_text(json.dumps({
        "cycle": 3,
        "next_run_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "error": None,
    }), encoding="utf-8")
    # فایل خروجی
    cfg.export_dir.mkdir(parents=True, exist_ok=True)
    (cfg.export_dir / "leads_torob_1.csv").write_text("x", encoding="utf-8")

    srv, base, tok = _serve(cfg)
    try:
        _, body = _get(base + f"/api/status?t={tok}")
        st = json.loads(body)
        assert st["db"]["leads"] == 2
        assert st["db"]["with_contact"] == 1
        assert st["db"]["phones"] == 1
        assert st["last_cycle"]["cycle"] == 3
        assert st["latest_export"]["name"] == "leads_torob_1.csv"
        # سرویس در محیط تست اجرا نمی‌شود → off؛ ولی فایل وضعیت خوانده شد
        assert st["activity"]["cycle"] == 3
    finally:
        srv.shutdown()


def test_page_served(tmp_path):
    cfg = _cfg(tmp_path)
    srv, base, tok = _serve(cfg)
    try:
        code, body = _get(base + "/")  # صفحه عمومی است؛ توکن از URL/localStorage خوانده می‌شود
        assert code == 200 and "داشبورد AbiiBot" in body
        assert "dir=\"rtl\"" in body
        assert "btn-start" in body and "btn-xlsx" in body  # دکمه‌های کنترل و دانلود
    finally:
        srv.shutdown()


def test_log_endpoint_tails_file(tmp_path, monkeypatch):
    log = tmp_path / "autorun.log"
    log.write_text("خط ۱\nخط ۲ WARNING تست\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    lines = tail_logs(10)
    assert any("WARNING" in ln for ln in lines)


# ═══════════════ استنتاج فعالیت ═══════════════
def test_activity_matrix():
    future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    assert derive_activity({"running": False, "mode": None}, None)["code"] == "off"
    assert derive_activity({"running": True}, {"next_run_at": future})["code"] == "sleep"
    assert 0 < derive_activity({"running": True}, {"next_run_at": future})["next_in_sec"] <= 310
    assert derive_activity({"running": True}, None)["code"] == "scan"          # وسط دور اول
    assert derive_activity({"running": True}, {"error": "X"})["code"] == "error"
    assert derive_activity({"running": True}, {"next_run_at": past})["code"] == "scan"  # وقتش رسیده


# ═══════════════ دانلود اکسل/CSV ═══════════════
def _seed(tmp_path):
    cfg = _cfg(tmp_path)
    store = LeadStore(cfg.db_path)
    for i, phones in ((1, ["09127640915"]), (2, [])):  # یکی با شماره، یکی بدون
        store.upsert(normalize_lead(Lead(
            source="torob", source_id=f"s{i}", url=f"https://t/{i}",
            seller_name=f"فروشگاه {i}", phones=phones,
        )))
    return cfg


def test_export_xlsx_endpoint(tmp_path):
    import io

    import openpyxl
    from abii_bot.dashboard import export_bytes

    cfg = _seed(tmp_path)
    data, mime, name = export_bytes(cfg, "xlsx")
    assert data[:2] == b"PK" and name.endswith(".xlsx") and "sheet" in mime
    wb = openpyxl.load_workbook(io.BytesIO(data))
    rows = list(wb.active.iter_rows(values_only=True))
    assert len(rows) == 2  # سرستون + فقط ۱ ردیفِ دارای تماس
    assert rows[0][0] == "پلتفرم"
    phones_col = [c for c in rows[1] if c and "09127640915" in str(c)]
    assert phones_col, "شماره باید در اکسل باشد"

    # از سرور HTTP هم همان بایت‌ها می‌آید
    srv, base, tok = _serve(cfg)
    try:
        req = urllib.request.Request(base + f"/api/export?fmt=xlsx&t={tok}")
        with urllib.request.urlopen(req, timeout=10) as r:
            assert r.status == 200
            assert r.headers["Content-Type"].startswith("application/vnd")
            assert "attachment" in r.headers["Content-Disposition"]
            assert r.read()[:2] == b"PK"
    finally:
        srv.shutdown()


def test_export_csv_only_with_contact(tmp_path):
    from abii_bot.dashboard import export_bytes

    cfg = _seed(tmp_path)
    data, mime, name = export_bytes(cfg, "csv")
    text = data.decode("utf-8-sig")
    assert "09127640915" in text
    assert "فروشگاه 2" not in text  # بدون شماره → بی‌ارزش → دانلود نمی‌شود


def test_export_bad_format_rejected(tmp_path):
    cfg = _seed(tmp_path)
    srv, base, tok = _serve(cfg)
    try:
        req = urllib.request.Request(base + f"/api/export?fmt=exe&t={tok}")
        try:
            urllib.request.urlopen(req, timeout=5)
            raise AssertionError("باید 400 بدهد")
        except urllib.error.HTTPError as e:
            assert e.code == 400
    finally:
        srv.shutdown()


# ═══════════════ کنترل: شروع/توقف ═══════════════
def _post(url, body, headers=None):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status, json.loads(r.read())


def test_action_requires_token(tmp_path):
    cfg = _seed(tmp_path)
    srv, base, tok = _serve(cfg)
    try:
        req = urllib.request.Request(
            base + "/api/action", data=b'{"action":"stop"}', method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(req, timeout=5)
            raise AssertionError("باید 401 بدهد")
        except urllib.error.HTTPError as e:
            assert e.code == 401
    finally:
        srv.shutdown()


def test_action_validates_payload(tmp_path):
    cfg = _seed(tmp_path)
    srv, base, tok = _serve(cfg)
    try:
        try:
            _post(base + "/api/action?t=" + tok, {"action": "boom"})
            raise AssertionError("باید 400 بدهد")
        except urllib.error.HTTPError as e:
            assert e.code == 400
    finally:
        srv.shutdown()


def test_stop_when_already_off_is_graceful(tmp_path, monkeypatch):
    """توقفِ رباتِ خاموش → پیام موفقیت، نه خطا (idempotent)."""
    import abii_bot.dashboard as dash

    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir(exist_ok=True)
    ok, msg = dash.stop_bot()
    assert ok and "از قبل متوقف" in msg


def test_start_stop_nohup_cycle(tmp_path, monkeypatch):
    """چرخه کامل شروع→توقف در حالت پس‌زمینه — با فرایند واقعی."""
    import subprocess as sp

    import abii_bot.dashboard as dash

    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()

    def fake_spawn():
        proc = sp.Popen(["sleep", "300"], start_new_session=True)
        dash.PID_FILE.write_text(str(proc.pid), encoding="utf-8")
        return proc.pid

    monkeypatch.setattr(dash, "_spawn_autorun", fake_spawn)

    ok, msg = dash.start_bot()
    assert ok, msg
    pid = int(dash.PID_FILE.read_text().strip())
    assert dash._pid_alive(pid), "باید زنده باشد"

    ok, msg = dash.stop_bot()
    assert ok, msg
    if dash._pid_alive(pid):  # اطمینان: فرایند تست را تمیز بکشیم
        os.kill(pid, 9)
        raise AssertionError("فرایند بعد از stop_bot باید مرده باشد")
