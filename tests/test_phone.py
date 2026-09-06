"""تست ماژول تشخیص شماره ایرانی — مهم‌ترین اجزای Data Recognizer."""
import pytest

from abii_bot.extraction.phone import (
    extract_phones,
    extract_phone_numbers,
    is_valid_mobile,
    to_english_digits,
)


class TestMobileExtraction:
    @pytest.mark.parametrize("text,expected", [
        ("09123456789", ["09123456789"]),                          # ساده
        ("۰۹۱۲۳۴۵۶۷۸۹", ["09123456789"]),                          # ارقام فارسی
        ("+98 912 345 6789", ["09123456789"]),                     # کد کشور + فاصله
        ("+98-912-345-6789", ["09123456789"]),                     # تیره
        ("00989123456789", ["09123456789"]),                       # 0098
        ("989123456789", ["09123456789"]),                         # بدون صفر
        ("9123456789", ["09123456789"]),                           # بدون پیش‌شماره صفر
        ("0912-345-6789", ["09123456789"]),                        # جداکننده
        ("تماس: ۰۹۱۲ ۳۴۵ ۶۷۸۹ بگیرید", ["09123456789"]),           # داخل جمله فارسی
        ("tel: (0935) 123.4567", ["09351234567"]),                 # پرانتز و نقطه
        ("۰۹۹۰۱۲۳۴۵۶۷ و 0936-123-4567", ["09901234567", "09361234567"]),  # دو شماره
    ])
    def test_formats(self, text, expected):
        assert extract_phone_numbers(text, mobile_only=True) == expected

    @pytest.mark.parametrize("text", [
        "0912345678",            # یک رقم کم
        "091234567891",          # یک رقم زیاد
        "09501234567",           # پیش‌شماره نامعتبر (950)
        "قیمت: 2,500,000 تومان",  # قیمت
        "45000000",              # عدد رند
        "شناسه ملی: 1234567890", # شناسه ۱۰ رقمی با پیش‌شماره نامعتبر
        "کد پیگیری 87654321",    # عدد کوتاه
    ])
    def test_invalid_or_noise(self, text):
        assert extract_phone_numbers(text, mobile_only=True) == []


class TestLandlineExtraction:
    @pytest.mark.parametrize("text,expected", [
        ("02112345678", ["02112345678"]),
        ("۰۲۱-۱۲۳۴۵۶۷۸", ["02112345678"]),
        ("+9821 88776655", ["02188776655"]),
        ("تلفن: 031-37778899", ["03137778899"]),
    ])
    def test_landline_formats(self, text, expected):
        assert [h.number for h in extract_phones(text) if h.kind == "landline"] == expected

    def test_mobile_priority(self):
        """هم موبایل هم ثابت — موبایل باید اول لیست باشد."""
        hits = extract_phones("09123456789 و 02112345678")
        assert hits[0].number == "09123456789"
        assert {h.number for h in hits} == {"09123456789", "02112345678"}

    def test_e164(self):
        hits = extract_phones("09123456789")
        assert hits[0].e164 == "+989123456789"


class TestHelpers:
    def test_to_english_digits(self):
        assert to_english_digits("۱۲۳۴۵") == "12345"
        assert to_english_digits("٠١٢") == "012"

    @pytest.mark.parametrize("num,valid", [
        ("09123456789", True),
        ("+989121234567", True),
        ("0912 345 6789", True),
        ("09501234567", False),
        ("12345", False),
    ])
    def test_is_valid_mobile(self, num, valid):
        assert is_valid_mobile(num) is valid

    def test_zwnj_inside_number(self):
        """نیم‌فاصله داخل شماره (رایج در کپی از دیوار) نباید شماره را بشکند."""
        assert extract_phone_numbers("0912‌345‌6789", mobile_only=True) == ["09123456789"]
