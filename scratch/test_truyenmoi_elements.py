import sys
import requests
import urllib.parse
from bs4 import BeautifulSoup

if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8')

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

keyword = "Ma Hoàng"
url = f"https://truyenmoiii.org/tim-kiem?tukhoa={urllib.parse.quote_plus(keyword)}"

try:
    r = requests.get(url, headers=HEADERS, timeout=15, verify=False)
    if r.status_code == 200:
        soup = BeautifulSoup(r.text, "html.parser")
        row = soup.select_one(".list-truyen .row")
        if row:
            print(row.prettify())
except Exception as e:
    print(f"Error: {e}")
