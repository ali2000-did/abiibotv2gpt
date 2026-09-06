"""آداپتور وب عمومی — «و امثال آن»: هر لیست URL از هر سایتی.

این آداپتور پایه «امتدادپذیری» پروژه است: هر سایت فروشنده‌ای که URL صفحاتش را
بدهید، شماره تماس/ایمیل/عنوان آن استخراج می‌شود (بدون کد اختصاصی برای آن سایت).
"""
from __future__ import annotations

import hashlib
import logging
from typing import Iterable, Iterator

from bs4 import BeautifulSoup

from ..crawler.base import Fetcher
from ..extraction import extract_emails, extract_phones
from ..extraction.fields import clean_text
from ..models import ListingRef, Lead
from .base import PlatformAdapter, ScanSpec

logger = logging.getLogger(__name__)


class WebAdapter(PlatformAdapter):
    name = "web"

    def __init__(self, fetcher: Fetcher):
        self.fetcher = fetcher

    # ---------- discover ----------
    def discover(self, spec: ScanSpec) -> Iterator[ListingRef]:
        for url in spec.urls:
            yield ListingRef(
                source=self.name,
                source_id=hashlib.sha1(url.encode()).hexdigest()[:12],
                url=url,
            )

    # ---------- fetch ----------
    def fetch_detail(self, ref: ListingRef) -> str:
        res = self.fetcher.get(ref.url)
        if not res.ok:
            raise ConnectionError(f"web fetch {ref.url}: HTTP {res.status_code}")
        return res.text

    # ---------- parse ----------
    def parse_detail(self, payload: str, ref: ListingRef) -> Lead:
        soup = BeautifulSoup(payload, "lxml")

        og_title = soup.find("meta", attrs={"property": "og:title"})
        title = (
            (og_title.get("content") if og_title else None)
            or (soup.h1.get_text(strip=True) if soup.h1 else None)
            or (soup.title.get_text(strip=True) if soup.title else None)
        )

        meta_desc = soup.find("meta", attrs={"name": "description"})
        description = meta_desc.get("content") if meta_desc else None

        text = soup.get_text(" ", strip=True)
        phones = extract_phones(text)
        emails = extract_emails(text)

        return Lead(
            source=self.name,
            source_id=ref.source_id,
            url=ref.url,
            title=clean_text(title),
            description=clean_text(description, 200),
            phones=[p.number for p in phones if p.is_mobile]
            + [p.number for p in phones if not p.is_mobile],
            emails=emails,
        )
