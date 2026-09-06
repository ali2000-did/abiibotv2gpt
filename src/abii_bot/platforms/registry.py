"""رجیستری آداپتورها — ساخت آداپتور مناسب بر اساس نام پلتفرم."""
from __future__ import annotations

from ..config import AppConfig
from ..crawler.base import Fetcher
from .base import PlatformAdapter
from .divar import DivarAdapter
from .torob import TorobAdapter
from .web import WebAdapter

_ADAPTERS: dict[str, type[PlatformAdapter]] = {
    "divar": DivarAdapter,
    "torob": TorobAdapter,
    "web": WebAdapter,
}


def supported_platforms() -> list[str]:
    return sorted(_ADAPTERS)


def build_adapter(name: str, fetcher: Fetcher, cfg: AppConfig) -> PlatformAdapter:
    name = name.lower().strip()
    if name not in _ADAPTERS:
        raise ValueError(f"پلتفرم '{name}' پشتیبانی نمی‌شود. موجود: {supported_platforms()}")
    cls = _ADAPTERS[name]
    if cls is WebAdapter:
        return cls(fetcher)
    return cls(fetcher, cfg.endpoints)
