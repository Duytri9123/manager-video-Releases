import re

with open("C:/Users/QUANG HUAN/PycharmProjects/toolvideo/scratch/google_test.html", "r", encoding="utf-8") as f:
    html = f.read()

with open("C:/Users/QUANG HUAN/PycharmProjects/toolvideo/scratch/output_log.txt", "w", encoding="utf-8") as out:
    out.write("Searching for URLs inside the 91KB HTML:\n")
    urls = re.findall(r'(https?://[^\s"\'\\<>]+)', html)
    out.write(f"Total URL-like strings found: {len(urls)}\n")
    for i, u in enumerate(urls[:30]):
        out.write(f"{i}: {u}\n")

print("Done! Saved log to output_log.txt")
