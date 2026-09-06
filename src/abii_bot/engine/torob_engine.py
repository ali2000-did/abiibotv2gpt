"""موتور ناهمگامِ فروشگاه‌محور ترب — پرفورمنس بالا با احترام به سرور.

معماری (۳ فاز):
  فاز ۱ — کشف:       کوئری‌ها → صفحه‌بندی جستجو → فهرست prk محصولات
  فاز ۲ — نگاشت:     هر محصول → شناسه فروشگاه‌هایش (detail + offers)
  فاز ۳ — برداشت:    هر فروشگاه فقط یک بار fetch → نام/شماره/شهر → Lead

کلید پرفورمنس: فروشگاه‌ها بین محصولات مشترک‌اند؛ dedupe قبل از fetch یعنی
هیچ فروشگاهی دو بار دانلود نمی‌شود. اسکن افزایشی: فروشگاه تازه‌ی دید‌شده
(shop_ttl_hours) رد می‌شود → اجرای مجدد فقط داده جدید می‌آورد.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import quote, urlsplit, urlunsplit

from ..config import AppConfig
from ..extraction import extract_phones
from ..models import Lead, utcnow
from ..pipeline.cleaner import Deduper, commit_lead, normalize_lead
from ..pipeline.quality import quality_score
from ..platforms.base import dig, json_text, walk_phone_values
from ..storage import LeadStore, export_leads
from .http_async import AsyncPoliteClient, BlockedError, HttpMetrics

logger = logging.getLogger(__name__)

# کلیدهایی که «شناسه فروشگاه» در آن‌ها قرار می‌گیرد
_SHOP_ID_KEYS = {"shop_id", "shopid", "seller_id", "store_id"}
_SHOP_NAME_KEYS = {"shop_name", "seller_name", "store_name", "name", "title"}
_CITY_KEYS = {"city", "city_name", "province", "town"}
_SITE_KEYS = {"site", "website", "site_url", "shop_url", "web_site", "url"}


# --------------------------------------------------------------------- helpers
def walk_shop_ids(node) -> dict[str, Optional[str]]:
    """پیمایش بازگشتی JSON و جمع‌آوری شناسه فروشگاه‌ها → {shop_id: name?}."""
    found: dict[str, Optional[str]] = {}

    def _walk(n):
        if isinstance(n, dict):
            sid = next((n[k] for k in _SHOP_ID_KEYS if n.get(k) not in (None, "", 0)), None)
            if sid is not None:
                name = next((n[k] for k in _SHOP_NAME_KEYS if isinstance(n.get(k), str) and n[k]), None)
                if str(sid) not in found:
                    found[str(sid)] = name
            # فرم تودرتو: {"shop": {"id": .., "name": ..}}
            shop = n.get("shop")
            if isinstance(shop, dict):
                inner = next((shop[k] for k in (list(_SHOP_ID_KEYS) + ["id"]) if shop.get(k)), None)
                if inner is not None and str(inner) not in found:
                    found[str(inner)] = next(
                        (shop[k] for k in _SHOP_NAME_KEYS if isinstance(shop.get(k), str) and shop[k]), None
                    )
            for v in n.values():
                _walk(v)
        elif isinstance(n, list):
            for item in n:
                _walk(item)

    _walk(node)
    return found


def walk_first(node, keys: Iterable[str]):
    keyset = set(keys)
    if isinstance(node, dict):
        for k, v in node.items():
            if k.lower() in keyset and isinstance(v, str) and v.strip():
                return v
        for v in node.values():
            r = walk_first(v, keyset)
            if r:
                return r
    elif isinstance(node, list):
        for item in node:
            r = walk_first(item, keyset)
            if r:
                return r
    return None


def parse_shop_payload(payload: dict, shop_id: str, url: str) -> Lead:
    """JSON فروشگاه → Lead نرمال‌شده (مقاوم در برابر تغییر نام فیلدها)."""
    name = walk_first(payload, _SHOP_NAME_KEYS)
    city = walk_first(payload, _CITY_KEYS)
    candidates = "\n".join(walk_phone_values(payload))
    phones = [p.number for p in extract_phones(candidates)]
    if not phones:
        phones = [p.number for p in extract_phones(json_text(payload))]
    lead = Lead(
        source="torob", source_id=f"shop:{shop_id}", url=url,
        title=name, seller_name=name, city=city, phones=phones,
        site=walk_site_url(payload),
    )
    return normalize_lead(lead)


def walk_site_url(node) -> str | None:
    """یافتن وب‌سایت اختصاصی فروشنده در JSON — URLهای داخلی خودِ ترب را نمی‌گیرد."""
    from urllib.parse import urlparse

    def rec(n):
        if isinstance(n, dict):
            for k, v in n.items():
                if k.lower() in _SITE_KEYS and isinstance(v, str) and v.startswith("http"):
                    p = urlparse(v)
                    if p.path.startswith(("/p/", "/shop/")):
                        continue  # صفحه محصول/فروشگاه خود ترب است، نه سایت فروشنده
                    return v
            for v in n.values():
                r = rec(v)
                if r:
                    return r
        elif isinstance(n, list):
            for item in n:
                r = rec(item)
                if r:
                    return r
        return None

    return rec(node)


def extract_contacts_from_html(html: str) -> tuple[list[str], list[str]]:
    """استخراج شماره/ایمیل از HTML سایت فروشنده → (phones, emails)."""
    from bs4 import BeautifulSoup

    from ..extraction import extract_emails

    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)
    phones = [p.number for p in extract_phones(text)]
    emails = extract_emails(text)
    return phones, emails


def parse_shop_html(html: str, shop_id: str, url: str) -> Lead:
    """HTML صفحه فروشگاه → Lead (fallback وقتی API پاسخ نداد یا شماره نداشت).

    توجه: شماره‌هایی که فقط با کلیک/JS تزریق می‌شوند در HTML خام نیستند —
    آن‌ها کار گذر مرورگری (`abii browse`) هستند.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    name = soup.h1.get_text(strip=True) if soup.h1 else None
    text = soup.get_text(" ", strip=True)
    phones = [p.number for p in extract_phones(text)]
    lead = Lead(
        source="torob", source_id=f"shop:{shop_id}", url=url,
        title=name, seller_name=name, phones=phones,
    )
    return normalize_lead(lead)


def load_query_pack(pack: str, path: Optional[Path] = None) -> list[str]:
    """بارگذاری بسته کوئری از configs/queries.torob.yaml."""
    import yaml

    p = path or Path(__file__).resolve().parents[2] / "configs" / "queries.torob.yaml"
    if not p.exists():
        p = Path.cwd() / "configs" / "queries.torob.yaml"
    if not p.exists():
        raise FileNotFoundError(f"فایل بسته کوئری پیدا نشد: {p}")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if pack not in data:
        available = "، ".join(data) or "—"
        raise ValueError(f"بسته '{pack}' موجود نیست. موجود: {available}")
    return [str(q) for q in data[pack]]


def _rebase(url: str, base: str) -> str:
    """جابه‌جایی scheme+host یک endpoint به base دیگر (تست/ماک) با حفظ مسیر."""
    if not base:
        return url
    b = urlsplit(base)
    s = urlsplit(url)
    return urlunsplit((b.scheme, b.netloc, s.path, s.query, s.fragment))


# --------------------------------------------------------------------- metrics
@dataclass
class EngineMetrics:
    http: HttpMetrics = field(default_factory=HttpMetrics)
    queries: int = 0
    pages_fetched: int = 0
    products_seen: int = 0
    shops_found: int = 0          # یکتای کشف‌شده
    shops_fetched: int = 0
    shops_skipped_fresh: int = 0  # به‌خاطر TTL رد شد
    shops_no_phone: int = 0
    shops_recovered_web: int = 0  # با fallback صفحه وب، شماره/API بازیابی شد
    sites_enriched: int = 0       # از سایت اختصاصی فروشنده داده جدید گرفته شد
    phones_found: int = 0
    leads_new: int = 0
    leads_updated: int = 0
    leads_duplicate: int = 0
    duration_sec: float = 0.0

    def summary(self) -> str:
        rate = (self.shops_fetched / self.duration_sec * 60) if self.duration_sec else 0
        return (
            f"کوئری={self.queries} صفحه={self.pages_fetched} محصول={self.products_seen} | "
            f"فروشگاه یکتا={self.shops_found} برداشت={self.shops_fetched} "
            f"رد‌شده(تازه)={self.shops_skipped_fresh} | "
            f"شماره‌ها={self.phones_found} بدون‌شماره={self.shops_no_phone} | "
            f"new={self.leads_new} updated={self.leads_updated} dup={self.leads_duplicate} | "
            f"{rate:.0f} فروشگاه/دقیقه | {self.http.snapshot()}"
        )


@dataclass
class ScanOutcome:
    leads: list[Lead] = field(default_factory=list)
    metrics: EngineMetrics = field(default_factory=EngineMetrics)
    export_paths: dict[str, Path] = field(default_factory=dict)


# --------------------------------------------------------------------- engine
class TorobShopScanner:
    def __init__(
        self,
        cfg: AppConfig,
        queries: list[str],
        store: LeadStore,
        max_shops: int = 100,
        max_pages: int = 3,
        workers: int | None = None,
        min_delay: float | None = None,
        shop_ttl_hours: float | None = None,
        api_base: str | None = None,   # برای تست/ماک: http://127.0.0.1:8931
        always_offers: bool = False,   # همیشه offers هم خوانده شود (کشف فروشندههای بیشتر)
        web_fallback: bool = True,     # اگر API فروشگاه پاسخ نداد/شماره نداشت → صفحه وب HTML
        follow_sites: bool = True,     # بازدید از وب‌سایت اختصاصی فروشنده (در صورت داشتن)
    ):
        self.cfg = cfg
        self.queries = queries
        self.store = store
        self.max_shops = max_shops
        self.max_pages = max_pages
        self.workers = workers or cfg.workers
        self.min_delay = min_delay
        self.web_fallback = web_fallback
        self.follow_sites = follow_sites
        self.ttl = timedelta(hours=shop_ttl_hours if shop_ttl_hours is not None else cfg.shop_ttl_hours)
        self.always_offers = always_offers
        ep = cfg.endpoints
        self._urls = {
            "search": _rebase(ep.torob_search, api_base),
            "detail": _rebase(ep.torob_detail, api_base),
            "offers": _rebase(ep.torob_offers, api_base),
            "shop": _rebase(ep.torob_shop, api_base),
            "shop_web": _rebase(ep.torob_shop_web, api_base),
        }
        self.metrics = EngineMetrics()

    # ------------------------------------------------------------------ run
    async def run(self) -> ScanOutcome:
        t0 = time.monotonic()
        client = AsyncPoliteClient(self.cfg, min_delay=self.min_delay)
        leads: list[Lead] = []
        try:
            prks = await self._discover_products(client)
            shops = await self._map_shops(client, prks)
            leads = await self._harvest_shops(client, shops)
        except BlockedError as exc:
            # IP به‌طور کامل بلاک شده — با داده‌های جمع‌شده تا این لحظه ادامه می‌دهیم
            logger.critical("توقف اسکن (بلاک کامل): %s", exc)
        finally:
            self.metrics.http = client.metrics
            await client.aclose()

        # ذخیره + خروجی (امن: duplicate بازنویسی نمی‌کند، updated ادغام می‌شود)
        deduper = Deduper(self.store)
        for lead in leads:
            status = commit_lead(lead, self.store, deduper)
            lead.status = status
            key = {"new": "leads_new", "updated": "leads_updated", "duplicate": "leads_duplicate"}[status]
            setattr(self.metrics, key, getattr(self.metrics, key) + 1)

        export_paths: dict[str, Path] = {}
        if leads:
            export_paths = export_leads(
                leads, out_dir=self.cfg.export_dir, formats=self.cfg.export_formats,
                name_prefix=f"leads_torob_{utcnow().strftime('%Y%m%d_%H%M%S')}",
            )
        self.metrics.duration_sec = round(time.monotonic() - t0, 1)
        self.store.record_run(
            {"platform": "torob", "mode": "engine", "queries": self.queries,
             "max_shops": self.max_shops},
            {"new": self.metrics.leads_new, "updated": self.metrics.leads_updated,
             "duplicate": self.metrics.leads_duplicate,
             "errors": self.metrics.http.errors},
            utcnow(),
        )
        logger.info("torob engine finished: %s", self.metrics.summary())
        return ScanOutcome(leads=leads, metrics=self.metrics, export_paths=export_paths)

    # ------------------------------------------------------------------ فاز ۱
    async def _discover_products(self, client: AsyncPoliteClient) -> list[str]:
        prks: list[str] = []
        seen: set[str] = set()
        product_cap = max(12, self.max_shops * 3)  # هر محصول به‌طور میانگین ~۱-۳ فروشگاه دارد
        for q in self.queries:
            if len(prks) >= product_cap:
                break
            self.metrics.queries += 1
            for page in range(1, self.max_pages + 1):
                url = self._urls["search"].format(query=quote(q, safe=""), page=page)
                try:
                    data = await client.get_json(url)
                except BlockedError:
                    raise
                except ConnectionError as exc:
                    logger.error("search failed q=%s page=%s: %s", q, page, exc)
                    break
                if client.abort_requested:
                    logger.critical("قطع‌کننده مدار: بلاک‌های متوالی زیاد — توقف کشف")
                    return prks
                if data is None:
                    logger.warning("search q=%s page=%s → 404/410", q, page)
                    break
                self.metrics.pages_fetched += 1
                results = data.get("results") or dig(data, "result.results") or []
                batch = [
                    str(r.get("random_key") or r.get("prk") or r.get("id") or "")
                    for r in results
                ]
                fresh = [p for p in batch if p and p not in seen]
                for p in fresh:
                    seen.add(p)
                prks.extend(fresh)
                logger.info("[discover] q='%s' page=%s → %s محصول (مجموع %s)", q, page, len(fresh), len(prks))
                if not fresh:
                    break
                if len(prks) >= product_cap:
                    break
        return prks

    # ------------------------------------------------------------------ فاز ۲
    async def _map_shops(self, client: AsyncPoliteClient, prks: list[str]) -> dict[str, Optional[str]]:
        shops: dict[str, Optional[str]] = {}
        q: asyncio.Queue = asyncio.Queue()
        for prk in prks:
            q.put_nowait(prk)
        for _ in range(self.workers):
            q.put_nowait(None)

        async def worker():
            while True:
                prk = await q.get()
                if prk is None:
                    return
                if client.abort_requested:
                    logger.critical("قطع‌کننده مدار فعال — توقف نگاشت")
                    return
                self.metrics.products_seen += 1
                found: dict[str, Optional[str]] = {}
                try:
                    detail = await client.get_json(self._urls["detail"].format(prk=prk))
                    if detail is not None:
                        found = walk_shop_ids(detail)
                except (ConnectionError, BlockedError) as exc:
                    logger.warning("detail %s failed: %s", prk, exc)
                if (not found or self.always_offers) and self._urls["offers"]:
                    try:
                        offers = await client.get_json(self._urls["offers"].format(prk=prk))
                        if offers is not None:
                            for sid, name in walk_shop_ids(offers).items():
                                found.setdefault(sid, name)
                    except (ConnectionError, BlockedError) as exc:
                        logger.debug("offers %s failed: %s", prk, exc)
                for sid, name in found.items():
                    shops.setdefault(sid, name)
                if len(shops) >= self.max_shops * 2:
                    return  # به‌اندازه کافی فروشگاه داریم؛ فاز بعد سقف نهایی را اعمال می‌کند

        await asyncio.gather(*(worker() for _ in range(self.workers)))
        self.metrics.shops_found = len(shops)
        logger.info("[map] %s محصول → %s فروشگاه یکتا", self.metrics.products_seen, len(shops))
        return shops

    # ------------------------------------------------------------------ فاز ۳
    async def _harvest_shops(self, client: AsyncPoliteClient, shops: dict[str, Optional[str]]) -> list[Lead]:
        # فیلتر افزایشی: فروشگاه تازه‌ی دید‌شده رد شود (TTL)
        fresh: list[str] = []
        now = utcnow()
        for sid in shops:
            prev = self.store.get("torob", f"shop:{sid}")
            if prev is not None and (now - prev.last_seen) < self.ttl:
                self.metrics.shops_skipped_fresh += 1
                continue
            fresh.append(sid)
            if len(fresh) >= self.max_shops:
                break

        q: asyncio.Queue = asyncio.Queue()
        for sid in fresh:
            q.put_nowait(sid)
        for _ in range(self.workers):
            q.put_nowait(None)
        leads: list[Lead] = []
        loop = asyncio.get_running_loop()

        async def worker():
            while True:
                sid = await q.get()
                if sid is None:
                    return
                if client.abort_requested:
                    logger.critical("قطع‌کننده مدار فعال — توقف برداشت (IP به‌نظر بلاک است)")
                    return
                url_api = self._urls["shop"].format(shop_id=sid)
                url_human = (self._urls.get("shop_web") or url_api).format(shop_id=sid)
                lead: Lead | None = None
                api_failed = False
                try:
                    payload = await client.get_json(url_api)
                    if payload is None:
                        api_failed = True  # 404/410 — endpoint فروشگاه در دسترس نیست
                    else:
                        lead = await loop.run_in_executor(
                            None, parse_shop_payload, payload, sid, url_human
                        )
                except (ConnectionError, BlockedError) as exc:
                    api_failed = True
                    logger.warning("shop %s API failed: %s", sid, exc)

                # fallback صفحه وب: API جواب نداد یا شماره نداشت
                if self.web_fallback and (api_failed or (lead is not None and not lead.phones)):
                    fb = await self._web_fallback(client, sid)
                    if fb is not None:
                        if api_failed:
                            lead = fb
                            self.metrics.shops_recovered_web += 1
                        elif fb.phones:
                            lead.phones = list(
                                dict.fromkeys((*lead.phones, *fb.phones))
                            )
                            if fb.seller_name and not lead.seller_name:
                                lead.seller_name = fb.seller_name
                            self.metrics.shops_recovered_web += 1
                if lead is None:
                    continue
                # وب‌سایت اختصاصی فروشنده: شماره/ایمیل بیشتر از خود سایتِ او
                if self.follow_sites and lead.site:
                    enriched = await self._enrich_from_site(client, lead)
                    if enriched:
                        self.metrics.sites_enriched += 1
                self.metrics.shops_fetched += 1
                if lead.phones:
                    self.metrics.phones_found += len(lead.phones)
                else:
                    self.metrics.shops_no_phone += 1
                leads.append(lead)

        await asyncio.gather(*(worker() for _ in range(self.workers)))
        logger.info("[harvest] %s فروشگاه برداشت شد (%s بدون شماره، %s بازیابی از وب، %s غنی‌سازی از سایت فروشنده)",
                    self.metrics.shops_fetched, self.metrics.shops_no_phone,
                    self.metrics.shops_recovered_web, self.metrics.sites_enriched)
        return leads

    async def _enrich_from_site(self, client: AsyncPoliteClient, lead: Lead) -> bool:
        """بازدید از وب‌سایت اختصاصی فروشنده و ادغام شماره/ایمیل جدید.

        فقط داده «جدید» اضافه می‌کند؛ چیزی حذف نمی‌شود. اگر سایت پاسخ نداد،
        لید دست‌نخورده می‌ماند.
        """
        try:
            html = await client.get_text(lead.site)
        except (ConnectionError, BlockedError) as exc:
            logger.debug("site %s failed: %s", lead.site, exc)
            return False
        if not html:
            return False
        loop = asyncio.get_running_loop()
        phones, emails = await loop.run_in_executor(
            None, extract_contacts_from_html, html
        )
        new_phones = [p for p in phones if p not in lead.phones]
        new_emails = [e for e in emails if e not in lead.emails]
        if not (new_phones or new_emails):
            return False
        mobiles = [p for p in (*lead.phones, *new_phones) if p.startswith("09")]
        landlines = [p for p in (*lead.phones, *new_phones) if not p.startswith("09")]
        lead.phones = list(dict.fromkeys(mobiles + landlines))
        lead.emails = list(dict.fromkeys((*lead.emails, *new_emails)))
        lead.quality_score = quality_score(lead)
        logger.info("[site] %s → +%s شماره +%s ایمیل از سایت خودش",
                    lead.seller_name, len(new_phones), len(new_emails))
        return True

    async def _web_fallback(self, client: AsyncPoliteClient, shop_id: str) -> Lead | None:
        """دریافت صفحه HTML فروشگاه و استخراج شماره — وقتی API کافی نبود."""
        if not self._urls.get("shop_web"):
            return None
        url = self._urls["shop_web"].format(shop_id=shop_id)
        try:
            html = await client.get_text(url)
        except (ConnectionError, BlockedError) as exc:
            logger.debug("web fallback %s failed: %s", shop_id, exc)
            return None
        if not html:
            return None
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, parse_shop_html, html, shop_id, url)


# --------------------------------------------------------------------- entry
def run_torob_engine(
    queries: list[str],
    cfg: AppConfig,
    store: Optional[LeadStore] = None,
    **kwargs,
) -> ScanOutcome:
    """نقطه ورود همگام (asyncio.run داخلی)."""
    store = store or LeadStore(cfg.db_path)
    scanner = TorobShopScanner(cfg, queries, store, **kwargs)
    return asyncio.run(scanner.run())
