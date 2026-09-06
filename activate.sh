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
DASH_SERVICE="abii-dashboard"
DASH_UNIT="/etc/systemd/system/${DASH_SERVICE}.service"
USER_DASH_UNIT="$HOME/.config/systemd/user/${DASH_SERVICE}.service"
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
  # ─── داشبورد ───
  local ip tok dash_up=""
  systemctl is-active --quiet "$DASH_SERVICE" 2>/dev/null && dash_up=1
  systemctl --user is-active --quiet "$DASH_SERVICE" 2>/dev/null && dash_up=1
  if [ -f "$LOG_DIR/dashboard.pid" ] && kill -0 "$(cat "$LOG_DIR/dashboard.pid")" 2>/dev/null; then dash_up=1; fi
  ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  tok="$(cat data/.dashboard_token 2>/dev/null || true)"
  echo
  if [ -n "$dash_up" ]; then
    echo "🖥  داشبورد زنده: http://${ip:-<آی‌پی-سرور>}:8501/?t=${tok:-<توکن>}"
  else
    echo "🖥  داشبورد خاموش است — روشن‌کردن: .venv/bin/abii dashboard"
  fi
}

# ═────────────────────────── توقف ═──────────────────────────
do_off() {
  box "توقف AbiiBot"
  if systemd_running && systemctl cat "$SERVICE" >/dev/null 2>&1; then
    sudo systemctl disable --now "$SERVICE" "$DASH_SERVICE" 2>/dev/null || true
    sudo rm -f "$UNIT" "$DASH_UNIT"; sudo systemctl daemon-reload
    ok "سرویس سیستمی حذف شد"
  elif [ -d "$HOME/.config/systemd/user" ] && systemctl --user cat "$SERVICE" >/dev/null 2>&1; then
    systemctl --user disable --now "$SERVICE" "$DASH_SERVICE" 2>/dev/null || true
    rm -f "$USER_UNIT" "$USER_DASH_UNIT"; systemctl --user daemon-reload
    ok "سرویس کاربر حذف شد"
  fi
  for pf in "$PID_FILE" "$LOG_DIR/dashboard.pid"; do
    if [ -f "$pf" ]; then
      kill "$(cat "$pf")" 2>/dev/null && ok "فرایند پس‌زمینه متوقف شد ($pf)" || true
      rm -f "$pf"
    fi
  done
  if have crontab && crontab -l 2>/dev/null | grep -q "$CRON_TAG"; then
    crontab -l | grep -v "$CRON_TAG" | crontab - && ok " cron پاک شد"
  fi
  ok "ربات متوقف شد (داده‌ها در data/ و exports/ دست‌نخورده‌اند)"
}

# ═────────────────────────── کمکی‌ها ═──────────────────────────
systemd_running() {  # systemd واقعی = فرایند ۱ سیستم
  [ "$(ps -p 1 -o comm= 2>/dev/null)" = "systemd" ]
}

render_unit() {  # $1=مسیر  $2=نام سرویس  $3=ExecStart  $4=توضیح — همه خودکار
  cat > "$1" <<EOF
# توسط activate.sh ساخته شد — نیازی به ویرایش دستی نیست
[Unit]
Description=AbiiBot $4
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$(id -un)
WorkingDirectory=$REPO
ExecStart=$3
Restart=always
RestartSec=30
KillSignal=SIGINT
TimeoutStopSec=120

[Install]
WantedBy=multi-user.target
EOF
}

install_system_service() {  # با sudo (یک بار رمز می‌پرسد) — موفقیت را برمی‌گرداند
  local tmp1 tmp2
  tmp1="$(mktemp)"; tmp2="$(mktemp)"
  render_unit "$tmp1" "$SERVICE" "$REPO/.venv/bin/abii autorun" "اتوران — اسکن خودکار ترب"
  render_unit "$tmp2" "$DASH_SERVICE" "$REPO/.venv/bin/abii dashboard" "داشبورد زنده"
  if [ "$(id -u)" -eq 0 ]; then
    cp "$tmp1" "$UNIT" && cp "$tmp2" "$DASH_UNIT" \
      && systemctl daemon-reload >/dev/null 2>&1 \
      && systemctl enable --now "$SERVICE" "$DASH_SERVICE" >/dev/null 2>&1
  else
    sudo -n true 2>/dev/null || { echo "  ${Y}برای نصب سرویس دائمی، رمز sudo لازم است (فقط همین یک بار):${N}"; sudo -v || return 1; }
    sudo cp "$tmp1" "$UNIT" && sudo cp "$tmp2" "$DASH_UNIT" \
      && sudo systemctl daemon-reload && sudo systemctl enable --now "$SERVICE" "$DASH_SERVICE"
  fi
  rm -f "$tmp1" "$tmp2"
  systemctl is-active --quiet "$SERVICE" 2>/dev/null || {  # نصب موفق نبود → پاکسازی
    sudo systemctl disable --now "$SERVICE" "$DASH_SERVICE" >/dev/null 2>&1 || true
    sudo rm -f "$UNIT" "$DASH_UNIT"; sudo systemctl daemon-reload >/dev/null 2>&1 || true
    return 1
  }
  ok "سرویس دائمی systemd نصب و شروع شد (بعد از ری‌استارت سرور هم خودش بالا می‌آید)"
  systemctl is-active --quiet "$DASH_SERVICE" 2>/dev/null \
    && ok "داشبورد زنده هم فعال شد (پورت 8501)" \
    || warn "داشبورد بالا نیامد — بعداً: .venv/bin/abii dashboard"
}

install_user_service() {
  mkdir -p "$HOME/.config/systemd/user"
  render_unit "$USER_UNIT" "$SERVICE" "$REPO/.venv/bin/abii autorun" "اتوران — اسکن خودکار ترب"
  render_unit "$USER_DASH_UNIT" "$DASH_SERVICE" "$REPO/.venv/bin/abii dashboard" "داشبورد زنده"
  systemctl --user daemon-reload
  systemctl --user enable --now "$SERVICE" "$DASH_SERVICE"
  systemctl --user is-active --quiet "$SERVICE" 2>/dev/null || return 1
  ok "سرویس کاربر systemd نصب شد"
  systemctl --user is-active --quiet "$DASH_SERVICE" 2>/dev/null && ok "داشبورد زنده هم فعال شد (پورت 8501)"
  sudo -n loginctl enable-linger "$(id -un)" 2>/dev/null \
    && ok "linger فعال شد (پس از خروج از SSH هم روشن می‌ماند)" \
    || warn "بدون linger، بعد از خروج از سرور سرویس می‌ایستد — با sudo فعال کنید: sudo loginctl enable-linger $(id -un)"
}

install_cron() {
  local line="@reboot cd $REPO && nohup .venv/bin/abii autorun >> $LOG_FILE 2>&1 & $CRON_TAG"
  local dline="@reboot cd $REPO && nohup .venv/bin/abii dashboard >> $LOG_DIR/dashboard.log 2>&1 & $CRON_TAG"
  (crontab -l 2>/dev/null | grep -v "$CRON_TAG"; echo "$line"; echo "$dline") | crontab -
  start_nohup
  start_bg ".venv/bin/abii dashboard" "$LOG_DIR/dashboard.pid" "$LOG_DIR/dashboard.log"
  ok "cron @reboot نصب شد + همین حالا شروع شد"
}

start_nohup() { start_bg ".venv/bin/abii autorun" "$PID_FILE" "$LOG_FILE"; }

start_bg() {  # $1=فرمان  $2=pidfile  $3=logfile — idempotent
  mkdir -p "$LOG_DIR"
  if [ -f "$2" ] && kill -0 "$(cat "$2")" 2>/dev/null; then
    ok "از قبل روشن است (PID $(cat "$2"))"; return
  fi
  nohup $1 >> "$3" 2>&1 &
  echo $! > "$2"
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
    start_bg ".venv/bin/abii dashboard" "$LOG_DIR/dashboard.pid" "$LOG_DIR/dashboard.log" \
      && ok "داشبورد زنده در پس‌زمینه روشن شد (پورت 8501)"
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
  local ip tok
  ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  tok="$(cat data/.dashboard_token 2>/dev/null || true)"
  [ -n "$tok" ] || { sleep 1.5; tok="$(cat data/.dashboard_token 2>/dev/null || true)"; }
  cat <<EOF
  🖥 داشبورد زنده:   http://${ip:-<آی‌پی-سرور>}:8501/?t=${tok:-<توکن-پس-از-چند-ثانیه>}
     (اگر از بیرون باز نمی‌شود: sudo ufw allow 8501)
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
