import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def print_row_html(url, name, selector):
    print(f"\n=== {name} row HTML ===")
    try:
        r = requests.get(url, headers=HEADERS, timeout=10, verify=False)
        soup = BeautifulSoup(r.text, "html.parser")
        rows = soup.select(selector)
        print("Found rows:", len(rows))
        if rows:
            print(rows[0].prettify()[:1500])
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    import socket
    # Apply local dns hook to bypass localhost resolution for test
    orig_getaddrinfo = socket.getaddrinfo
    SINKHOLE_IPS = {
        "truyenfull.vn": ["104.26.15.14", "104.26.14.14", "172.67.74.31"],
        "truyenfull.today": ["104.21.79.185", "172.67.147.11"],
        "truyenmoiii.org": ["104.21.54.196", "172.67.141.93"],
        "truyenmoiss.com": ["104.21.54.196", "172.67.141.93"]
    }
    def custom_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        for domain, ips in SINKHOLE_IPS.items():
            if host == domain or host.endswith("." + domain):
                return orig_getaddrinfo(ips[0], port, socket.AF_INET, type, proto, flags)
        return orig_getaddrinfo(host, port, family, type, proto, flags)
    socket.getaddrinfo = custom_getaddrinfo

    print_row_html("https://truyenmoiii.org/tim-kiem?tukhoa=Đại+Quản+Gia+Là+Ma+Hoàng", "TruyenMoi", ".list-truyen .row")
    print_row_html("https://truyenfull.today/tim-kiem/?tukhoa=Ma+Hoàng+Đại+Quản+Gia", "TruyenFull", ".list-truyen .row")
