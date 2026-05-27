import sys
sys.path.append('.')
from core.novel_scraper import search_novels
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

    print("--- search_novels('Ma Hoàng Đại Quản Gia') ---")
    try:
        res1 = search_novels("Ma Hoàng Đại Quản Gia")
        print(json.dumps(res1, indent=2, ensure_ascii=False))
    except Exception as e:
        print("Error:", e)

    print("\n--- search_novels('Đại Quản Gia Là Ma Hoàng') ---")
    try:
        res2 = search_novels("Đại Quản Gia Là Ma Hoàng")
        print(json.dumps(res2, indent=2, ensure_ascii=False))
    except Exception as e:
        print("Error:", e)
