# AbiiBot — ربات استخراج لید (شماره تماس فروشندگان)

ربات استخراجگر داده برای پلتفرم‌های نیازمندی ایران: **دیوار**، **ترب** و هر **سایت فروشنده** عمومی.
یک **محصول هدف** می‌گیرد → فروشنده‌هایش را پیدا می‌کند → سایت/صفحه هر فروشنده را باز می‌کند →
**شماره تماس** (و ایمیل/نام/شهر/سایت) را استخراج می‌کند → اکسل تمیز بدون تکراری تحویل می‌دهد.

📘 **سند معماری**: [`docs/ARCHITECTURE.fa.md`](docs/ARCHITECTURE.fa.md)
📗 **سند پلتفرم‌ها**: [`docs/PLATFORMS.fa.md`](docs/PLATFORMS.fa.md)
🚀 **راهنمای نصب روی سرور (شروع از اینجا)**: [`docs/DEPLOY.fa.md`](docs/DEPLOY.fa.md)
🔍 **گزارش ممیزی**: [`docs/AUDIT.fa.md`](docs/AUDIT.fa.md)

---

## ⚡ فعال‌سازی خودکار — یک فرمان (پیشنهادی برای سرور)

```bash
bash activate.sh
```

همه‌چیز خودکار و با راستی‌آزمایی: نصب ← تست سلامت آفلاین ← سرویس دائمی
(systemd؛ User و مسیرها خودکار تشخیص داده می‌شوند — بدون ویرایش دستی) ←
شروع فوری + اثبات شروع اولین دور. اگر systemd در دسترس نبود، خودش به
cron و بعد nohup برمی‌گردد. سایر حالت‌ها: `--status` (وضعیت)، `--once`
(یک دور)، `--off` (توقف).

## 🖥 داشبورد زنده — «ربات فعاله؟ الان داره چیکار می‌کنه؟»

`activate.sh` همراه ربات، **داشبورد وب** را هم روی پورت ۸۵۰۱ فعال می‌کند:
نشانگر سبزِ فعال/متوقف، فعالیت لحظه‌ای (در حال اسکن دور چند / خواب تا دور
بعد با شمارش معکوس)، آمار لید/شماره، نتیجه دور آخر و **لاگ زنده** — همه
فارسی، راست‌به‌چپ، بدون نیاز به اینترنت (بدون CDN). آدرس + توکن دسترسی
پایانِ فعال‌سازی چاپ می‌شود. اجرای دستی: `abii dashboard`.

## نصب (دستی، برای توسعه)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## تست و دموی آفلاین (بدون اینترنت)

```bash
pytest        # ۴۰ تست واحد/یکپارچگی
abii demo     # اجرای کامل pipeline روی فیکسچرهای نمونه + خروجی CSV/XLSX
```

## اجرای زنده (نیاز به اینترنت ایران دارد)

```bash
# دیوار: آپارتمان‌های فروشی تهران
abii run -p divar --city tehran --category buy-apartment --max-items 20 --max-pages 2

# ترب: جستجوی محصول
abii run -p torob --query "لپ تاپ" --max-items 20

# وب عمومی: لیست URL فروشندگان
abii run -p web --urls-file urls.txt
abii run -p web --url https://example-shop.ir/contact --url https://other.ir

# خروجی‌گیری مجدد از دیتابیس
abii export --format xlsx
```

## 🤖 جریان مرورگری کاربرگونه (Playwright + Chromium) — فاز ۲

رفتار دقیقاً مثل یک کاربر: وارد سایت می‌شود، عبارت را حرف‌به‌حرف تایپ می‌کند،
روی محصولات نتایج کلیک می‌کند، وارد صفحه فروشنده می‌شود، دکمه «نمایش شماره»
را می‌زند و شماره را کپی می‌کند؛ سپس محصول بعدی.

```bash
# نصب کرومیوم (یک بار) — اگر CDN پلی‌رایت فیلتر بود، خودش از npm نصب می‌کند
bash scripts/setup_browser.sh

# اجرا روی ترب واقعی (داخل ایران) — پنجره مرورگر قابل مشاهده + ضبط ویدیو
abii browse -p torob --query "لپ تاپ" --max-products 10 --headed --record

# اجرای شبیه‌سازی‌شده بدون اینترنت (روی سرور ماک محلی — برای تست/دمو)
python examples/mock_sites/mock_torob.py 8931 &
abii browse -p torob --query "لپ تاپ" --base-url http://127.0.0.1:8931 --record
```

- ویدیو + اسکرین‌شات هر قدم در `sessions/<timestamp>/` ذخیره می‌شود
- سلکتورهای ترب در `configs/selectors.torob.yaml` — اگر ساختار سایت عوض شد فقط همین فایل را به‌روز کنید
- تایپ انسانی (تأخیر تصادفی بین حروف)، مکث‌های تصادفی، اسکرول طبیعی، حذف نشانه‌های اتوماسیون
- شماره‌های پشت دکمه «نمایش شماره» با کلیک واقعی استخراج می‌شوند (چیزی که در سورس HTML نیست!)

## ⚡ موتور پرفورمنس ترب (async) — `abii torob scan`

اسکن ناهمگامِ فروشگاه‌محور: محصولات فقط راهِ کشف فروشگاه‌ها هستند؛ هر فروشگاه
**یک بار** fetch می‌شود؛ اسکن افزایشی (فروشگاه تازه دیده‌شده رد می‌شود)؛
کندسازی تطبیقی هنگام 429/5xx؛ متریک کامل.

```bash
# روی ترب واقعی (سرور ایران):
abii torob scan --pack digital --max-shops 100 --workers 4 --min-delay 1.2
abii torob scan --query "لپ تاپ" --query "تبلت" --max-shops 50
abii torob packs                                   # فهرست بسته‌های کوئری

# تست بدون اینترنت روی ماک:
python examples/mock_sites/mock_torob.py 8931 &
abii torob scan --base-url http://127.0.0.1:8931 --pack digital --min-delay 0.02
```

**کالیبراسیون با ترب واقعی**: روی سرور ایران `python3 scripts/probe_torob.py` را
اجرا کنید و فایل zip ساخته‌شده را بفرستید تا endpointها دقیق شوند (بدون این
قدم، اجرای زنده روی ساختار احتمالاً متفاوت API ممکن است خطا دهد).

## 🧹 مدیریت داده (حق حذف و آمار)

```bash
abii stats                          # آمار دیتابیس + اجراهای اخیر
abii delete --phone 09123456789     # حذف همه رکوردهای یک شماره (حق حذف)
```

ممیزی کامل فنی با نمره‌دهی: [`docs/AUDIT.fa.md`](docs/AUDIT.fa.md)

## تنظیمات (اختیاری)

```yaml
# config.yaml
db_path: data/leads.db
export_dir: exports
export_formats: [csv, xlsx]
politeness:
  min_delay: 3.0      # فاصله حداقلی بین درخواست‌ها (ثانیه)
  max_retries: 3
proxies:              # اختیاری
  - "http://user:pass@proxy:port"
endpoints:            # اگر ساختار پلتفرم عوض شد، فقط همینجا را عوض کنید
  divar_search: "https://api.divar.ir/api/v1/post2/w/{city}/{category}"
```

```bash
abii run --config config.yaml -p divar --city tehran --category mobile-phones
```

## ساختار پروژه

```
src/abii_bot/
├── cli.py          دستورات abii (run/demo/export/browse)
├── runner.py       ارکستراتور pipeline (حالت API)
├── browser/        جریان مرورگری کاربرگونه (Playwright) — فاز ۲
├── crawler/        HttpFetcher (rate-limit/proxy/retry) + BrowserFetcher
├── platforms/      آداپتور divar / torob / web + registry
├── extraction/     تشخیص شماره ایرانی (ارقام فارسی، +98، پیش‌شماره‌ها) + ایمیل
├── pipeline/       پاکسازی + dedupe + امتیاز کیفیت
└── storage/        SQLite + خروجی CSV/XLSX(RTL)/JSON
```

## ⚠️ نکته حقوقی

شماره‌های استخراج‌شده «داده شخصی» هستند و شرایط استفاده دیوار/ترب جمع‌آوری
خودکار را ممنوع کرده است. استفادهٔ مسئولانه (تماس هدفمند، بدون اسپم) و
رعایت قوانین جرایم رایانه‌ای بر عهده کاربر است — جزئیات در
[سند معماری، بخش ۳](docs/ARCHITECTURE.fa.md).
