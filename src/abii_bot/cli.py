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
