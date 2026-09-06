"""کلاینت فیکسچر محلی — دانلود «جعلی» از فایل‌های examples/fixtures.

کاربرد:
  1. اجرای کامل pipeline بدون اینترنت (دمو، CI، این سندباکس!)
  2. تست آداپتورها با پاسخ‌های واقعی ضبط‌شده (وقتی سرور در دسترس است،
     فایل واقعی را جایگزین فیکسچر کنید تا تست با واقعیت هم‌گام بماند)
"""
from __future__ import annotations

from pathlib import Path

from .crawler.base import FetchResult, Fetcher


class LocalFixtureFetcher(Fetcher):
    """URL را به فایل فیکسچر نگاشت می‌کند (بر اساس زیررشته در URL)."""

    def __init__(self, fixtures_dir: Path | str, mapping: dict[str, str]):
        """mapping: {'زیررشته‌ای در URL': 'نام فایل در دایرکتوری فیکسچرها'}"""
        self.dir = Path(fixtures_dir)
        self.mapping = mapping

    def get(self, url: str) -> FetchResult:
        for needle, filename in self.mapping.items():
            if needle in url:
                path = self.dir / filename
                return FetchResult(url, 200, path.read_text(encoding="utf-8"))
        return FetchResult(url, 404, "")
