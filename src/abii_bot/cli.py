"""CLI ابزار — دستورات: run / demo / export / platforms."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .config import AppConfig
from .logging_conf import setup_logging
from .platforms import ScanSpec, supported_platforms
from .runner import run_demo, run_scan
from .storage import LeadStore, export_leads

app = typer.Typer(
    help="AbiiBot — ربات استخراج لید (شماره تماس فروشندگان) از دیوار، ترب و وب",
    no_args_is_help=True, add_completion=False,
)
console = Console()
ERR = typer.Option(None, "--config", help="مسیر فایل تنظیمات YAML")


def _cfg(config: Optional[Path]) -> AppConfig:
    return AppConfig.load(config)


@app.command()
def run(
    platform: str = typer.Option(..., "--platform", "-p", help="divar | torob | web"),
    city: Optional[str] = typer.Option(None, help="شهر (دیوار) — مثل tehran"),
    category: Optional[str] = typer.Option(None, help="دسته‌بندی (دیوار/ترب) — مثل buy-apartment"),
    query: Optional[str] = typer.Option(None, help="عبارت جستجو (ترب)"),
    url: List[str] = typer.Option(None, "--url", help="URL مستقیم (web) — تکرارپذیر"),
    urls_file: Optional[Path] = typer.Option(None, help="فایل متنی هر خط یک URL (web)"),
    max_pages: int = typer.Option(1, "--max-pages", help="حداکثر صفحات جستجو"),
    max_items: Optional[int] = typer.Option(None, "--max-items", help="حداکثر آگهی"),
    delay: Optional[float] = typer.Option(None, help="حداقل فاصله درخواست‌ها (ثانیه)"),
    out: Optional[Path] = typer.Option(None, "--out", help="پوشه خروجی"),
    fmt: Optional[str] = typer.Option(None, "--format", help="csv,xlsx,json"),
    config: Optional[Path] = ERR,
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """اجرای یک اسکن استخراج لید."""
    setup_logging(verbose)
    if platform not in supported_platforms():
        console.print(f"[red]پلتفرم '{platform}' نامعتبر است. موجود: {supported_platforms()}[/red]")
        raise typer.Exit(2)

    urls = list(url or [])
    if urls_file:
        urls += [ln.strip() for ln in urls_file.read_text(encoding="utf-8").splitlines() if ln.strip()]

    if platform == "divar" and not (city and category):
        console.print("[red]برای دیوار: --city و --category لازم است (مثلاً tehran و buy-apartment)[/red]")
        raise typer.Exit(2)
    if platform == "torob" and not (query or category):
        console.print("[red]برای ترب: --query یا --category لازم است[/red]")
        raise typer.Exit(2)
    if platform == "web" and not urls:
        console.print("[red]برای وب: حداقل یک --url یا --urls-file لازم است[/red]")
        raise typer.Exit(2)

    cfg = _cfg(config)
    if delay is not None:
        cfg.politeness.min_delay = delay
    if out:
        cfg.export_dir = out
    if fmt:
        cfg.export_formats = [f.strip() for f in fmt.split(",")]

    spec = ScanSpec(
        platform=platform, city=city, category=category, query=query,
        urls=urls, max_pages=max_pages, max_items=max_items,
    )
    report = run_scan(spec, cfg)
    _print_report(report)


@app.command()
def demo(config: Optional[Path] = ERR):
    """اجرای کامل pipeline روی داده‌های نمونه محلی — بدون اینترنت."""
    setup_logging(True)
    cfg = _cfg(config)
    reports = run_demo(cfg)
    for report in reports:
        _print_report(report)


@app.command()
def browse(
    platform: str = typer.Option("torob", "--platform", "-p", help="فعلاً: torob"),
    query: str = typer.Option(..., "--query", "-q", help="عبارت جستجو (مثل: لپ تاپ)"),
    max_products: int = typer.Option(5, "--max-products", help="حداکثر تعداد محصولی که کلیک می‌شود"),
    max_shops: int = typer.Option(1, "--max-shops", help="حداکثر فروشنده هر محصول"),
    headless: bool = typer.Option(True, "--headless/--headed", help="headed = پنجره مرورگر قابل مشاهده"),
    record: bool = typer.Option(False, "--record", help="ضبط ویدیو + اسکرین‌شات جلسه در sessions/"),
    base_url: Optional[str] = typer.Option(None, help=" Override آدرس سایت (تست/دمو)"),
    min_delay: Optional[float] = typer.Option(None, help="حداقل مکث بین اکشن‌ها (ثانیه)"),
    selectors_file: Optional[Path] = typer.Option(None, help="فایل YAML سلکتورهای اختصاصی"),
    out: Optional[Path] = typer.Option(None, "--out", help="پوشه خروجی"),
    config: Optional[Path] = ERR,
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """جریان مرورگری کاربرگونه: جستجو → کلیک محصول → کلیک فروشنده → کپی شماره → بعدی."""
    setup_logging(verbose)
    if platform != "torob":
        console.print(f"[red]فعلاً فقط torob پشتیبانی می‌شود (divar در قدم بعدی)[/red]")
        raise typer.Exit(2)
    cfg = _cfg(config)
    if out:
        cfg.export_dir = out
    if min_delay is not None:
        cfg.politeness.min_delay = min_delay

    from .browser import run_torob_browser  # نصب playwright فقط همین‌جا لازم است

    try:
        result = run_torob_browser(
            query=query, cfg=cfg, max_products=max_products, headless=headless,
            min_delay=min_delay, max_shops_per_product=max_shops, record=record,
            base_url=base_url, selectors_file=selectors_file,
        )
    except ImportError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2)

    table = Table(title=f"لیدهای استخراج‌شده — جریان مرورگری {result.platform}")
    for col in ["#", "عنوان/فروشگاه", "شماره تماس", "کیفیت", "وضعیت", "لینک"]:
        table.add_column(col, overflow="fold")
    for i, lead in enumerate(result.leads, 1):
        table.add_row(
            str(i), (lead.seller_name or lead.title or "—")[:40],
            ", ".join(lead.phones) or "—", str(lead.quality_score),
            lead.status, lead.url[:60],
        )
    console.print(table)
    console.print(f"[cyan]خلاصه:[/cyan] {result.summary()} | مدت: {result.duration_sec}s")
    for p in result.export_paths.values():
        console.print(f"[cyan]خروجی:[/cyan] {p}")
    for k, v in result.artifacts.items():
        console.print(f"[cyan]{k}:[/cyan] {v}")


@app.command()
def export(
    fmt: str = typer.Option("xlsx", "--format", help="csv | xlsx | json"),
    db: Optional[Path] = typer.Option(None, "--db", help="مسیر دیتابیس"),
    out: Optional[Path] = typer.Option(None, "--out", help="پوشه خروجی"),
    config: Optional[Path] = ERR,
):
    """خروجی‌گیری از همه لیدهای ذخیره‌شده در دیتابیس."""
    cfg = _cfg(config)
    store = LeadStore(db or cfg.db_path)
    leads = store.all_leads()
    if not leads:
        console.print("[yellow]دیتابیس خالی است. اول `abii run` یا `abii demo` بزنید.[/yellow]")
        raise typer.Exit(1)
    paths = export_leads(leads, out or cfg.export_dir, [fmt], name_prefix="leads_all")
    console.print(f"[green]{len(leads)} لید خروجی گرفته شد:[/green]")
    for p in paths.values():
        console.print(f"  • {p}")


@app.command()
def platforms():
    """فهرست پلتفرم‌های پشتیبانی‌شده."""
    console.print("[green]" + "، ".join(supported_platforms()) + "[/green]")


@app.command()
def version():
    console.print(f"AbiiBot v{__version__}")


def _print_report(report) -> None:
    table = Table(title=f"گزارش اسکن — {report.spec.platform}", show_lines=False)
    for col in ["#", "عنوان", "شماره تماس", "شهر", "کیفیت", "وضعیت"]:
        table.add_column(col, overflow="fold")
    for i, lead in enumerate(report.leads, 1):
        table.add_row(
            str(i), (lead.title or "—")[:48], ", ".join(lead.phones) or "—",
            lead.city or "—", str(lead.quality_score), lead.status,
        )
    console.print(table)
    console.print(f"[cyan]خلاصه:[/cyan] {report.summary()}")
    if report.export_paths:
        console.print("[cyan]خروجی‌ها:[/cyan] " + " | ".join(str(p) for p in report.export_paths.values()))


if __name__ == "__main__":
    app()
