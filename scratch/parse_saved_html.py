from bs4 import BeautifulSoup

with open("scratch/bing_first_50k.html", "r", encoding="utf-8") as f:
    soup = BeautifulSoup(f.read(), "html.parser")

imgs = soup.find_all("img")
print("Found total img tags:", len(imgs))

for i, img in enumerate(imgs[:20]):
    print(f"Img {i}: class={img.get('class')}, src={img.get('src') or img.get('data-src') or img.get('data-original')}")
