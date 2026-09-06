"""سرور ترب شبیه‌سازی‌شده — دو سطح:

  ۱) HTML (برای جریان مرورگری Playwright): صفحه اصلی/جستجو/محصول/فروشگاه
  ۲) API v4 (برای موتور ناهمگام): /v4/base-product/search | detail-v2 | offer-list | /v4/shop/detail

اجرا:  python examples/mock_sites/mock_torob.py [port]
سپس:  abii torob scan --base-url http://127.0.0.1:8931 --pack digital ...

نکته: ۵ محصول و ۴ فروشگاه اول دقیقاً مثل نسخه قبلی‌اند (تست‌های جریان مرورگر
به آن‌ها وابسته‌اند)؛ بقیه به‌صورت قطعی (seed ثابت) تولید می‌شوند.
"""
from __future__ import annotations

import json
import random
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

rng = random.Random(42)

# ═══════════════════════════════ دیتاست ═══════════════════════════════
CITIES = ["تهران", "مشهد", "اصفهان", "شیراز", "تبریز", "کرج", "اهواز", "قم", "رشت", "کرمان"]
NAME_A = ["فروشگاه", "مرکز", "پخش", "نمایندگی", "سامانه", "دیجیتال", "تک", "بازار"]
NAME_B = ["موبایل", "کامپیوتر", "دیجیتال", "پارس", "آریا", "پیشرو", "فن‌آوری", "هوش", "باران", "میترا"]

# id → dict(name, city, address, phone|None)
SHOPS: dict[str, dict] = {
    "shop-1": {"name": "فروشگاه رایان تک", "city": "تهران",
               "address": "تهران، خیابان جمهوری، پاساژ علاءالدین", "phone": "۰۹۱۲-۳۴۵-۶۷۸۹"},
    "shop-2": {"name": "کالای دیجیتال پارس", "city": "اصفهان",
               "address": "اصفهان، خیابان چهارباغ بالا", "phone": "+98 935 222 3344"},
    "shop-3": {"name": "موبایل شهر", "city": "شیراز",
               "address": "شیراز، بلوار زند", "phone": "۰۲۱-۸۸۷۷۶۶۵۵"},
    "shop-4": {"name": "پخش باران", "city": "تهران",
               "address": "تهران، بازار بزرگ، راسته لوازم جانبی", "phone": None},
}

_TO_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
_PHONE_FORMATS = [
    # همه فرمت‌ها معتبر ۱۱ رقمی: 09 + ۹ رقم
    lambda i: f"0912{i % 10000000:07d}",                              # ساده انگلیسی
    lambda i: f"0935 {300 + i % 700} {i % 10000:04d}".translate(_TO_FA_DIGITS),  # فارسی با فاصله
    lambda i: f"+98 919 {300 + i % 600} {i % 10000:04d}",             # بین‌المللی
    lambda i: f"0913-{400 + i % 500}-{i % 10000:04d}",                # تیره‌دار
]

# تولید shop-5 .. shop-44
for i in range(5, 45):
    sid = f"shop-{i}"
    has_phone = rng.random() < 0.8  # ۲۰٪ بدون شماره (فقط چت)
    phone = _PHONE_FORMATS[i % 4](i) if has_phone else None
    SHOPS[sid] = {
        "name": f"{NAME_A[i % 8]} {NAME_B[(i * 3) % 10]} {i}",
        "city": CITIES[i % 10],
        "address": f"{CITIES[i % 10]}، خیابان {['ولیعصر','آزادی','انقلاب','شریعتی','فردوسی'][i % 5]}، پلاک {10 + i}",
        "phone": phone,
    }

# فروشگاه‌هایی که شماره‌شان فقط با دکمه «نمایش شماره» در دسترس است (API حذف می‌کند)
PHONE_BEHIND_BUTTON = {f"shop-{i}" for i in range(8, 45, 4)} & {
    s for s, d in SHOPS.items() if d["phone"]
}

TITLE_WORDS = ["لپ تاپ", "گوشی موبایل", "تبلت", "هدفون", "پاور بانک", "هارد اکسترنال",
               "قطعات کامپیوتر", "ساعت هوشمند", "مانیتور", "کیف و کاور گوشی"]
BRANDS = ["ایسوس", "لنوو", "سامسونگ", "شیائومی", "اچ‌پی", "دل", "اپل", "ال‌جی"]

# id → dict(title, price, shops[], desc?)
PRODUCTS: dict[str, dict] = {
    "prk-1": {"title": "لپ تاپ ایسوس ۱۵ اینچ مدل VivoBook X1504",
              "price": "۴۵٬۵۰۰٬۰۰۰ تومان", "shops": ["shop-1"]},
    "prk-2": {"title": "لپ تاپ لنوو IdeaPad 3 — قطع اورجینال",
              "price": "۳۸٬۷۰۰٬۰۰۰ تومان", "shops": ["shop-2"]},
    "prk-3": {"title": "لپ تاپ گیمینگ MSI Katana با گارانتی",
              "price": "۶۲٬۰۰۰٬۰۰۰ تومان", "shops": ["shop-3"],
              "desc": "ارسال از تهران، برای استعلام موجودی با ۰۹۱۲ ۴۴۵ ۶۶۷۷ تماس بگیرید."},
    "prk-4": {"title": "قاب گوشی مدل ضدضربه — پخش عمده",
              "price": "۹۵٬۰۰۰ تومان", "shops": ["shop-4"]},
    "prk-5": {"title": "مانیتور ۲۴ اینچ ال‌جی نو آکبند",
              "price": "۸٬۹۰۰٬۰۰۰ تومان", "shops": []},
}

# تولید prk-6 .. prk-135 (عنوان‌ها با کلمات دیجیتال؛ «لپ تاپ» پرتکرار)
for j in range(6, 136):
    word = TITLE_WORDS[j % 10] if j % 10 != 9 else "لپ تاپ"
    if j % 3 == 0:
        word = "لپ تاپ"
    brand = BRANDS[j % 8]
    n_shops = rng.choice([1, 1, 2, 3])
    shop_ids = rng.sample(list(SHOPS), n_shops)
    PRODUCTS[f"prk-{j}"] = {
        "title": f"{word} {brand} مدل {1000 + j}",
        "price": f"{rng.randint(3, 900) * 100000:,} تومان",
        "shops": shop_ids,
    }

ALL_PRKS = list(PRODUCTS)  # ترتیب پایدار: اول ۵ محصول ثابت

# ═══════════════════════════════ HTML ═══════════════════════════════
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


def page_html(title: str, body: str) -> bytes:
    return f"""<!DOCTYPE html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
<title>{title} | ترب</title>{STYLE}</head><body>{body}</body></html>""".encode()


def _header(q: str = "") -> str:
    return f"""
<header><div class="logo">ترب</div>
<form action="/search" method="get">
  <input name="q" value="{q}" placeholder="نام کالا را جستجو کنید…">
  <button type="submit">جستجو</button>
</form></header>"""


def home() -> bytes:
    return page_html("ترب — جستجوی محصولات", f"""
{_header()}
<main><h2>جستجوی هوشمند محصولات</h2>
<p>در ترب بین هزاران فروشگاه جستجو کنید.</p></main>""")


def match_prks(q: str) -> list[str]:
    q = (q or "").strip()
    if not q:
        return ALL_PRKS
    return [p for p in ALL_PRKS if q in PRODUCTS[p]["title"]]


def search_html(q: str) -> bytes:
    items = "\n".join(
        f'<a class="product" href="/p/{prk}">{PRODUCTS[prk]["title"]} — '
        f'<span class="price">{PRODUCTS[prk]["price"]}</span></a>'
        for prk in match_prks(q)
    )
    return page_html(f"جستجوی {q}", f"""
{_header(q)}
<main><h2>نتایج جستجو برای «{q}»</h2>{items}</main>""")


def product_html(prk: str) -> bytes:
    p = PRODUCTS.get(prk)
    if not p:
        return page_html("پیدا نشد", "<main>محصول یافت نشد</main>")
    desc = f"<p>{p['desc']}</p>" if p.get("desc") else ""
    if p["shops"]:
        shop_name = SHOPS[p["shops"][0]]["name"]
        seller = f"""
<div class="seller-box">
  <b>فروشنده:</b> <a href="/shop/{p['shops'][0]}/">{shop_name}</a>
  <p style="color:#666">برای دیدن مشخصات و تماس، روی نام فروشنده کلیک کنید.</p>
</div>"""
    else:
        seller = """
<div class="seller-box">
  <b>فروشنده:</b> فروشنده حضوری
  <p style="color:#666">این فروشنده فقط از طریق چت در دسترس است.</p>
</div>"""
    return page_html(p["title"], f"""
{_header()}
<main><h1>{p["title"]}</h1><p class="price">{p["price"]}</p>{desc}{seller}</main>""")


def shop_html(sid: str) -> bytes:
    s = SHOPS.get(sid)
    if not s:
        return page_html("پیدا نشد", "<main>فروشگاه یافت نشد</main>")
    if s["phone"]:
        phone_html = f"""
<p><b>شماره تماس:</b>
  <button onclick="document.getElementById('ph').style.display='inline'">نمایش شماره</button>
  <span id="ph" style="display:none; font-size:17px">{s['phone']}</span>
</p>"""
    else:
        phone_html = "<p><b>تماس:</b> فقط از طریق پیام دایرکت ترب</p>"
    return page_html(s["name"], f"""
{_header()}
<main><h1>{s['name']}</h1><p><b>شهر:</b> {s['city']}</p>
<p><b>آدرس:</b> {s['address']}</p>{phone_html}</main>""")


# ═══════════════════════════════ API v4 ═══════════════════════════════
def api_search(q: str, page: int, size: int) -> dict:
    prks = match_prks(q)
    start = (max(1, page) - 1) * size
    batch = prks[start:start + size]
    return {
        "count": len(prks),
        "results": [
            {"random_key": prk, "name1": PRODUCTS[prk]["title"],
             "price_text": PRODUCTS[prk]["price"]}
            for prk in batch
        ],
    }


def api_detail(prk: str) -> dict:
    p = PRODUCTS.get(prk)
    if not p:
        return {"error": "not found"}
    primary = p["shops"][0] if p["shops"] else None
    return {
        "random_key": prk,
        "name1": p["title"],
        "price_text": p["price"],
        "shop_id": primary,
        "shop": ({"id": primary, "name": SHOPS[primary]["name"],
                  "city": SHOPS[primary]["city"]} if primary else None),
    }


def api_offers(prk: str) -> dict:
    p = PRODUCTS.get(prk)
    if not p:
        return {"error": "not found"}
    offers = [
        {"shop_id": sid, "shop_name": SHOPS[sid]["name"],
         "price_text": p["price"], "in_stock": True, "seller_key": f"sk{idx}"}
        for idx, sid in enumerate(p["shops"])
    ]
    return {"result": {"offer_list": offers, "count": len(offers)}}


def api_shop(sid: str) -> dict:
    s = SHOPS.get(sid)
    if not s:
        return {"error": "not found"}
    phone = s["phone"] if sid not in PHONE_BEHIND_BUTTON else None
    out = {
        "shop_id": sid, "id": sid,
        "name": s["name"], "shop_name": s["name"],
        "city": s["city"], "address": s["address"],
    }
    if phone:
        out["phone"] = phone  # فیلد شماره — برخی پاسخ‌های واقعی این را حذف می‌کنند
    return out


# ═══════════════════════════════ Router ═══════════════════════════════
class Handler(BaseHTTPRequestHandler):
    def _send(self, body: bytes, ctype: str = "text/html; charset=utf-8"):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        path = u.path

        # --- API v4 ---
        if path.startswith("/v4/base-product/search"):
            q = qs.get("q", [""])[0]
            page = int(qs.get("page", ["1"])[0] or 1)
            size = int(qs.get("size", ["24"])[0] or 24)
            return self._send(json.dumps(api_search(q, page, size), ensure_ascii=False).encode(),
                              "application/json")
        if path.startswith("/v4/base-product/detail-v2"):
            return self._send(json.dumps(api_detail(qs.get("prk", [""])[0]), ensure_ascii=False).encode(),
                              "application/json")
        if path.startswith("/v4/base-product/offer-list") or path.startswith("/v4/base-product/offers"):
            return self._send(json.dumps(api_offers(qs.get("prk", [""])[0]), ensure_ascii=False).encode(),
                              "application/json")
        if path.startswith("/v4/shop/"):
            return self._send(json.dumps(api_shop(qs.get("shop_id", qs.get("id", [""])[0])[0]),
                                         ensure_ascii=False).encode(), "application/json")

        # --- HTML ---
        if path in ("", "/"):
            body = home()
        elif path == "/search":
            body = search_html(qs.get("q", [""])[0])
        elif path.startswith("/p/"):
            body = product_html(path.split("/p/", 1)[1].strip("/"))
        elif path.startswith("/shop/"):
            body = shop_html(path.split("/shop/", 1)[1].strip("/"))
        else:
            self.send_error(404)
            return
        self._send(body)

    def log_message(self, fmt, *args):  # لاگ کم‌نویز
        path = self.path.split("?")[0] + (f"?q={parse_qs(urlparse(self.path).query).get('q', [''])[0]}"
                                          if "?" in self.path else "")
        if path.startswith("/v4"):
            print(f"[mock-torob] GET {self.path[:90]}", flush=True)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8931
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"[mock-torob] http://0.0.0.0:{port} — {len(PRODUCTS)} محصول، {len(SHOPS)} فروشگاه "
          f"({len(PHONE_BEHIND_BUTTON)} فروشگاه با شماره فقط-دکمه)", flush=True)
    srv.serve_forever()
