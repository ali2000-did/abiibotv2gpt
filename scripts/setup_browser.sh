#!/usr/bin/env bash
# نصب مرورگر کرومیوم برای AbiiBot (Playwright) + ffmpeg برای ضبط ویدیو
#
# ترتیب: ۱) نصب استاندارد Playwright  ۲) fallback از npm (@sparticuz/chromium)
# fallback برای محیط‌هایی است که CDN پلی‌رایت در آن‌ها فیلتر است.
# بعد از نصب، مسیر binary در ~/.cache/abii-browsers قرار می‌گیرد و خودکار پیدا می‌شود.
set -euo pipefail

VENV="${1:-.venv}"
# مسیر مطلق (اسکریپت وسط کار cd می‌کند — مسیر نسبی می‌شکند)
case "$VENV" in
  /*) ;;
  *) VENV="$(cd "$(dirname "$VENV")" && pwd)/$(basename "$VENV")" ;;
esac
PY="$VENV/bin/python"
DIR="$HOME/.cache/abii-browsers"
FFDIR="$HOME/.cache/ms-playwright"

command -v python3 >/dev/null || { echo "python3 لازم است"; exit 1; }
[ -x "$PY" ] || { echo "venv پیدا نشد: $VENV (اول python3 -m venv .venv)"; exit 1; }

echo "▶ [1/3] تلاش: playwright install chromium"
if "$PY" -m playwright install chromium 2>/dev/null; then
  echo "✅ نصب استاندارد Playwright انجام شد."
else
  echo "⚠ نصب استاندارد ناموفق بود → روش جایگزین (npm @sparticuz/chromium)"
  "$PY" -m pip install -q brotli playwright || { echo "pip install ناموفق"; exit 1; }

  echo "▶ [2/3] دانلود کرومیوم از registry.npmjs.org …"
  mkdir -p "$DIR" && cd "$DIR"
  VER="$("$PY" - <<'EOF'
import json, urllib.request
d = json.load(urllib.request.urlopen("https://registry.npmjs.org/@sparticuz%2Fchromium/latest"))
print(d["version"])
EOF
)"
  curl -fsSL -o chromium.tgz "https://registry.npmjs.org/@sparticuz/chromium/-/chromium-$VER.tgz"
  tar xzf chromium.tgz
  "$PY" - <<'EOF'
import brotli, tarfile, io, os
os.chdir(os.path.expanduser("~/.cache/abii-browsers/package/bin"))
for name in ["chromium", "al2023.tar", "fonts.tar", "swiftshader.tar"]:
    with open(name + ".br", "rb") as f:
        data = brotli.decompress(f.read())
    if name.endswith(".tar"):
        with tarfile.open(fileobj=io.BytesIO(data)) as t:
            t.extractall(".")
    else:
        open(name, "wb").write(data)
        os.chmod(name, 0o755)
print("extracted OK")
EOF
  rm -f chromium.tgz
  echo "✅ کرومیوم در $DIR/package/bin/chromium نصب شد (خودکار تشخیص داده می‌شود)."
fi

echo "▶ [3/3] ffmpeg (برای --record) اگر سیستم ندارد…"
if command -v ffmpeg >/dev/null; then
  echo "✅ ffmpeg سیستم موجود است."
else
  # شماره نسخه ffmpeg مورد انتظار پلی‌رایت از browsers.json خودش خوانده می‌شود
  EXP="$("$PY" - <<'EOF'
import json, pathlib, sys
bj = pathlib.Path(sys.executable).parent.parent / "lib" / "python3.11" / "site-packages" / "playwright" / "driver" / "package" / "browsers.json"
try:
    data = json.loads(bj.read_text())
    for b in data["browsers"]:
        if b["name"] == "ffmpeg":
            print(f"ffmpeg-{b['revision']}")
            break
    else:
        print("ffmpeg-1011")
except Exception:
    print("ffmpeg-1011")
EOF
)"
  TARGET="$FFDIR/$EXP/ffmpeg-linux"
  if [ -x "$TARGET" ]; then
    echo "✅ ffmpeg پلی‌رایت موجود است ($EXP)."
  else
    mkdir -p /tmp/ffdl && cd /tmp/ffdl
    curl -fsSL -o ffmpeg.tgz "https://registry.npmjs.org/@ffmpeg-installer/linux-x64/-/linux-x64-4.1.0.tgz"
    tar xzf ffmpeg.tgz
    mkdir -p "$FFDIR/$EXP"
    cp package/ffmpeg "$TARGET" && chmod +x "$TARGET"
    echo "✅ ffmpeg در $TARGET نصب شد."
  fi
fi

"$PY" - <<'EOF'
# راستی‌آزمایی نهایی: کرومیوم بالا می‌آید؟
from playwright.sync_api import sync_playwright
try:
    from abii_bot.browser.setup import find_chromium, launch_chromium
except ImportError:
    import sys; sys.exit(0)
exe = find_chromium()
if exe is None:
    print("ℹ کرومیوم استاندارد پلی‌رایت استفاده می‌شود.")
    raise SystemExit(0)
with sync_playwright() as p:
    b = launch_chromium(p, headless=True)
    b.close()
print("✅ راه‌اندازی کرومیوم راستی‌آزمایی شد.")
EOF
