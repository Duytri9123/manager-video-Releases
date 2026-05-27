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
    print(f"Searching for '{keyword}'...")
    r = requests.get(url, headers=HEADERS, timeout=15, verify=False)
    if r.status_code == 200:
        soup = BeautifulSoup(r.text, "html.parser")
        list_container = soup.select_one(".list-truyen")
        if list_container:
            print("\n--- List Container Found! ---")
            # Print class names of immediate children
            children = list_container.find_all(recursive=False)
            print(f"Immediate children of .list-truyen: {len(children)}")
            for idx, c in enumerate(children):
                print(f"  Child {idx}: name={c.name}, class={c.get('class')}")
            
            # Print text of first 1000 chars of list-truyen
            print("\n--- List Container Text (First 2000 chars) ---")
            print(list_container.text.strip()[:2000])
            
            # Let's see if there are any row classes inside list-container
            rows = list_container.select(".row")
            print(f"\nFound {len(rows)} .row elements inside .list-truyen.")
            for i, row in enumerate(rows[:5]):
                print(f"  Row {i} HTML snippet:")
                print(row.prettify()[:400])
        else:
            print("No .list-truyen found!")
except Exception as e:
    print(f"Error: {e}")
