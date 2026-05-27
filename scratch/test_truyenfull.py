import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def test():
    url = "https://truyenfull.today//tim-kiem/?tukhoa=Ma+Hoang+Dai+Quan+Gia"
    print("Requesting:", url)
    try:
        r = requests.get(url, headers=HEADERS, timeout=15, verify=False)
        print("Status code:", r.status_code)
        print("Response length:", len(r.text))
        print("Preview:")
        print(r.text[:1000])
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    test()
