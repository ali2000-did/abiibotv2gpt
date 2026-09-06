# AbiiBot — ربات استخراج لید (شماره تماس فروشندگان)

ربات استخراجگر داده برای پلتفرم‌های نیازمندی ایران: **دیوار**، **ترب** و هر **سایت فروشنده** عمومی.
وارد حوزه مشخص (شهر/دسته/کوئری) می‌شود، آگهی‌ها را یکی‌یکی باز می‌کند، شماره تماس و فیلدهای
خواسته‌شده را استخراج می‌کند و دیتابیس تمیز + خروجی اکسل/CSV بدون تکراری می‌سازد.

📘 **سند معماری کامل**: [`docs/ARCHITECTURE.fa.md`](docs/ARCHITECTURE.fa.md)
📗 **سند فنی پلتفرم‌ها**: [`docs/PLATFORMS.fa.md`](docs/PLATFORMS.fa.md)

---

## نصب

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
