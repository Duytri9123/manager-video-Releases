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
        images = soup.find_all("img")
        print(f"Found {len(images)} images on page:")
        for idx, img in enumerate(images):
            print(f"  Img {idx}: class={img.get('class')}, id={img.get('id')}, src={img.get('src')}, alt={img.get('alt')}")
except Exception as e:
    print(f"Error: {e}")
