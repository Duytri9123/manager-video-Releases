"""Probe NetTruyen / TruyenQQ mirrors via curl_cffi."""
from curl_cffi import requests as cf

SITES = [
    "https://www.nettruyenvio.com/",
    "https://nettruyenrr.com/",
    "https://nettruyenz.com/",
    "https://nettruyentt.com/",
    "https://nettruyenfun.com/",
    "https://www.nettruyenviet.com/",
    "https://nhattruyenu.com/",
    "https://nhattruyens.com/",
    "https://truyenqq.cc/",
    "https://truyenqqgo.com/",
    "https://www.truyenqqto.com/",
    "https://blogtruyenmoi.com/",
    "https://blogtruyenvn.com/",
]
for url in SITES:
    try:
        r = cf.get(url, impersonate="chrome120", timeout=8)
        body = r.text or ""
        marker = "/truyen-tranh/" in body or "/truyen/" in body
        print(f"{r.status_code:>3}  len={len(body):>6}  marker={marker}  {url}")
    except Exception as e:
        msg = str(e).split(".")[0][:80]
        print(f" --  err   {url}  →  {msg}")
