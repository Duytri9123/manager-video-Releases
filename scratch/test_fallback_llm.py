import os
import sys
import requests

if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from routes.story import _cfg

cfg = _cfg()
deepseek_key = cfg.get("translation", {}).get("deepseek_key", "").strip()
gemini_key = cfg.get("gemini_video", {}).get("api_key", "").strip()

print(f"DeepSeek Key: {deepseek_key[:10]}...")
print(f"Gemini Key: {gemini_key[:10]}...")

system_msg = "Bạn là một nhà văn mạng viết truyện chữ. Hãy viết 1 câu chào ngắn."

# 1. Test DeepSeek fallback
if deepseek_key:
    print("\n--- Testing DeepSeek Fallback ---")
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "user", "content": system_msg}
        ],
        "max_tokens": 50,
        "temperature": 0.7
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {deepseek_key}"
    }
    try:
        resp = requests.post("https://api.deepseek.com/chat/completions", json=payload, headers=headers, timeout=15)
        print(f"Status: {resp.status_code}")
        print(f"Response: {resp.text[:200]}")
    except Exception as e:
        print(f"DeepSeek failed: {e}")

# 2. Test Gemini fallback
if gemini_key:
    print("\n--- Testing Gemini Fallback ---")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
    payload = {
        "contents": [
            {"parts": [{"text": system_msg}]}
        ]
    }
    try:
        resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=15)
        print(f"Status: {resp.status_code}")
        print(f"Response: {resp.text[:200]}")
    except Exception as e:
        print(f"Gemini failed: {e}")
