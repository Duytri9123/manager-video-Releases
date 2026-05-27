import sys
sys.path.append('.')
from routes.story import api_novel_search
from flask import Flask, json

app = Flask(__name__)
app.register_blueprint(sys.modules['routes.story'].bp)

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

    with app.test_request_context(json={"q": "Ma Hoàng Đại Quản Gia", "ai_search": True}, method="POST"):
        resp = api_novel_search()
        data = resp.get_json()
        print("Success status:", data.get("ok"))
        print("AI Note:", data.get("ai_note"))
        print("Results Count:", data.get("count"))
        print("\nTop 5 Results:")
        for idx, item in enumerate(data.get("items", [])[:5], 1):
            print(f"{idx}. Title: {item.get('title')}")
            print(f"   URL: {item.get('url')}")
            print(f"   Chapters Est: {item.get('chapters_est')}")
            print(f"   Scrapable: {item.get('is_scrapable')}")
            print("-" * 40)
