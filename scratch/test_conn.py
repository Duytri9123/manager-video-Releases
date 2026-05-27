import os
import sys
import requests

if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8')

print("--- System Proxy Env Vars ---")
for env in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
    print(f"{env}: {os.environ.get(env)}")

print("\n--- Test Google (default) ---")
try:
    r = requests.get("https://www.google.com", timeout=10)
    print(f"Google status: {r.status_code}")
except Exception as e:
    print(f"Google error: {e}")

print("\n--- Test TruyenFull (default) ---")
try:
    r = requests.get("https://truyenfull.today/", timeout=10, verify=False)
    print(f"TruyenFull status: {r.status_code}")
except Exception as e:
    print(f"TruyenFull error: {e}")

print("\n--- Test TruyenFull (trust_env=False) ---")
try:
    session = requests.Session()
    session.trust_env = False
    r = session.get("https://truyenfull.today/", timeout=10, verify=False)
    print(f"TruyenFull (trust_env=False) status: {r.status_code}")
except Exception as e:
    print(f"TruyenFull (trust_env=False) error: {e}")
