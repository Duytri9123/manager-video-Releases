import os
import sys

# Set standard output encoding to UTF-8
if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from extensions import create_app

app = create_app()
client = app.test_client()

payload = {
    "url": "https://truyenfull.vn/invalid-chapter-url-for-testing",
    "novel_title": "Ma Hoàng Đại Quản Gia",
    "chapter_title": "Chương 1: Trọng Sinh Về Làm Đại Quản Gia"
}
r = client.post("/api/story/novel/chapter_content", json=payload)
print(f"Status: {r.status_code}")
print(r.get_data(as_text=True))
