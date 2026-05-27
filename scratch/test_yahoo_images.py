import requests
import urllib.parse
import urllib3
import re
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def check_yahoo():
    url = "https://images.search.yahoo.com/search/images?p=" + urllib.parse.quote("trac pham")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    }
    r = requests.get(url, headers=headers, verify=False, timeout=15)
    print("Status:", r.status_code)
    print("Length:", len(r.text))
    
    # Save first 2000 chars of yahoo response
    with open("C:/Users/QUANG HUAN/PycharmProjects/toolvideo/scratch/yahoo_html.html", "w", encoding="utf-8") as f:
        f.write(r.text)
        
    # Search for all image file extensions or occurrences of http/https
    urls = re.findall(r'(https?://[^\s"\'\\<>]+?\.(?:jpg|png|jpeg|webp))', r.text)
    print("Found image URLs:", len(urls))
    for i, u in enumerate(urls[:10]):
        print(f"{i}: {u}")

if __name__ == "__main__":
    check_yahoo()
