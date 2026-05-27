import sys
import requests
from bs4 import BeautifulSoup

if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8')

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

url = "https://truyenmoiii.org/dai-quan-gia-la-ma-hoang/chuong-1"

try:
    print(f"Fetching chapter from: {url}")
    r = requests.get(url, headers=HEADERS, timeout=15, verify=False)
    print(f"Status: {r.status_code}")
    print(f"Length: {len(r.text)}")
    if r.status_code == 200:
        soup = BeautifulSoup(r.text, "html.parser")
        
        # 1. Check title
        title_el = soup.select_one(".chapter-title")
        print(f"Title selector check: {title_el.text.strip() if title_el else 'None'}")
        
        # 2. Check content body
        body_el = soup.select_one(".chapter-c") or soup.select_one("#chapter-c") or soup.select_one(".chapter-content")
        if body_el:
            print("--- Found Chapter Content! ---")
            print(f"Tag: {body_el.name}, Class: {body_el.get('class')}, Id: {body_el.get('id')}")
            # print first 500 characters of text
            print(body_el.text.strip()[:600])
        else:
            print("No chapter content body found!")
except Exception as e:
    print(f"Error: {e}")
