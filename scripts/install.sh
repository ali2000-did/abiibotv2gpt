#!/usr/bin/env bash
# ═══ نصب AbiiBot روی سرور شما (یک فرمان) ═══
#   bash scripts/install.sh
# پیش‌نیاز: Ubuntu/Debian با python3.10+ و git
set -euo pipefail
cd "$(dirname "$0")/.."

echo "▶ ۱/۴ بررسی پیش‌نیازها…"
command -v python3 >/dev/null || { echo "✗ python3 نصب نیست"; exit 1; }
PYVER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
python3 -c "import sys; assert sys.version_info >= (3, 10)" || { echo "✗ پایتون ۳.۱۰+ لازم است (شما: $PYVER)"; exit 1; }
echo "  ✓ پایتون $PYVER"

echo "▶ ۲/۴ ساخت محیط مجازی و نصب پکیج…"
if [ ! -x ".venv/bin/python" ]; then python3 -m venv .venv; fi
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -e .
echo "  ✓ نصب شد"

echo "▶ ۳/۴ آماده‌سازی مرورگر (برای شماره‌های «نمایش شماره»)…"
if bash scripts/setup_browser.sh .venv >/dev/null 2>&1; then
  echo "  ✓ مرورگر آماده است"
else
  echo "  ⚠ مرورگر نصب نشد — حالت API کار می‌کند؛ بعداً './venv/bin/python -m playwright install chromium' را بزنید"
fi

echo "▶ ۴/۴ راستی‌آزمایی…"
.venv/bin/abii version
echo
echo "✅ نصب کامل شد! اجرای اول (تست آفلاین روی شبیه‌ساز):"
echo "     bash scripts/selftest.sh"
echo "   اجرای واقعی روی ترب (نمونه):"
echo "     .venv/bin/abii torob scan --pack digital --max-shops 50"
