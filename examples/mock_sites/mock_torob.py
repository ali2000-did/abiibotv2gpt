"""سرور ترب شبیه‌سازی‌شده — برای تست و دموی جریان مرورگری بدون دسترسی به ترب واقعی.

اجرا:  python examples/mock_sites/mock_torob.py [port]
سپس:   abii browse -p torob --query "لپ تاپ" --base-url http://127.0.0.1:8931 ...

ساختار دقیقاً مثل ترب: صفحه اصلی با جستجو → نتایج (لینک‌های /p/) →
صفحه محصول با کارت فروشنده (لینک /shop/) → صفحه فروشگاه با شماره پشت
دکمه «نمایش شماره».
"""
from __future__ import annotations

import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

STYLE = """
<style>
  body { font-family: Vazirmatn, Tahoma, sans-serif; direction: rtl; margin: 0; background: #f5f5f5; }
  header { background: #e61737; color: #fff; padding: 18px 24px; display: flex; gap: 16px; align-items: center; }
  header .logo { font-size: 22px; font-weight: bold; }
  input[name=q] { flex: 1; max-width: 520px; padding: 10px 14px; border: none; border-radius: 8px; font-size: 15px; font-family: inherit; }
  main { max-width: 860px; margin: 24px auto; background: #fff; border-radius: 12px; padding: 20px; }
  a.product { display: block; padding: 14px; border-bottom: 1px solid #eee; text-decoration: none; color: #222; font-size: 16px; }
  a.product:hover { background: #fafafa; }
  .price { color: #e61737; font-weight: bold; }
  .seller-box { border: 1px solid #ddd; border-radius: 10px; padding: 14px; margin-top: 16px; }
  button { background: #e61737; color: #fff; border: none; border-radius: 8px; padding: 9px 18px; font-family: inherit; font-size: 14px; cursor: pointer; }
</style>
"""

PRODUCTS = {
    "prk-1": ("لپ تاپ ایسوس ۱۵ اینچ مدل VivoBook X1504", "۴۵٬۵۰۰٬۰۰۰ تومان", "shop-1", None),
    "prk-2": ("لپ تاپ لنوو IdeaPad 3 — قطع اورجینال", "۳۸٬۷۰۰٬۰۰۰ تومان", "shop-2", None),
    "prk-3": ("لپ تاپ گیمینگ MSI Katana با گارانتی", "۶۲٬۰۰۰٬۰۰۰ تومان", "shop-3",
              "ارسال از تهران، برای استعلام موجودی با ۰۹۱۲ ۴۴۵ ۶۶۷۷ تماس بگیرید."),
    "prk-4": ("قاب گوشی مدل ضدضربه — پخش عمده", "۹۵٬۰۰۰ تومان", "shop-4", None),
    "prk-5": ("مانیتور ۲۴ اینچ ال‌جی نو آکبند", "۸٬۹۰۰٬۰۰۰ تومان", None, None),
}

SHOPS = {
    "shop-1": ("فروشگاه رایان تک", "تهران، خیابان جمهوری، پاساژ علاءالدین", "۰۹۱۲-۳۴۵-۶۷۸۹"),
    "shop-2": ("کالای دیجیتال پارس", "اصفهان، خیابان چهارباغ بالا", "+98 935 222 3344"),
    "shop-3": ("موبایل شهر", "شیراز، بلوار زند", "۰۲۱-۸۸۷۷۶۶۵۵"),
    "shop-4": ("پخش باران", "تهران، بازار بزرگ، راسته لوازم جانبی", None),
}


def page_html(title: str, body: str) -> bytes:
    return f"""<!DOCTYPE html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
<title>{title} | ترب</title>{STYLE}</head><body>{body}</body></html>""".encode()


def home() -> bytes:
    return page_html("ترب — جستجوی محصولات", f"""
<header><div class="logo">ترب</div>
<form action="/search" method="get">
  <input name="q" placeholder="نام کالا را جستجو کنید…">
  <button type="submit">جستجو</button>
</form></header>
<main><h2>جستجوی هوشمند محصولات</h2>
<p>در ترب بین هزاران فروشگاه جستجو کنید.</p></main>""")


def search(q: str) -> bytes:
    items = "\n".join(
        f'<a class="product" href="/p/{prk}">{t} — <span class="price">{p}</span></a>'
        for prk, (t, p, _, _) in PRODUCTS.items()
    )
    return page_html(f"جستجوی {q}", f"""
<header><div class="logo">ترب</div>
<form action="/search" method="get">
  <input name="q" value="{q}">
  <button type="submit">جستجو</button>
</form></header>
<main><h2>نتایج جستجو برای «{q}»</h2>{items}</main>""")


def product(prk: str) -> bytes:
    if prk not in PRODUCTS:
        return page_html("پیدا نشد", "<main>محصول یافت نشد</main>")
    title, price, shop, desc = PRODUCTS[prk]
    desc_html = f"<p>{desc}</p>" if desc else ""
    if shop and shop in SHOPS:
        shop_name = SHOPS[shop][0]
        seller = f"""
<div class="seller-box">
  <b>فروشنده:</b> <a href="/shop/{shop}/">{shop_name}</a>
  <p style="color:#666">برای دیدن مشخصات و تماس، روی نام فروشنده کلیک کنید.</p>
</div>"""
    else:
        seller = """
<div class="seller-box">
  <b>فروشنده:</b> فروشنده حضوری
  <p style="color:#666">این فروشنده فقط از طریق چت در دسترس است.</p>
</div>"""
    return page_html(title, f"""
<header><div class="logo">ترب</div>
<form action="/search" method="get"><input name="q"><button type="submit">جستجو</button></form></header>
<main>
  <h1>{title}</h1>
  <p class="price">{price}</p>
  {desc_html}
  {seller}
</main>""")


def shop(sid: str) -> bytes:
    if sid not in SHOPS:
        return page_html("پیدا نشد", "<main>فروشگاه یافت نشد</main>")
    name, address, phone = SHOPS[sid]
    if phone:
        phone_html = f"""
<p><b>شماره تماس:</b>
  <button onclick="document.getElementById('ph').style.display='inline'">نمایش شماره</button>
  <span id="ph" style="display:none; font-size:17px">{phone}</span>
</p>"""
    else:
        phone_html = "<p><b>تماس:</b> فقط از طریق پیام دایرکت ترب</p>"
    return page_html(name, f"""
<header><div class="logo">ترب</div>
<form action="/search" method="get"><input name="q"><button type="submit">جستجو</button></form></header>
<main>
  <h1>{name}</h1>
  <p><b>آدرس:</b> {address}</p>
  {phone_html}
</main>""")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        u = urlparse(self.path)
        if u.path == "/" or u.path == "":
            body = home()
        elif u.path == "/search":
            q = parse_qs(u.query).get("q", [""])[0]
            body = search(q)
        elif u.path.startswith("/p/"):
            body = product(u.path.split("/p/", 1)[1].strip("/"))
        elif u.path.startswith("/shop/"):
            body = shop(u.path.split("/shop/", 1)[1].strip("/"))
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # لاگ تمیزتر
        path = self.path if len(self.path) < 80 else self.path[:80] + "…"
        print(f"[mock-torob] GET {path}", flush=True)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8931
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"[mock-torob] http://0.0.0.0:{port}  (Ctrl+C برای توقف)", flush=True)
    srv.serve_forever()
