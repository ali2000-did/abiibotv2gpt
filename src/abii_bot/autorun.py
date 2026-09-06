"""اتوران — ربات روشن می‌ماند و خودش دور می‌زند؛ هیچ فرمانی لازم نیست.

جریان:
    set-product (یک بار) → ذخیره محصول/دوره در configs/autorun.yaml
    abii autorun          → حلقه بی‌نهایت: اسکن افزایشی → خروجی → خواب → تکرار
    systemd Restart=always → بعد از ری‌استارت سرور هم خودش بالا می‌آید

هر دور فقط فروشگاه‌های «جدید» را می‌گیرد (TTL) → بار سرور تقریباً ثابت و کم.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from .config import AppConfig
from .engine import run_torob_engine
from .models import utcnow

logger = logging.getLogger(__name__)

DEFAULT_SETTINGS_FILE = "configs/autorun.yaml"


def default_settings_path() -> Path:
    """مسیر تنظیمات اتوران: پوشه جاری ← ریشه ریپو."""
    for base in (Path.cwd(), Path(__file__).resolve().parents[2]):
        p = base / DEFAULT_SETTINGS_FILE
        if p.exists():
            return p
    return Path.cwd() / DEFAULT_SETTINGS_FILE


def parse_interval(text: str | int | float) -> int:
    """«24h» / «6h» / «30m» / «45s» / «86400» → ثانیه."""
    if isinstance(text, (int, float)):
        return int(text)
    s = str(text).strip().lower()
    mult = {"d": 86400, "h": 3600, "m": 60, "s": 1}
    if s and s[-1] in mult:
        return int(float(s[:-1]) * mult[s[-1]])
    return int(float(s))


@dataclass
class AutorunSettings:
    """تنظیمات دائمی اتوران — فایل YAML قابل ویرایش دستی."""

    queries: list[str] = field(default_factory=list)  # محصول(های) هدف
    every_seconds: int = 86400      # فاصله بین دورها (پیش‌فرض: روزانه)
    max_shops: int = 100            # سقف فروشگاه جدید در هر دور
    workers: int = 4
    min_delay: float = 1.2
    shop_ttl_hours: float = 168.0
    export_formats: list[str] = field(default_factory=lambda: ["csv", "xlsx"])
    api_base: Optional[str] = None  # فقط برای تست روی شبیه‌ساز
    updated_at: str = ""

    # ---------- serialization ----------
    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("api_base", None)  # تنظیم تستی ذخیره نشود
        return d

    def save(self, path: Path | None = None) -> Path:
        path = Path(path) if path else default_settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.updated_at = utcnow().isoformat()
        payload = {"تنظیمات اتوران — ویرایش دستی هم مجاز است": None, **self.to_dict()}
        payload.pop("تنظیمات اتوران — ویرایش دستی هم مجاز است")
        path.write_text(
            yaml.safe_dump(self.to_dict(), allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return path

    @classmethod
    def load(cls, path: Path | None = None) -> "AutorunSettings":
        path = Path(path) if path else default_settings_path()
        if not path.exists():
            raise FileNotFoundError(
                f"تنظیمات اتوران پیدا نشد ({path}). اول: abii set-product \"نام محصول\""
            )
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        queries = [str(q) for q in (data.get("queries") or []) if str(q).strip()]
        if not queries:
            raise ValueError(f"هیچ محصولی در {path} تنظیم نشده است")
        s = cls(
            queries=queries,
            every_seconds=int(parse_interval(data.get("every_seconds", 86400))),
            max_shops=int(data.get("max_shops", 100)),
            workers=int(data.get("workers", 4)),
            min_delay=float(data.get("min_delay", 1.2)),
            shop_ttl_hours=float(data.get("shop_ttl_hours", 168)),
            export_formats=list(data.get("export_formats", ["csv", "xlsx"])),
            api_base=data.get("api_base"),
            updated_at=str(data.get("updated_at", "")),
        )
        return s


def status_path(cfg: AppConfig) -> Path:
    return cfg.db_path.parent / "autorun_status.json"


def write_status(
    path: Path,
    *,
    cycle: int,
    started,
    outcome,
    error: Optional[str],
    next_run_iso: Optional[str],
) -> None:
    """فایل وضعیت — `abii status` از همین می‌خواند (آخرین دور، شمارنده‌ها، دور بعدی)."""
    data = {
        "cycle": cycle,
        "last_run_at": started.isoformat(),
        "finished_at": utcnow().isoformat(),
        "next_run_at": next_run_iso,
        "error": error,
    }
    if outcome is not None:
        m = outcome.metrics
        data.update(
            {
                "shops_found": m.shops_found,
                "shops_fetched": m.shops_fetched,
                "phones_found": m.phones_found,
                "sites_enriched": m.sites_enriched,
                "recovered_web": m.shops_recovered_web,
                "leads_new": m.leads_new,
                "leads_updated": m.leads_updated,
                "leads_duplicate": m.leads_duplicate,
                "duration_sec": m.duration_sec,
                "http": {
                    "requests": m.http.requests,
                    "blocked": m.http.blocked,
                    "errors": m.http.errors,
                },
                "exports": [str(p) for p in outcome.export_paths.values()],
            }
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def explain_plan(settings: "AutorunSettings", cfg: AppConfig) -> str:
    """نمایش مسیر دقیق اجرا «بدون هیچ درخواست شبکه» — برای اطمینان قبل از اجرا."""
    from urllib.parse import quote

    ep = cfg.endpoints
    lines = [
        "📍 مسیر اجرای ربات (بدون هیچ درخواست شبکه — فقط نقشه):",
        "",
        "فاز ۱ — کشف محصولات (API جستجوی ترب):",
    ]
    for q in settings.queries:
        lines.append(f"  ① GET {ep.torob_search.format(query=quote(q, safe=''), page=0)}")
    lines += [
        "     └ صفحه بعد: دنبال‌کردن فیلد next پاسخ (تا max_pages)",
        "",
        "فاز ۲ — نگاشت فروشنده‌ها (از جزئیات هر محصول):",
        f"  ② GET {ep.torob_detail.format(prk='PRK', search_id='SEARCH_ID')}",
        f"     fallback: {ep.torob_detail_v2.format(prk='PRK')}",
        f"     fallback: {ep.torob_offers.format(prk='PRK')}",
        "     └ PRK و SEARCH_ID از نتایج فاز ۱ (فیلد more_info_url)",
        "",
        "فاز ۳ — برداشت شماره هر فروشگاه (هر فروشگاه فقط یک بار):",
        f"  ③ GET {ep.torob_shop.format(shop_id='SHOP_ID')}",
        f"     fallback صفحه وب: {ep.torob_shop_web.format(shop_id='SHOP_ID')}",
        "  ④ GET سایت اختصاصی فروشنده (اگر داشته باشد) → شماره/ایمیل بیشتر",
        "",
        "فاز ۴ — پاکسازی → SQLite → اکسل/CSV در exports/",
        "",
        f"🔁 تکرار: هر {settings.every_seconds:,} ثانیه | سقف هر دور: {settings.max_shops} فروشگاه جدید",
        f"   اسکن افزایشی: فروشگاه دیده‌شده تا {settings.shop_ttl_hours} ساعت دوباره fetch نمی‌شود",
        f"   محترمانه: {settings.workers} worker، حداقل {settings.min_delay}s بین درخواست‌های هر هاست",
    ]
    return "\n".join(lines)


def run_forever(
    settings: AutorunSettings,
    cfg: AppConfig,
    once: bool = False,
    stop: threading.Event | None = None,
    settings_path: Path | None = None,
) -> int:
    """حلقه اصلی اتوران. خروجی: تعداد دورهای کامل‌شده.

    • هر دور: اسکن افزایشی (فروشگاه تازه دیده‌شده رد می‌شود)
    • خطای یک دور، دور بعدی را نمی‌کشد (بعد از حداکثر ۱۰ دقیقه دوباره)
    • خواب قطع‌شدنی: با SIGINT/SIGTERM بین دورها تمیز قطع می‌شود
    """
    stop = stop or threading.Event()
    st_path = status_path(cfg)
    # شماره دور بین اجراها ادامه پیدا کند (فایل وضعیت قبلی)
    cycle = 0
    try:
        cycle = int(json.loads(st_path.read_text(encoding="utf-8")).get("cycle", 0))
    except Exception:  # noqa: BLE001 — فایل نبود/خراب بود
        pass
    logger.info(
        "اتوران شروع شد | محصول: %s | هر %s ثانیه | سقف هر دور: %s فروشگاه",
        "، ".join(settings.queries), settings.every_seconds, settings.max_shops,
    )
    if settings_path:
        # تغییرات دستی فایل تنظیمات بین دورها دوباره خوانده می‌شود
        logger.info("تنظیمات: %s (بین دورها دوباره خوانده می‌شود)", settings_path)

    while not stop.is_set():
        cycle += 1
        started = utcnow()
        outcome = None
        error: Optional[str] = None
        try:
            outcome = run_torob_engine(
                settings.queries, cfg,
                workers=settings.workers, max_shops=settings.max_shops,
                min_delay=settings.min_delay, shop_ttl_hours=settings.shop_ttl_hours,
                api_base=settings.api_base,
            )
            m = outcome.metrics
            logger.info(
                "[autorun دور %s] new=%s fetched=%s phones=%s مدت=%ss",
                cycle, m.leads_new, m.shops_fetched, m.phones_found, m.duration_sec,
            )
            wait = settings.every_seconds
        except Exception as exc:  # noqa: BLE001 — یک دور خراب نباید اتوران را بکشد
            error = f"{type(exc).__name__}: {exc}"
            logger.critical("[autorun دور %s] خطا: %s → ۱۰ دقیقه دیگر تلاش مجدد", cycle, error)
            wait = min(settings.every_seconds, 600)

        next_run = None
        if not once and not stop.is_set():
            from datetime import timedelta

            next_run = (utcnow() + timedelta(seconds=wait)).isoformat()
        write_status(st_path, cycle=cycle, started=started, outcome=outcome,
                     error=error, next_run_iso=next_run)

        if once:
            break
        for _ in range(wait):
            if stop.is_set():
                break
            time.sleep(1)

        # بین دورها: تنظیمات را دوباره بخوان (اگر کاربر محصول را عوض کرد)
        if settings_path is not None and not stop.is_set():
            try:
                fresh = AutorunSettings.load(settings_path)
                fresh.api_base = settings.api_base  # تنظیم تستی حفظ شود
                settings = fresh
            except Exception:  # noqa: BLE001 — فایل موقتاً خراب بود؛ قبلی می‌ماند
                logger.warning("بازخوانی تنظیمات ناموفق بود؛ با قبلی ادامه می‌دهیم")

    logger.info("اتوران متوقف شد (بعد از %s دور)", cycle)
    return cycle
