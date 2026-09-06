"""تنظیمات پروژه — همگی رفتارهای قابل تغییر از فایل YAML یا CLI هستند."""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENTS = [
    # چرخش User-Agent برای شبیه‌سازی ترافیک واقعی مرورگر
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]


@dataclass
class PolitenessConfig:
    """محترمانه بودن با سرور هدف — پیش‌فرض محافظه‌کارانه است."""

    min_delay: float = 2.5  # حداقل فاصله بین دو درخواست به یک هاست (ثانیه)
    jitter: float = 1.2  # نویز تصادفی روی تأخیر تا رفتار رباتیک تشخیص داده نشود
    timeout: float = 20.0
    max_retries: int = 3
    backoff_base: float = 2.0  # انتظار exponential: base^attempt ثانیه
    respect_robots: bool = True


@dataclass
class EndpointConfig:
    """قالب endpointهای هر پلتفرم.

    ⚠️ این URLها خارج از ایران قابل تست نیستند و پلتفرم‌ها مرتب ساختار را عوض
    می‌کنند؛ بنابراین «قابل تنظیم» هستند و parserها resilient طراحی شده‌اند تا
    تغییر جزئی ساختار JSON آن‌ها را نشکند.
    """

    divar_search: str = "https://api.divar.ir/api/v1/post2/w/{city}/{category}"
    divar_detail: str = "https://api.divar.ir/post/v2/web/post/{token}"
    divar_web_fallback: str = "https://divar.ir/v/{token}"
    # ⬇ تأییدشده از اسکرپرهای واقعی گیت‌هاب (Torob-Integration / torob-scraper):
    #   - صفحه‌بندی از ۰ شروع می‌شود، sort=popularity، و پاسج شامل فیلد next است
    #   - details به prk + search_id نیاز دارد (هر دو از more_info_url نتایج جستجو)
    torob_search: str = "https://api.torob.com/v4/base-product/search/?q={query}&sort=popularity&size=24&page={page}"
    torob_detail: str = "https://api.torob.com/v4/base-product/details/?prk={prk}&search_id={search_id}"
    torob_detail_v2: str = "https://api.torob.com/v4/base-product/detail-v2/?prk={prk}"  # fallback قدیمی
    torob_offers: str = "https://api.torob.com/v4/base-product/offer-list/?prk={prk}&size=24"
    torob_suggestion: str = "https://api.torob.com/suggestion2/?q={query}"
    torob_shop: str = "https://api.torob.com/v4/shop/detail/?shop_id={shop_id}"  # NEEDS LIVE VERIFICATION
    torob_shop_web: str = "https://torob.com/shop/{shop_id}/"
    torob_web_fallback: str = "https://torob.com/p/{prk}/"


@dataclass
class AppConfig:
    db_path: Path = Path("data/leads.db")
    export_dir: Path = Path("exports")
    politeness: PolitenessConfig = field(default_factory=PolitenessConfig)
    endpoints: EndpointConfig = field(default_factory=EndpointConfig)
    proxies: list[str] = field(default_factory=list)  # اختیاری: http://user:pass@host:port
    user_agents: list[str] = field(default_factory=lambda: list(DEFAULT_USER_AGENTS))
    export_formats: list[str] = field(default_factory=lambda: ["csv", "xlsx"])
    workers: int = 4  # تعداد workerهای ناهمگام موتور
    shop_ttl_hours: float = 168.0  # فروشگاهی که اخیراً اسکن شده، تا این مدت دوباره fetch نشود

    # ---------- serialization ----------
    def to_dict(self) -> dict:
        d = asdict(self)
        d["db_path"] = str(self.db_path)
        d["export_dir"] = str(self.export_dir)
        return d

    @classmethod
    def load(cls, path: Optional[Path] = None, **overrides) -> "AppConfig":
        """بارگذاری از YAML (اختیاری) + بازنویسی با آرگومان‌های صریح."""
        data: dict = {}
        if path and Path(path).exists():
            data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
            logger.info("config loaded from %s", path)
        cfg = cls(
            db_path=Path(data.get("db_path", "data/leads.db")),
            export_dir=Path(data.get("export_dir", "exports")),
            politeness=PolitenessConfig(**data.get("politeness", {})),
            endpoints=EndpointConfig(**data.get("endpoints", {})),
            proxies=list(data.get("proxies", [])),
            user_agents=list(data.get("user_agents", DEFAULT_USER_AGENTS)),
            export_formats=list(data.get("export_formats", ["csv", "xlsx"])),
            workers=int(data.get("workers", 4)),
            shop_ttl_hours=float(data.get("shop_ttl_hours", 168.0)),
        )
        for k, v in overrides.items():
            if v is not None and hasattr(cfg, k):
                setattr(cfg, k, v)
        return cfg
