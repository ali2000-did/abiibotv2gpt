#!/usr/bin/env bash
# نصب مرورگر کرومیوم برای AbiiBot (Playwright)
#
# ترتیب: ۱) نصب استاندارد Playwright  ۲) fallback از npm (@sparticuz/chromium)
# fallback برای محیط‌هایی است که CDN پلی‌رایت در آن‌ها فیلتر است.
# بعد از نصب، مسیر binary در ~/.cache/abii-browsers قرار می‌گیرد و خودکار پیدا می‌شود.
set -euo pipefail

VENV="${1:-.venv}"
PY="$VENV/bin/python"
DIR="$HOME/.cache/abii-browsers"

echo "▶ [1/2] تلاش: playwright install chromium"
if "$PY" -m playwright install chromium 2>/dev/null; then
  echo "✅ نصب استاندارد Playwright انجام شد."
  exit 0
fi
echo "⚠ نصب استاندارد ناموفق بود → روش جایگزین (npm @sparticuz/chromium)"

command -v python3 >/dev/null || { echo "python3 لازم است"; exit 1; }
"$PY" -m pip install -q brotli playwright || { echo "pip install ناموفق"; exit 1; }

echo "▶ [2/2] دانلود کرومیوم از registry.npmjs.org …"
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
