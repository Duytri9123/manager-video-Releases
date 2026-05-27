import requests
from bs4 import BeautifulSoup

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def test_search():
    url = "https://truyenfull.today//tim-kiem/?tukhoa=kiem+hiep"
    print(f"Testing search URL: {url}")
    r = requests.get(url, headers=headers, timeout=15)
    print("Status code:", r.status_code)
    soup = BeautifulSoup(r.text, "html.parser")
    
    rows = soup.select(".list-truyen .row")
    print(f"Found {len(rows)} story rows.")
    for row in rows[:3]:
        title_el = row.select_one(".truyen-title a")
        if title_el:
            title = title_el.text.strip()
            href = title_el["href"]
            print(f"Title: {title} | URL: {href}")
            
        author_el = row.select_one(".author")
        if author_el:
            print("Author:", author_el.text.strip())
            
        img_el = row.select_one(".lazyimg") or row.select_one("img")
        if img_el:
            img_src = img_el.get("data-image") or img_el.get("src") or ""
            print("Image src:", img_src)
        print("-" * 30)

if __name__ == "__main__":
    test_search()
