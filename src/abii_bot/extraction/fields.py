"""استخراج فیلدهای متنی دیگر: ایمیل، پاکسازی متن، حذف HTML."""
from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup

from .phone import scrub_text

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# حذف علائم نامرئی bidi (بدون حذف نیم‌فاصله — نیم‌فاصله در متن فارسی معنادار است)
_BIDI = {ord(c): None for c in "\u200f\u200e\u2066\u2067\u2068\u2069"}
_BIDI[0x00A0] = " "  # nbsp → فاصله


def extract_emails(text: str) -> list[str]:
    if not text:
        return []
    found = EMAIL_RE.findall(scrub_text(text))
    seen, out = set(), []
    for e in found:
        e = e.strip(".").lower()
        if e not in seen:
            seen.add(e)
            out.append(e)
    return out


def strip_html(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    return soup.get_text(" ", strip=True)


def clean_text(text: Optional[str], max_len: int = 300) -> Optional[str]:
    """فشرده‌سازی فاصله‌ها + حذف علائم bidi + کوتاه‌سازی (نیم‌فاصله حفظ می‌شود)."""
    if not text:
        return None
    t = re.sub(r"\s+", " ", text.translate(_BIDI)).strip(" -–|،,")
    if not t:
        return None
    return t[:max_len] + ("…" if len(t) > max_len else "")
