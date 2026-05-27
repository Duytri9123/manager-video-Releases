import re
import requests
import urllib.parse as urlparse

query = "Tiêu Viêm Đấu Phá Thương Khung manhua"
# A standard mobile/low-bandwidth user-agent to trigger simplified Google page
headers = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 10_3 like Mac OS X) AppleWebKit/602.1.50 (KHTML, like Gecko) CriOS/56.0.2924.75 Mobile/14E5239e Safari/602.1",
    "Accept-Language": "en-US,en;q=0.9",
}

# Google Images Mobile Search URL
search_url = f"https://www.google.com/search?q={urlparse.quote(query)}&tbm=isch"

try:
    r = requests.get(search_url, headers=headers, timeout=8)
    print("Status Code:", r.status_code)
    print("Content length:", len(r.text))
    
    # Save a small snippet to see the format
    with open("scratch/google_first_50k.html", "w", encoding="utf-8") as f:
        f.write(r.text[:50000])
        
    # Extract image URLs using regex
    # In mobile Google images, the links are typically inside src="..." of img tags, 
    # or inside key-value patterns like [ "https://...", 200, 300 ]
    img_urls = re.findall(r'https://encrypted-tbn0\.gstatic\.com/images\?q=tbn:[^"\']+', r.text)
    print("Found gstatic thumbnails count:", len(img_urls))
    
    for i, url in enumerate(img_urls[:5]):
        print(f"Thumb {i}: {url}")
        
except Exception as e:
    print("Error querying Google Mobile:", e)
