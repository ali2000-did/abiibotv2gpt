#!/usr/bin/env bash
# ═══ تست خودکار سلامت روی سرور شما — بدون اینترنت (روی شبیه‌ساز محلی) ═══
#   bash scripts/selftest.sh
# اگر همه مراحل سبز بود، ربات روی سیستم شما سالم است و می‌توانید سراغ ترب واقعی بروید.
set -euo pipefail
cd "$(dirname "$0")/.."
ABII=".venv/bin/abii"
PY=".venv/bin/python"

echo "▶ ۱/۳ تست واحد (پارسر شماره، پاکسازی، دیتابیس)…"
$PY -m pytest tests/test_phone.py tests/test_pipeline.py -q 2>/dev/null | tail -1 || {
  $PY -m pip install -q pytest; $PY -m pytest tests/test_phone.py tests/test_pipeline.py -q | tail -1; }

echo "▶ ۲/۳ اجرای کامل موتور روی شبیه‌ساز ترب…"
PORT=8941
$PY examples/mock_sites/mock_torob.py $PORT >/tmp/mock_torob.log 2>&1 &
MOCK_PID=$!
trap 'kill $MOCK_PID 2>/dev/null || true' EXIT
sleep 1

rm -rf /tmp/abii_selftest_data /tmp/abii_selftest_out
# دیتابیس ایزوله — تا اسکن افزایشی رکوردهای قبلی سیستم را رد نکند
cat > /tmp/abii_selftest_config.yaml <<YAML
db_path: /tmp/abii_selftest_data/leads.db
export_dir: /tmp/abii_selftest_out
workers: 4
politeness:
  min_delay: 0.02
YAML
$ABII torob scan --config /tmp/abii_selftest_config.yaml \
    --base-url http://127.0.0.1:$PORT \
    --query "لپ تاپ" --max-shops 30 --min-delay 0.02 \
    --out /tmp/abii_selftest_out 2>/dev/null | grep -E "فروشگاه یکتا|شماره پیدا|غنی|مدت" || {
  echo "✗ اسکن شکست خورد — لاگ ماک: /tmp/mock_torob.log"; exit 1; }

echo "▶ ۳/۳ بررسی خروجی…"
CSV=$(ls /tmp/abii_selftest_out/*.csv | head -1)
LINES=$(wc -l < "$CSV")
echo "  خروجی: $CSV ($LINES ردیف)"
[ "$LINES" -ge 10 ] || { echo "✗ خروجی خیلی کم است"; exit 1; }

echo
echo "✅ سلامت کامل تأیید شد — ربات آماده اجرای واقعی است:"
echo "     .venv/bin/abii torob scan --pack digital --max-shops 50"
