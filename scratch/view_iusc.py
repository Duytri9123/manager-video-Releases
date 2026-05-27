with open("scratch/bing_first_50k.html", "r", encoding="utf-8") as f:
    text = f.read()

import re
matches = [m.start() for m in re.finditer("iusc", text)]
for i, idx in enumerate(matches):
    start = max(0, idx - 100)
    end = min(len(text), idx + 200)
    print(f"Match {i}: {text[start:end]}\n")
