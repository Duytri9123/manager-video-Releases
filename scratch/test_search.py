import sys
import os

# Set standard output encoding to UTF-8
if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr:
    sys.stderr.reconfigure(encoding='utf-8')

# Add root folder to sys.path so we can import core
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.novel_scraper import search_novels

def test():
    queries = ["Ma Hoàng Đại Quản Gia", "Ma Hoang Dai Quan Gia", "ma hoang dai quan gia", "Đại Quản Gia Là Ma Hoàng"]
    for q in queries:
        print(f"--- Searching for: '{q}' ---")
        try:
            results = search_novels(q)
            print(f"Found {len(results)} results.")
            for item in results[:3]:
                print(f"  - Title: {item['title']}")
                print(f"    URL: {item['url']}")
                print(f"    Author: {item['author']}")
        except Exception as e:
            print(f"Error for '{q}': {e}")

if __name__ == "__main__":
    test()
