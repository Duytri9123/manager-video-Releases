import os
import sys
import requests

if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from routes.story import _cfg

cfg = _cfg()
nr_cfg = cfg.get("nine_router") or {}
api_key = (nr_cfg.get("api_key") or "").strip()
model = (nr_cfg.get("default_model") or "duytris").strip()

# Try public gateway instead of localhost
public_endpoint = "https://api.9router.com/v1"

print(f"Public Endpoint: {public_endpoint}")
print(f"API Key: {api_key[:10]}...")
print(f"Model: {model}")

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {api_key}"
}

payload = {
    "model": model,
    "messages": [
        {"role": "user", "content": "Xin chào, hãy phản hồi lại từ 'OK'."}
    ],
    "temperature": 0.7,
    "max_tokens": 100,
    "stream": False,
}

try:
    url = f"{public_endpoint}/chat/completions"
    print(f"Sending POST to {url}...")
    resp = requests.post(url, json=payload, headers=headers, timeout=15)
    print(f"Response status: {resp.status_code}")
    print(f"Response body: {resp.text}")
except Exception as e:
    print(f"Connection failed: {e}")
