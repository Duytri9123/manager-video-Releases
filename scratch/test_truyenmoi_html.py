import sys
import requests
from bs4 import BeautifulSoup

if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8')

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

try:
    print("--- Fetching homepage: https://truyenmoiii.org/ ---")
    r = requests.get("https://truyenmoiii.org/", headers=HEADERS, timeout=15, verify=False)
    print(f"Status: {r.status_code}")
    print(f"Response snippet: {r.text[:800]}")
    
    if r.status_code == 200:
        soup = BeautifulSoup(r.text, "html.parser")
        # Let's search for search forms
        forms = soup.find_all("form")
        print(f"\nFound {len(forms)} forms:")
        for idx, f in enumerate(forms):
            print(f"  Form {idx}: action={f.get('action')}, method={f.get('method')}")
            inputs = f.find_all("input")
            for inp in inputs:
                print(f"    Input: name={inp.get('name')}, type={inp.get('type')}, value={inp.get('value')}")
except Exception as e:
    print(f"Error: {e}")
