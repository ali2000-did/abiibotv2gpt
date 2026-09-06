"""رفتار کاربرگونه — تایپ انسانی، مکث‌های تصادفی، اسکرول natural.

مسئول تخصصی: Web Scraping Engineer (رفتار bot-like → user-like)
"""
from __future__ import annotations

import random
import time

from playwright.sync_api import Page


def human_pause(min_delay: float = 1.0) -> None:
    """مکث بین اکشن‌ها: min_delay*0.6 تا min_delay*1.4 ثانیه + کمی نویز."""
    if min_delay <= 0:
        return
    base = random.uniform(min_delay * 0.6, min_delay * 1.4)
    time.sleep(max(0.05, base))


def human_type(page: Page, selector: str, text: str, min_delay: float = 1.0) -> None:
    """تایپ حرف‌به‌حرف با تأخیر تصادفی مثل کاربر واقعی."""
    page.click(selector)
    for ch in text:
        page.keyboard.type(ch, delay=random.randint(70, 180))
    human_pause(min_delay)


def human_scroll(page: Page, times: int = 2) -> None:
    """چند اسکرول کوچک تصادفی — شبیه‌سازی مرور لیست نتایج."""
    for _ in range(times):
        page.mouse.wheel(0, random.randint(250, 600))
        time.sleep(random.uniform(0.3, 0.8))


def first_visible(page: Page, selectors: list[str], timeout_ms: int = 2500):
    """اولین سلکتور (از کاندیدها) که در صفحه پیدا شد → Locator؛ نبود → None.

    پایه «پارس مقاوم»: چند کاندید به‌ترتیب امتحان می‌شوند تا تغییر کلاس/ساختار
    سایت یکی را بشکند، بقیه پاسخگو باشند.
    """
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=timeout_ms)
            return loc
        except Exception:  # noqa: BLE001
            continue
    return None


def collect_hrefs(page: Page, selector: str, base_url: str) -> list[str]:
    """همه hrefهای مچ‌شده به‌صورت URL مطلق و یکتا (به ترتیب ظاهر)."""
    from urllib.parse import urljoin

    hrefs: list[str] = []
    for loc in page.locator(selector).all():
        try:
            href = loc.get_attribute("href", timeout=1000)
        except Exception:  # noqa: BLE001
            continue
        if href:
            full = urljoin(base_url + "/", href)
            if full not in hrefs:
                hrefs.append(full)
    return hrefs


def collect_hrefs_any(page: Page, selectors: list[str], base_url: str) -> list[str]:
    """اولین کاندیدی که href بدهد برمی‌گرداند (پارس مقاوم با چند سلکتور)."""
    for sel in selectors:
        hrefs = collect_hrefs(page, sel, base_url)
        if hrefs:
            return hrefs
    return []
