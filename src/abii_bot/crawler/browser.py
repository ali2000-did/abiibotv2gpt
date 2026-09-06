"""دانلود صفحات نیازمند رندر JavaScript با Playwright (مرورگر هدلس).

استفاده: `pip install "abii-bot[browser]"` سپس `playwright install chromium`

سناریوهای هدف:
  - صفحاتی که شماره تماس فقط بعد از کلیک روی دکمه «نمایش شماره» ظاهر می‌شود
  - سایت‌های SPA که محتوایشان در JSON اولیه HTML نیست
"""
from __future__ import annotations

import logging
from typing import Optional

from .base import FetchResult, Fetcher

logger = logging.getLogger(__name__)


class BrowserFetcher(Fetcher):
    """رندر صفحه با Chromium هدلس. برای فازهای بعدی (دکمه‌های «نمایش شماره»)."""

    def __init__(self, headless: bool = True, locale: str = "fa-IR"):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "Playwright نصب نیست. برای فعال‌سازی: pip install 'abii-bot[browser]' && playwright install chromium"
            ) from exc
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=headless, locale=locale)

    def get(self, url: str, wait_selector: Optional[str] = None, timeout_ms: int = 30_000) -> FetchResult:
        page = self._browser.new_page(user_agent=_UA)
        try:
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            if wait_selector:
                page.wait_for_selector(wait_selector, timeout=timeout_ms)
            html = page.content()
            return FetchResult(url, 200, html)
        finally:
            page.close()

    def click_and_get(
        self,
        url: str,
        click_selector: str,
        wait_selector: Optional[str] = None,
        timeout_ms: int = 30_000,
    ) -> FetchResult:
        """باز کردن صفحه، کلیک روی دکمه (مثل «نمایش شماره») و گرفتن HTML نتیجه."""
        page = self._browser.new_page(user_agent=_UA)
        try:
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            page.click(click_selector, timeout=timeout_ms)
            if wait_selector:
                page.wait_for_selector(wait_selector, timeout=timeout_ms)
            return FetchResult(url, 200, page.content())
        finally:
            page.close()

    def close(self) -> None:
        try:
            self._browser.close()
            self._pw.stop()
        except Exception:  # pragma: no cover
            pass


_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
