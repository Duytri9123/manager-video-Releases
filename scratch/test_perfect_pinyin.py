import re
import requests
import html
import json
import urllib.parse as urlparse

query = 'Xiao Yan Battle Through the Heavens manhua'
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Cookie": "SRCHHPGUSR=ADLT=OFF", # Turn Safe Search OFF!
}

search_url = f"https://www.bing.com/images/search?q={urlparse.quote(query)}"
r = requests.get(search_url, headers=headers, timeout=8)

print("Status Code:", r.status_code)
print("HTML length:", len(r.text))

m_attrs = re.findall(r'\sm="([^"]+)"', r.text)
print("Found m attributes count:", len(m_attrs))

for m in m_attrs[:5]:
    unescaped = html.unescape(m)
    try:
        m_data = json.loads(unescaped)
        print("MURL:", m_data.get("murl"))
    except Exception as e:
        print("Error parsing:", e)
