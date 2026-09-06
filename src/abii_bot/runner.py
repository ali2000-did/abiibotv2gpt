"""ارکستراتور اصلی — اتصال همه مراحل: discover → fetch → parse → clean → dedupe → store → export.

این همان «Crawler Engine» از دیاگرام معماری است که یک ScanSpec می‌گیرد و
ScanReport برمی‌گرداند.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import AppConfig
from .crawler.base import Fetcher
from .local import LocalFixtureFetcher
from .models import Lead, utcnow
from .pipeline.cleaner import Deduper, commit_lead, normalize_lead
from .pipeline.quality import dataset_report
from .platforms import ScanSpec, build_adapter
from .storage import LeadStore, export_leads

logger = logging.getLogger(__name__)


@dataclass
class ScanReport:
    spec: ScanSpec
    started_at: datetime
    duration_sec: float
    counts: dict
    leads: list[Lead] = field(default_factory=list)
    export_paths: dict[str, Path] = field(default_factory=dict)
    quality: dict = field(default_factory=dict)

    def summary(self) -> str:
        q = self.quality
        return (
            f"platform={self.spec.platform} | "
            f"new={self.counts.get('new', 0)} updated={self.counts.get('updated', 0)} "
            f"duplicate={self.counts.get('duplicate', 0)} errors={self.counts.get('errors', 0)} | "
            f"با شماره تماس: {q.get('with_phone_pct', 0)}% | "
            f"میانگین کیفیت: {q.get('avg_quality', 0)}/100"
        )


def run_scan(
    spec: ScanSpec,
    cfg: AppConfig,
    fetcher: Optional[Fetcher] = None,
    store: Optional[LeadStore] = None,
) -> ScanReport:
    """اجرای کامل یک اسکن. fetcher/store قابل تزریق برای تست/دمو."""
    started = utcnow()
    t0 = time.monotonic()
    fetcher = fetcher or _default_fetcher(cfg)
    store = store or LeadStore(cfg.db_path)
    adapter = build_adapter(spec.platform, fetcher, cfg)
    deduper = Deduper(store)

    counts = {"new": 0, "updated": 0, "duplicate": 0, "errors": 0}
    leads: list[Lead] = []

    logger.info("scan started: %s", spec.describe())
    try:
        for i, ref in enumerate(adapter.discover(spec)):
            if spec.max_items is not None and i >= spec.max_items:
                logger.info("max_items=%s reached — stopping discovery", spec.max_items)
                break
            try:
                payload = adapter.fetch_detail(ref)
                lead = normalize_lead(adapter.parse_detail(payload, ref))
                commit_lead(lead, store, deduper)
                counts[lead.status] = counts.get(lead.status, 0) + 1
                leads.append(lead)
                logger.info("[%s/%s] %s", i + 1, spec.max_items or "∞", lead)
            except Exception as exc:  # noqa: BLE001 — خطای یک آگهی نباید کل اسکن را بکشد
                counts["errors"] += 1
                logger.error("failed on %s: %s", ref.url, exc)
    except Exception as exc:  # noqa: BLE001
        counts["errors"] += 1
        logger.critical("discovery failed: %s", exc)

    duration = time.monotonic() - t0
    paths: dict[str, Path] = {}
    if leads:
        paths = export_leads(
            leads,
            out_dir=cfg.export_dir,
            formats=cfg.export_formats,
            name_prefix=f"leads_{spec.platform}_{started.strftime('%Y%m%d_%H%M%S')}",
        )

    report = ScanReport(
        spec=spec, started_at=started, duration_sec=round(duration, 1),
        counts=counts, leads=leads, export_paths=paths,
        quality=dataset_report(leads),
    )
    store.record_run(
        {"platform": spec.platform, "city": spec.city, "category": spec.category,
         "query": spec.query, "max_items": spec.max_items},
        counts, started,
    )
    logger.info("scan finished in %.1fs — %s", duration, report.summary())
    return report


def _default_fetcher(cfg: AppConfig) -> Fetcher:
    from .crawler.http_client import HttpFetcher

    return HttpFetcher(cfg)


# ---------------------------------------------------------------- demo (آفلاین)
DEMO_FIXTURES = {
    # نگاشت‌های اختصاصی (token دقیق) قبل از نگاشت عمومی بررسی می‌شوند
    "web/post/wZJmF8xu": "divar_detail.json",
    "web/post/gQ7kL2pA": "divar_detail_2.json",
    "web/post/mNb3vRt9": "divar_detail_3.json",
    "post2/w/": "divar_search.json",        # جستجوی دیوار
    "web/post/": "divar_detail.json",       # جزئیات آگهی دیوار (پیش‌فرض)
    "base-product/search": "torob_search.json",
    "detail-v2": "torob_detail.json",
    "example-seller": "web_sample.html",
}


def run_demo(cfg: Optional[AppConfig] = None) -> list[ScanReport]:
    """اجرای کامل pipeline روی فیکسچرهای محلی — بدون هیچ دسترسی شبکه."""
    cfg = cfg or AppConfig()
    fixtures = Path(__file__).parent.parent.parent / "examples" / "fixtures"
    fetcher = LocalFixtureFetcher(fixtures, DEMO_FIXTURES)

    reports = [
        run_scan(
            ScanSpec("divar", city="tehran", category="buy-apartment", max_pages=1),
            cfg, fetcher=fetcher,
        ),
        run_scan(
            ScanSpec("torob", query="لپتاپ", max_pages=1),
            cfg, fetcher=fetcher,
        ),
        run_scan(
            ScanSpec("web", urls=["https://example-seller.ir/contact"]),
            cfg, fetcher=fetcher,
        ),
    ]
    return reports
