import urllib.request
import urllib.parse
import re
import json

def search_ddg_images(query, limit=5):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://duckduckgo.com/",
    }
    
    # Step 1: Get the vqd token
    enc_query = urllib.parse.quote(query)
    url = f"https://duckduckgo.com/?q={enc_query}"
    
    try:
        req = urllib.request.Request(url, headers={"User-Agent": headers["User-Agent"]})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode('utf-8', 'replace')
        
        # Look for vqd value in the HTML
        match = re.search(r"vqd=([\"']?)([\d-]+)\1", html)
        if not match:
            match = re.search(r"vqd=([\d-]+)", html)
        
        if not match:
            print("Failed to find vqd token in DuckDuckGo HTML")
            return []
            
        vqd = match.group(2) if len(match.groups()) >= 2 else match.group(1)
        print(f"Found vqd token: {vqd}")
        
        # Step 2: Query the image search API
        img_url = f"https://duckduckgo.com/i.js?l=wt-wt&o=json&q={enc_query}&vqd={vqd}&f=,,,"
        req2 = urllib.request.Request(img_url, headers=headers)
        with urllib.request.urlopen(req2, timeout=10) as resp2:
            data = json.loads(resp2.read().decode('utf-8', 'replace'))
            
        results = data.get("results", [])
        images = []
        for r in results[:limit]:
            images.append({
                "title": r.get("title"),
                "image": r.get("image"),
                "thumbnail": r.get("thumbnail"),
                "url": r.get("url")
            })
        return images
    except Exception as e:
        print(f"Error in search_ddg_images: {e}")
        return []

if __name__ == "__main__":
    imgs = search_ddg_images("nhân vật trác phàm trong đại quản gia là ma hoàng", limit=5)
    with open("C:/Users/QUANG HUAN/PycharmProjects/toolvideo/scratch/test_output.json", "w", encoding="utf-8") as f:
        json.dump(imgs, f, indent=2, ensure_ascii=False)
    print("Success! Saved to test_output.json. Found images:", len(imgs))
