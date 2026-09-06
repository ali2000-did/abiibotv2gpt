"""داشبورد زنده AbiiBot — «ربات فعاله؟ الان داره چیکار می‌کنه؟»

یک صفحه وب سبک (فقط stdlib، بدون اینترنت/CDN) که نشان می‌دهد:
  • وضعیت ربات: فعال/متوقف + روش اجرا (systemd/cron/پس‌زمینه)
  • فعالیت لحظه‌ای: در حال اسکن دور چند است یا خواب تا دور بعد (شمارش معکوس)
  • آمار: لیدها، شماره‌ها، نتیجه دور آخر، فایل اکسل آخر
  • لاگ زنده: آخرین خطوط با رنگ

اجرا:  abii dashboard   →  http://SERVER-IP:8501/?t=TOKEN
توکن یک‌بار ساخته می‌شود (data/.dashboard_token) چون شماره‌ها داده حساس‌اند.
"""
from __future__ import annotations

import json
import logging
import secrets
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .config import AppConfig
from .models import Lead
from .storage import LeadStore

logger = logging.getLogger(__name__)

SERVICE_NAME = "abii-autorun"
DASH_SERVICE = "abii-dashboard"
DEFAULT_PORT = 8501


# ═══════════════════════════ داده‌ها ═══════════════════════════
def token_path(cfg: AppConfig) -> Path:
    return cfg.db_path.parent / ".dashboard_token"


def get_token(cfg: AppConfig) -> str:
    """توکن دسترسی — یک بار ساخته و در data/ نگه‌داری می‌شود."""
    p = token_path(cfg)
    try:
        tok = p.read_text(encoding="utf-8").strip()
        if tok:
            return tok
    except Exception:  # noqa: BLE001
        pass
    tok = secrets.token_hex(4)  # 8 کاراکتر خوانا
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(tok, encoding="utf-8")
    return tok


def service_state() -> dict:
    """ربات اتوران از کجا/method دارد اجرا می‌شود؟"""
    for mode, checker in (
        ("system", lambda: subprocess.run(
            ["systemctl", "is-active", SERVICE_NAME], capture_output=True, text=True
        ).stdout.strip() == "active"),
        ("user", lambda: subprocess.run(
            ["systemctl", "--user", "is-active", SERVICE_NAME], capture_output=True, text=True
        ).stdout.strip() == "active"),
    ):
        try:
            if checker():
                return {"running": True, "mode": mode}
        except Exception:  # noqa: BLE001
            continue
    # حالت پس‌زمینه nohup/cron
    try:
        pid = int(Path("logs/autorun.pid").read_text().strip())
        if Path(f"/proc/{pid}").exists():
            return {"running": True, "mode": "پس‌زمینه"}
    except Exception:  # noqa: BLE001
        pass
    return {"running": False, "mode": None}


def _read_status(cfg: AppConfig) -> dict | None:
    p = cfg.db_path.parent / "autorun_status.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _db_stats(cfg: AppConfig) -> dict:
    try:
        leads: list[Lead] = LeadStore(cfg.db_path).all_leads()
        phones = sum(len(l.phones) for l in leads)
        with_contact = sum(1 for l in leads if l.phones or l.emails)
        return {"leads": len(leads), "phones": phones, "with_contact": with_contact}
    except Exception:  # noqa: BLE001
        return {"leads": 0, "phones": 0, "with_contact": 0}


def _latest_export(cfg: AppConfig) -> dict | None:
    try:
        files = [p for p in cfg.export_dir.glob("leads_*") if p.is_file()]
        if not files:
            return None
        p = max(files, key=lambda x: x.stat().st_mtime)
        return {
            "name": p.name,
            "size_kb": round(p.stat().st_size / 1024, 1),
            "modified": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat(),
        }
    except Exception:  # noqa: BLE001
        return None


def tail_logs(n: int = 60) -> list[str]:
    """آخرین خطوط لاگ — از journald یا فایل logs/autorun.log."""
    if shutil.which("journalctl"):
        try:
            out = subprocess.run(
                ["journalctl", "-u", SERVICE_NAME, "-n", str(n),
                 "--no-pager", "-o", "cat"],
                capture_output=True, text=True, timeout=5,
            ).stdout
            lines = [ln for ln in out.splitlines() if ln.strip()]
            if lines:
                return lines[-n:]
        except Exception:  # noqa: BLE001
            pass
    log_file = Path("logs/autorun.log")
    try:
        lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[-n:]
    except Exception:  # noqa: BLE001
        return []


def _parse_iso(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def derive_activity(state: dict, status: dict | None) -> dict:
    """فعالیت فعلی ربات را از وضعیت سرویس + فایل وضعیت استنتاج می‌کند."""
    now = datetime.now(timezone.utc)
    if not state["running"]:
        return {"code": "off", "text": "ربات متوقف است", "next_in_sec": None,
                "cycle": (status or {}).get("cycle")}
    err = (status or {}).get("error")
    nxt = _parse_iso((status or {}).get("next_run_at"))
    if nxt and nxt > now:
        return {"code": "sleep", "text": "خواب بین دورها — دور بعدی به‌زودی",
                "next_in_sec": int((nxt - now).total_seconds()),
                "cycle": (status or {}).get("cycle")}
    if err and not nxt:
        return {"code": "error", "text": f"خطا در دور آخر: {err}",
                "next_in_sec": None, "cycle": (status or {}).get("cycle")}
    # فایل وضعیت نبود یا دور بعد نرسیده بود → احتمالاً وسط اسکن است
    cyc = (status or {}).get("cycle", 1)
    return {"code": "scan", "text": f"در حال اسکن — دور {cyc}",
            "next_in_sec": None, "cycle": cyc}


def snapshot(cfg: AppConfig) -> dict:
    """یک عکس کامل از وضعیت — خروجی /api/status."""
    state = service_state()
    status = _read_status(cfg)
    return {
        "now": datetime.now(timezone.utc).isoformat(),
        "service": state,
        "activity": derive_activity(state, status),
        "last_cycle": status,
        "db": _db_stats(cfg),
        "latest_export": _latest_export(cfg),
    }


# ═══════════════════════════ صفحه وب ═══════════════════════════
_PAGE = """<!doctype html>
<html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>داشبورد AbiiBot</title>
<style>
:root{--bg:#0d1117;--card:#161b22;--line:#30363d;--txt:#e6edf3;--dim:#8b949e;
--green:#2ea043;--red:#f85149;--amber:#d29922;--blue:#388bfd}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--txt);font-family:Vazirmatn,Tahoma,sans-serif;padding:20px;max-width:980px;margin:0 auto}
h1{font-size:20px;margin-bottom:14px;display:flex;align-items:center;gap:10px}
.dot{width:14px;height:14px;border-radius:50%;display:inline-block}
.dot.on{background:var(--green);box-shadow:0 0 12px var(--green);animation:pulse 2s infinite}
.dot.off{background:var(--red)}
.dot.warn{background:var(--amber)}
@keyframes pulse{50%{opacity:.55}}
.hero{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px;margin-bottom:14px}
.hero .state{font-size:22px;font-weight:bold;margin-bottom:4px}
.hero .sub{color:var(--dim);font-size:14px}
.hero .count{color:var(--blue);font-variant-numeric:tabular-nums}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}
.card .v{font-size:24px;font-weight:bold;margin-top:2px}
.card .k{color:var(--dim);font-size:12px}
.log{background:#0a0e14;border:1px solid var(--line);border-radius:10px;padding:10px;height:300px;overflow-y:auto;direction:ltr;text-align:left;font-family:Consolas,monospace;font-size:12px;line-height:1.7}
.log .INFO{color:#7ee787}.log .WARNING{color:#d29922}.log .ERROR,.log .CRITICAL{color:#f85149}.log .DEBUG{color:#6e7681}
.foot{color:var(--dim);font-size:12px;margin-top:10px;text-align:center}
a{color:var(--blue);text-decoration:none}
</style></head><body>
<h1><span class="dot off" id="dot"></span> داشبورد AbiiBot</h1>
<div class="hero">
  <div class="state" id="state">در حال دریافت…</div>
  <div class="sub" id="sub">—</div>
</div>
<div class="grid" id="cards"></div>
<div class="log" id="log"></div>
<div class="foot" id="foot">به‌روزرسانی هر ۲ ثانیه — AbiiBot</div>
<script>
const TOKEN = "__TOKEN__";
const qs = new URLSearchParams(location.search);
if (qs.get("t")) localStorage.setItem("abii_t", qs.get("t"));
const tok = qs.get("t") || localStorage.getItem("abii_t") || TOKEN;
const api = (p) => fetch(p + "?t=" + tok).then(r => r.json()).catch(() => null);
function fmt(n){return (n ?? 0).toLocaleString("fa-IR")}
function hms(s){if(s==null)return "—";const h=Math.floor(s/3600),m=Math.floor(s%3600/60),x=Math.floor(s%60);
  return (h?h+":":"")+String(m).padStart(2,"0")+":"+String(x).padStart(2,"0")}
async function refresh(){
  const st = await api("/api/status");
  if (!st){document.getElementById("state").textContent="⛔ دسترسی ندارید — توکن اشتباه است";return}
  const a = st.activity, sv = st.service;
  const dot = document.getElementById("dot");
  dot.className = "dot " + (sv.running ? (a.code==="error"?"warn":"on") : "off");
  const stateEl = document.getElementById("state");
  const names = {scan:"🟢 در حال اسکن", sleep:"🟢 فعال — بین دو دور", error:"🟡 فعال با خطا", off:"🔴 متوقف"};
  stateEl.textContent = names[a.code] || a.text;
  let sub = a.text;
  if (a.code === "sleep" && a.next_in_sec != null) sub += " — دور بعدی تا " + hms(a.next_in_sec);
  if (sv.mode) sub += " | روش اجرا: " + ({system:"سرویس دائمی systemd", user:"سرویس کاربر systemd"}[sv.mode] || sv.mode);
  document.getElementById("sub").textContent = sub;
  const lc = st.last_cycle || {}, m = lc.metrics || {};
  const cards = [
    ["فروشگاه‌های دارای تماس", fmt(st.db.with_contact)],
    ["مجموع شماره‌ها", fmt(st.db.phones)],
    ["دور آخر: فروشگاه", fmt(m.shops_fetched)],
    ["دور آخر: شماره جدید", fmt(m.phones_found)],
    ["خطاها", fmt(m.http_errors ?? 0)],
  ];
  document.getElementById("cards").innerHTML = cards.map(c =>
    '<div class="card"><div class="k">'+c[0]+'</div><div class="v">'+c[1]+'</div></div>').join("");
  const ex = st.latest_export;
  document.getElementById("foot").innerHTML = ex
    ? "آخرین خروجی: " + ex.name + " (" + ex.size_kb + "KB) — به‌روزرسانی هر ۲ ثانیه"
    : "هنوز فایل خروجی ساخته نشده — به‌روزرسانی هر ۲ ثانیه";
}
async function refreshLog(){
  const j = await api("/api/log");
  if (!j || !j.lines) return;
  const el = document.getElementById("log");
  const stick = el.scrollTop + el.clientHeight >= el.scrollHeight - 30;
  el.innerHTML = j.lines.map(l => {
    const m = l.match(/\\b(INFO|WARNING|ERROR|DEBUG|CRITICAL)\\b/);
    const cls = m ? m[1] : "";
    return '<div class="'+cls+'">'+l.replace(/&/g,"&amp;").replace(/</g,"&lt;")+"</div>";
  }).join("");
  if (stick) el.scrollTop = el.scrollHeight;
}
refresh(); refreshLog();
setInterval(refresh, 2000); setInterval(refreshLog, 2000);
</script></body></html>"""


def make_handler(cfg: AppConfig, token: str):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # ساکت
            pass

        def _check(self) -> bool:
            q = parse_qs(urlsplit(self.path).query)
            got = (q.get("t") or [None])[0] or self.headers.get("X-Token", "")
            if got != token:
                self.send_response(401)
                body = "دسترسی ندارید — توکن را در URL بگذارید: ?t=..."
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body.encode())))
                self.end_headers()
                self.wfile.write(body.encode())
                return False
            return True

        def _json(self, obj):
            body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/" :
                page = _PAGE.replace("__TOKEN__", token)
                body = page.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif path == "/api/status":
                if self._check():
                    self._json(snapshot(cfg))
            elif path == "/api/log":
                if self._check():
                    self._json({"lines": tail_logs(60)})
            else:
                self.send_response(404)
                self.end_headers()

    return Handler


def run_dashboard(
    cfg: AppConfig, host: str = "0.0.0.0", port: int = DEFAULT_PORT,
) -> None:
    """سرور داشبورد — تا Ctrl+C روشن می‌ماند."""
    token = get_token(cfg)
    srv = ThreadingHTTPServer((host, port), make_handler(cfg, token))
    url = f"http://{host}:{port}/?t={token}" if host not in ("0.0.0.0", "::") \
        else f"http://<آی‌پی-سرور>:{port}/?t={token}"
    print(f"✅ داشبورد AbiiBot روشن شد → {url}")
    print("   (برای دسترسی از بیرون، پورت را در فایروال باز کنید)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nداشبورد بسته شد.")
    finally:
        srv.server_close()
