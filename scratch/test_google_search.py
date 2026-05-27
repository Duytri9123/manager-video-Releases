import sys
import requests
import urllib.parse
from bs4 import BeautifulSoup

if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8')

def google_search_sources(keyword: str):
    query = f"{keyword} đọc truyện chữ"
    url = f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    r = requests.get(url, headers=headers, timeout=15)
    print(f"Google HTTP Status: {r.status_code}")
    
    soup = BeautifulSoup(r.text, "html.parser")
    results = []
    
    for a in soup.select("a"):
        href = a.get("href")
        if not href or not href.startswith("http") or "google.com" in href:
            continue
            
        h3 = a.select_one("h3")
        if not h3:
            continue
            
        title = h3.text.strip()
        domain = urllib.parse.urlparse(href).netloc
        
        results.append({
            "title": title,
            "url": href,
            "domain": domain
        })
    return results

keyword = "Ma Hoàng Đại Quản Gia"
print(f"Searching Google for: '{keyword}'")
try:
    res = google_search_sources(keyword)
    print(f"Found {len(res)} web sources:")
    for idx, r in enumerate(res[:10]):
        print(f"  Source {idx}: title='{r['title']}'")
        print(f"            url='{r['url']}'")
        print(f"            domain='{r['domain']}'")
except Exception as e:
    print(f"Error: {e}")
