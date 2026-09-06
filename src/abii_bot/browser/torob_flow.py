"""جریان مرورگریِ کاربرگونه ترب — دقیقاً همان رفتاری که کاربر خواست:

    وارد torob.com می‌شود → عبارت را مثل کاربر تایپ می‌کند → اینتر →
    روی محصولات نتایج یکی‌یکی کلیک می‌کند → در صفحه محصول لینک فروشنده را
    کلیک می‌کند → شماره سایت را کپی می‌کند (حتی اگر پشت دکمه
    «نمایش شماره» پنهان باشد) → سایت بعدی.

خروجی: Leadهای نرمال‌شده + optionally ویدیو/اسکرین‌شات جلسه.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.sync_api import Browser, BrowserContext, Page

from ..config import AppConfig
from ..extraction import extract_phones
from ..models import Lead, utcnow
from ..pipeline.cleaner import Deduper, normalize_lead
from ..storage import LeadStore, export_leads
from .human import collect_hrefs_any, first_visible, human_pause, human_scroll
from .selectors import load_selectors
from .setup import launch_chromium

logger = logging.getLogger(__name__)

_STEALTH_JS = """
// شبیه‌سازی مرورگر واقعی — حذف نشانه‌های اتوماسیون
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = window.chrome || { runtime: {} };
Object.defineProperty(navigator, 'languages', {get: () => ['fa-IR', 'fa', 'en']});
"""

_PRK_RE = re.compile(r"/p/([^/?#]+)")
_SHOP_RE = re.compile(r"/shop/([^/?#]+)")


@dataclass
class BrowserScanResult:
    platform: str
    query: str
    started_at: datetime
    duration_sec: float
    counts: dict = field(default_factory=dict)
    leads: list[Lead] = field(default_factory=list)
    export_paths: dict[str, Path] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)  # video / screenshots dir
    pages_visited: int = 0

    def summary(self) -> str:
        return (
            f"platform={self.platform} query='{self.query}' | "
            f"صفحات دیده‌شده: {self.pages_visited} | "
            f"new={self.counts.get('new', 0)} updated={self.counts.get('updated', 0)} "
            f"duplicate={self.counts.get('duplicate', 0)} | "
            f"لید با شماره: {sum(1 for l in self.leads if l.phones)}"
        )


class TorobUserFlow:
    """پیاده‌سازی جریان کاربر ترب با Playwright."""

    def __init__(
        self,
        cfg: AppConfig,
        selectors: Optional[dict] = None,
        headless: bool = True,
        min_delay: Optional[float] = None,
        max_shops_per_product: int = 1,
        artifacts_dir: Optional[Path] = None,
    ):
        self.cfg = cfg
        self.sel = selectors or load_selectors("torob")
        self.headless = headless
        self.min_delay = cfg.politeness.min_delay if min_delay is None else min_delay
        self.max_shops = max_shops_per_product
        self.shots = Path(artifacts_dir) if artifacts_dir else None
        self._shot_i = 0

    # ------------------------------------------------------------------ main
    def run(self, query: str, max_products: int) -> tuple[list[Lead], dict[str, str]]:
        from playwright.sync_api import sync_playwright

        artifacts: dict[str, str] = {}
        leads: list[Lead] = []
        with sync_playwright() as p:
            browser = launch_chromium(p, headless=self.headless)
            ctx_kw = dict(
                locale="fa-IR",
                timezone_id="Asia/Tehran",
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
            )
            if self.shots:
                ctx_kw["record_video_dir"] = str(self.shots)
                ctx_kw["record_video_size"] = {"width": 1280, "height": 800}
            context = browser.new_context(**ctx_kw)
            context.add_init_script(_STEALTH_JS)
            page = context.new_page()

            try:
                leads = self._session(page, context, query, max_products)
            finally:
                try:
                    context.close()  # ویدیو اینجا نهایی می‌شود
                except Exception:  # noqa: BLE001
                    pass
                if self.shots:
                    videos = sorted(self.shots.glob("*.webm"))
                    if videos:
                        artifacts["video"] = str(videos[-1])
                try:
                    browser.close()
                except Exception:  # noqa: BLE001
                    pass
        if self.shots:
            artifacts["screenshots"] = str(self.shots)
        return leads, artifacts

    # ------------------------------------------------------------------ flow
    def _session(self, page: Page, context: BrowserContext, query: str, max_products: int) -> list[Lead]:
        base = self.sel["base_url"].rstrip("/")
        leads: list[Lead] = []
        visited: set[str] = set()
        self._pages = 0

        # ۱) ورود به صفحه اصلی — مثل کاربر
        logger.info("[torob-flow] ورود به %s", base)
        page.goto(base, wait_until="domcontentloaded", timeout=45_000)
        human_pause(self.min_delay)
        self._snap(page, "01_home")

        # ۲) تایپ جستجو مثل انسان + اینتر
        inp = first_visible(page, self.sel["search"]["input"])
        if inp is None:
            raise RuntimeError("صفحه جستجوی ترب پیدا نشد — سلکتورها را در configs/selectors.torob.yaml به‌روز کنید")
        logger.info("[torob-flow] تایپ جستجو: %s", query)
        inp.click()
        for ch in query:
            page.keyboard.type(ch, delay=90)  # تایپ حرف‌به‌حرف انسانی
        human_pause(self.min_delay * 0.5)
        page.keyboard.press("Enter")
        page.wait_for_load_state("domcontentloaded")
        wait_sel = (self.sel["results"]["wait_for"] or ["a[href*='/p/']"])[0]
        try:
            page.wait_for_selector(wait_sel, timeout=20_000)
        except Exception:  # noqa: BLE001
            logger.warning("[torob-flow] نتیجه‌ای ظاهر نشد؛ ادامه با محتوای فعلی")
        human_pause(self.min_delay)
        human_scroll(page, times=2)
        self._snap(page, "02_search_results")

        # ۳) پیمایش محصولات: کلیک → استخراج → فروشنده → شماره → بازگشت → بعدی
        done = 0
        while done < max_products:
            link_sel = self.sel["results"]["product_link"]
            sels = link_sel if isinstance(link_sel, list) else [link_sel]
            hrefs = collect_hrefs_any(page, sels, base)
            nxt = next((h for h in hrefs if h not in visited), None)
            if nxt is None:
                logger.info("[torob-flow] دیگر محصول بازدیدنشده‌ای نیست")
                break
            visited.add(nxt)
            self._pages += 1

            # کلیک روی لینک محصول (نه goto — مثل کاربر)
            prk = self._prk_of(nxt) or str(done)
            self._click_href(page, context, nxt)
            human_pause(self.min_delay)
            self._snap(page, f"03_product_{done + 1}_{prk}")
            prod_lead = self._extract_product(page, nxt, prk)
            if prod_lead:
                leads.append(prod_lead)

            # فروشنده‌ها: کلیک روی لینک فروشگاه → شماره (حتی پشت دکمه)
            shop_hrefs = collect_hrefs_any(page, self.sel["product"]["shop_link"], base)[: self.max_shops]
            for surl in shop_hrefs:
                sid = self._shop_of(surl) or prk
                self._click_href(page, context, surl)
                human_pause(self.min_delay)
                shop_lead = self._extract_shop(page, surl, sid)
                self._snap(page, f"04_shop_{sid}")
                if shop_lead:
                    leads.append(shop_lead)
                page.go_back(wait_until="domcontentloaded")
                human_pause(self.min_delay * 0.6)
                self._pages += 1

            page.go_back(wait_until="domcontentloaded")
            human_pause(self.min_delay * 0.6)
            done += 1
            logger.info("[torob-flow] محصول %s/%s انجام شد", done, max_products)

        return leads

    # ------------------------------------------------------------------ extractors
    def _extract_product(self, page: Page, url: str, prk: str) -> Optional[Lead]:
        title_loc = first_visible(page, self.sel["product"]["title"], timeout_ms=1500)
        title = title_loc.inner_text() if title_loc else None
        price_loc = first_visible(page, self.sel["product"]["price"], timeout_ms=1000)
        price = price_loc.inner_text() if price_loc else None
        body = page.inner_text("body")
        phones = [h.number for h in extract_phones(body)]
        lead = Lead(
            source="torob", source_id=f"p:{prk}", url=url,
            title=title, price=price, description=None,
            phones=phones,
        )
        logger.info("[torob-flow] محصول: %s | شماره در صفحه محصول: %s", title, phones or "—")
        return normalize_lead(lead)

    def _extract_shop(self, page: Page, url: str, shop_id: str) -> Optional[Lead]:
        # کلیک روی «نمایش شماره» اگر دکمه وجود داشته باشد
        btn = first_visible(page, self.sel["shop"]["show_phone"], timeout_ms=1500)
        if btn:
            try:
                btn.click()
                human_pause(max(self.min_delay, 0.8))  # فرصت لود شماره
                logger.info("[torob-flow] دکمه «نمایش شماره» کلیک شد")
            except Exception as exc:  # noqa: BLE001
                logger.debug("show-phone click failed: %s", exc)

        title_loc = first_visible(page, self.sel["shop"]["title"], timeout_ms=1500)
        shop_name = title_loc.inner_text() if title_loc else None
        body = page.inner_text("body")
        phones = [h.number for h in extract_phones(body)]
        lead = Lead(
            source="torob", source_id=f"shop:{shop_id}", url=url,
            title=shop_name, seller_name=shop_name,
            phones=phones, description=None,
        )
        logger.info("[torob-flow] فروشگاه: %s | شماره: %s", shop_name, phones or "—")
        return normalize_lead(lead)

    # ------------------------------------------------------------------ helpers
    def _click_href(self, page: Page, context: BrowserContext, url: str) -> None:
        """کلیک روی لینک موجود در صفحه (مثل کاربر)؛ اگر تب جدید باز شد مدیریت می‌شود."""
        from urllib.parse import urlparse

        path = urlparse(url).path.rstrip("/")  # مثلاً /p/prk-1
        before = len(context.pages)
        try:
            loc = page.locator(f"a[href*='{path}']").first
            loc.scroll_into_view_if_needed(timeout=3000)
            loc.click(timeout=5000)
        except Exception:  # noqa: BLE001
            logger.debug("click fallback to goto: %s", url)
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            return
        page.wait_for_load_state("domcontentloaded")
        # اگر تب جدیدی باز شده بود، مسیر را در همان ادامه می‌دهیم (صفحه اصلی دست‌نخورده)
        if len(context.pages) > before:
            popup = context.pages[-1]
            popup.wait_for_load_state("domcontentloaded")
            # محتوای popup را با یک goto همان URL روی صفحه اصلی پردازش می‌کنیم و popup را می‌بندیم
            popup.close()
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)

    @staticmethod
    def _prk_of(url: str) -> Optional[str]:
        m = _PRK_RE.search(url)
        return m.group(1) if m else None

    @staticmethod
    def _shop_of(url: str) -> Optional[str]:
        m = _SHOP_RE.search(url)
        return m.group(1) if m else None

    def _snap(self, page: Page, name: str) -> None:
        if not self.shots:
            return
        try:
            page.screenshot(path=str(self.shots / f"{name}.png"), full_page=False)
        except Exception as exc:  # noqa: BLE001
            logger.debug("screenshot %s failed: %s", name, exc)


# ------------------------------------------------------------------ orchestration
def run_torob_browser(
    query: str,
    cfg: AppConfig,
    max_products: int = 5,
    headless: bool = True,
    min_delay: Optional[float] = None,
    max_shops_per_product: int = 1,
    record: bool = False,
    base_url: Optional[str] = None,
    selectors_file: Optional[Path] = None,
    store: Optional[LeadStore] = None,
) -> BrowserScanResult:
    """اجرای کامل جریان مرورگری + اتصال به پایپ‌لاین (dedupe/store/export)."""
    started = utcnow()
    t0 = time.monotonic()
    store = store or LeadStore(cfg.db_path)
    selectors = load_selectors("torob", selectors_file)
    if base_url:
        selectors["base_url"] = base_url.rstrip("/")

    session_dir: Optional[Path] = None
    if record:
        session_dir = cfg.export_dir.parent / "sessions" / started.strftime("%Y%m%d_%H%M%S")
        session_dir.mkdir(parents=True, exist_ok=True)

    flow = TorobUserFlow(
        cfg, selectors=selectors, headless=headless, min_delay=min_delay,
        max_shops_per_product=max_shops_per_product, artifacts_dir=session_dir,
    )
    leads, artifacts = flow.run(query, max_products)

    deduper = Deduper(store)
    counts = {"new": 0, "updated": 0, "duplicate": 0}
    for lead in leads:
        lead.status = deduper.classify(lead)
        store.upsert(lead)
        counts[lead.status] = counts.get(lead.status, 0) + 1

    export_paths: dict[str, Path] = {}
    if leads:
        export_paths = export_leads(
            leads, out_dir=cfg.export_dir, formats=cfg.export_formats,
            name_prefix=f"leads_torob_browser_{started.strftime('%Y%m%d_%H%M%S')}",
        )

    result = BrowserScanResult(
        platform="torob", query=query, started_at=started,
        duration_sec=round(time.monotonic() - t0, 1),
        counts=counts, leads=leads, export_paths=export_paths, artifacts=artifacts,
        pages_visited=getattr(flow, "_pages", 0),
    )
    logger.info("browser scan finished: %s", result.summary())
    return result
