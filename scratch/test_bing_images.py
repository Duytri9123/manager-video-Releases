import requests
import re
import json
import urllib.parse
import urllib3
import html
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def test_extract(q, log_file):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    }
    url = f"https://www.bing.com/images/search?q={urllib.parse.quote(q)}"
    r = requests.get(url, headers=headers, timeout=10, verify=False)
    
    # 1. Match the entire m attribute content: m="([^"]+)"
    # Note: the attribute is m="..." so we can match m="([^"]+)"
    m_attrs = re.findall(r'\sm="([^"]+)"', r.text)
    
    results = []
    for m in m_attrs:
        # Unescape HTML entities (converts &quot; back to ", &amp; back to &, etc.)
        unescaped = html.unescape(m)
        try:
            data = json.loads(unescaped)
            murl = data.get("murl")
            turl = data.get("turl")
            title = data.get("title") or q
            if murl:
                results.append({
                    "title": title,
                    "image": murl,
                    "thumbnail": turl or murl
                })
        except Exception:
            pass
            
    log_file.write(f"Query: '{q}'\n")
    log_file.write(f"Found images: {len(results)}\n")
    
    for i, r in enumerate(results[:10]):
        log_file.write(f"  {i} - Image: {r['image']}\n")
        log_file.write(f"    - Thumb: {r['thumbnail']}\n")
    log_file.write("\n")

if __name__ == "__main__":
    with open("C:/Users/QUANG HUAN/PycharmProjects/toolvideo/scratch/output_log.txt", "w", encoding="utf-8") as f:
        test_extract("Ma Hoàng Trác Phàm", f)
        test_extract("Trác Phàm Đại Quản Gia Là Ma Hoàng", f)
    print("Done! Saved log to output_log.txt")
