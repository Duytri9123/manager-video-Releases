import requests
import re

query = "Tiêu Viêm Đấu Phá Thương Khung manhua"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

search_url = f"https://www.bing.com/images/search?q={requests.utils.quote(query)}"
r = requests.get(search_url, headers=headers, timeout=8)

# Find all occurrences of "murl" or similar keys
murls = re.findall(r'"murl"\s*:\s*"([^"]+)"', r.text)
print("Found direct 'murl' count:", len(murls))
for url in murls[:10]:
    print("Direct murl:", url)

# Save first 50k chars of html for inspection
with open("scratch/bing_first_50k.html", "w", encoding="utf-8") as f:
    f.write(r.text[:100000])

print("Saved HTML for inspection.")
