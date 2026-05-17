# DuyTris Downloader — production-ish container
# Build:  docker build -t duytris .
# Run:    docker run -p 5000:5000 -v $(pwd)/Downloaded:/app/Downloaded \
#               -v $(pwd)/.state:/app/.state \
#               -e WEBAPP_PASSWORD=changeme \
#               duytris
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Native deps:
#  - ffmpeg (video pipeline)
#  - libsndfile1 (pydub / soundfile)
#  - tesseract (optional, used by storywriter comic OCR)
#  - fonts-noto-cjk (subtitle burn-in for CJK languages)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        libsndfile1 \
        tesseract-ocr tesseract-ocr-vie tesseract-ocr-eng \
        fonts-noto-cjk \
        ca-certificates \
        gcc && \
    rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install -r requirements.txt

# (Optional) install Playwright Chromium for TikTok semi-auto upload
# Enable by setting INSTALL_PLAYWRIGHT=1 at build time.
ARG INSTALL_PLAYWRIGHT=0
RUN if [ "$INSTALL_PLAYWRIGHT" = "1" ]; then \
        python -m playwright install --with-deps chromium; \
    fi

COPY . .

RUN mkdir -p /app/Downloaded /app/.state /app/temp_uploads

EXPOSE 5000

# Bind 0.0.0.0 inside the container; require auth via WEBAPP_PASSWORD.
ENV FLASK_HOST=0.0.0.0 FLASK_PORT=5000 OPEN_BROWSER=0

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:5000/healthz', timeout=3)" || exit 1

CMD ["python", "run_flask.py"]
