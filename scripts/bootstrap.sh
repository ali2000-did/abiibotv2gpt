#!/usr/bin/env bash
# بازسازی سریع محیط توسعه (در سندباکس/سرور): venv + نصب پکیج + کرومیوم
# استفاده: bash scripts/bootstrap.sh
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -x ".venv/bin/python" ]; then
  echo "▶ ساخت venv…"
  python3 -m venv .venv
fi
echo "▶ نصب پکیج‌ها…"
.venv/bin/pip install -q -e ".[browser,dev]"
echo "▶ آماده‌سازی مرورگر (در صورت نیاز)…"
bash scripts/setup_browser.sh .venv
echo "▶ راستی‌آزمایی…"
.venv/bin/abii version
echo "✅ محیط آماده است: .venv/bin/abii --help"
