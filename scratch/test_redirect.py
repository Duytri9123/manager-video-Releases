import requests

query = "Tiêu Viêm Đấu Phá Thương Khung manhua"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

search_url = f"https://www.bing.com/images/search?q={requests.utils.quote(query)}"
r = requests.get(search_url, headers=headers, timeout=8)

print("Original URL:", search_url)
print("Final URL:", r.url)
print("History:", r.history)
