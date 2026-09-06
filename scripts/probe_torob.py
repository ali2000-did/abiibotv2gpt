#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""کالیبراسیون ترب واقعی — این اسکریپت را روی سرور داخل ایران اجرا کنید.

    python3 probe_torob.py            # کوئری پیش‌فرض «لپ تاپ»
    python3 probe_torob.py "گوشی موبایل"

خروجی:
  • torob_probe_<date>.zip  ← حاوی پاسخ‌های خام (JSON/HTML) — همین را برای ما بفرستید
  • خلاصه‌ای از ساختار هر endpoint در ترمینال

وابستگی: فقط پایتون استاندارد (urllib) — هیچ نصبی لازم نیست.
"""
from __future__ import annotations

import datetime
import io
import json
import re
import sys
import zipfile
from urllib.request import Request, urlopen

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

PHONE_RE = re.compile(r"0?9\d{9}|9\d{9}")

STEPS = [
    # (نام، الگوی URL — {q} و {prk} و {sid} جایگزین می‌شوند)
    ("search_v4",      "https://api.torob.com/v4/base-product/search/?q={q}&size=24&page=1"),
    ("search_v4_p2",   "https://api.torob.com/v4/base-product/search/?q={q}&size=24&page=2"),
    ("detail_v2",      "https://api.torob.com/v4/base-product/detail-v2/?prk={prk}"),
    ("offers_a",       "https://api.torob.com/v4/base-product/offer-list/?prk={prk}&size=24"),
    ("offers_b",       "https://api.torob.com/v4/base-product/offers/?prk={prk}&size=24"),
    ("shop_api_a",     "https://api.torob.com/v4/shop/detail/?shop_id={sid}"),
    ("shop_api_b",     "https://api.torob.com/v4/shop/?id={sid}"),
    ("shop_web",       "https://torob.com/shop/{sid}/"),        # HTML
    ("product_web",    "https://torob.com/p/{prk}/"),           # HTML
    ("sitemap_robots", "https://torob.com/robots.txt"),
]


def fetch(url: str, timeout: float = 20.0):
    req = Request(url, headers={"User-Agent": UA, "Accept-Language": "fa,en;q=0.8"})
    try:
        with urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return None, f"ERROR: {exc}"


def keys_of(text: str, depth: int = 2) -> str:
    """خلاصه سبک از ساختار JSON (کلیدهای سطح بالا + یک سطح پایین‌تر)."""
    try:
        data = json.loads(text)
    except Exception:
        return "(not json)"
    def walk(d, lvl):
        if not isinstance(d, dict) or lvl > depth:
            return {}
        return {k: walk(v, lvl + 1) if isinstance(v, dict)
                else (f"list[{len(v)}]" if isinstance(v, list) else type(v).__name__)
                for k, v in list(d.items())[:25]}
    return json.dumps(walk(data, 1), ensure_ascii=False)


def find_ids(text: str, pattern: str):
    return list(dict.fromkeys(re.findall(pattern, text)))[:8]


def main() -> None:
    q = sys.argv[1] if len(sys.argv) > 1 else "لپ تاپ"
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = io.BytesIO()
    prk, sid = None, None
    print(f"▶ probe_torob — query='{q}'\n")

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, template in STEPS:
            url = template
            for placeholder, value in [("{q}", q), ("{prk}", prk or ""), ("{sid}", sid or "")]:
                url = url.replace(placeholder, value)
            if "{prk}" in template and not prk:
                print(f"• {name}: skip (prk هنوز مشخص نیست)")
                continue
            if "{sid}" in template and not sid:
                print(f"• {name}: skip (sid هنوز مشخص نیست)")
                continue
            status, text = fetch(url)
            ok = status == 200
            print(f"• {name}: HTTP {status} | {len(text)} chars | {url[:100]}")
            z.writestr(f"{name}.{'json' if not name.endswith(('web','robots')) and ok else 'txt'}", text)
            if not ok:
                continue
            if name == "search_v4":
                print(f"    کلیدها: {keys_of(text)}")
                m = re.search(r'"random_key"\s*:\s*"([^"]+)"', text)
                if m:
                    prk = m.group(1)
                print(f"    اولین prk: {prk}")
            elif name in ("detail_v2", "offers_a", "offers_b"):
                print(f"    کلیدها: {keys_of(text)}")
                if sid is None:
                    m = (re.search(r'"shop_id"\s*:\s*"?([\w-]+)"?', text)
                         or re.search(r'"shop"\s*:\s*{\s*"id"\s*:\s*"?([\w-]+)"?', text))
                    if m:
                        sid = m.group(1)
                        print(f"    اولین shop_id: {sid}")
            elif name.startswith("shop_api"):
                print(f"    کلیدها: {keys_of(text)}")
                phones = PHONE_RE.findall(text)
                print(f"    شماره‌های یافت‌شده در پاسخ: {phones[:5]}")
            elif name == "shop_web":
                phones = PHONE_RE.findall(text)
                print(f"    شماره در HTML خام: {phones[:5]} (خالی = فقط با دکمه نمایش شماره)")
                has_btn = "نمایش شماره" in text or "show-phone" in text.lower()
                print(f"    دکمه نمایش شماره: {'دارد' if has_btn else 'ندارد'}")
                for key in ["__NUXT__", "__NEXT_DATA__", "window.__INITIAL_STATE__"]:
                    if key in text:
                        print(f"    JSON داخلی: {key} موجود است")
            elif name == "sitemap_robots":
                print("    --- robots.txt ---")
                print("    " + "\n    ".join(text.splitlines()[:12]))

    fname = f"torob_probe_{stamp}.zip"
    with open(fname, "wb") as f:
        f.write(out.getvalue())
    print(f"\n✅ فایل {fname} ساخته شد — لطفاً همین فایل را بفرستید تا پارسرها کالیبره شوند.")
    print("   (فایل فقط پاسخ‌های عمومی ترب را دارد؛ هیچ اطلاعات شخصی شما داخلش نیست)")


if __name__ == "__main__":
    main()
