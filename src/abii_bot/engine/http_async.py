"""کلاینت HTTP ناهمگامِ محترمانه — قلب پرفورمنس موتور ترب.

ویژگی‌ها:
  • همزمانی workerهای متعدد + صف‌بندی per-host (نرخ کل به هر هاست کنترل می‌شود)
  • کندسازی تطبیقی (Adaptive Slowdown): با 429/5xx فاصله درخواست‌ها خودکار
    بیشتر می‌شود و با موفقیت‌ها آرام برمی‌گردد — بدون دخالت دستی
  • چرخش User-Agent + retry با backoff نمایی
  • متریک زنده: تعداد درخواست/ری‌تری/بلاک/خطا
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

from ..config import AppConfig

logger = logging.getLogger(__name__)


class BlockedError(RuntimeError):
    """سرور پاسخ 401/403 داد — احتمال بلاک IP؛ ادامه‌ی بی‌مورد درست نیست."""


@dataclass
class HttpMetrics:
    requests: int = 0
    retries: int = 0
    blocked: int = 0  # 429/5xx/403
    errors: int = 0
    by_status: dict[int, int] = field(default_factory=dict)

    def snapshot(self) -> str:
        top = sorted(self.by_status.items(), key=lambda kv: -kv[1])[:3]
        top_s = ", ".join(f"{k}×{v}" for k, v in top) or "—"
        return (
            f"requests={self.requests} retries={self.retries} "
            f"blocked={self.blocked} errors={self.errors} | status: {top_s}"
        )


class AsyncPoliteClient:
    """یک نمونه بین همه workerها به اشتراک می‌رود؛ نرخ per-host تضمین می‌شود."""

    ABORT_AFTER_CONSEC_BLOCKS = 15  # قطع‌کننده مدار: پس از این تعدال بلاک متوالی، اسکن متوقف شود

    def __init__(self, cfg: AppConfig, min_delay: float | None = None):
        self._ua_pool = cfg.user_agents or ["abii-bot/0.1"]
        self._ua_i = 0
        self._min_delay = min_delay if min_delay is not None else cfg.politeness.min_delay
        self._jitter_cap = min(cfg.politeness.jitter, max(self._min_delay * 0.5, 0.05))
        self._max_retries = cfg.politeness.max_retries
        self._backoff_base = cfg.politeness.backoff_base
        # چرخش پروکسی: به ازای هر پروکسی یک client (بدون پروکسی هم یکی)
        proxies = cfg.proxies or [None]
        self._clients = [
            httpx.AsyncClient(
                timeout=cfg.politeness.timeout,
                follow_redirects=True,
                headers={"Accept-Language": "fa,en;q=0.8"},
                proxy=p,
            )
            for p in proxies
        ]
        self._client_i = 0
        self._host_next: dict[str, float] = {}
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._slowdown = 1.0  # ضریب کندسازی تطبیقی (1.0 = سرعت عادی)
        self._consec_blocks = 0
        self.metrics = HttpMetrics()

    @property
    def abort_requested(self) -> bool:
        """قطع‌کننده مدار: بلاک‌های متوالی نشان می‌دهد IP سوخته — ادامه بی‌فایده و بی‌احترام است."""
        return self._consec_blocks >= self.ABORT_AFTER_CONSEC_BLOCKS

    def _client(self) -> httpx.AsyncClient:
        c = self._clients[self._client_i % len(self._clients)]
        self._client_i += 1
        return c

    # ---------- نرخ per-host ----------
    async def _wait_turn(self, url: str) -> None:
        host = urlparse(url).netloc
        lock = self._host_locks.setdefault(host, asyncio.Lock())
        async with lock:
            now = time.monotonic()
            interval = self._min_delay * self._slowdown + random.uniform(0, self._jitter_cap)
            wait = self._host_next.get(host, 0.0) - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._host_next[host] = time.monotonic() + interval

    def _next_ua(self) -> str:
        ua = self._ua_pool[self._ua_i % len(self._ua_pool)]
        self._ua_i += 1
        return ua

    # ---------- API ----------
    async def get_json(self, url: str) -> dict | None:
        """GET و parse JSON.

        • 404/410 → None بدون retry (منبع واقعاً موجود نیست — retry بی‌احترامی بی‌مورد است)
        • پاسخ 200 غیر-JSON → ConnectionError (بدون قتل کل اسکن توسط استثنای خام)
        """
        last_exc: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            await self._wait_turn(url)
            self.metrics.requests += 1
            try:
                resp = await self._client().get(url, headers={"User-Agent": self._next_ua()})
                self.metrics.by_status[resp.status_code] = (
                    self.metrics.by_status.get(resp.status_code, 0) + 1
                )
                if resp.status_code in (401, 403):
                    self.metrics.blocked += 1
                    self._consec_blocks += 1
                    self._slowdown = min(self._slowdown * 1.5, 10.0)
                    raise BlockedError(f"HTTP {resp.status_code} برای {url}")
                if resp.status_code in (404, 410):
                    logger.debug("منبع موجود نیست (HTTP %s): %s", resp.status_code, url)
                    return None
                if resp.status_code == 429 or resp.status_code >= 500:
                    self.metrics.blocked += 1
                    self._consec_blocks += 1
                    self._slowdown = min(self._slowdown * 1.5, 10.0)
                    retry_after = float(resp.headers.get("Retry-After", 0) or 0)
                    wait = retry_after or self._backoff_base**attempt + random.uniform(0, 1)
                    logger.warning("transient %s → %.1fs صبر (slowdown×%.1f)",
                                   resp.status_code, wait, self._slowdown)
                    await asyncio.sleep(wait)
                    last_exc = RuntimeError(f"HTTP {resp.status_code}")
                    continue
                resp.raise_for_status()
                try:
                    data = resp.json()
                except ValueError as exc:  # پاسخ 200 اما غیر JSON (مثلاً HTML خطا)
                    self.metrics.errors += 1
                    raise ConnectionError(
                        f"پاسخ 200 اما JSON نیست: {url} ({str(exc)[:80]})"
                    ) from exc
                # موفقیت → کندسازی آرام به حالت عادی برمی‌گردد
                self._consec_blocks = 0
                self._slowdown = max(1.0, self._slowdown * 0.97)
                return data
            except BlockedError:
                if self.abort_requested:
                    raise  # در سطح موتور هندل می‌شود (توقف کل اسکن)
                if attempt >= self._max_retries:
                    self.metrics.errors += 1
                    raise
                await asyncio.sleep(1.0)
                continue
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_exc = exc
                self.metrics.retries += 1
                wait = self._backoff_base**attempt + random.uniform(0, 1)
                logger.warning("retry %s/%s برای %s (%s) → %.1fs",
                               attempt, self._max_retries, url, type(exc).__name__, wait)
                await asyncio.sleep(wait)
        self.metrics.errors += 1
        raise ConnectionError(f"شکست پس از {self._max_retries} تلاش: {url} ({last_exc})")

    async def get_text(self, url: str) -> str | None:
        """GET متنی (HTML) — همان منطق get_json بدون parse JSON."""
        last_exc: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            await self._wait_turn(url)
            self.metrics.requests += 1
            try:
                resp = await self._client().get(url, headers={"User-Agent": self._next_ua()})
                self.metrics.by_status[resp.status_code] = (
                    self.metrics.by_status.get(resp.status_code, 0) + 1
                )
                if resp.status_code in (401, 403):
                    self.metrics.blocked += 1
                    self._consec_blocks += 1
                    raise BlockedError(f"HTTP {resp.status_code} برای {url}")
                if resp.status_code in (404, 410):
                    return None
                if resp.status_code == 429 or resp.status_code >= 500:
                    self.metrics.blocked += 1
                    self._consec_blocks += 1
                    retry_after = float(resp.headers.get("Retry-After", 0) or 0)
                    wait = retry_after or self._backoff_base**attempt + random.uniform(0, 1)
                    await asyncio.sleep(wait)
                    last_exc = RuntimeError(f"HTTP {resp.status_code}")
                    continue
                resp.raise_for_status()
                self._consec_blocks = 0
                self._slowdown = max(1.0, self._slowdown * 0.97)
                return resp.text
            except BlockedError:
                if self.abort_requested:
                    raise
                if attempt >= self._max_retries:
                    self.metrics.errors += 1
                    raise
                await asyncio.sleep(1.0)
                continue
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_exc = exc
                self.metrics.retries += 1
                await asyncio.sleep(self._backoff_base**attempt + random.uniform(0, 1))
        self.metrics.errors += 1
        raise ConnectionError(f"شکست پس از {self._max_retries} تلاش: {url} ({last_exc})")

    async def aclose(self) -> None:
        for c in self._clients:
            await c.aclose()
