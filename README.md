# DuyTris Downloader - Douyin/TikTok Video Downloader

Công cụ tải video từ Douyin/TikTok với giao diện web, hỗ trợ:
- 🔍 Tìm kiếm và tải video từ user
- 🎬 Xử lý video (phụ đề, dịch, đổi giọng)
- 🎙 Phiên âm tự động (ASS + SRT)
- 📤 Đăng video lên YouTube

## Yêu cầu

- Python 3.8+
- FFmpeg (để xử lý video/audio)

## Cài đặt

### 1. Clone repository

```bash
git clone <repo-url>
cd toolvideo
```

### 2. Tạo virtual environment

```bash
python -m venv .venv
```

**Windows:**
```bash
.venv\Scripts\activate
```

**Linux/Mac:**
```bash
source .venv/bin/activate
```

### 3. Cài đặt dependencies

```bash
pip install -r requirements.txt
```

### 4. Cài đặt FFmpeg

**Windows:**
- Tải từ https://ffmpeg.org/download.html
- Giải nén và thêm vào PATH

**Linux:**
```bash
sudo apt install ffmpeg
```

**Mac:**
```bash
brew install ffmpeg
```

## Cấu hình

Copy file cấu hình mẫu:

```bash
cp config.example.yml config.yml
```

Chỉnh sửa `config.yml` theo nhu cầu:

```yaml
# Thư mục lưu video
path: ./Downloaded

# Số luồng tải đồng thời
thread: 4

# Cookie mode (default hoặc custom)
cookie_mode: default

# API keys (tùy chọn)
translation:
  deepseek_api_key: "sk-..."
  groq_api_key: "gsk_..."

# YouTube upload (tùy chọn)
upload:
  youtube:
    enabled: true
    client_secrets_file: "client_secrets.json"
```

## Chạy ứng dụng

### Chạy Flask Web UI

```bash
python run_flask.py
```

Hoặc:

```bash
python app.py
```

Mở trình duyệt: http://localhost:5000

### Tùy chỉnh host/port

```bash
# Windows
set FLASK_HOST=0.0.0.0
set FLASK_PORT=8080
python run_flask.py

# Linux/Mac
export FLASK_HOST=0.0.0.0
export FLASK_PORT=8080
python run_flask.py
```

## Sử dụng

### 1. Tìm người dùng

- Vào tab "Tìm người dùng"
- Dán URL user Douyin: `https://www.douyin.com/user/...`
- Click "Tìm kiếm"
- Chọn video muốn tải → "Thêm vào hàng chờ"

### 2. Xử lý video

- Vào tab "Xử lý Video"
- Import file video hoặc nhập URL
- Cấu hình:
  - ✅ Phụ đề & Dịch (ASS/SRT)
  - ✅ Đổi giọng tiếng Việt
  - ✅ Anti-Fingerprint (lách bản quyền)
- Click "▶ Xử lý ngay"

### 3. Phiên âm

- Vào tab "Phiên âm"
- Chọn thư mục video hoặc file đơn
- Chọn mô hình Whisper (base/small/medium)
- Click "▶ Bắt đầu phiên âm"
- Xuất file `.ass` và `.srt`

### 4. Đăng YouTube

- Vào tab "Xử lý Video" → Card "🚀 Đăng video"
- Đăng nhập YouTube (cần `client_secrets.json`)
- Chọn file video đã xử lý
- Nhập tiêu đề, mô tả
- Click "🚀 Đăng video"

## Cấu trúc thư mục

```
toolvideo/
├── app.py                 # Flask web server
├── run_flask.py           # Launcher script
├── config.yml             # Cấu hình
├── requirements.txt       # Python dependencies
├── auth/                  # Cookie & auth management
├── core/                  # Core downloaders
│   ├── video_downloader.py
│   ├── user_downloader.py
│   ├── transcript_manager.py
│   └── video_processor.py
├── storage/               # Database & file management
├── templates/             # Web UI templates
│   ├── spa_new.html
│   └── components/
├── static/                # CSS, JS, assets
├── tools/                 # YouTube uploader
└── utils/                 # Helpers
```

## API Keys

### DeepSeek (Dịch phụ đề)

1. Đăng ký tại: https://platform.deepseek.com/
2. Tạo API key
3. Thêm vào `config.yml`:

```yaml
translation:
  deepseek_api_key: "sk-..."
```

### Groq (Whisper phiên âm nhanh)

1. Đăng ký tại: https://console.groq.com/
2. Tạo API key
3. Thêm vào `config.yml`:

```yaml
translation:
  groq_api_key: "gsk_..."
```

### YouTube Upload

1. Tạo project tại: https://console.cloud.google.com/
2. Enable YouTube Data API v3
3. Tạo OAuth 2.0 credentials
4. Tải `client_secrets.json` về thư mục gốc
5. Cấu hình trong `config.yml`:

```yaml
upload:
  youtube:
    enabled: true
    client_secrets_file: "client_secrets.json"
```

## Troubleshooting

### Lỗi "FFmpeg not found"

Cài đặt FFmpeg và thêm vào PATH.

### Lỗi "Cookie invalid"

- Vào tab "Cookies"
- Bật "Dùng Cookie tùy chỉnh"
- Lấy cookie từ trình duyệt (F12 → Application → Cookies → douyin.com)
- Dán vào và click "Phân tích" → "Lưu"

### Lỗi "API key missing"

Thêm API keys vào `config.yml` (xem phần API Keys ở trên).

### Port 5000 đã được sử dụng

```bash
# Đổi port
set FLASK_PORT=8080
python run_flask.py
```

## Tính năng

### ✅ Đã có
- Tải video đơn/hàng loạt
- Tìm kiếm user và tải tất cả video
- Phiên âm tự động (Whisper)
- Tạo phụ đề ASS/SRT
- Dịch phụ đề sang tiếng Việt
- Đổi giọng tiếng Việt (TTS)
- Anti-fingerprint (lách bản quyền)
- Đăng YouTube tự động
- Web UI responsive (Tailwind CSS)

### ❌ Đã xóa
- CLI interface (chỉ dùng Web UI)
- TikTok upload (chỉ giữ YouTube)
- HuggingFace TTS local (dùng cloud TTS)
- CapCut integration
- Desktop GUI (Tkinter)

## License

MIT License

## Credits

- Flask - Web framework
- Tailwind CSS - UI styling
- OpenAI Whisper - Speech recognition
- FFmpeg - Video/audio processing
- Edge TTS / FPT AI - Text-to-speech
