"""کلاینت HTTP محترمانه: Rate-limit، چرخش User-Agent و Proxy، retry با backoff.

مسئول تخصصی: Web Scraping Engineer — مدیریت Anti-Bot و بار روی سرور هدف.
"""
from __future__ import annotations

import logging
import random
import time
from urllib.parse import urlparse

import httpx

from ..config import AppConfig
from .base import FetchResult, Fetcher

logger = logging.getLogger(__name__)


class _HostRateLimiter:
    """حداقل فاصله زمانی بین دو درخواست به هر هاست + jitter تصادفی."""

    def __init__(self, min_delay: float, jitter: float):
        self.min_delay = min_delay
        self.jitter = jitter
        self._last: dict[str, float] = {}

    def wait(self, url: str) -> None:
        host = urlparse(url).netloc
        now = time.monotonic()
        prev = self._last.get(host)
        delay = self.min_delay + random.uniform(0, self.jitter)
        if prev is not None:
            remaining = delay - (now - prev)
            if remaining > 0:
                logger.debug("rate-limit: sleeping %.2fs for %s", remaining, host)
                time.sleep(remaining)
        self._last[host] = time.monotonic()


class HttpFetcher(Fetcher):
    """دانلود از APIها و صفحات HTML با httpx."""

    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        pol = cfg.politeness
        self._limiter = _HostRateLimiter(pol.min_delay, pol.jitter)
        self._ua_cycle = 0
        self._proxy_cycle = 0
        # به ازای هر proxy یک کلاینت می‌سازیم تا چرخش بدون بازسازی اتصال باشد
        proxies = cfg.proxies or [None]
        self._clients = [
            httpx.Client(
                timeout=pol.timeout,
                follow_redirects=True,
                proxy=p,
                headers={"Accept-Language": "fa,en;q=0.8"},
            )
            for p in proxies
        ]

    # ---------- internals ----------
    def _next_headers(self) -> dict[str, str]:
        uas = self.cfg.user_agents or ["abii-bot/0.1"]
        ua = uas[self._ua_cycle % len(uas)]
        self._ua_cycle += 1
        return {"User-Agent": ua}

    def _next_client(self) -> httpx.Client:
        client = self._clients[self._proxy_cycle % len(self._clients)]
        self._proxy_cycle += 1
        return client

    # ---------- public ----------
    def get(self, url: str) -> FetchResult:
        pol = self.cfg.politeness
        last_err: Exception | None = None
        for attempt in range(1, pol.max_retries + 1):
            self._limiter.wait(url)
            try:
                resp = self._next_client().get(url, headers=self._next_headers())
                if resp.status_code == 429 or resp.status_code >= 500:
                    retry_after = float(resp.headers.get("Retry-After", 0) or 0)
                    raise _Transient(f"status={resp.status_code}", backoff=retry_after or None)
                if resp.status_code == 403 or resp.status_code == 401:
                    # احتمال بلاک شدن / نیاز به مرورگر — بدون retry بی‌معنی است اگر تکراری باشد
                    logger.warning("blocked? %s -> %s (attempt %s)", url, resp.status_code, attempt)
                    if attempt == pol.max_retries:
                        return FetchResult(url, resp.status_code, resp.text)
                    raise _Transient(f"status={resp.status_code}", backoff=8.0)
                return FetchResult(url, resp.status_code, resp.text)
            except (_Transient, httpx.TransportError) as exc:
                last_err = exc
                backoff = getattr(exc, "backoff", None)
                wait = backoff if backoff else pol.backoff_base**attempt + random.uniform(0, 1)
                logger.warning(
                    "fetch retry %s/%s for %s (%s); waiting %.1fs",
                    attempt, pol.max_retries, url, exc, wait,
                )
                time.sleep(wait)
        raise ConnectionError(f"failed after {pol.max_retries} attempts: {url} ({last_err})")


class _Transient(Exception):
    def __init__(self, msg: str, backoff: float | None = None):
        super().__init__(msg)
        self.backoff = backoff
