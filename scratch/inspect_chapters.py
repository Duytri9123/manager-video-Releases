import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def print_chapters(url, name):
    print(f"\n=== {name} chapters ===")
    try:
        r = requests.get(url, headers=HEADERS, timeout=10, verify=False)
        soup = BeautifulSoup(r.text, "html.parser")
        chapter_links = soup.select(".list-chapter li a, .list-chap li a, ul.chapters li a, #list-chapter a")
        print("Chapters on page 1:", len(chapter_links))
        if chapter_links:
            print("First chapter:", chapter_links[0].text.strip())
            print("Last chapter:", chapter_links[-1].text.strip())
            
        # Let's check total pages
        total_pages = 1
        pag_links = soup.select(".pagination li a")
        import re
        for link in pag_links:
            title_attr = link.get("title") or ""
            text = link.text.strip()
            if "Cuối" in title_attr or "cuối" in title_attr or "Trang cuối" in title_attr:
                m = re.search(r"trang-(\d+)", link["href"])
                if m:
                    total_pages = int(m.group(1))
            elif text.isdigit():
                total_pages = max(total_pages, int(text))
        print("Total pages:", total_pages)
        
        if total_pages > 1:
            last_url = url.rstrip("/") + f"/trang-{total_pages}/"
            r2 = requests.get(last_url, headers=HEADERS, timeout=10, verify=False)
            soup2 = BeautifulSoup(r2.text, "html.parser")
            ch_links2 = soup2.select(".list-chapter li a, .list-chap li a, ul.chapters li a, #list-chapter a")
            print(f"Chapters on last page ({total_pages}):", len(ch_links2))
            if ch_links2:
                print("First chapter on last page:", ch_links2[0].text.strip())
                print("Last chapter on last page:", ch_links2[-1].text.strip())
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

    print_chapters("https://truyenmoiii.org/dai-quan-gia-la-ma-hoang", "TruyenMoi - Đại Quản Gia Là Ma Hoàng")
    print_chapters("https://truyenfull.today/ma-hoang-dai-quan-gia/", "TruyenFull - Ma Hoàng Đại Quản Gia")
