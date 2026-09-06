"""فعال‌ساز محلی AbiiBot — ویندوز و لینوکس (بدون نیاز به bash)

دابل‌کلیک روی activate.bat (ویندوز) یا اجرای مستقیم:
    python scripts/activate_windows.py            فعال‌سازی کامل + داشبورد
    python scripts/activate_windows.py --status   وضعیت
    python scripts/activate_windows.py --stop     توقف ربات و داشبورد
    python scripts/activate_windows.py --start    فقط شروع (برای Task Scheduler)

مراحل کامل: نصب venv ← تست سلامت ← شروع ربات ← شروع داشبورد ← باز کردن
مرورگر ← (ویندوز) پیشنهاد اجرای خودکار در ورود به ویندوز.
فاز ۲ (بعد از نصب) با پایتونِ خودِ venv دوباره اجرا می‌شود.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
os.chdir(REPO)
IS_WINDOWS = sys.platform == "win32"
DASH_PORT = 8501
VENV_PY = REPO / (".venv/Scripts/python.exe" if IS_WINDOWS else ".venv/bin/python")
VENV_ABII = REPO / (".venv/Scripts/abii.exe" if IS_WINDOWS else ".venv/bin/abii")
DASH_PID = REPO / "logs/dashboard.pid"
DASH_LOG = REPO / "logs/dashboard.log"


def say(icon: str, msg: str) -> None:
    print(f"  {icon} {msg}", flush=True)


def step(n: str, msg: str) -> None:
    print(f"\n▶ {n} {msg}", flush=True)


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(REPO), **kw)


def port_busy(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


# ═════════════════ فاز ۱: نصب (با پایتون فعلی) ═════════════════
def phase_install() -> None:
    print("╔══════════════════════════════════════════════╗", flush=True)
    print("║   AbiiBot — فعال‌ساز (ویندوز/لینوکس)          ║")
    print("║   نصب ← تست ← شروع ربات ← داشبورد            ║")
    print("╚══════════════════════════════════════════════╝")

    step("۱/۴", "بررسی پایتون…")
    if sys.version_info < (3, 10):
        say("✗", f"پایتون ۳.۱۰+ لازم است (شما: {sys.version.split()[0]})")
        sys.exit(1)
    say("✓", f"پایتون {sys.version.split()[0]}")

    step("۲/۴", "ساخت محیط مجازی و نصب برنامه…")
    if VENV_ABII.exists():
        r = _run([str(VENV_ABII), "version"], capture_output=True, text=True)
        if r.returncode == 0:
            say("✓", "از قبل نصب است — رد شد")
            return
    if not VENV_PY.exists():
        r = _run([sys.executable, "-m", "venv", ".venv"])
        if r.returncode != 0:
            say("✗", "ساخت venv ناموفق")
            sys.exit(1)
    r = _run([str(VENV_PY), "-m", "pip", "install", "-q", "--upgrade", "pip"])
    r = _run([str(VENV_PY), "-m", "pip", "install", "-q", "-e", ".[dev]"])
    if r.returncode != 0:
        say("✗", "نصب وابستگی‌ها ناموفق — اینترنت را چک کنید")
        sys.exit(1)
    say("✓", "نصب کامل شد")

    # مرورگر (اختیاری — برای شماره‌های «نمایش شماره»)
    if "--no-browser-install" not in sys.argv:
        try:
            _run([str(VENV_PY), "-m", "playwright", "install", "chromium"],
                 timeout=420, capture_output=True)
            say("✓", "مرورگر خودکار هم آماده شد")
        except Exception:  # noqa: BLE001
            say("⚠", "مرورگر نصب نشد (اختیاری) — بعداً: playwright install chromium")


# ═════════════════ فاز ۲: تست + اجرا (با پایتون venv) ═════════════════
def phase_run(no_open_browser: bool) -> None:
    sys.path.insert(0, str(REPO / "src"))
    from abii_bot.config import AppConfig
    from abii_bot import dashboard as dash

    step("۳/۴", "تست سلامت (آفلاین)…")
    r = _run([str(VENV_PY), "-m", "pytest", "-q",
              "tests/test_phone.py", "tests/test_pipeline.py"],
             capture_output=True, text=True)
    if r.returncode == 0:
        say("✓", "همه تست‌ها سبز شدند")
    else:
        tail = (r.stdout + r.stderr).strip().splitlines()[-5:]
        for ln in tail:
            say(" ", ln)
        say("✗", "تست سلامت رد شد — ادامه نمی‌دهیم")
        sys.exit(1)

    step("۴/۴", "شروع ربات و داشبورد…")
    ok, msg = dash.start_bot()
    say("✓" if ok else "✗", msg)
    if not ok:
        sys.exit(1)

    # داشبورد — اگر نیست، بالا بیاور (ویندوز: فقط همین سیستم، بدون دیوار آتش)
    if port_busy(DASH_PORT):
        say("✓", "داشبورد از قبل روشن است")
    else:
        (REPO / "logs").mkdir(exist_ok=True)
        host = "127.0.0.1" if IS_WINDOWS else "0.0.0.0"
        kw: dict = {}
        if IS_WINDOWS:
            kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW — پنجره سیاه باز نمی‌شود
        else:
            kw["start_new_session"] = True
        logf = open(DASH_LOG, "ab")  # noqa: SIM115
        proc = subprocess.Popen([str(VENV_ABII), "dashboard", "--host", host],
                                stdout=logf, stderr=subprocess.STDOUT,
                                cwd=str(REPO), **kw)
        DASH_PID.write_text(str(proc.pid), encoding="utf-8")
        for _ in range(30):
            if port_busy(DASH_PORT):
                break
            time.sleep(0.5)
        say("✓", f"داشبورد روشن شد (پورت {DASH_PORT})")

    cfg = AppConfig()
    tok = dash.get_token(cfg)
    url = f"http://{'127.0.0.1' if IS_WINDOWS else 'localhost'}:{DASH_PORT}/?t={tok}"
    print("\n╔══════════════════════════════════════════════════╗")
    print("║  ✅ ربات فعال شد و کار می‌کند                     ║")
    print("╚══════════════════════════════════════════════════╝")
    print(f"  🖥 داشبورد:   {url}")
    print("  📁 اکسل‌ها:   exports/   |   دیتابیس: data/leads.db")
    print("  ⏹  توقف:     داشبورد ← دکمه «توقف ربات» یا این اسکریپت با --stop")
    if not no_open_browser:
        try:
            webbrowser.open(url)
            say("✓", "داشبورد در مرورگر باز شد")
        except Exception:  # noqa: BLE001
            pass

    if IS_WINDOWS and "--no-autostart" not in sys.argv and sys.stdin.isatty():
        ans = input("\n  اجرای خودکار هنگام روشن شدن ویندوز؟ (y/n): ").strip().lower()
        if ans == "y":
            register_autostart()


def register_autostart() -> None:
    """Task Scheduler ویندوز — اجرای بی‌صدا ربات+داشبورد در هر ورود."""
    pyw = VENV_PY.parent / "pythonw.exe"
    exe = str(pyw if pyw.exists() else VENV_PY)
    tr = f'"{exe}" "{REPO / "scripts/activate_windows.py"}" --start'
    r = _run(["schtasks", "/Create", "/TN", "AbiiBot", "/TR", tr,
              "/SC", "ONLOGON", "/F"], capture_output=True, text=True)
    say("✓" if r.returncode == 0 else "✗",
        "اجرای خودکار در ورود به ویندوز فعال شد" if r.returncode == 0
        else f"schtasks خطا داد: {(r.stdout + r.stderr).strip()[:80]}")


def do_stop() -> None:
    sys.path.insert(0, str(REPO / "src"))
    from abii_bot import dashboard as dash
    ok, msg = dash.stop_bot()
    say("✓" if ok else "✗", msg)
    try:
        pid = int(DASH_PID.read_text().strip())
        if IS_WINDOWS:
            _run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
        else:
            import signal as sg
            os.kill(pid, sg.SIGTERM)
        DASH_PID.unlink(missing_ok=True)
        say("✓", "داشبورد بسته شد")
    except Exception:  # noqa: BLE001
        say("⚠", "داشبورد پیدا نشد (شاید بسته بود)")


def do_status() -> None:
    sys.path.insert(0, str(REPO / "src"))
    from abii_bot.config import AppConfig
    from abii_bot import dashboard as dash
    st = dash.service_state()
    snap = dash.snapshot(AppConfig())
    a = snap["activity"]
    print(f"ربات: {'🟢 فعال (' + st['mode'] + ')' if st['running'] else '🔴 متوقف'}")
    print(f"فعالیت: {a['text']}")
    print(f"داده‌ها: {snap['db']['leads']} لید | {snap['db']['phones']} شماره")
    tok = dash.get_token(AppConfig())
    print(f"داشبورد: {'روشن' if port_busy(DASH_PORT) else 'خاموش'}"
          f" — http://{'127.0.0.1' if IS_WINDOWS else 'localhost'}:{DASH_PORT}/?t={tok}")


# ═════════════════ ورودی ═════════════════
def main() -> None:
    args = sys.argv[1:]
    if "--phase2" in args or any(a in args for a in ("--start", "--stop", "--status")):
        if not VENV_PY.exists():
            say("✗", "اول نصب کنید: python scripts/activate_windows.py")
            sys.exit(1)
        if "--stop" in args:
            do_stop()
        elif "--status" in args:
            do_status()
        else:  # --phase2 / --start
            phase_run(no_open_browser="--start" in args or "--no-browser" in args)
        return
    phase_install()
    # فاز ۲ با پایتون venv — برای دسترسی به ماژول‌های نصب‌شده
    extra = ["--no-browser"] if "--no-browser" in args else []
    r = _run([str(VENV_PY), str(Path(__file__).resolve()), "--phase2", *extra])
    sys.exit(r.returncode)


if __name__ == "__main__":
    main()
