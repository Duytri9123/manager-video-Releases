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
        rows = soup.select(".list-truyen .row")
        print(f"Found {len(rows)} rows.")
        for idx, row in enumerate(rows[:2]):
            print(f"\n--- Selector Check Row {idx} ---")
            
            # 1. Check title anchor
            title_el = row.select_one(".truyen-title a") or row.select_one("h3.truyen-title a") or row.find("a")
            print(f"Title anchor: {title_el}")
            if title_el:
                print(f"  Text: {title_el.text.strip()}")
                print(f"  Href: {title_el.get('href')}")
                
            # 2. Check author
            author_el = row.select_one(".author")
            print(f"Author element: {author_el}")
            if author_el:
                print(f"  Text: {author_el.text.strip()}")
                
            # 3. Check cover image
            img_el = row.select_one(".lazyimg") or row.select_one("img")
            print(f"Image element: {img_el}")
            if img_el:
                print(f"  Src/Data-image: {img_el.get('src') or img_el.get('data-image')}")
except Exception as e:
    print(f"Error: {e}")
