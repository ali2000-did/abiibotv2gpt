"""یافتن و راه‌اندازی کرومیوم برای Playwright — سه منبع به ترتیب:

1. متغیر محیطی ``ABII_BROWSER_PATH`` (مسیر مستقیم executable)
2. نصب استاندارد Playwright (``playwright install chromium``)
3. نسخه fallback در ``~/.cache/abii-browsers`` — با ``scripts/setup_browser.sh``
   از پکیج npm ``@sparticuz/chromium`` نصب می‌شود (وقتی CDN پلی‌رایت در دسترس نیست)
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

FALLBACK_BIN = Path.home() / ".cache" / "abii-browsers" / "package" / "bin"

LAUNCH_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-blink-features=AutomationControlled",  # شبیه‌سازی مرورگر واقعی
]


def find_chromium() -> Optional[str]:
    """مسیر executable کرومیوم را برمی‌گرداند یا None اگر فقط نصب استاندارد پلی‌رایت کار کند."""
    env = os.environ.get("ABII_BROWSER_PATH")
    if env and Path(env).exists():
        logger.debug("chromium from ABII_BROWSER_PATH: %s", env)
        return env
    fb = FALLBACK_BIN / "chromium"
    if fb.exists():
        # کتابخانه‌های همراه (NSS و…) باید در مسیر جستجوی لینکر باشند
        lib = str(FALLBACK_BIN / "lib")
        os.environ["LD_LIBRARY_PATH"] = lib + ":" + os.environ.get("LD_LIBRARY_PATH", "")
        logger.debug("chromium fallback: %s (libs=%s)", fb, lib)
        return str(fb)
    return None


def launch_chromium(p, headless: bool = True, slow_mo: int = 0):
    """راه‌اندازی مرورگر با بهترین منبع موجود. ``p`` = شیء sync_playwright()."""
    exe = find_chromium()
    kwargs = dict(headless=headless, args=list(LAUNCH_ARGS), slow_mo=slow_mo)
    if exe:
        kwargs["executable_path"] = exe
    logger.info("launching chromium (headless=%s, exe=%s)", headless, exe or "playwright-default")
    return p.chromium.launch(**kwargs)
