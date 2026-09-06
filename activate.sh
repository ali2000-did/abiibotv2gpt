#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
#  AbiiBot — فعال‌ساز خودکار (یک کلیک)
#  bash activate.sh            → نصب + تست + سرویس دائمی + شروع فوری
#  bash activate.sh --status   → وضعیت ربات
#  bash activate.sh --once     → فقط یک دور اجرا (بدون نصب سرویس)
#  bash activate.sh --off      → توقف و حذف سرویس
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail
REPO="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO"

SERVICE="abii-autorun"
UNIT="/etc/systemd/system/${SERVICE}.service"
USER_UNIT="$HOME/.config/systemd/user/${SERVICE}.service"
LOG_DIR="$REPO/logs"; LOG_FILE="$LOG_DIR/autorun.log"
PID_FILE="$LOG_DIR/autorun.pid"
CRON_TAG="#_abii_autorun"

# ─── رنگ و پیام ───
if [ -t 1 ]; then
  B='\033[1m'; G='\033[32m'; R='\033[31m'; Y='\033[33m'; C='\033[36m'; N='\033[0m'
else
  B=''; G=''; R=''; Y=''; C=''; N=''
fi
step() { printf "\n${C}▶ %s${N}\n" "$1"; }
ok()   { printf "  ${G}✓ %s${N}\n" "$1"; }
warn() { printf "  ${Y}⚠ %s${N}\n" "$1"; }
die()  { printf "  ${R}✗ %s${N}\n" "$1"; exit 1; }
box()  { printf "\n${B}═══ %s ═══${N}\n" "$1"; }

have() { command -v "$1" >/dev/null 2>&1; }

# ═────────────────────────── وضعیت ═──────────────────────────
do_status() {
  box "وضعیت AbiiBot"
  if systemd_running && systemctl cat "$SERVICE" >/dev/null 2>&1; then
    systemctl status "$SERVICE" --no-pager -n 5 || true
  elif [ -d "$HOME/.config/systemd/user" ] && systemctl --user cat "$SERVICE" >/dev/null 2>&1; then
    systemctl --user status "$SERVICE" --no-pager -n 5 || true
  elif [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "حالت پس‌زمینه (nohup): فعال — PID $(cat "$PID_FILE")"
    tail -n 5 "$LOG_FILE" 2>/dev/null || true
  else
    echo "ربات فعال نیست — با «bash activate.sh» فعالش کنید."
  fi
  echo
  if [ -x ".venv/bin/abii" ]; then
    .venv/bin/abii status 2>/dev/null || true
  fi
}

# ═────────────────────────── توقف ═──────────────────────────
do_off() {
  box "توقف AbiiBot"
  if systemd_running && systemctl cat "$SERVICE" >/dev/null 2>&1; then
    sudo systemctl disable --now "$SERVICE" 2>/dev/null || true
    sudo rm -f "$UNIT"; sudo systemctl daemon-reload
    ok "سرویس سیستمی حذف شد"
  elif [ -d "$HOME/.config/systemd/user" ] && systemctl --user cat "$SERVICE" >/dev/null 2>&1; then
    systemctl --user disable --now "$SERVICE" 2>/dev/null || true
    rm -f "$USER_UNIT"; systemctl --user daemon-reload
    ok "سرویس کاربر حذف شد"
  fi
  if [ -f "$PID_FILE" ]; then
    kill "$(cat "$PID_FILE")" 2>/dev/null && ok "فرایند پس‌زمینه متوقف شد" || true
    rm -f "$PID_FILE"
  fi
  if have crontab && crontab -l 2>/dev/null | grep -q "$CRON_TAG"; then
    crontab -l | grep -v "$CRON_TAG" | crontab - && ok " cron پاک شد"
  fi
  ok "ربات متوقف شد (داده‌ها در data/ و exports/ دست‌نخورده‌اند)"
}

# ═────────────────────────── کمکی‌ها ═──────────────────────────
systemd_running() {  # systemd واقعی = فرایند ۱ سیستم
  [ "$(ps -p 1 -o comm= 2>/dev/null)" = "systemd" ]
}

render_unit() {  # $1=مسیر خروجی — User/مسیرها خودکار تشخیص داده می‌شوند
  cat > "$1" <<EOF
# توسط activate.sh ساخته شد — نیازی به ویرایش دستی نیست
[Unit]
Description=AbiiBot اتوران — اسکن خودکار ترب
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$(id -un)
WorkingDirectory=$REPO
ExecStart=$REPO/.venv/bin/abii autorun
Restart=always
RestartSec=30
KillSignal=SIGINT
TimeoutStopSec=120

[Install]
WantedBy=multi-user.target
EOF
}

install_system_service() {  # با sudo (یک بار رمز می‌پرسد) — موفقیت را برمی‌گرداند
  local tmp; tmp="$(mktemp)"
  render_unit "$tmp"
  if [ "$(id -u)" -eq 0 ]; then
    cp "$tmp" "$UNIT" && systemctl daemon-reload >/dev/null 2>&1 && systemctl enable --now "$SERVICE" >/dev/null 2>&1
  else
    sudo -n true 2>/dev/null || { echo "  ${Y}برای نصب سرویس دائمی، رمز sudo لازم است (فقط همین یک بار):${N}"; sudo -v || return 1; }
    sudo cp "$tmp" "$UNIT" && sudo systemctl daemon-reload && sudo systemctl enable --now "$SERVICE"
  fi
  rm -f "$tmp"
  systemctl is-active --quiet "$SERVICE" 2>/dev/null || {  # نصب موفق نبود → پاکسازی
    sudo systemctl disable --now "$SERVICE" >/dev/null 2>&1 || true
    sudo rm -f "$UNIT"; sudo systemctl daemon-reload >/dev/null 2>&1 || true
    return 1
  }
  ok "سرویس دائمی systemd نصب و شروع شد (بعد از ری‌استارت سرور هم خودش بالا می‌آید)"
}

install_user_service() {
  mkdir -p "$HOME/.config/systemd/user"
  render_unit "$USER_UNIT"
  systemctl --user daemon-reload
  systemctl --user enable --now "$SERVICE"
  systemctl --user is-active --quiet "$SERVICE" 2>/dev/null || return 1
  ok "سرویس کاربر systemd نصب شد"
  sudo -n loginctl enable-linger "$(id -un)" 2>/dev/null \
    && ok "linger فعال شد (پس از خروج از SSH هم روشن می‌ماند)" \
    || warn "بدون linger، بعد از خروج از سرور سرویس می‌ایستد — با sudo فعال کنید: sudo loginctl enable-linger $(id -un)"
}

install_cron() {
  local line="@reboot cd $REPO && nohup .venv/bin/abii autorun >> $LOG_FILE 2>&1 & $CRON_TAG"
  (crontab -l 2>/dev/null | grep -v "$CRON_TAG"; echo "$line") | crontab -
  start_nohup
  ok "cron @reboot نصب شد + همین حالا شروع شد"
}

start_nohup() {
  mkdir -p "$LOG_DIR"
  if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    ok "از قبل روشن است (PID $(cat "$PID_FILE"))"; return
  fi
  nohup .venv/bin/abii autorun >> "$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"
}

wait_first_cycle() {  # شواهد شروع اولین دور را با مهلت بررسی می‌کند
  local deadline=$(( $(date +%s) + 90 ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    if journalctl -u "$SERVICE" -n 20 --no-pager 2>/dev/null | grep -q "اتوران شروع شد"; then return 0; fi
    if [ -s "$LOG_FILE" ] && grep -q "اتوران شروع شد" "$LOG_FILE" 2>/dev/null; then return 0; fi
    sleep 3
  done
  return 1
}

# ═────────────────────────── فعال‌سازی کامل ═──────────────────────────
do_activate() {
  printf "${B}"
  echo "╔══════════════════════════════════════════════╗"
  echo "║   AbiiBot — فعال‌ساز خودکار (یک کلیک)        ║"
  echo "║   نصب ← تست ← سرویس دائمی ← شروع فوری       ║"
  echo "╚══════════════════════════════════════════════╝"
  printf "${N}"

  # ─── ۱/۴ نصب ───
  step "۱/۴ بررسی/نصب برنامه…"
  if [ -x ".venv/bin/abii" ] && .venv/bin/abii version >/dev/null 2>&1; then
    ok "از قبل نصب است ($(.venv/bin/abii version 2>/dev/null | head -1))"
  else
    bash scripts/install.sh || die "نصب ناموفق — اینترنت/پایتون ۳.۱۰+ را چک کنید"
    ok "نصب کامل شد"
  fi

  # ─── ۲/۴ تست سلامت (آفلاین، روی شبیه‌ساز) ───
  step "۲/۴ تست سلامت (آفلاین — بدون اینترنت)…"
  if bash scripts/selftest.sh >/tmp/abii_selftest_run.log 2>&1; then
    ok "همه تست‌ها سبز شدند"
  else
    tail -20 /tmp/abii_selftest_run.log
    die "تست سلامت رد شد — لاگ: /tmp/abii_selftest_run.log"
  fi

  # ─── ۳/۴ سرویس دائمی ───
  step "۳/۴ نصب سرویس دائمی…"
  MODE=""
  if systemd_running; then
    if [ "$(id -u)" -eq 0 ] || sudo -n true 2>/dev/null || { [ -t 0 ] && sudo -v >/dev/null 2>&1; }; then
      install_system_service && MODE="system" || warn "سرویس سیستمی بالا نیامد → روش بعدی"
    fi
    if [ -z "$MODE" ] && systemctl --user is-system-running >/dev/null 2>&1; then
      install_user_service && MODE="user" || warn "سرویس کاربر بالا نیامد → روش بعدی"
    fi
  else
    warn "systemd روی این سیستم فعال نیست → روش بعدی"
  fi
  if [ -z "$MODE" ] && have crontab; then
    warn "استفاده از cron @reboot"
    install_cron && MODE="cron"
  fi
  if [ -z "$MODE" ]; then
    warn "نه systemd نه cron — فقط اجرای پس‌زمینه (بدون روشن‌ماندن بعد از ری‌بوت)"
    start_nohup; MODE="nohup"
  fi

  # ─── ۴/۴ راستی‌آزمایی دقیق ───
  step "۴/۴ راستی‌آزمایی — آیا واقعاً شروع به کار کرد؟"
  if [ "$MODE" = "system" ]; then
    systemctl is-active --quiet "$SERVICE" && ok "سرویس فعال (running)" || die "سرویس فعال نشد: journalctl -u $SERVICE -n 30"
  elif [ "$MODE" = "user" ]; then
    systemctl --user is-active --quiet "$SERVICE" && ok "سرویس کاربر فعال (running)" || die "سرویس کاربر فعال نشد"
  else
    [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null && ok "فرایند پس‌زمینه زنده است (PID $(cat "$PID_FILE"))" || die "فرایند پس‌زمینه زنده نیست — $LOG_FILE را ببینید"
  fi

  printf "  شروع اولین دور اسکن… "
  if wait_first_cycle; then
    ok "چرخه اسکن آغاز شد"
  else
    warn "۹۰ ثانیه صبر شد و لاگِ شروع نیامد — لاگ را ببینید (شبکه کند ممکن است)"
  fi

  # ─── گزارش نهایی ───
  box "✅ ربات فعال شد و کار می‌کند"
  cat <<EOF
  محصول فعلی:      configs/autorun.yaml  (تغییر: abii set-product "کالای شما")
  خروجی اکسل:      $REPO/exports/
  دیتابیس:         $REPO/data/leads.db
  وضعیت لحظه‌ای:    bash activate.sh --status   (یا: abii status)
  توقف:            bash activate.sh --off
  لاگ زنده:         journalctl -u $SERVICE -f   ${Y}← یا tail -f $LOG_FILE${N}
EOF
}

# ═────────────────────────── ورودی ═──────────────────────────
case "${1:-}" in
  --status) do_status ;;
  --off)    do_off ;;
  --once)
    [ -x ".venv/bin/abii" ] || bash scripts/install.sh
    exec .venv/bin/abii autorun --once ;;
  --help|-h|"")
    [ -z "${1:-}" ] && do_activate && exit 0
    echo "استفاده: bash activate.sh [--status|--once|--off]" ;;
  *) echo "گزینه ناشناخته: $1 — استفاده: bash activate.sh [--status|--once|--off]"; exit 2 ;;
esac
