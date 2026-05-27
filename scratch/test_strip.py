import sys
import unicodedata

if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8')

def _strip_accents(text: str) -> str:
    # Normalize unicode to separate accents
    nfkd_form = unicodedata.normalize('NFKD', text)
    s = "".join([c for c in nfkd_form if not unicodedata.combining(c)])
    # Replace Đ/đ
    s = s.replace("đ", "d").replace("Đ", "D")
    return " ".join(s.split())

test_strings = [
    "Ma Hoàng Đại Quản Gia",
    "đại quản gia là ma hoàng",
    "Trọng Sinh Chi Đô Thị Tu Tiên"
]

for s in test_strings:
    print(f"Original: '{s}' -> Stripped: '{_strip_accents(s)}'")
