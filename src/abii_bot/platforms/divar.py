"""آداپتور دیوار (divar.ir) — اولویت API، fallback مرورگر.

روش:
  1. discover: endpoint جستجو بر اساس شهر+دسته‌بندی (slug) → توکن آگهی‌ها
  2. fetch: endpoint جزئیات هر آگهی (JSON)
  3. parse: استخراج عنوان/شهر/دسته + شماره تماس:
     - مسیرهای هدفمند (widgetهای CONTACT / phone)
     - fallback: اسکن Regex کل JSON (شماره هرجا پنهان باشد پیدا می‌شود)

⚠️ NEEDS LIVE VERIFICATION: endpointهای دیوار خارج از ایران قابل تست نیستند
   و ساختارشان دوره‌ای تغییر می‌کند. URLها از config قابل تنظیم‌اند.
"""
from __future__ import annotations

import json
import logging
from typing import Iterable, Iterator

from ..config import EndpointConfig
from ..crawler.base import Fetcher
from ..extraction import extract_phones
from ..models import ListingRef, Lead
from .base import PlatformAdapter, ScanSpec, dig, json_text, walk_phone_values

logger = logging.getLogger(__name__)


class DivarAdapter(PlatformAdapter):
    name = "divar"

    def __init__(self, fetcher: Fetcher, endpoints: EndpointConfig):
        self.fetcher = fetcher
        self.ep = endpoints

    # ---------- discover ----------
    def discover(self, spec: ScanSpec) -> Iterator[ListingRef]:
        city = spec.city or "tehran"
        category = spec.category or "browse"
        for page in range(1, max(1, spec.max_pages) + 1):
            url = self.ep.divar_search.format(city=city, category=category)
            if page > 1:
                url += f"&page={page}"
            res = self.fetcher.get(url)
            if not res.ok:
                logger.warning("divar search failed: %s -> %s", url, res.status_code)
                return
            data = res.json()
            posts = (
                dig(data, "result.posts")
                or dig(data, "posts")
                or dig(data, "data.posts")
                or []
            )
            if not posts:
                return
            for p in posts:
                token = p.get("token") or dig(p, "data.token")
                if not token:
                    continue
                yield ListingRef(
                    source=self.name,
                    source_id=token,
                    url=self.ep.divar_web_fallback.format(token=token),
                )

    # ---------- fetch ----------
    def fetch_detail(self, ref: ListingRef) -> dict:
        url = self.ep.divar_detail.format(token=ref.source_id)
        res = self.fetcher.get(url)
        if not res.ok:
            raise ConnectionError(f"divar detail {ref.source_id}: HTTP {res.status_code}")
        return res.json()

    # ---------- parse ----------
    def parse_detail(self, payload: dict, ref: ListingRef) -> Lead:
        sections = payload.get("sections") or dig(payload, "result.post.sections") or []

        title = (
            self._title_from_sections(sections)
            or dig(payload, "header.title")
            or dig(payload, "post.title")
            or dig(payload, "result.post.title")
        )
        city = dig(payload, "post.city.name") or dig(payload, "city.name")
        categories = dig(payload, "post.categories") or []
        category = " > ".join(c for c in categories if c) or None
        price_val = dig(payload, "price.value") or dig(payload, "post.price.value")
        price = f"{price_val:,}" if isinstance(price_val, int) else None

        phones = self._extract_phones(payload)

        return Lead(
            source=self.name,
            source_id=ref.source_id,
            url=ref.url,
            title=title,
            category=category,
            city=city,
            price=price,
            phones=[p.number for p in phones if p.is_mobile]
            + [p.number for p in phones if not p.is_mobile],
        )

    # ---------- helpers ----------
    @staticmethod
    def _title_from_sections(sections: list) -> str | None:
        for sec in sections:
            widget = str(sec.get("widget_type") or sec.get("widget") or "").upper()
            data = sec.get("data") or {}
            title = data.get("title") if isinstance(data, dict) else None
            if widget in {"HEADER", "TITLE_ROW", "TITLE", "LEGEND_TITLE"} and title:
                return title
        return None

    def _extract_phones(self, payload: dict):
        """اول مسیرهای هدفمند، بعد اسکن کل JSON."""
        candidates = list(walk_phone_values(payload))
        # متن توضیحات آگهی هم اغلب شماره دارد
        for sec in payload.get("sections") or []:
            data = sec.get("data") or {}
            if isinstance(data, dict):
                desc = data.get("text") or data.get("description")
                if isinstance(desc, str):
                    candidates.append(desc)
        hits = extract_phones("\n".join(candidates))
        if not hits:
            hits = extract_phones(json_text(payload))
        return hits
