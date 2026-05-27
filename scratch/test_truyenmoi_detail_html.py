import sys
import requests
from bs4 import BeautifulSoup

if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8')

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

url = "https://truyenmoiii.org/dai-quan-gia-la-ma-hoang"

try:
    r = requests.get(url, headers=HEADERS, timeout=15, verify=False)
    if r.status_code == 200:
        soup = BeautifulSoup(r.text, "html.parser")
        
        # Print elements around class truyen-desc or info or book
        info_el = soup.select_one(".info") or soup.select_one(".book") or soup.select_one(".truyen-info")
        if info_el:
            print("--- Found Info Panel! ---")
            print(info_el.prettify()[:1000])
        else:
            print("No info panel found!")
            
        # Let's search for the title text "Đại Quản Gia Là Ma Hoàng" in h1 or h2 or h3
        h1s = soup.find_all("h1") or soup.find_all("h2") or soup.find_all("h3")
        print(f"\nFound heading tags:")
        for h in h1s[:5]:
            print(f"  {h.name}: class={h.get('class')}, text='{h.text.strip()}'")
except Exception as e:
    print(f"Error: {e}")
