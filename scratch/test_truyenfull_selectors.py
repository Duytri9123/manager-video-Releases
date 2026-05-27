import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def test():
    url = "https://truyenfull.today//tim-kiem/?tukhoa=Ma+Hoang+Dai+Quan+Gia"
    r = requests.get(url, headers=HEADERS, timeout=15, verify=False)
    soup = BeautifulSoup(r.text, "html.parser")
    
    # Check list-truyen presence
    list_truyen = soup.select(".list-truyen")
    print("Found list-truyen:", len(list_truyen))
    
    rows = soup.select(".list-truyen .row")
    print("Found .list-truyen .row:", len(rows))
    
    # Let's inspect all row elements in the page
    all_rows = soup.select(".row")
    print("Found total .row in page:", len(all_rows))
    
    # Let's print the structure of list_truyen if found
    if list_truyen:
        # Write inner HTML of list_truyen to a file
        with open("scratch/output.html", "w", encoding="utf-8") as f:
            f.write(list_truyen[0].prettify())
        print("Wrote list_truyen prettified HTML to scratch/output.html")

if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    test()
