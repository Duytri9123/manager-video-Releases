import requests
from bs4 import BeautifulSoup
import urllib.parse

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def test():
    query = "Ma Hoàng Đại Quản Gia"
    url = f"https://truyenfull.today//tim-kiem/?tukhoa={urllib.parse.quote_plus(query)}"
    print("Encoded URL:", url)
    r = requests.get(url, headers=HEADERS, timeout=15, verify=False)
    soup = BeautifulSoup(r.text, "html.parser")
    
    rows = soup.select(".list-truyen .row")
    print("Found .list-truyen .row:", len(rows))
    for row in rows[:3]:
        title_el = row.select_one(".truyen-title a")
        if title_el:
            print("Title:", title_el.text.strip())

if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    test()
