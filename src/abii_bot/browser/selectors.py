"""بارگذاری سلکتورهای پلتفرم از فایل YAML با پیش‌فرض‌های امن."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

def _candidate_dirs() -> list[Path]:
    """دایرکتوری‌های ممکن برای فایل‌های سلکتور: ریشه ریپو، پوشه جاری."""
    here = Path(__file__).resolve()
    dirs = [
        here.parents[3] / "configs" if len(here.parents) > 3 else None,  # ریشه ریپو (حالت توسعه)
        Path.cwd() / "configs",  # پوشه اجرا
    ]
    return [d for d in dirs if d]


DEFAULTS_PATH = _candidate_dirs()[0] if _candidate_dirs() else Path.cwd() / "configs"

_DEFAULTS: dict[str, Any] = {
    "base_url": "https://torob.com",
    "search": {"input": ["input[name='q']"], "submit": []},
    "results": {"wait_for": ["a[href*='/p/']"], "product_link": "a[href*='/p/']"},
    "product": {
        "title": ["h1"],
        "price": ["[class*='price']"],
        "shop_link": ["a[href*='/shop/']"],
        "show_phone": ["button:has-text('نمایش شماره')"],
    },
    "shop": {
        "title": ["h1"],
        "show_phone": ["button:has-text('نمایش شماره')"],
        "phone_text": ["body"],
    },
}


def _merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_selectors(platform: str = "torob", config_path: Path | None = None) -> dict:
    """سلکتورها = پیش‌فرض کد ← فایل configs/selectors.<platform>.yaml (در صورت وجود)."""
    path = config_path or (DEFAULTS_PATH / f"selectors.{platform}.yaml")
    data: dict = {}
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return _merge(_DEFAULTS, data)
