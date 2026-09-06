"""داشبورد زنده AbiiBot — «ربات فعاله؟ الان داره چیکار می‌کنه؟»

یک صفحه وب سبک (فقط stdlib، بدون اینترنت/CDN) که نشان می‌دهد:
  • وضعیت ربات: فعال/متوقف + روش اجرا (systemd/cron/پس‌زمینه)
  • فعالیت لحظه‌ای: در حال اسکن دور چند است یا خواب تا دور بعد (شمارش معکوس)
  • آمار: لیدها، شماره‌ها، نتیجه دور آخر، فایل اکسل آخر
  • لاگ زنده: آخرین خطوط با رنگ
  • کنترل: دکمه شروع/توقف ربات + دانلود اکسل/CSV داده‌های جمع‌آوری‌شده

اجرا:  abii dashboard   →  http://SERVER-IP:8501/?t=TOKEN
توکن یک‌بار ساخته می‌شود (data/.dashboard_token) چون شماره‌ها داده حساس‌اند.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .config import AppConfig
from .models import Lead
from .storage import LeadStore, export_leads

logger = logging.getLogger(__name__)

SERVICE_NAME = "abii-autorun"
DASH_SERVICE = "abii-dashboard"
DEFAULT_PORT = 8501
UNIT_PATH = Path("/etc/systemd/system/abii-autorun.service")
USER_UNIT_PATH = Path.home() / ".config/systemd/user/abii-autorun.service"
PID_FILE = Path("logs/autorun.pid")
LOG_FILE = Path("logs/autorun.log")


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


def _run(cmd: list[str]) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except Exception:  # noqa: BLE001
        return None


def _pid_alive(pid: int) -> bool:
    """زنده = فرایند واقعاً در حال اجرا (زامبی = مرده)."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        state = stat.rpartition(")")[2].split()[0]
        return state not in ("Z", "X", "x")
    except Exception:  # noqa: BLE001
        return False


def service_state() -> dict:
    """ربات اتوران از کجا/method دارد اجرا می‌شود؟"""
    r = _run(["systemctl", "is-active", SERVICE_NAME])
    if r and r.stdout.strip() == "active":
        return {"running": True, "mode": "system", "controllable": True}
    r = _run(["systemctl", "--user", "is-active", SERVICE_NAME])
    if r and r.stdout.strip() == "active":
        return {"running": True, "mode": "user", "controllable": True}
    try:
        pid = int(PID_FILE.read_text().strip())
        if _pid_alive(pid):
            return {"running": True, "mode": "پس‌زمینه", "controllable": True}
    except Exception:  # noqa: BLE001
        pass
    return {"running": False, "mode": None, "controllable": True}


def _abii_bin() -> str:
    return str(Path(sys.executable).parent / "abii")


def _spawn_autorun() -> int:
    """اجرای اتوران در پس‌زمینه (حالت nohup) — PID را برمی‌گرداند."""
    Path("logs").mkdir(exist_ok=True)
    logf = open(LOG_FILE, "ab")  # noqa: SIM115
    proc = subprocess.Popen(
        [_abii_bin(), "autorun"], stdout=logf, stderr=subprocess.STDOUT,
        start_new_session=True, cwd=str(Path.cwd()),
    )
    PID_FILE.write_text(str(proc.pid), encoding="utf-8")
    return proc.pid


def start_bot() -> tuple[bool, str]:
    """شروع ربات — بهترین روش موجود؛ خروجی: (موفق؟، پیام)."""
    if service_state()["running"]:
        return True, "ربات از قبل فعال است"
    # ۱) سرویس سیستمی systemd (با sudo بدون رمز یا اجرای root)
    if UNIT_PATH.exists():
        for cmd in (["sudo", "-n", "systemctl", "start", SERVICE_NAME],
                    ["systemctl", "start", SERVICE_NAME]):
            r = _run(cmd)
            if r and r.returncode == 0:
                return True, "ربات با سرویس systemd شروع شد"
    # ۲) سرویس کاربر
    if USER_UNIT_PATH.exists():
        r = _run(["systemctl", "--user", "start", SERVICE_NAME])
        if r and r.returncode == 0:
            return True, "ربات با سرویس کاربر systemd شروع شد"
    # ۳) پس‌زمینه (nohup)
    try:
        pid = _spawn_autorun()
        return True, f"ربات در پس‌زمینه شروع شد (PID {pid})"
    except Exception as exc:  # noqa: BLE001
        return False, f"شروع نشد: {exc} — از ترمینال: bash activate.sh"


def stop_bot() -> tuple[bool, str]:
    """توقف ربات — تمیز (SIGINT مثل systemd)؛ خروجی: (موفق؟، پیام)."""
    if not service_state()["running"]:
        return True, "ربات از قبل متوقف است"
    # ۱) systemd
    for stop_cmd in (["sudo", "-n", "systemctl", "stop", SERVICE_NAME],
                     ["systemctl", "stop", SERVICE_NAME]):
        if UNIT_PATH.exists():
            r = _run(stop_cmd)
            if r and r.returncode == 0 and not service_state()["running"]:
                return True, "ربات متوقف شد (systemd)"
    if USER_UNIT_PATH.exists():
        r = _run(["systemctl", "--user", "stop", SERVICE_NAME])
        if r and r.returncode == 0 and not service_state()["running"]:
            return True, "ربات متوقف شد (سرویس کاربر)"
    # ۲) پس‌زمینه: SIGINT تمیز، بعد از ۱۰ ثانیه SIGTERM
    try:
        pid = int(PID_FILE.read_text().strip())
    except Exception:  # noqa: BLE001
        return False, "ربات در حال اجراست ولی PID پیدا نشد — از ترمینال: bash activate.sh --off"
    try:
        os.kill(pid, signal.SIGINT)
    except ProcessLookupError:
        PID_FILE.unlink(missing_ok=True)
        return True, "ربات متوقف شد"
    except PermissionError:
        return False, "دسترسی کافی نیست — از ترمینال: bash activate.sh --off"
    for _ in range(20):
        if not _pid_alive(pid):
            PID_FILE.unlink(missing_ok=True)
            return True, "ربات متوقف شد"
        time.sleep(0.5)
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    PID_FILE.unlink(missing_ok=True)
    return True, "ربات متوقف شد"


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
    try:
        lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
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


def export_bytes(cfg: AppConfig, fmt: str) -> tuple[bytes, str, str]:
    """تولید فایل خروجی از دیتابیس → (بایت‌ها، mime، نام فایل)."""
    leads = LeadStore(cfg.db_path).all_leads()
    leads = [l for l in leads if l.phones or l.emails]  # فقط ردیف‌های باارزش
    with tempfile.TemporaryDirectory() as tmp:
        paths = export_leads(leads, tmp, [fmt], only_with_contact=True)
        data = paths[fmt].read_bytes()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if fmt == "xlsx":
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        name = f"abii-leads-{stamp}.xlsx"
    else:
        mime = "text/csv; charset=utf-8"
        name = f"abii-leads-{stamp}.csv"
    return data, mime, name


# ═══════════════════════════ صفحه وب ═══════════════════════════
_PAGE = """<!doctype html>
<html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>داشبورد AbiiBot</title>
<style>
:root{--bg:#0b0f17;--card:#151b27;--card2:#1a2233;--line:#2a3550;--txt:#eef2f8;
--dim:#93a0b4;--green:#3ddc84;--red:#ff6b6b;--amber:#ffc857;--blue:#5ba8ff;--violet:#b18cff}
*{box-sizing:border-box;margin:0;padding:0}
body{background:radial-gradient(1200px 500px at 80% -10%,#16213a 0%,var(--bg) 55%);
color:var(--txt);font-family:Vazirmatn,Tahoma,sans-serif;padding:20px;max-width:1000px;margin:0 auto}
h1{font-size:21px;margin-bottom:16px;display:flex;align-items:center;gap:10px;
background:linear-gradient(90deg,#7ee787,#5ba8ff);-webkit-background-clip:text;background-clip:text;color:transparent}
.dot{width:15px;height:15px;border-radius:50%;display:inline-block;flex:none}
.dot.on{background:var(--green);box-shadow:0 0 14px var(--green);animation:pulse 1.6s infinite}
.dot.off{background:var(--red);box-shadow:0 0 10px var(--red)}
.dot.warn{background:var(--amber);box-shadow:0 0 10px var(--amber)}
@keyframes pulse{50%{opacity:.5}}
.hero{background:linear-gradient(135deg,var(--card),var(--card2));border:1px solid var(--line);
border-radius:16px;padding:20px;margin-bottom:14px;box-shadow:0 8px 24px rgba(0,0,0,.35)}
.hero .state{font-size:24px;font-weight:800;margin-bottom:6px}
.hero .sub{color:var(--dim);font-size:14px;line-height:1.9}
.bar{height:8px;background:#0d1420;border-radius:99px;margin-top:12px;overflow:hidden;display:none}
.bar i{display:block;height:100%;background:linear-gradient(90deg,var(--green),var(--blue));
border-radius:99px;transition:width 1s linear}
.actions{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px}
.btn{border:1px solid var(--line);background:var(--card);color:var(--txt);border-radius:12px;
padding:11px 18px;font-family:inherit;font-size:14px;font-weight:700;cursor:pointer;
transition:transform .12s,box-shadow .12s,opacity .12s}
.btn:hover:not(:disabled){transform:translateY(-2px);box-shadow:0 6px 16px rgba(0,0,0,.4)}
.btn:disabled{opacity:.4;cursor:not-allowed}
.btn.start{background:linear-gradient(135deg,#1d5c3a,#173a2a);border-color:#2f7a4f}
.btn.stop{background:linear-gradient(135deg,#6b2530,#3f1a22);border-color:#a03a4a}
.btn.dl{background:linear-gradient(135deg,#1e3a6b,#1a2747);border-color:#2f5aa0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:10px;margin-bottom:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px;
position:relative;overflow:hidden}
.card::before{content:"";position:absolute;inset:0 0 auto 0;height:3px}
.card.g1::before{background:var(--green)}.card.g2::before{background:var(--blue)}
.card.g3::before{background:var(--violet)}.card.g4::before{background:var(--amber)}
.card.g5::before{background:var(--red)}
.card .v{font-size:26px;font-weight:800;margin-top:4px;font-variant-numeric:tabular-nums}
.card .k{color:var(--dim);font-size:12.5px}
.log{background:#080c13;border:1px solid var(--line);border-radius:14px;padding:12px;height:300px;
overflow-y:auto;direction:ltr;text-align:left;font-family:Consolas,monospace;font-size:12px;line-height:1.75}
.log .INFO{color:#7ee787}.log .WARNING{color:#ffc857}
.log .ERROR,.log .CRITICAL{color:#ff6b6b}.log .DEBUG{color:#5d6b7f}
.foot{color:var(--dim);font-size:12.5px;margin-top:12px;text-align:center}
.toast{position:fixed;bottom:22px;right:50%;transform:translateX(50%);background:var(--card2);
border:1px solid var(--line);border-radius:12px;padding:12px 22px;font-size:14px;font-weight:700;
box-shadow:0 10px 30px rgba(0,0,0,.5);opacity:0;transition:opacity .25s;pointer-events:none;z-index:9}
.toast.show{opacity:1}.toast.ok{border-color:#2f7a4f}.toast.err{border-color:#a03a4a}
</style></head><body>
<h1><span class="dot off" id="dot"></span> داشبورد AbiiBot</h1>
<div class="hero">
  <div class="state" id="state">در حال دریافت…</div>
  <div class="sub" id="sub">—</div>
  <div class="bar" id="bar"><i id="barfill" style="width:0%"></i></div>
</div>
<div class="actions">
  <button class="btn start" id="btn-start">▶ شروع ربات</button>
  <button class="btn stop" id="btn-stop">■ توقف ربات</button>
  <button class="btn dl" id="btn-xlsx">⬇ دانلود اکسل</button>
  <button class="btn dl" id="btn-csv">⬇ دانلود CSV</button>
</div>
<div class="grid" id="cards"></div>
<div class="log" id="log"></div>
<div class="foot" id="foot">به‌روزرسانی هر ۲ ثانیه — AbiiBot</div>
<div class="toast" id="toast"></div>
<script>
const qs = new URLSearchParams(location.search);
if (qs.get("t")) localStorage.setItem("abii_t", qs.get("t"));
const tok = qs.get("t") || localStorage.getItem("abii_t") || "";
const api = (p) => fetch(p + "?t=" + tok).then(r => r.json()).catch(() => null);
function fmt(n){return (n ?? 0).toLocaleString("fa-IR")}
function hms(s){if(s==null)return "—";const h=Math.floor(s/3600),m=Math.floor((s%3600)/60),x=s%60;
  return (h?h+":":"")+String(m).padStart(2,"0")+":"+String(x).padStart(2,"0")}
let toastTimer=null;
function toast(msg, ok){
  const t=document.getElementById("toast");
  t.textContent=msg; t.className="toast show "+(ok?"ok":"err");
  clearTimeout(toastTimer); toastTimer=setTimeout(()=>t.className="toast",3500);
}
async function action(kind){
  const btn=document.getElementById(kind==="start"?"btn-start":"btn-stop");
  btn.disabled=true; toast("در حال اجرا…", true);
  try{
    const r=await fetch("/api/action?t="+tok,{method:"POST",
      headers:{"Content-Type":"application/json","X-Token":tok},
      body:JSON.stringify({action:kind})});
    const j=await r.json();
    toast(j.message||"", j.ok);
  }catch(e){toast("ارتباط با سرور برقرار نشد", false)}
  refresh();
}
document.getElementById("btn-start").onclick=()=>action("start");
document.getElementById("btn-stop").onclick=()=>{ if(confirm("ربات متوقف شود؟")) action("stop"); };
document.getElementById("btn-xlsx").onclick=()=>{location.href="/api/export?fmt=xlsx&t="+tok;};
document.getElementById("btn-csv").onclick=()=>{location.href="/api/export?fmt=csv&t="+tok;};
async function refresh(){
  const st = await api("/api/status");
  if (!st){document.getElementById("state").textContent="⛔ دسترسی ندارید — توکن اشتباه است";return}
  const a = st.activity, sv = st.service;
  const dot = document.getElementById("dot");
  dot.className = "dot " + (sv.running ? (a.code==="error"?"warn":"on") : "off");
  const names = {scan:"🟢 در حال اسکن", sleep:"🟢 فعال — استراحت بین دو دور", error:"🟡 فعال با خطا", off:"🔴 ربات متوقف است"};
  document.getElementById("state").textContent = names[a.code] || a.text;
  let sub = a.text;
  if (a.code === "sleep" && a.next_in_sec != null) sub += " — دور بعدی تا " + hms(a.next_in_sec);
  if (sv.mode) sub += " | روش اجرا: " + ({system:"سرویس دائمی systemd", user:"سرویس کاربر systemd"}[sv.mode] || sv.mode);
  document.getElementById("sub").textContent = sub;
  const bar = document.getElementById("bar");
  const lc = st.last_cycle || {};
  if (a.code === "sleep" && lc.next_run_at && lc.finished_at){
    const total = Date.parse(lc.next_run_at) - Date.parse(lc.finished_at);
    if (total > 0){
      bar.style.display="block";
      document.getElementById("barfill").style.width = Math.min(100, Math.max(0, 100*(1 - a.next_in_sec/total))) + "%";
    }
  } else bar.style.display="none";
  document.getElementById("btn-start").disabled = sv.running;
  document.getElementById("btn-stop").disabled = !sv.running;
  const m = lc.metrics || {};
  const cards = [
    ["🏪 فروشگاه‌های دارای تماس", fmt(st.db.with_contact), "g1"],
    ["📞 مجموع شماره‌ها", fmt(st.db.phones), "g2"],
    ["🔄 دور آخر: فروشگاه", fmt(m.shops_fetched), "g3"],
    ["✨ دور آخر: شماره جدید", fmt(m.phones_found), "g4"],
    ["⛔ خطاها", fmt(((m.http || {}).errors) ?? m.http_errors ?? 0), "g5"],
  ];
  document.getElementById("cards").innerHTML = cards.map(c =>
    '<div class="card '+c[2]+'"><div class="k">'+c[0]+'</div><div class="v">'+c[1]+'</div></div>').join("");
  const ex = st.latest_export;
  document.getElementById("foot").innerHTML = ex
    ? "آخرین خروجی خودکار: " + ex.name + " (" + ex.size_kb + "KB) — به‌روزرسانی هر ۲ ثانیه"
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
                self._text(401, "دسترسی ندارید — توکن را در URL بگذارید: ?t=...")
                return False
            return True

        def _text(self, code: int, body: str, ctype: str = "text/plain; charset=utf-8"):
            data = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _json(self, obj, code: int = 200):
            body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parts = urlsplit(self.path)
            path, q = parts.path, parse_qs(parts.query)
            if path == "/":
                body = _PAGE.encode()
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
            elif path == "/api/export":
                if not self._check():
                    return
                fmt = (q.get("fmt") or ["xlsx"])[0]
                if fmt not in ("xlsx", "csv"):
                    self._json({"ok": False, "message": "فرمت نامعتبر"}, 400)
                    return
                try:
                    data, mime, name = export_bytes(cfg, fmt)
                except Exception as exc:  # noqa: BLE001
                    self._json({"ok": False, "message": f"خطا در تولید فایل: {exc}"}, 500)
                    return
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Disposition",
                                 f"attachment; filename*=UTF-8''{name}")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                self._text(404, "نه پیدا شد")

        def do_POST(self):
            if urlsplit(self.path).path != "/api/action":
                self._text(404, "نه پیدا شد")
                return
            if not self._check():
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(length) or b"{}")
            except Exception:  # noqa: BLE001
                self._json({"ok": False, "message": "بدنه نامعتبر"}, 400)
                return
            act = payload.get("action")
            if act == "start":
                ok, msg = start_bot()
            elif act == "stop":
                ok, msg = stop_bot()
            else:
                self._json({"ok": False, "message": "action باید start یا stop باشد"}, 400)
                return
            self._json({"ok": ok, "message": msg})

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
