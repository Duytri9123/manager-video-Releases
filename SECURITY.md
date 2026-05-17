# Security & Migration Notes

Đây là tóm tắt các thay đổi bảo mật vừa được thực hiện cùng tính năng mới.
Đọc trước khi pull về máy khác hoặc deploy.

## ⚠ Bắt buộc làm ngay

Repo này **đã từng commit token thật** (`.facebook_token.json`, `.cookies.json`)
ở các commit `efcc1f1` và `b94be4e`. Các token đó vẫn còn trong git history
nếu repo từng được push. Hãy coi như đã bị lộ:

1. **Revoke / rotate**:
   - Facebook App Secret + tất cả Page Token đang dùng.
   - Google OAuth client (mở Google Cloud Console → API & Services → Credentials → tạo lại).
   - Ngrok authtoken.
   - OpenAI / Groq / DeepSeek / HuggingFace / TikTok / FPT TTS API keys.
2. **Xoá file thật khỏi working tree** (đã làm — file giờ là placeholder rỗng):
   - `config.yml` → giờ là template không key
   - `client_secrets.json` → placeholder rỗng
3. **Tuỳ chọn**: viết lại git history bằng `git filter-repo`:
   ```
   git filter-repo --path .facebook_token.json --path .cookies.json --invert-paths
   git push --force
   ```

## Các thay đổi trong code

### Bảo mật
- `core_app.py`: SECRET_KEY tự sinh (`.state/.flask_secret`) hoặc lấy từ `FLASK_SECRET_KEY` env. Không còn hardcoded `"douyin-dl-secret"`.
- `core_app.py`: `_DEFAULT_COOKIES` đã xoá. Cookies đọc từ `config.yml.cookies` hoặc `.cookies.json` (gitignored).
- `core/video_processor.py`: `FPT_TTS_DEFAULT_KEY` rỗng. Lấy qua env `FPT_TTS_API_KEY` hoặc `video_process.fpt_api_key`.
- `core_app.py`: CORS giới hạn về `localhost`/`127.0.0.1`/ngrok URL thay vì `*`. Bật rộng hơn qua `auth.cors_origins` trong `config.yml`.
- `core_app.py`: max upload giảm từ 2 GB → 512 MB (tuỳ chỉnh `WEBAPP_MAX_UPLOAD_MB`).
- `routes/content.py`: vá path traversal trong `delete_content` / `rename_content`.
- `auth/web_auth.py` (mới): cổng đăng nhập 1-người-dùng + CSRF token cho POST/PUT/DELETE/PATCH. Mặc định **off**, bật bằng `auth.enabled: true` trong `config.yml`.

### Hạ tầng
- `Dockerfile`: fix entrypoint sai (`run.py` → `run_flask.py`), cài thêm `ffmpeg`, `tesseract-ocr-vie`, `fonts-noto-cjk`, `libsndfile1`, healthcheck.
- `vercel.json`: xoá (Flask-SocketIO/FFmpeg/Playwright không chạy được trên Vercel serverless).
- `requirements.txt`: bổ sung 9 dep đang được import nhưng thiếu (`faster-whisper`, `edge-tts`, `gtts`, `playwright`, `pydub`, `numpy`, `imageio-ffmpeg`, `aiosqlite`, `PySocks`); pin lower bounds rõ ràng.
- `.dockerignore`: nối thêm `.state/`, `youtube_token.pickle`.

## Tính năng mới

### 🌐 Proxy Pool (`/proxies`)
- Quản lý HTTP / HTTPS / SOCKS4 / SOCKS5 proxy.
- Bulk import nhiều dòng (chấp nhận `host:port`, `host:port:user:pass`, full URL).
- Test từng proxy hoặc test tất cả (đo latency, lấy IP công cộng).
- 3 chiến lược rotation: `round_robin`, `random`, `sticky`.
- Auto-disable proxy sau 5 lần fail liên tiếp.
- Persisted vào `.state/proxies.json` (gitignored).
- Tự động được Douyin API client dùng khi `proxies.enabled: true`.

API: `/api/proxies/{list, add, bulk_import, update, delete, test, test_all, pick}`

### 📡 Router rotation (`/proxies` → block "4G/LTE Router")
Buộc router đổi IP công cộng bằng cách gọi HTTP request hoặc shell command. 5 preset có sẵn:
- Huawei HiLink (toggle data switch)
- TP-Link 4G/LTE (luci reconnect)
- MikroTik (DHCP release+renew)
- 9Proxy gateway rotate (residential)
- Shell — airplane mode toggle qua adb

Mỗi router có cooldown để tránh hammering. Sau rotate sẽ verify IP mới.

API: `/api/routers/{list, presets, add, update, delete, rotate}`

### 🎬 Movie review (`/movie`)
- Tích hợp **TMDb** API (cần `movie.tmdb_api_key` hoặc env `TMDB_API_KEY`).
- Search phim/series, xem chi tiết (đạo diễn, diễn viên, điểm), trending.
- Sinh **kịch bản review** bằng LLM (DeepSeek/OpenAI/Groq):
  - 4 phong cách: `cinematic`, `informative`, `hook_short` (Reels/Shorts), `top_list`.
  - Tuỳ chỉnh thời lượng (giây), tự ước tính số từ.
  - Output JSON `{title, hashtags, hook, script, thumbnail_idea}`.
  - Có fallback template nếu chưa có LLM key.
- Cache TMDb lookup vào `.state/tmdb_cache.json` (TTL mặc định 24h).

API: `/api/movie/{status, search, details, trending, review}`

### 📖 Truyện → Video Script (`/story`)
- 3 nguồn input: paste văn bản, fetch URL bài viết (qua proxy nếu cần),
  upload **ZIP truyện tranh** (giải nén + OCR bằng tesseract `vie+eng`).
- Pipeline: normalize → split sentences → chunk theo target/max chars
  (mặc định 350/600 ký tự, có overlap câu nếu cần).
- Tuỳ chọn dịch sang ngôn ngữ đích bằng provider có sẵn.
- Output từng segment kèm `est_duration_sec` để gửi sang TTS.
- Auto-save kết quả vào `Downloaded/scripts/<title>_<ts>.json`.

API: `/api/story/{normalize, fetch_url, chunk, generate, comic_upload, comic_ocr}`

## Khuyến nghị deploy

```bash
# 1. Build container
docker build -t duytris .

# 2. Chạy với mật khẩu bắt buộc (đặc biệt khi mở LAN/ngrok)
docker run -d \
  -p 5000:5000 \
  -v $(pwd)/Downloaded:/app/Downloaded \
  -v $(pwd)/.state:/app/.state \
  -v $(pwd)/config.yml:/app/config.yml \
  -e WEBAPP_PASSWORD=your-strong-password \
  -e FLASK_SECRET_KEY=$(openssl rand -hex 32) \
  -e TMDB_API_KEY=... \
  -e DEEPSEEK_API_KEY=... \
  duytris
```

Sau khi container start lần đầu, mở `http://localhost:5000/login`, đăng nhập
bằng `WEBAPP_PASSWORD`. Bật `auth.enabled: true` trong `config.yml` để cổng
auth có hiệu lực (mặc định false để giữ tương thích ngược trên dev local).

## Backwards compatibility

Khi `auth.enabled: false` (mặc định), toàn bộ behavior cũ giữ nguyên — không
có guard, không CSRF, hoạt động đúng như trước. Mọi blueprint/endpoint cũ
vẫn còn nguyên (tổng cộng 32 endpoint mới, 0 endpoint cũ bị xoá). 
