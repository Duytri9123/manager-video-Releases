import sys
import requests
from bs4 import BeautifulSoup

if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8')

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Test both mirrors
urls = [
    "https://truyenmoiii.org/dai-quan-gia-la-ma-hoang",
    "https://truyenmoiss.com/dai-quan-gia-la-ma-hoang"
]

for url in urls:
    print(f"\n--- Fetching details from: {url} ---")
    try:
        r = requests.get(url, headers=HEADERS, timeout=15, verify=False)
        print(f"Status: {r.status_code}")
        print(f"Length: {len(r.text)}")
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            print(f"Title tag: {soup.title.text if soup.title else 'No Title'}")
            
            # Selector checks
            title_el = soup.select_one(".title[itemprop='name']") or soup.select_one("h3.title")
            print(f"Title selector check: {title_el.text.strip() if title_el else 'None'}")
            
            author_el = soup.select_one(".info a[itemprop='author']") or soup.select_one(".author")
            print(f"Author selector check: {author_el.text.strip() if author_el else 'None'}")
            
            desc_el = soup.select_one(".desc-text")
            print(f"Desc selector check: {desc_el.text.strip()[:100] if desc_el else 'None'}...")
            
            chapters = soup.select(".list-chapter li a")
            print(f"Found {len(chapters)} chapters in page.")
            for c in chapters[:3]:
                print(f"  - {c.text.strip()}: {c.get('href')}")
    except Exception as e:
        print(f"Error: {e}")
