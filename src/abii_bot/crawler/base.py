"""اینترفیس مشترک لایه خزیدن (Crawler Engine)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class FetchResult:
    """نتیجه دانلود یک URL — متن خام یا HTML."""

    url: str
    status_code: int
    text: str

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> dict:
        import json

        return json.loads(self.text)


class Fetcher(ABC):
    """هر روش دانلود (HTTP مستقیم، مرورگر هدلس، فایل محلی برای تست) این قرارداد را دارد."""

    @abstractmethod
    def get(self, url: str) -> FetchResult:  # pragma: no cover
        ...
