"""تشخیص و اعتبارسنجی شماره تلفن ایران — قلب Data Recognizer.

پشتیبانی:
  - اعداد فارسی (۰-۹) و عربی (٠-٩) → انگلیسی
  - موبایل: 09xxxxxxxxx | +989xxxxxxxxx | 00989... | 989... | 9xxxxxxxxx (بدون صفر)
  - جداسازها: فاصله، تیره، نقطه، پرانتز  →  0912-345-6789
  - ثابت: 02112345678 | 021-12345678 | +9821 12345678 (با کد شهر معتبر)
  - حذف نویسه‌های نامرئی رایج متن فارسی (نیم‌فاصله و علائم RTL)

اعتبارسنجی:
  - پیش‌شماره موبایل باید در لیست پیش‌شماره‌های اختصاص‌یافته باشد
  - کد شهر ثابت باید معتبر باشد
  - عدد کوتاه/بلند، قیمت‌ها و شناسه‌های رند به‌عنوان شماره تشخیص داده نمی‌شوند
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# ---------- نرمال‌سازی ارقام ----------
_FA = "۰۱۲۳۴۵۶۷۸۹"
_AR = "٠١٢٣٤٥٦٧٨٩"
_TO_EN = str.maketrans(_FA + _AR, "0123456789" * 2)

# نویسه‌های نامرئی: نیم‌فاصله ZWNJ، علائم LTR/RTL mark، جداکننده‌های bidi، nbsp
_INVISIBLE = {ord(c): None for c in "\u200c\u200f\u200e\u2066\u2067\u2068\u2069"}
_INVISIBLE[0x00A0] = " "  # nbsp → فاصله معمولی


def to_english_digits(text: str) -> str:
    return text.translate(_TO_EN)


def scrub_text(text: str) -> str:
    """تبدیل ارقام + حذف نویسه‌های نامرئی — پیش‌نیاز هر استخراجی از متن فارسی."""
    return to_english_digits(text).translate(_INVISIBLE)


# ---------- پیش‌شماره‌های معتبر ----------
# پیش‌شماره‌های ۳ رقمی موبایل ایران (بدون صفر ابتدایی)
MOBILE_PREFIXES = frozenset(
    {
        # همراہ اول (MCI)
        "910", "911", "912", "913", "914", "915", "916", "917", "918", "919",
        # 092x
        "920", "921", "922", "923",
        # ایرانسل
        "930", "931", "932", "933",
        # رایتل / تالیا / سایر
        "934", "935", "936", "937", "938", "939",
        # 099x
        "990", "991", "992", "993", "994", "995", "996",
    }
)

# کدهای شهر ۲ رقمی (بدون صفر ابتدایی)
LANDLINE_AREA_CODES = frozenset(
    {
        "21",  # تهران
        "26",  # البرز/کرج
        "31",  # اصفهان
        "34",  # کرمان
        "41",  # آذربایجان شرقی
        "44",  # آذربایجان غربی
        "45",  # اردبیل
        "51",  # خراسان رضوی
        "54",  # سیستان و بلوچستان
        "56",  # هرمزگان
        "58",  # خراسان جنوبی
        "61",  # خوزستان
        "66",  # لرستان
        "71",  # فارس
        "74",  # کرمانشاه
        "76",  # کهگیلویه
        "77",  # بوشهر
        "81",  # قم
        "83",  # مرکزی
        "84",  # همدان
        "86",  # گلستان
        "87",  # قزوین
        "28",  # خراسان شمالی (NEW)
        "38",  # یزد
    }
)

# ---------- الگوها ----------
_SEP = r"[\s\-.\u2013\u2014()]*"  # فاصله، تیره (کوتاه/بلند)، نقطه، پرانتز

_MOBILE_RE = re.compile(
    r"""
    (?<![\d])                      # قبل: مرز عدد
    (?:\+98|0098|98|0)?            # کد کشور یا صفر ابتدایی (اختیاری)
    (9\d{2})                       # پیش‌شماره اپراتور
    """ + _SEP + r"""
    (\d{3})
    """ + _SEP + r"""
    (\d{4})
    (?!\d)                         # بعد: مرز عدد
    """,
    re.VERBOSE,
)

_LANDLINE_RE = re.compile(
    r"""
    (?<![\d])
    (?:\+98|0098|98|0)?
    (\d{2})                        # کد شهر
    """ + _SEP + r"""
    (\d{8})                        # شماره ۸ رقمی
    (?!\d)
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class PhoneHit:
    raw: str
    number: str  # ملی: 09123456789 یا 02112345678
    e164: str  # بین‌المللی: +989123456789
    kind: str  # mobile | landline

    @property
    def is_mobile(self) -> bool:
        return self.kind == "mobile"


def _to_e164(national: str) -> str:
    return "+98" + national.lstrip("0")


def extract_phones(text: str, include_landline: bool = True) -> list[PhoneHit]:
    """استخراج همه شماره‌های معتبر از متن (فارسی یا انگلیسی)."""
    if not text:
        return []
    text = scrub_text(text)
    hits: list[PhoneHit] = []
    taken: list[tuple[int, int]] = []

    for m in _MOBILE_RE.finditer(text):
        prefix = m.group(1)
        if prefix not in MOBILE_PREFIXES:
            continue
        number = "0" + prefix + m.group(2) + m.group(3)
        hits.append(PhoneHit(m.group(0), number, _to_e164(number), "mobile"))
        taken.append(m.span())

    if include_landline:
        for m in _LANDLINE_RE.finditer(text):
            # اگر داخل محدوده یک موبایل قبلاً match شده، رد کن
            s, e = m.span()
            if any(s < te and ts < e for ts, te in taken):
                continue
            area = m.group(1)
            if area not in LANDLINE_AREA_CODES:
                continue
            number = "0" + area + m.group(2)
            hits.append(PhoneHit(m.group(0), number, _to_e164(number), "landline"))
            taken.append((s, e))

    # حذف تکراری با حفظ ترتیب
    seen: set[str] = set()
    unique: list[PhoneHit] = []
    for h in hits:
        if h.number not in seen:
            seen.add(h.number)
            unique.append(h)
    return unique


def extract_phone_numbers(text: str, mobile_only: bool = False) -> list[str]:
    """نسخه ساده: فقط لیست شماره‌های ملی."""
    return [h.number for h in extract_phones(text, include_landline=not mobile_only)]


def is_valid_mobile(number: str) -> bool:
    """اعتبارسنجی یک شماره از پیش نرمال‌شده (09xxxxxxxxx)."""
    n = scrub_text(number).replace(" ", "").replace("-", "")
    if n.startswith("+98"):
        n = "0" + n[3:]
    elif n.startswith("0098"):
        n = "0" + n[4:]
    elif n.startswith("98") and len(n) == 12:
        n = "0" + n[2:]
    return bool(re.fullmatch(r"09\d{9}", n)) and n[1:4] in MOBILE_PREFIXES
