import os
import sys
import requests

if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from routes.story import _cfg

cfg = _cfg()
nr_cfg = cfg.get("nine_router") or {}
endpoint = (nr_cfg.get("endpoint") or "http://localhost:20128/v1").rstrip("/")
api_key = (nr_cfg.get("api_key") or "").strip()
model = (nr_cfg.get("default_model") or "duytris").strip()

print(f"Endpoint: {endpoint}")
print(f"API Key: {api_key[:10]}...")
print(f"Model: {model}")

headers = {"Content-Type": "application/json"}
if api_key:
    headers["Authorization"] = f"Bearer {api_key}"

payload = {
    "model": model,
    "messages": [
        {"role": "user", "content": "Xin chào, đây là kiểm tra kết nối."}
    ],
    "temperature": 0.7,
    "max_tokens": 100,
    "stream": False,
}

try:
    url = f"{endpoint}/chat/completions"
    print(f"Sending POST to {url}...")
    resp = requests.post(url, json=payload, headers=headers, timeout=10)
    print(f"Response status: {resp.status_code}")
    print(f"Response body: {resp.text}")
except Exception as e:
    print(f"Connection failed: {e}")
