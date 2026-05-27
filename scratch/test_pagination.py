"""Debug script - test pagination scraping for truyenmoiii.org"""
import sys
sys.path.insert(0, '.')

from core.novel_scraper import get_chapters_page, get_novel_details, _build_page_url, HEADERS
import urllib.parse
import requests
from bs4 import BeautifulSoup

# === Test 1: Thu lay trang 2 cua Dau Pha Thuong Khung ===
# Truy cap truc tiep de xem HTML tra ve gi
test_novel_url = "https://truyenmoiii.org/dau-pha-thuong-khung/"

print("="*60)
print("TEST 1: Build paginated URL")
domain = urllib.parse.urlparse(test_novel_url).netloc
page2_url = _build_page_url(test_novel_url, 2, domain)
print(f"  Base URL: {test_novel_url}")
print(f"  Page 2 URL: {page2_url}")

print("\nTEST 2: Fetch paginated page & check HTML structure")
try:
    r = requests.get(page2_url, headers=HEADERS, timeout=20, verify=False)
    print(f"  HTTP status: {r.status_code}")
    print(f"  Content length: {len(r.text)} chars")
    
    soup = BeautifulSoup(r.text, "html.parser")
    
    # Check selectors
    selectors_to_check = [
        ".list-chapter li a",
        ".list-chap li a",
        "#list-chapter li a",
        "#list-chapter a",
        ".list-chapter a",
        "#chapters-list li a",
        ".box-list-chapter li a",
        "ul.chapters li a",
        ".chapter-list li a",
        ".chapter-item a",
    ]
    for sel in selectors_to_check:
        found = soup.select(sel)
        if found:
            print(f"  FOUND: '{sel}' -> {len(found)} items, first: {found[0].get_text(strip=True)[:40]}")
        else:
            print(f"  miss:  '{sel}'")
    
    # Check pagination
    pag = soup.select(".pagination li a")
    print(f"\n  Pagination links: {len(pag)}")
    for lnk in pag[:5]:
        print(f"    text={lnk.get_text(strip=True)!r} href={lnk.get('href','')}")
        
except Exception as e:
    print(f"  EXCEPTION: {e}")

print("\nTEST 3: get_chapters_page() function")
try:
    result = get_chapters_page(test_novel_url, 2)
    chaps = result.get("chapters", [])
    print(f"  chapters count: {len(chaps)}")
    print(f"  total_pages: {result.get('total_pages')}")
    if chaps:
        print(f"  First chapter: {chaps[0]}")
        print(f"  Last chapter: {chaps[-1]}")
    else:
        print("  -> NO CHAPTERS RETURNED (this is the bug)")
except Exception as e:
    print(f"  EXCEPTION: {e}")

print("\nTEST 4: Try truyenfull.today")
try:
    # Search for the novel on truyenfull
    tf_url = "https://truyenfull.today/dau-pha-thuong-khung/"
    result2 = get_chapters_page(tf_url, 2)
    chaps2 = result2.get("chapters", [])
    print(f"  truyenfull chapters: {len(chaps2)}")
    if chaps2:
        print(f"  First: {chaps2[0]}")
except Exception as e:
    print(f"  truyenfull EXCEPTION: {e}")
