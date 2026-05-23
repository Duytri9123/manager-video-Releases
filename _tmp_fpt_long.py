import urllib.request, json, time

key = "5Hiwj5Qlp7Gv11zH4JQx5T76EtetDxPj"
text = (
    "Gia đình là nơi chúng ta bắt đầu cuộc sống và cũng là nơi luôn dang rộng vòng tay đón ta trở về. "
    "Dù ngoài kia có bao nhiêu khó khăn, áp lực hay mệt mỏi, chỉ cần nghĩ đến gia đình, lòng ta lại có thêm sự bình yên.\n\n"
    "Ý nghĩa của gia đình không nằm ở những điều quá lớn lao, mà nằm trong những bữa cơm giản dị, "
    "những lời hỏi han quen thuộc, những sự quan tâm âm thầm và cả những hy sinh không cần được nhắc đến. "
    "Gia đình là nơi có thể có những lúc bất đồng, nhưng sau tất cả vẫn là yêu thương và bao dung.\n\n"
    "Có thể khi trưởng thành, ta mải mê chạy theo công việc, ước mơ và những mối quan hệ bên ngoài. "
    "Nhưng rồi ta sẽ nhận ra, điều quý giá nhất không phải là đi được bao xa, mà là luôn có một nơi để quay về.\n\n"
    "Gia đình chính là điểm tựa, là yêu thương, là bình yên và là món quà vô giá trong cuộc đời mỗi người."
)
print("len(text)=", len(text))

req = urllib.request.Request(
    "https://api.fpt.ai/hmi/tts/v5",
    data=text.encode("utf-8"),
    method="POST",
    headers={"api-key": key, "voice": "banmai", "speed": "0", "format": "mp3"},
)
t0 = time.time()
with urllib.request.urlopen(req, timeout=60) as resp:
    body = resp.read().decode("utf-8", errors="replace")
print(f"submit took {time.time()-t0:.2f}s status=200 body={body[:300]}")
j = json.loads(body)
audio_url = j.get("async")
print("audio_url", audio_url)

start = time.time()
for i in range(120):
    time.sleep(1.0)
    try:
        with urllib.request.urlopen(audio_url, timeout=10) as r2:
            ctype = r2.headers.get("Content-Type") or ""
            blob = r2.read()
            if "audio" in ctype.lower() and len(blob) > 1000:
                print(f"READY after {time.time()-start:.1f}s ctype={ctype} bytes={len(blob)}")
                break
            else:
                print(f"poll {i+1} t={time.time()-start:.1f}s ctype={ctype} bytes={len(blob)}")
    except urllib.error.HTTPError as e:
        print(f"poll {i+1} t={time.time()-start:.1f}s HTTP {e.code}")
    except Exception as e:
        print(f"poll {i+1} t={time.time()-start:.1f}s err {e}")
else:
    print("TIMEOUT after 120s")
