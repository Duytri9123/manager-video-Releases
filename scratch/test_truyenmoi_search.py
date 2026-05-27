import sys
import requests
import urllib.parse
from bs4 import BeautifulSoup

if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8')

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

keyword = "Ma Hoàng Đại Quản Gia"
url = f"https://truyenmoiii.org/tim-kiem?tukhoa={urllib.parse.quote_plus(keyword)}"

try:
    r = requests.get(url, headers=HEADERS, timeout=15, verify=False)
    if r.status_code == 200:
        soup = BeautifulSoup(r.text, "html.parser")
        
        # Find all strong or tag containing Ma Hoàng
        matches = soup.find_all(string=lambda text: text and "Ma Hoàng" in text)
        print(f"Matches found: {len(matches)}")
        for idx, m in enumerate(matches):
            parent = m.parent
            # Travel up to 4 parents to see the structure
            current = parent
            print(f"\n--- Match {idx} hierarchy ---")
            path = []
            for i in range(5):
                if not current:
                    break
                path.append(f"{current.name}.{'.'.join(current.get('class', []))}" if current.get('class') else current.name)
                # Print outer HTML if it looks like a list item container (e.g. div or li)
                if current.name in ("div", "li") and any(c in "".join(current.get('class', [])).lower() for c in ("story", "truyen", "item", "row")):
                    print(f"Found container {current.name} (class={current.get('class')}):")
                    print(current.prettify()[:600])
                    break
                current = current.parent
            print(" -> ".join(path))
except Exception as e:
    print(f"Error: {e}")
