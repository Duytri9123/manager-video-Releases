import re
import requests
import html
import json
import urllib.parse as urlparse

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Cookie": "SRCHHPGUSR=ADLT=OFF",
}

terms = [
    '"Tiêu Viêm"',
    '"Tiêu Viêm" truyện tranh',
    '"Tiêu Viêm" manhua',
    '"Huân Nhi"',
    '"Huân Nhi" truyện tranh',
    '"Huân Nhi" manhua',
    '"Tiêu Chiến" "Đấu Phá Thương Khung"',
]

for t in terms:
    search_url = f"https://www.bing.com/images/search?q={urlparse.quote(t)}"
    r = requests.get(search_url, headers=headers, timeout=8)
    m_attrs = re.findall(r'\sm="([^"]+)"', r.text)
    print(f"\nTerm: '{t}' -> Found: {len(m_attrs)}")
    for m in m_attrs[:3]:
        unescaped = html.unescape(m)
        try:
            m_data = json.loads(unescaped)
            print("  URL:", m_data.get("murl"))
        except:
            pass
