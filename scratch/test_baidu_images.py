import requests
import json
import urllib.parse as urlparse

query = "萧炎"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "text/plain, */*; q=0.01",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://image.baidu.com/search/index?tn=baiduimage&ps=1&ct=201326592&lm=-1&cl=2&nc=1&ie=utf-8&word=" + urlparse.quote(query),
}

# Baidu Image search AJAX API
search_url = f"https://image.baidu.com/search/acjson?tn=resultjson_com&ipn=rj&ct=201326592&is=&fp=result&queryWord={urlparse.quote(query)}&cl=2&lm=-1&ie=utf-8&oe=utf-8&adpicid=&st=-1&z=&ic=0&word={urlparse.quote(query)}&face=0&istype=2&qc=&nc=1&fr=&pn=0&rn=30"

try:
    r = requests.get(search_url, headers=headers, timeout=8)
    print("Status Code:", r.status_code)
    print("Content length:", len(r.text))
    
    # Try to parse JSON
    data = r.json()
    items = data.get("data", [])
    print("Found items count:", len(items))
    
    for i, item in enumerate(items[:5]):
        thumb = item.get("thumbURL")
        middle = item.get("middleURL")
        hover = item.get("hoverURL")
        if thumb or middle:
            print(f"Item {i}: thumb={thumb}, middle={middle}")
except Exception as e:
    print("Error querying Baidu Images:", e)
