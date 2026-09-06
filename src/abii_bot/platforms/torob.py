"""آداپتور ترب (torob.com) — جستجوی محصول → جزئیات → اطلاعات فروشنده.

روش:
  1. discover: جستجو با query (یا دسته‌بندی) → random_key محصولات
  2. fetch: endpoint جزئیات محصول (JSON)
  3. parse: نام محصول/قیمت + اطلاعات فروشگاه (نام، شماره تماس فروشگاه)

نکته домain: در ترب «فروشنده» = فروشگاه (shop) است؛ شماره تماس فروشگاه‌ها در
صفحه/دیتای shop در دسترس است. در فاز بعد endpoint پیشنهاد فروشنده‌ها (offers)
و صفحات shop اضافه می‌شود.

⚠️ NEEDS LIVE VERIFICATION — URLها از config قابل تنظیم‌اند.
"""
from __future__ import annotations

import logging
from typing import Iterator

from ..config import EndpointConfig
from ..crawler.base import Fetcher
from ..extraction import extract_phones
from ..models import ListingRef, Lead
from .base import PlatformAdapter, ScanSpec, dig, json_text, walk_phone_values

logger = logging.getLogger(__name__)


class TorobAdapter(PlatformAdapter):
    name = "torob"

    def __init__(self, fetcher: Fetcher, endpoints: EndpointConfig):
        self.fetcher = fetcher
        self.ep = endpoints

    # ---------- discover ----------
    def discover(self, spec: ScanSpec) -> Iterator[ListingRef]:
        for page in range(1, max(1, spec.max_pages) + 1):
            url = self.ep.torob_search.format(
                query=spec.query or spec.category or "", page=page
            )
            res = self.fetcher.get(url)
            if not res.ok:
                logger.warning("torob search failed: %s -> %s", url, res.status_code)
                return
            data = res.json()
            results = data.get("results") or []
            if not results:
                return
            for r in results:
                prk = r.get("random_key") or r.get("prk") or r.get("id")
                if not prk:
                    continue
                yield ListingRef(
                    source=self.name,
                    source_id=str(prk),
                    url=self.ep.torob_web_fallback.format(prk=prk),
                )

    # ---------- fetch ----------
    def fetch_detail(self, ref: ListingRef) -> dict:
        url = self.ep.torob_detail.format(prk=ref.source_id)
        res = self.fetcher.get(url)
        if not res.ok:
            raise ConnectionError(f"torob detail {ref.source_id}: HTTP {res.status_code}")
        return res.json()

    # ---------- parse ----------
    def parse_detail(self, payload: dict, ref: ListingRef) -> Lead:
        title = " ".join(
            p for p in [payload.get("name1"), payload.get("name2")] if p
        ) or None
        price = payload.get("price_text") or dig(payload, "price.text")
        seller = payload.get("shop_name") or dig(payload, "shop.name")
        city = payload.get("city") or dig(payload, "shop.city")

        candidates = list(walk_phone_values(payload))
        hits = extract_phones("\n".join(candidates))
        if not hits:
            hits = extract_phones(json_text(payload))

        return Lead(
            source=self.name,
            source_id=ref.source_id,
            url=ref.url,
            title=title,
            city=city,
            price=str(price) if price else None,
            seller_name=seller,
            phones=[p.number for p in hits if p.is_mobile]
            + [p.number for p in hits if not p.is_mobile],
        )
