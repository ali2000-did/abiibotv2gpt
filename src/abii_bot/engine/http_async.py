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

    def __init__(self, cfg: AppConfig, min_delay: float | None = None):
        self._ua_pool = cfg.user_agents or ["abii-bot/0.1"]
        self._ua_i = 0
        self._min_delay = min_delay if min_delay is not None else cfg.politeness.min_delay
        self._jitter_cap = min(cfg.politeness.jitter, max(self._min_delay * 0.5, 0.05))
        self._max_retries = cfg.politeness.max_retries
        self._backoff_base = cfg.politeness.backoff_base
        self._client = httpx.AsyncClient(
            timeout=cfg.politeness.timeout,
            follow_redirects=True,
            headers={"Accept-Language": "fa,en;q=0.8"},
            proxy=(cfg.proxies[0] if cfg.proxies else None),
        )
        self._host_next: dict[str, float] = {}
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._slowdown = 1.0  # ضریب کندسازی تطبیقی (1.0 = سرعت عادی)
        self.metrics = HttpMetrics()

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
    async def get_json(self, url: str) -> dict:
        last_exc: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            await self._wait_turn(url)
            self.metrics.requests += 1
            try:
                resp = await self._client.get(url, headers={"User-Agent": self._next_ua()})
                self.metrics.by_status[resp.status_code] = (
                    self.metrics.by_status.get(resp.status_code, 0) + 1
                )
                if resp.status_code in (401, 403):
                    self.metrics.blocked += 1
                    self._slowdown = min(self._slowdown * 1.5, 10.0)
                    raise BlockedError(f"HTTP {resp.status_code} برای {url}")
                if resp.status_code == 429 or resp.status_code >= 500:
                    self.metrics.blocked += 1
                    self._slowdown = min(self._slowdown * 1.5, 10.0)
                    retry_after = float(resp.headers.get("Retry-After", 0) or 0)
                    wait = retry_after or self._backoff_base**attempt + random.uniform(0, 1)
                    logger.warning("transient %s → %.1fs صبر (slowdown×%.1f)",
                                   resp.status_code, wait, self._slowdown)
                    await asyncio.sleep(wait)
                    last_exc = RuntimeError(f"HTTP {resp.status_code}")
                    continue
                resp.raise_for_status()
                # موفقیت → کندسازی آرام به حالت عادی برمی‌گردد
                self._slowdown = max(1.0, self._slowdown * 0.97)
                return resp.json()
            except BlockedError:
                raise
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_exc = exc
                self.metrics.retries += 1
                wait = self._backoff_base**attempt + random.uniform(0, 1)
                logger.warning("retry %s/%s برای %s (%s) → %.1fs",
                               attempt, self._max_retries, url, type(exc).__name__, wait)
                await asyncio.sleep(wait)
        self.metrics.errors += 1
        raise ConnectionError(f"شکست پس از {self._max_retries} تلاش: {url} ({last_exc})")

    async def aclose(self) -> None:
        await self._client.aclose()
