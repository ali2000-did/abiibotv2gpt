"""CLI ابزار — دستورات: run / demo / export / platforms."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.panel import Panel
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
torob_app = typer.Typer(help="موتور ترب — اسکن ناهمگام فروشگاه‌محور", no_args_is_help=True)
app.add_typer(torob_app, name="torob")
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
def set_product(
    product: List[str] = typer.Argument(..., help="محصول(ها) هدف — همان عبارت جستجو در ترب"),
    every: str = typer.Option("24h", "--every", "-e", help="فاصله دورها: 24h / 6h / 30m / 45s"),
    max_shops: int = typer.Option(100, "--max-shops", help="سقف فروشگاه جدید در هر دور"),
    workers: int = typer.Option(4, "--workers", "-w"),
    min_delay: float = typer.Option(1.2, "--min-delay"),
    path: Optional[Path] = typer.Option(None, "--path", help="مسیر فایل تنظیمات (پیش‌فرض configs/autorun.yaml)"),
):
    """ثبت محصول هدف برای اتوران — بعد از این، خودش دور می‌زند."""
    from .autorun import AutorunSettings, parse_interval

    settings = AutorunSettings(
        queries=[p.strip() for p in product if p.strip()],
        every_seconds=parse_interval(every),
        max_shops=max_shops, workers=workers, min_delay=min_delay,
    )
    saved = settings.save(path)
    console.print(Panel.fit(
        f"[bold green]محصول هدف ثبت شد ✅[/bold green]\n"
        f"محصول(ها): {'، '.join(settings.queries)}\n"
        f"دوره تکرار: هر {every} ({settings.every_seconds:,} ثانیه)\n"
        f"سقف هر دور: {settings.max_shops} فروشگاه جدید\n"
        f"فایل: {saved}",
        title="autorun",
    ))
    console.print(
        "[cyan]اجرا:[/cyan] sudo systemctl enable --now abii-autorun"
        "  (یا بدون سرویس: .venv/bin/abii autorun)"
    )


@app.command()
def autorun(
    once: bool = typer.Option(False, "--once", help="فقط یک دور اجرا و خروج (تست)"),
    explain: bool = typer.Option(False, "--explain", help="نمایش مسیر دقیق اجرا بدون شروع آن"),
    settings_file: Optional[Path] = typer.Option(None, "--settings", help="فایل تنظیمات"),
    config: Optional[Path] = ERR,
):
    """اجرای دائمی: دور‌بهدور اسکن می‌کند و روشن می‌ماند (Ctrl+C تمیز قطع می‌کند)."""
    import signal
    import threading

    from .autorun import AutorunSettings, default_settings_path, explain_plan, run_forever

    setup_logging(True)
    cfg = _cfg(config)
    spath = settings_file or default_settings_path()
    try:
        settings = AutorunSettings.load(spath)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2)

    if explain:
        console.print(explain_plan(settings, cfg))
        return

    stop = threading.Event()

    def _stop(signum, frame):  # noqa: ARG001
        console.print("\n[yellow]دریافت سیگنال توقف — بعد از اتمام کار جاری تمیز قطع می‌شود…[/yellow]")
        stop.set()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    cycles = run_forever(settings, cfg, once=once, stop=stop, settings_path=spath)
    console.print(f"[green]اتوران پس از {cycles} دور متوقف شد.[/green]")


@app.command()
def status(
    db: Optional[Path] = typer.Option(None, "--db"),
    config: Optional[Path] = ERR,
):
    """وضعیت اتوران (آخرین دور، دور بعدی) + آمار دیتابیس."""
    import json as _json

    cfg = _cfg(config)
    from .autorun import status_path

    st = status_path(cfg)
    if st.exists():
        data = _json.loads(st.read_text(encoding="utf-8"))
        table = Table(title=f"اتوران — دور {data.get('cycle', '?')}")
        for col in ["آخرین اجرا", "دور بعدی", "فروشگاه جدید", "شماره", "خطا"]:
            table.add_column(col, overflow="fold")
        table.add_row(
            (data.get("last_run_at") or "")[:19],
            (data.get("next_run_at") or "—")[:19],
            str(data.get("leads_new", "—")),
            str(data.get("phones_found", "—")),
            (data.get("error") or "—")[:60],
        )
        console.print(table)
        for p in data.get("exports", []):
            console.print(f"[cyan]آخرین خروجی:[/cyan] {p}")
    else:
        console.print("[yellow]اتوران هنوز اجرا نشده است.[/yellow]")

    store = LeadStore(db or cfg.db_path)
    s = store.stats()
    console.print(
        f"[green]دیتابیس:[/green] {s['total']} لید | {s['with_phone']} دارای شماره | "
        f"({', '.join(f'{k}: {v}' for k, v in s['by_source'].items()) or 'خالی'})"
    )


@app.command()
def platforms():
    """فهرست پلتفرم‌های پشتیبانی‌شده."""
    console.print("[green]" + "، ".join(supported_platforms()) + "[/green]")


@app.command()
def stats(
    db: Optional[Path] = typer.Option(None, "--db", help="مسیر دیتابیس"),
    config: Optional[Path] = ERR,
):
    """آمار دیتابیس لیدها + اجراهای اخیر."""
    cfg = _cfg(config)
    store = LeadStore(db or cfg.db_path)
    s = store.stats()
    table = Table(title="آمار دیتابیس")
    table.add_column("شاخص", style="cyan")
    table.add_column("مقدار")
    table.add_row("کل لیدها", str(s["total"]))
    table.add_row("دارای شماره تماس", str(s["with_phone"]))
    for src, cnt in s["by_source"].items():
        table.add_row(f" — {src}", str(cnt))
    table.add_row("اسکن‌های ثبت‌شده", str(s["runs"]))
    console.print(table)

    runs = store.recent_runs(5)
    if runs:
        rt = Table(title="اجراهای اخیر")
        for col in ["زمان", "پلتفرم", "new", "updated", "duplicate", "errors"]:
            rt.add_column(col)
        for r in runs:
            rt.add_row(
                (r.get("started_at") or "")[:19], r.get("platform") or "?",
                str(r.get("new_count", 0)), str(r.get("updated_count", 0)),
                str(r.get("duplicate_count", 0)), str(r.get("error_count", 0)),
            )
        console.print(rt)


@app.command()
def delete(
    phone: str = typer.Option(..., "--phone", help="شماره‌ای که همه رکوردهایش باید حذف شود"),
    db: Optional[Path] = typer.Option(None, "--db", help="مسیر دیتابیس"),
    config: Optional[Path] = ERR,
    yes: bool = typer.Option(False, "--yes", help="بدون تأیید تعاملی"),
):
    """حق حذف: حذف همه رکوردهای دارای یک شماره از دیتابیس."""
    cfg = _cfg(config)
    store = LeadStore(db or cfg.db_path)
    if not yes:
        confirm = typer.confirm(f"همه رکوردهای دارای شماره {phone} حذف شوند؟")
        if not confirm:
            raise typer.Abort()
    n = store.delete_by_phone(phone)
    console.print(f"[green]{n} رکورد حذف شد.[/green]" if n else "[yellow]رکوردی پیدا نشد.[/yellow]")


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


# ═══════════════════════════ abii torob scan ═══════════════════════════
@torob_app.command()
def scan(
    query: List[str] = typer.Option(None, "--query", "-q", help="کوئری جستجو (تکرارپذیر) — جایگزین pack"),
    pack: str = typer.Option("digital", "--pack", help="نام بسته کوئری از configs/queries.torob.yaml"),
    workers: int = typer.Option(4, "--workers", "-w", help="تعداد workerهای همزمان"),
    max_shops: int = typer.Option(100, "--max-shops", help="حداکثر فروشگاه جدید در این اجرا"),
    max_pages: int = typer.Option(3, "--max-pages", help="حداکثر صفحه جستجو برای هر کوئری"),
    min_delay: float = typer.Option(1.2, "--min-delay", help="حداقل فاصله درخواست‌ها به هر هاست (ثانیه)"),
    shop_ttl: Optional[float] = typer.Option(None, "--shop-ttl", help="TTL فروشگاه تازه‌ی‌دیده‌شده (ساعت)"),
    always_offers: bool = typer.Option(False, "--always-offers", help="خواندن offers همه محصولات (کشف فروشنده بیشتر، کندتر)"),
    web_fallback: bool = typer.Option(True, "--web-fallback/--no-web-fallback", help="اگر API فروشگاه جواب نداد/شماره نداشت → صفحه وب HTML"),
    follow_sites: bool = typer.Option(True, "--sites/--no-sites", help="بازدید از وب‌سایت اختصاصی فروشندگان (استخراج شماره/ایمیل بیشتر)"),
    base_url: Optional[str] = typer.Option(None, help="Override هاست API (تست/ماک، مثل http://127.0.0.1:8931)"),
    out: Optional[Path] = typer.Option(None, "--out", help="پوشه خروجی"),
    config: Optional[Path] = ERR,
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """اسکن ناهمگام فروشگاه‌محور: جستجو → محصولات → فروشگاه‌ها (هرکدام یک بار) → شماره تماس."""
    setup_logging(verbose)
    cfg = _cfg(config)
    if out:
        cfg.export_dir = out

    from .engine import load_query_pack, run_torob_engine

    queries = list(query) if query else load_query_pack(pack)
    preview = "، ".join(queries[:6]) + ("…" if len(queries) > 6 else "")
    console.print(f"[cyan]شروع اسکن ترب[/cyan] | کوئری‌ها ({len(queries)}): {preview}")
    outcome = run_torob_engine(
        queries, cfg, workers=workers, max_shops=max_shops, max_pages=max_pages,
        min_delay=min_delay, shop_ttl_hours=shop_ttl, api_base=base_url,
        always_offers=always_offers, web_fallback=web_fallback, follow_sites=follow_sites,
    )

    m = outcome.metrics
    console.print(Panel.fit(
        f"[bold]متریک موتور[/bold]\n"
        f"فروشگاه یکتا: {m.shops_found} | برداشت: {m.shops_fetched} | "
        f"رد‌شده (تازه): {m.shops_skipped_fresh} | بازیابی از وب: {m.shops_recovered_web} | "
        f"غنی‌سازی از سایت فروشنده: {m.sites_enriched}\n"
        f"شماره پیدا شده: {m.phones_found} | بدون شماره: {m.shops_no_phone}\n"
        f"لید: new={m.leads_new} updated={m.leads_updated} duplicate={m.leads_duplicate}\n"
        f"مدت: {m.duration_sec}s | {m.http.snapshot()}",
        title="torob engine",
    ))

    table = Table(title=f"لیدهای فروشگاهی — {len(outcome.leads)} عدد", show_lines=False)
    for col in ["#", "فروشگاه", "شماره تماس", "شهر", "کیفیت", "وضعیت"]:
        table.add_column(col, overflow="fold")
    for i, lead in enumerate(outcome.leads[:30], 1):
        table.add_row(
            str(i), (lead.seller_name or "—")[:36], ", ".join(lead.phones) or "—",
            lead.city or "—", str(lead.quality_score), lead.status,
        )
    console.print(table)
    if len(outcome.leads) > 30:
        console.print(f"[dim]… و {len(outcome.leads) - 30} مورد دیگر (در فایل خروجی)[/dim]")
    for p in outcome.export_paths.values():
        console.print(f"[cyan]خروجی:[/cyan] {p}")


@torob_app.command()
def packs():
    """فهرست بسته‌های کوئری موجود."""
    from .engine import load_query_pack
    import yaml

    p = Path("configs/queries.torob.yaml")
    if not p.exists():
        p = Path(__file__).resolve().parents[2] / "configs" / "queries.torob.yaml"
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    for name, queries in data.items():
        console.print(f"[green]{name}[/green] ({len(queries)} کوئری): {'، '.join(queries[:5])}…")


if __name__ == "__main__":
    app()
