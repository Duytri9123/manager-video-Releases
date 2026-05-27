import re
import urllib.parse
import requests
from bs4 import BeautifulSoup

# --- Dynamic DNS Patch for TruyenFull & TruyenMoi ---
import socket
orig_getaddrinfo = socket.getaddrinfo
SINKHOLE_IPS = {
    "truyenfull.vn": ["104.26.15.14", "104.26.14.14", "172.67.74.31"],
    "truyenfull.today": ["104.21.79.185", "172.67.147.11"],
    "truyenmoiii.org": ["104.21.54.196", "172.67.141.93"]
}

def custom_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    try:
        results = orig_getaddrinfo(host, port, family, type, proto, flags)
        is_blocked = False
        for res in results:
            ip = res[4][0]
            if ip in ("127.0.0.1", "::1", "localhost") or ip.startswith("127."):
                is_blocked = True
                break
        if not is_blocked:
            return results
    except Exception:
        pass

    for domain, ips in SINKHOLE_IPS.items():
        if host == domain or host.endswith("." + domain):
            for ip in ips:
                try:
                    return orig_getaddrinfo(ip, port, socket.AF_INET, type, proto, flags)
                except Exception:
                    continue
    return orig_getaddrinfo(host, port, family, type, proto, flags)

socket.getaddrinfo = custom_getaddrinfo
# ----------------------------------------

# Disable requests SSL verification warnings for corporate firewalls / proxies
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
}

AJAX_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
}

# ── Helpers ────────────────────────────────────────────────────────────────────

def _extract_novel_id(novel_url: str) -> str:
    """Extract numeric novel ID from URL if present (used for AJAX endpoints)."""
    m = re.search(r"-(\d+)(?:\.html|/)?$", novel_url.rstrip("/"))
    return m.group(1) if m else ""


def _build_page_url(novel_url: str, page: int, domain: str) -> str:
    """Build the correct paginated URL based on the domain convention."""
    base = novel_url.rstrip("/")
    if page <= 1:
        return base + "/"

    # truyenfull.vn / truyenfull.today: /<slug>/trang-<n>/
    if "truyenfull" in domain:
        return f"{base}/trang-{page}/"

    # truyenmoiii.org / truyenmoiss.com: same pattern
    if "truyenmoi" in domain or "truyenmoiss" in domain:
        return f"{base}/trang-{page}/"

    # Generic fallback: try /trang-N/ first
    return f"{base}/trang-{page}/"


def _parse_chapters_from_soup(soup: BeautifulSoup, base_domain: str = "") -> list:
    """Extract chapter list from BeautifulSoup object using multiple selectors."""
    selectors = [
        ".list-chapter li a",
        ".list-chap li a",
        "#list-chapter li a",
        "#list-chapter a",
        "ul.chapters li a",
        ".chapter-list li a",
        ".list_chapter li a",
        "table.chapter-list td a",
        ".chapter-item a",
        ".row-chapter a",
        # truyenmoiii.org uses this structure
        ".list-chapter a",
        "#chapters-list li a",
        ".box-list-chapter li a",
    ]
    for sel in selectors:
        links = soup.select(sel)
        if links:
            chapters = []
            for link in links:
                title = link.get_text(strip=True)
                href = link.get("href", "")
                if not title or not href:
                    continue
                # Rewrite mirror domains
                if "truyenmoiss.com" in href:
                    href = href.replace("truyenmoiss.com", "truyenmoiii.org")
                chapters.append({"title": title, "url": href})
            if chapters:
                return chapters
    return []


def _parse_total_pages_from_soup(soup: BeautifulSoup) -> int:
    """Detect total number of chapter-list pages from pagination HTML."""
    total = 1

    # Strategy 1: look for a "last page" link with trang-N in href
    for link in soup.select(".pagination li a, .paging li a, ul.pagination a, nav.pagination a"):
        href = link.get("href", "")
        title_attr = (link.get("title") or link.get("aria-label") or "").lower()
        text = link.get_text(strip=True)

        if any(k in title_attr for k in ("cuối", "last", "trang cuối")):
            m = re.search(r"trang-(\d+)", href)
            if m:
                total = max(total, int(m.group(1)))

        if text.isdigit():
            total = max(total, int(text))

        # Catch ?page=N or /trang-N/ patterns
        m2 = re.search(r"[?&/](?:page|trang)[=\-](\d+)", href)
        if m2:
            total = max(total, int(m2.group(1)))

    # Strategy 2: look for the last page number in any pagination container
    for container in soup.select(".pagination, .paging, nav[aria-label*='page'], .chapter-paging"):
        for text_node in container.find_all(string=re.compile(r"\d+")):
            nums = re.findall(r"\d+", text_node)
            for n in nums:
                total = max(total, int(n))

    return total


def _try_ajax_chapters(novel_url: str, page: int) -> list:
    """
    Try fetching chapters via common AJAX endpoints used by Vietnamese novel sites.
    Returns list of {title, url} dicts, or empty list on failure.
    """
    novel_id = _extract_novel_id(novel_url)
    if not novel_id:
        return []

    domain = urllib.parse.urlparse(novel_url).netloc

    # truyenmoiii.org AJAX endpoint
    if "truyenmoi" in domain or "truyenmoiss" in domain:
        try:
            ajax_url = f"https://truyenmoiii.org/index.php?ngta=chapter_list&id_truyen={novel_id}&trang={page}"
            r = requests.get(ajax_url, headers=AJAX_HEADERS, timeout=15, verify=False)
            if r.status_code == 200 and r.text.strip():
                soup = BeautifulSoup(r.text, "html.parser")
                chapters = _parse_chapters_from_soup(soup, domain)
                if chapters:
                    return chapters
        except Exception:
            pass

    # truyenfull AJAX endpoint
    if "truyenfull" in domain:
        try:
            ajax_url = f"https://{domain}/index.php?ngta=chapter_list&id_truyen={novel_id}&trang={page}"
            r = requests.get(ajax_url, headers=AJAX_HEADERS, timeout=15, verify=False)
            if r.status_code == 200 and r.text.strip():
                soup = BeautifulSoup(r.text, "html.parser")
                chapters = _parse_chapters_from_soup(soup, domain)
                if chapters:
                    return chapters
        except Exception:
            pass

    return []


# ── Public API ─────────────────────────────────────────────────────────────────

def search_novels(keyword: str):
    # Primary search on truyenmoiii.org
    url = f"https://truyenmoiii.org/tim-kiem?tukhoa={urllib.parse.quote_plus(keyword)}"
    r = requests.get(url, headers=HEADERS, timeout=20, verify=False)
    if r.status_code != 200:
        raise Exception(f"Không thể truy cập TruyenMoi (HTTP {r.status_code})")
        
    soup = BeautifulSoup(r.text, "html.parser")
    rows = (soup.select(".list-truyen:not(.list-cat) div.row") or 
            soup.select(".list-truyen:not(.list-cat) .row") or 
            soup.select(".list-story:not(.list-cat) .row") or 
            soup.select(".list:not(.list-cat) .row"))
    items = []
    for row in rows:
        title_el = row.select_one(".truyen-title a") or row.select_one("h3.truyen-title a") or row.find("a")
        if not title_el or not title_el.text.strip():
            continue
        title = title_el.text.strip()
        link = title_el["href"]
        
        # Rewrite mirror domains back to truyenmoiii.org for consistency
        if "truyenmoiss.com" in link:
            link = link.replace("truyenmoiss.com", "truyenmoiii.org")
            
        author_el = row.select_one(".author")
        author = author_el.text.strip() if author_el else "Ẩn danh"
        
        img_el = row.select_one(".lazyimg") or row.select_one("img")
        cover = ""
        if img_el:
            cover = img_el.get("src") or img_el.get("data-image") or ""
            
        # Estimate chapters count from row elements
        chapters_est = 0
        chap_el = row.select_one(".label-primary") or row.select_one(".text-white")
        if chap_el:
            m = re.search(r"(\d+)", chap_el.text)
            if m:
                chapters_est = int(m.group(1))
        if not chapters_est:
            m = re.search(r"chương\s*(\d+)", row.text.lower()) or re.search(r"(\d+)\s*chương", row.text.lower())
            if m:
                chapters_est = int(m.group(1))

        items.append({
            "title": title,
            "url": link,
            "author": author,
            "cover": cover,
            "chapters_est": chapters_est
        })
    return items


def get_novel_details(novel_url: str):
    """Fetch novel metadata + first-page chapter list."""
    r = requests.get(novel_url, headers=HEADERS, timeout=20, verify=False)
    if r.status_code != 200:
        raise Exception(f"Không thể tải chi tiết truyện (HTTP {r.status_code})")
        
    soup = BeautifulSoup(r.text, "html.parser")
    domain = urllib.parse.urlparse(novel_url).netloc
    
    title_el = (soup.select_one("h1.story-title") or 
                soup.select_one(".title[itemprop='name']") or 
                soup.select_one("h3.title") or 
                soup.select_one("h1"))
    title = title_el.text.strip() if title_el else ""
    
    author_el = (soup.select_one(".info [itemprop='author'] a") or 
                 soup.select_one(".info a[itemprop='author']") or 
                 soup.select_one(".author"))
    author = author_el.text.strip() if author_el else "Ẩn danh"
    
    cover_el = (soup.select_one(".book img") or 
                soup.select_one(".info-holder img") or 
                soup.select_one("img.img-responsive") or 
                soup.select_one("img"))
    cover = cover_el["src"] if cover_el else ""
    
    desc_el = soup.select_one(".desc-text") or soup.select_one(".story-detail-info")
    desc = desc_el.text.strip() if desc_el else ""
    
    # Scrape chapter list from HTML
    chapters = _parse_chapters_from_soup(soup, domain)

    # If HTML gave no chapters, try AJAX endpoint
    if not chapters:
        chapters = _try_ajax_chapters(novel_url, 1)

    # Detect total pages
    total_pages = _parse_total_pages_from_soup(soup)

    return {
        "title": title,
        "author": author,
        "cover": cover,
        "description": desc,
        "chapters": chapters,
        "total_pages": total_pages,
    }


def get_chapters_page(novel_url: str, page: int) -> dict:
    """
    Fetch chapter list for a specific page number.
    Tries multiple strategies:
      1. Static HTML at paginated URL
      2. AJAX endpoint
    Returns {"chapters": [...], "total_pages": N}
    """
    domain = urllib.parse.urlparse(novel_url).netloc
    page_url = _build_page_url(novel_url, page, domain)

    chapters = []
    total_pages = page  # at minimum we know this page exists

    # ── Strategy 1: fetch paginated HTML page ──────────────────────────────
    try:
        r = requests.get(page_url, headers=HEADERS, timeout=20, verify=False)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            chapters = _parse_chapters_from_soup(soup, domain)
            tp = _parse_total_pages_from_soup(soup)
            if tp > 1:
                total_pages = tp
    except Exception:
        pass

    # ── Strategy 2: AJAX fallback (if HTML gave no chapters) ───────────────
    if not chapters:
        chapters = _try_ajax_chapters(novel_url, page)

    # ── Strategy 3: try ?page=N query string variant ───────────────────────
    if not chapters:
        try:
            qs_url = novel_url.rstrip("/") + f"/?page={page}"
            r2 = requests.get(qs_url, headers=HEADERS, timeout=15, verify=False)
            if r2.status_code == 200:
                soup2 = BeautifulSoup(r2.text, "html.parser")
                chapters = _parse_chapters_from_soup(soup2, domain)
                if not chapters:
                    # Some sites embed chapter JSON in a <script> tag
                    for script in soup2.find_all("script"):
                        txt = script.string or ""
                        if "chapter" in txt.lower() and "url" in txt.lower():
                            matches = re.findall(
                                r'"url"\s*:\s*"([^"]+)"[^}]*"title"\s*:\s*"([^"]+)"',
                                txt
                            )
                            if matches:
                                chapters = [{"url": u, "title": t} for u, t in matches]
                                break
        except Exception:
            pass

    return {
        "chapters": chapters,
        "total_pages": total_pages,
    }


def get_chapter_content(chapter_url: str):
    r = requests.get(chapter_url, headers=HEADERS, timeout=20, verify=False)
    if r.status_code != 200:
        raise Exception(f"Không thể tải nội dung chương (HTTP {r.status_code})")
        
    soup = BeautifulSoup(r.text, "html.parser")
    
    title_el = soup.select_one(".chapter-title") or soup.select_one("h2") or soup.select_one("h3")
    title = title_el.text.strip() if title_el else ""
    
    body_el = soup.select_one(".chapter-c") or soup.select_one(".chapter-content") or soup.select_one("#chapter-c")
    if not body_el:
        raise Exception("Không tìm thấy nội dung chương")
        
    # Replace br/p tags for correct spacing
    for br in body_el.find_all("br"):
        br.replace_with("\n")
    for p in body_el.find_all("p"):
        p.insert_before("\n")
        p.insert_after("\n")
        
    content = body_el.text.strip()
    
    # Post-process content to strip watermarks and ads
    lines = []
    for line in content.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Filter watermarks
        if any(w in line.lower() for w in ("truyenfull.vn", "truyện full", "truyenmoiii", "truyenmoi", "adsbygoogle", "quảng cáo")):
            continue
        lines.append(line)
        
    return {
        "title": title,
        "content": "\n\n".join(lines)
    }
