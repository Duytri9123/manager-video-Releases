import urllib.parse
import requests
from bs4 import BeautifulSoup
import re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def get_novel_details(url):
    print("\nFetching details for:", url)
    try:
        r = requests.get(url, headers=HEADERS, timeout=10, verify=False)
        soup = BeautifulSoup(r.text, "html.parser")
        
        # Scrape title
        title_el = soup.select_one("h1, h2, h3")
        title = title_el.text.strip() if title_el else "Unknown"
        
        # Scrape chapters on first page
        chapter_links = soup.select(".list-chapter li a, .list-chap li a, ul.chapters li a, #list-chapter a")
        print(f"  Title: {title}")
        print(f"  Chapters on page 1: {len(chapter_links)}")
        if chapter_links:
            print(f"  First chapter: {chapter_links[0].text.strip()}")
            print(f"  Last chapter on page 1: {chapter_links[-1].text.strip()}")

        # Pagination
        total_pages = 1
        pag_links = soup.select(".pagination li a")
        for link in pag_links:
            title_attr = link.get("title") or ""
            text = link.text.strip()
            if "Cuối" in title_attr or "cuối" in title_attr or "Trang cuối" in title_attr:
                m = re.search(r"trang-(\d+)", link["href"])
                if m:
                    total_pages = int(m.group(1))
            elif text.isdigit():
                total_pages = max(total_pages, int(text))
        print(f"  Total pages of chapters: {total_pages}")
        
        # Let's see what the actual total chapter count might be
        # Usually it's page 1 chapters * total_pages or we can look at the last page
        if total_pages > 1:
            # Let's build last page url
            last_page_url = url.rstrip("/") + f"/trang-{total_pages}/"
            print("  Fetching last page:", last_page_url)
            r_last = requests.get(last_page_url, headers=HEADERS, timeout=10, verify=False)
            soup_last = BeautifulSoup(r_last.text, "html.parser")
            last_chapter_links = soup_last.select(".list-chapter li a, .list-chap li a, ul.chapters li a, #list-chapter a")
            if last_chapter_links:
                print(f"  Last page chapters count: {len(last_chapter_links)}")
                print(f"  Last chapter on last page: {last_chapter_links[-1].text.strip()}")
    except Exception as e:
        print("Error fetching details:", e)

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

    get_novel_details("https://truyenmoiii.org/dai-quan-gia-la-ma-hoang")
    get_novel_details("https://truyenfull.today/ma-hoang-dai-quan-gia/")
