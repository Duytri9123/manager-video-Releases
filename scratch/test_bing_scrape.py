import re
import requests
import html
import json
import urllib.parse as urlparse

query = "Tiêu Viêm Đấu Phá Thương Khung manhua"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
}

search_url = f"https://www.bing.com/images/search?q={urlparse.quote(query)}"
r = requests.get(search_url, headers=headers, timeout=8)

print("Status Code:", r.status_code)
print("HTML length:", len(r.text))

m_attrs = re.findall(r'\sm="([^"]+)"', r.text)
print("Found m attributes count:", len(m_attrs))

results = []
for m in m_attrs[:10]:
    unescaped = html.unescape(m)
    try:
        m_data = json.loads(unescaped)
        print("murl:", m_data.get("murl"))
        print("turl:", m_data.get("turl"))
        results.append(m_data.get("murl"))
    except Exception as e:
        print("Error parsing unescaped JSON:", e)
