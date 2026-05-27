import socket
import sys
import requests

if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8')

# Save original getaddrinfo
orig_getaddrinfo = socket.getaddrinfo

# Override DNS resolution for truyenfull.vn
def custom_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    if host == "truyenfull.vn":
        # Force resolution to the actual Cloudflare IPs of truyenfull.vn
        real_ip = "104.26.15.14"
        print(f"[DNS Patch] Redirecting {host} -> {real_ip}")
        # Note: we pass family=socket.AF_INET to force IPv4
        return orig_getaddrinfo(real_ip, port, socket.AF_INET, type, proto, flags)
    return orig_getaddrinfo(host, port, family, type, proto, flags)

socket.getaddrinfo = custom_getaddrinfo

print("--- Testing patched TruyenFull search ---")
try:
    url = "https://truyenfull.today//tim-kiem/?tukhoa=Ma+Ho%C3%A0ng+%C4%90%E1%BA%A1i+Qu%E1%BA%A3n+Gia"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    r = requests.get(url, headers=headers, timeout=15, verify=False)
    print(f"Patched connection status: {r.status_code}")
    print(f"Response snippet length: {len(r.text)}")
    if r.status_code == 200:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "html.parser")
        rows = soup.select(".list-truyen .row")
        print(f"Found {len(rows)} novel rows.")
        for row in rows[:2]:
            title_el = row.select_one(".truyen-title a")
            if title_el:
                print(f"  - {title_el.text.strip()}")
except Exception as e:
    print(f"Patched connection failed: {e}")
