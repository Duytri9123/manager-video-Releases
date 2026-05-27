import sys
sys.path.append('.')
from utils.web_search import search as web_search_func
import json

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

    kw = "Ma Hoàng Đại Quản Gia đọc truyện chữ"
    print(f"Searching: {kw}")
    results = web_search_func(kw, limit=8)
    for r in results:
        print(f"Title: {r.get('title')}")
        print(f"URL: {r.get('url')}")
        print(f"Source: {r.get('source')}")
        print(f"Snippet: {r.get('snippet')}")
        print("-" * 40)
