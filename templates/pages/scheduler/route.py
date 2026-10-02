"""Closed-loop content planning and publishing schedule API."""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import socket
import sqlite3
import threading
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta
from html import unescape
from pathlib import Path

from flask import Blueprint, jsonify, request

from core_app import STATE_DIR, LOGGER, ROOT

bp = Blueprint("scheduler", __name__)
DB_PATH = STATE_DIR / "publishing_schedule.db"
STATUSES = {"queued", "draft", "planned", "processing", "ready", "publishing", "published", "failed"}
_PROCESS_PROFILES_FILE = ROOT / "data" / "process_profiles.json"


def _db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS schedule_items (
      id TEXT PRIMARY KEY, source_url TEXT NOT NULL, source_title TEXT DEFAULT '', source_summary TEXT DEFAULT '',
      platform TEXT DEFAULT 'youtube', account_id TEXT DEFAULT '', account_name TEXT DEFAULT '', video_path TEXT DEFAULT '',
      processing_json TEXT DEFAULT '{}', caption TEXT DEFAULT '', scheduled_at TEXT DEFAULT '', timezone TEXT DEFAULT 'Asia/Ho_Chi_Minh',
      status TEXT DEFAULT 'draft', published_url TEXT DEFAULT '', error TEXT DEFAULT '', ai_generated INTEGER DEFAULT 0,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL, published_at TEXT DEFAULT ''
    )""")

    # Safe migration: ensure new columns exist
    existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(schedule_items)").fetchall()}
    new_cols = [
        ("preset_id", "TEXT DEFAULT ''"),
        ("preset_name", "TEXT DEFAULT ''"),
        ("post_title", "TEXT DEFAULT ''"),
        ("hashtags", "TEXT DEFAULT ''"),
        ("tone", "TEXT DEFAULT 'hấp dẫn'"),
        ("thumbnail_url", "TEXT DEFAULT ''"),
    ]
    for col_name, col_def in new_cols:
        if col_name not in existing_cols:
            try:
                conn.execute(f"ALTER TABLE schedule_items ADD COLUMN {col_name} {col_def}")
            except Exception:
                pass
    conn.commit()
    return conn


def _row(row):
    item = dict(row)
    try:
        item["processing"] = json.loads(item.pop("processing_json") or "{}")
    except Exception:
        item["processing"] = {}
    item["ai_generated"] = bool(item.get("ai_generated"))
    return item


def _validate_url(value: str) -> str:
    value = (value or "").strip()
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Link phải bắt đầu bằng http:// hoặc https://")
    try:
        for info in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                raise ValueError("Không cho phép truy cập địa chỉ mạng nội bộ")
    except socket.gaierror as exc:
        raise ValueError("Không phân giải được tên miền") from exc
    return value


def _fetch_metadata(url: str):
    url = _validate_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 ToolVideo/1.0", "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=12) as response:
        ctype = response.headers.get("Content-Type", "")
        if "text/html" not in ctype:
            return {"url": response.geturl(), "title": urllib.parse.urlparse(url).netloc, "summary": "Nguồn media trực tiếp"}
        raw = response.read(1_000_000).decode("utf-8", "replace")

    def meta(prop):
        patterns = [
            rf'<meta[^>]+(?:property|name)=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']+)',
            rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']{re.escape(prop)}["\']'
        ]
        for pattern in patterns:
            hit = re.search(pattern, raw, re.I)
            if hit:
                return unescape(hit.group(1)).strip()
        return ""

    title_hit = re.search(r"<title[^>]*>(.*?)</title>", raw, re.I | re.S)
    title = meta("og:title") or (unescape(re.sub(r"\s+", " ", title_hit.group(1))).strip() if title_hit else "")
    summary = meta("og:description") or meta("description")
    return {"url": url, "title": title[:300], "summary": summary[:1500], "image": meta("og:image")}


def _compute_batch_schedules(start_dt_str: str, count: int, mode: str, interval_hours: float = 24.0, golden_slots: list = None) -> list[str]:
    """Compute progressive ISO scheduled_at timestamps."""
    schedules = []
    try:
        current = datetime.fromisoformat(start_dt_str) if start_dt_str else datetime.now() + timedelta(hours=1)
    except Exception:
        current = datetime.now() + timedelta(hours=1)

    golden_slots = golden_slots or ["11:30", "19:30"]

    if mode == "golden_hours":
        day_offset = 0
        slot_idx = 0
        base_date = current.date()
        for i in range(count):
            slot_time_str = golden_slots[slot_idx % len(golden_slots)]
            sh, sm = [int(p) for p in slot_time_str.split(":")]
            target_dt = datetime.combine(base_date + timedelta(days=day_offset), datetime.min.time().replace(hour=sh, minute=sm))
            if target_dt < current and i == 0:
                slot_idx += 1
                if slot_idx >= len(golden_slots):
                    slot_idx = 0
                    day_offset += 1
                slot_time_str = golden_slots[slot_idx % len(golden_slots)]
                sh, sm = [int(p) for p in slot_time_str.split(":")]
                target_dt = datetime.combine(base_date + timedelta(days=day_offset), datetime.min.time().replace(hour=sh, minute=sm))
            schedules.append(target_dt.isoformat(timespec="minutes"))
            slot_idx += 1
            if slot_idx % len(golden_slots) == 0:
                day_offset += 1
    elif mode == "interval":
        hours = max(0.5, float(interval_hours or 24.0))
        for i in range(count):
            target_dt = current + timedelta(hours=i * hours)
            schedules.append(target_dt.isoformat(timespec="minutes"))
    else:
        fixed = current.isoformat(timespec="minutes")
        schedules = [fixed] * count
    return schedules


@bp.route("/api/scheduler/items", methods=["GET", "POST"])
def items():
    conn = _db()
    if request.method == "GET":
        status = (request.args.get("status") or "").strip()
        sql, params = "SELECT * FROM schedule_items", []
        if status in STATUSES:
            sql, params = sql + " WHERE status=?", [status]
        rows = conn.execute(sql + " ORDER BY CASE WHEN scheduled_at='' THEN 1 ELSE 0 END, scheduled_at, created_at DESC", params).fetchall()
        conn.close()
        return jsonify({"ok": True, "items": [_row(r) for r in rows]})

    data = request.get_json(silent=True) or {}
    urls = data.get("urls") or [data.get("source_url")]
    if isinstance(urls, str):
        urls = [line.strip() for line in urls.splitlines() if line.strip()]

    valid_urls = [u.strip() for u in (urls or []) if u and u.strip()]
    if not valid_urls:
        conn.close()
        return jsonify({"ok": False, "error": "Chưa có đường link hoặc file video"}), 400

    count = len(valid_urls)
    batch_mode = data.get("batch_mode") or ("interval" if data.get("is_batch") else "fixed")
    start_at = data.get("scheduled_at") or data.get("start_at") or ""
    interval_hours = data.get("interval_hours", 24)
    computed_schedules = _compute_batch_schedules(start_at, count, batch_mode, interval_hours)

    accounts = data.get("accounts") or []
    round_robin = bool(data.get("round_robin")) and len(accounts) > 1

    preset_name = data.get("preset_name", "")
    preset_id = data.get("preset_id", "")
    hashtags = data.get("hashtags", "")
    tone = data.get("tone", "hấp dẫn")

    # Support multiple platforms for the same video
    raw_platforms = data.get("platforms")
    if isinstance(raw_platforms, list) and len(raw_platforms) > 0:
        target_platforms = [str(p).strip().lower() for p in raw_platforms if str(p).strip()]
    else:
        target_platforms = [str(data.get("platform") or "youtube").strip().lower()]

    platform_accounts = data.get("platform_accounts") or {}
    default_acc_id = data.get("account_id", "")
    default_acc_name = data.get("account_name", "")
    processing_dict = data.get("processing") or {}

    created, now = [], datetime.now().isoformat(timespec="seconds")
    for i, source_url in enumerate(valid_urls[:100]):
        source_url = _resolve_search_url(source_url)
        sched_time = computed_schedules[i] if i < len(computed_schedules) else start_at
        video_path = data.get("video_path", "") if count == 1 else ""

        for plat in target_platforms:
            item_id = uuid.uuid4().hex

            # Resolve account for this specific platform
            plat_acc = platform_accounts.get(plat) or {}
            if plat_acc and (plat_acc.get("id") or plat_acc.get("name")):
                acc_id = str(plat_acc.get("id") or "")
                acc_name = str(plat_acc.get("name") or plat_acc.get("channel_title") or acc_id)
            elif round_robin and accounts:
                acc = accounts[i % len(accounts)]
                acc_id = str(acc.get("id") or acc.get("account_id") or "")
                acc_name = str(acc.get("name") or acc.get("channel_title") or acc_id)
            elif plat == data.get("platform"):
                acc_id = default_acc_id
                acc_name = default_acc_name
            else:
                acc_id = ""
                acc_name = ""

            init_status = "queued"

            conn.execute("""INSERT INTO schedule_items
              (id, source_url, source_title, source_summary, platform, account_id, account_name, video_path,
               processing_json, caption, scheduled_at, timezone, status, ai_generated, preset_id, preset_name,
               post_title, hashtags, tone, created_at, updated_at)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (item_id, source_url, data.get("source_title", ""), data.get("source_summary", ""),
               plat, acc_id, acc_name, video_path,
               json.dumps(processing_dict, ensure_ascii=False), data.get("caption", ""),
               sched_time, data.get("timezone", "Asia/Ho_Chi_Minh"),
               init_status, int(bool(data.get("ai_generated"))),
               preset_id, preset_name, data.get("post_title", ""), hashtags, tone,
               now, now))
            created.append(item_id)

    conn.commit()
    conn.close()
    return jsonify({"ok": True, "ids": created, "count": len(created)}), 201


@bp.route("/api/scheduler/items/<item_id>", methods=["PATCH", "DELETE"])
def item_detail(item_id):
    conn = _db()
    current = conn.execute("SELECT status FROM schedule_items WHERE id=?", (item_id,)).fetchone()
    if current and current["status"] in {"processing", "publishing"}:
        conn.close()
        return jsonify({"ok": False, "error": "Chờ tác vụ hiện tại hoàn tất trước khi sửa hoặc xóa"}), 409
    if request.method == "DELETE":
        conn.execute("DELETE FROM schedule_items WHERE id=?", (item_id,))
        conn.commit()
        conn.close()
        return jsonify({"ok": True})

    data = request.get_json(silent=True) or {}
    allowed = {
        "source_url", "source_title", "source_summary", "platform", "account_id", "account_name",
        "video_path", "caption", "scheduled_at", "timezone", "status", "published_url", "error",
        "published_at", "preset_id", "preset_name", "post_title", "hashtags", "tone", "thumbnail_url"
    }
    fields, params = [], []
    for key in allowed:
        if key in data:
            if key == "status" and data[key] not in STATUSES:
                continue
            fields.append(f"{key}=?")
            params.append(data[key])
    if "processing" in data:
        fields.append("processing_json=?")
        params.append(json.dumps(data["processing"], ensure_ascii=False))

    if not fields:
        conn.close()
        return jsonify({"ok": False, "error": "Không có dữ liệu cập nhật"}), 400

    fields.append("updated_at=?")
    params.extend([datetime.now().isoformat(timespec="seconds"), item_id])
    conn.execute(f"UPDATE schedule_items SET {', '.join(fields)} WHERE id=?", params)
    conn.commit()
    row = conn.execute("SELECT * FROM schedule_items WHERE id=?", (item_id,)).fetchone()
    conn.close()
    return jsonify({"ok": True, "item": _row(row) if row else None})


# ── XỬ LÝ VIDEO BẰNG PROCESSOR (ASYNC THREAD) ───────────────────────────────

def _run_processing_job(item_id: str):
    """Worker thread that executes video download + full processor pipeline."""
    conn = _db()
    row = conn.execute("SELECT * FROM schedule_items WHERE id=?", (item_id,)).fetchone()
    if not row:
        conn.close()
        return
    item = _row(row)
    now = datetime.now().isoformat(timespec="seconds")
    claimed = conn.execute("UPDATE schedule_items SET status='processing', error='', updated_at=? WHERE id=? AND status IN ('queued','planned','draft','failed')", (now, item_id)).rowcount
    conn.commit()
    conn.close()
    if not claimed:
        return

    try:
        source_url = item.get("source_url") or ""
        video_path = item.get("video_path") or ""
        preset_name = item.get("preset_name") or ""
        processing = item.get("processing") or {}

        req_settings = dict(processing)
        if not req_settings and preset_name and _PROCESS_PROFILES_FILE.exists():
            profiles = json.loads(_PROCESS_PROFILES_FILE.read_text(encoding="utf-8"))
            req_settings = dict((profiles.get(preset_name) or {}).get("processing") or {})
        if not req_settings or any(key.startswith("proc-") for key in req_settings) or "subtitles" in req_settings:
            raise ValueError("Hãy chọn lại cấu hình bước 2 và lưu lịch để đồng bộ đầy đủ thông số")
        req_settings["skip_ass_review"] = True

        if not video_path or not Path(video_path).exists():
            if not source_url.startswith("http://") and not source_url.startswith("https://"):
                if Path(source_url).exists():
                    video_path = source_url
                else:
                    raise FileNotFoundError(f"Không tìm thấy video tại đường dẫn: {source_url}")
            else:
                LOGGER.info("Scheduler: Downloading video from %s", source_url)
                from templates.pages.process.route import download_original_source
                video_path, downloaded_title = download_original_source(source_url)
                req_settings["video_title"] = downloaded_title

        from core.video_processor import process_video_full
        req_settings["video_path"] = str(video_path)
        req_settings["delete_source_after_process"] = False

        final_output_path = None
        for line in process_video_full(req_settings):
            if isinstance(line, bytes):
                line = line.decode("utf-8", "ignore")
            try:
                ev = json.loads(line)
            except (ValueError, TypeError):
                continue
            if ev.get("failed"):
                raise RuntimeError(ev.get("log") or "Xử lý video thất bại")
            if ev.get("file_path"):
                final_output_path = ev["file_path"]

        if not final_output_path or not Path(final_output_path).is_file():
            raise RuntimeError("Xử lý chưa tạo được video đầu ra; không đăng video gốc")

        conn = _db()
        now = datetime.now().isoformat(timespec="seconds")
        conn.execute("UPDATE schedule_items SET status='ready', error='', video_path=?, updated_at=? WHERE id=?",
                     (str(final_output_path), now, item_id))
        conn.commit()
        conn.close()
        LOGGER.info("Scheduler item %s processed successfully: %s", item_id, final_output_path)

    except Exception as exc:
        LOGGER.exception("Scheduler job processing failed for item %s: %s", item_id, exc)
        conn = _db()
        now = datetime.now().isoformat(timespec="seconds")
        conn.execute("UPDATE schedule_items SET status='failed', error=?, updated_at=? WHERE id=?",
                     (str(exc), now, item_id))
        conn.commit()
        conn.close()


@bp.route("/api/scheduler/items/<item_id>/process", methods=["POST"])
def trigger_process(item_id):
    """Trigger background video processing for this scheduled item."""
    conn = _db()
    row = conn.execute("SELECT * FROM schedule_items WHERE id=?", (item_id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"ok": False, "error": "Không tìm thấy nội dung"}), 404

    conn = _db()
    changed = conn.execute("UPDATE schedule_items SET status='queued', error='' WHERE id=? AND status IN ('draft','planned','failed')", (item_id,)).rowcount
    conn.commit()
    conn.close()
    if not changed:
        return jsonify({"ok": False, "error": "Video đã nằm trong hàng chờ hoặc đã xử lý"}), 409
    _start_schedule_worker()
    return jsonify({"ok": True, "message": "Đã bắt đầu xử lý video ngầm"})


# ── ĐĂNG BÀI LÊN MẠNG XÃ HỘI (ASYNC THREAD) ──────────────────────────────────

def _run_publishing_job(item_id: str):
    """Worker thread that executes publishing to YouTube/TikTok/Facebook."""
    conn = _db()
    row = conn.execute("SELECT * FROM schedule_items WHERE id=?", (item_id,)).fetchone()
    if not row:
        conn.close()
        return
    item = _row(row)
    now = datetime.now().isoformat(timespec="seconds")
    claimed = conn.execute("UPDATE schedule_items SET status='publishing', error='', updated_at=? WHERE id=? AND status='ready'", (now, item_id)).rowcount
    conn.commit()
    conn.close()
    if not claimed:
        return

    try:
        platform = (item.get("platform") or "youtube").lower()
        video_path = item.get("video_path")
        if not video_path or not Path(video_path).exists():
            raise FileNotFoundError(f"Chưa có file video hoàn thiện để đăng (video_path={video_path})")

        title = item.get("post_title") or item.get("source_title") or Path(video_path).stem
        caption = item.get("caption") or ""
        hashtags = item.get("hashtags") or ""

        full_content = caption
        if hashtags and hashtags not in full_content:
            full_content = f"{caption}\n\n{hashtags}".strip()

        published_url = ""

        if platform == "youtube":
            from tools.youtube_uploader import YouTubeUploader
            uploader = YouTubeUploader(account_id=item.get("account_id") or None)
            if not uploader.credentials and not uploader.authenticate():
                raise RuntimeError("Chưa đăng nhập tài khoản YouTube")

            tags_list = [t.strip().lstrip("#") for t in hashtags.split() if t.strip()]
            res = uploader.upload_video(
                video_path=Path(video_path),
                title=title[:100],
                description=full_content,
                tags=tags_list or ["shorts", "video"],
                privacy_status="public",
                is_short=True
            )
            if not res or not res.get("url"):
                raise RuntimeError("YouTube upload thất bại")
            published_url = res.get("url")

        elif platform == "facebook":
            from templates.pages.publish.facebook import _load_fb_token, _resolve_page_token
            td = _load_fb_token()
            if not td:
                raise RuntimeError("Chưa kết nối tài khoản Facebook")
            page_id = item.get("account_id")
            page_token, perr = _resolve_page_token(td, page_id)
            if not page_token:
                raise RuntimeError(perr or "Không tìm thấy Facebook Page token")

            import urllib.request
            req_init = urllib.request.Request(
                f"https://graph.facebook.com/v19.0/{page_id}/video_reels",
                data=urllib.parse.urlencode({"upload_phase": "start", "access_token": page_token}).encode(),
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            with urllib.request.urlopen(req_init, timeout=20) as resp:
                init_res = json.loads(resp.read().decode())
            video_id = init_res.get("video_id")
            upload_url = init_res.get("upload_url")
            if not upload_url:
                raise RuntimeError("Không khởi tạo được session upload Facebook Reel")

            with open(video_path, "rb") as f:
                video_bytes = f.read()
            req_bin = urllib.request.Request(
                upload_url,
                data=video_bytes,
                headers={"Authorization": f"OAuth {page_token}", "offset": "0", "file_size": str(len(video_bytes))}
            )
            with urllib.request.urlopen(req_bin, timeout=120) as resp:
                resp.read()

            req_fin = urllib.request.Request(
                f"https://graph.facebook.com/v19.0/{page_id}/video_reels",
                data=urllib.parse.urlencode({
                    "upload_phase": "finish",
                    "access_token": page_token,
                    "video_id": video_id,
                    "video_state": "PUBLISHED",
                    "description": full_content
                }).encode(),
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            with urllib.request.urlopen(req_fin, timeout=20) as resp:
                fin_res = json.loads(resp.read().decode())
            if not fin_res.get("success"):
                raise RuntimeError(f"Xuất bản Reel Facebook lỗi: {fin_res}")
            published_url = f"https://www.facebook.com/{page_id}/videos/{video_id}"

        elif platform == "tiktok":
            from templates.pages.publish.tiktok import _new_session, _sessions, _sessions_lock, _run_upload_flow
            from auth.account_manager import get_tiktok_account_manager
            sid = uuid.uuid4().hex
            with _sessions_lock:
                _sessions[sid] = _new_session()
                _sessions[sid]["auto_publish"] = True
            account_id = item.get("account_id")
            profile = get_tiktok_account_manager().get_profile_dir(None if account_id in {None, '', 'default'} else account_id)
            asyncio.run(_run_upload_flow(sid, Path(video_path), full_content or title, profile))
            state = _sessions[sid]
            if not state.get("published"):
                raise RuntimeError(state.get("error") or "TikTok chưa xác nhận đăng thành công")
            published_url = state.get("published_url") or ""
        else:
            raise ValueError(f"Nền tảng chưa hỗ trợ: {platform}")

        conn = _db()
        now = datetime.now().isoformat(timespec="seconds")
        conn.execute("UPDATE schedule_items SET status='published', published_url=?, published_at=?, updated_at=? WHERE id=?",
                     (published_url, now, now, item_id))
        conn.commit()
        conn.close()
        LOGGER.info("Scheduler item %s published successfully to %s: %s", item_id, platform, published_url)
        try:
            from core.publish_history import record
            record(platform, 'published', video_path=video_path, title=item.get('post_title') or item.get('caption') or '',
                   account=item.get('account_name') or item.get('account_id') or '', url=published_url, source='scheduler')
        except Exception:
            LOGGER.exception('Could not save published result')

    except Exception as exc:
        LOGGER.exception("Publishing failed for item %s: %s", item_id, exc)
        conn = _db()
        now = datetime.now().isoformat(timespec="seconds")
        conn.execute("UPDATE schedule_items SET status='failed', error=?, updated_at=? WHERE id=?",
                     (str(exc), now, item_id))
        conn.commit()
        conn.close()
        try:
            from core.publish_history import record
            record(platform, 'failed', video_path=item.get('video_path') or '',
                   title=item.get('post_title') or '', account=item.get('account_name') or '',
                   error=str(exc), source='scheduler')
        except Exception:
            LOGGER.exception('Could not save failed publish result')


@bp.route("/api/scheduler/items/<item_id>/publish", methods=["POST"])
def trigger_publish(item_id):
    """Trigger publishing of a ready video item immediately."""
    conn = _db()
    row = conn.execute("SELECT * FROM schedule_items WHERE id=?", (item_id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"ok": False, "error": "Không tìm thấy nội dung"}), 404

    conn = _db()
    changed = conn.execute("UPDATE schedule_items SET scheduled_at=? WHERE id=? AND status='ready'", (datetime.now().isoformat(), item_id)).rowcount
    conn.commit()
    conn.close()
    if not changed:
        return jsonify({"ok": False, "error": "Video chưa xử lý xong hoặc đã đăng"}), 409
    _start_schedule_worker()
    return jsonify({"ok": True, "message": "Đang tiến hành xuất bản bài đăng..."})


# ── AI LẬP KẾ HOẠCH NỘI DUNG & HASHTAGS ──────────────────────────────────────

@bp.route("/api/scheduler/analyze", methods=["POST"])
def analyze():
    data = request.get_json(silent=True) or {}
    try:
        return jsonify({"ok": True, "metadata": _fetch_metadata(data.get("url", ""))})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@bp.route("/api/scheduler/ai-plan", methods=["POST"])
def ai_plan():
    data = request.get_json(silent=True) or {}
    sources = data.get("sources") or []
    if not sources:
        return jsonify({"ok": False, "error": "Chưa có nội dung nguồn"}), 400

    model = (data.get("model") or "gemini-3.8-flash-high").strip()
    tone = data.get("tone") or "Hấp dẫn, viral, kích thích tương tác"
    default_hashtags = data.get("default_hashtags") or ""
    start = data.get("start_at") or (datetime.now() + timedelta(hours=2)).replace(minute=0, second=0).isoformat()

    prompt = f"""Bạn là chuyên gia quản lý nội dung đa nền tảng (YouTube Shorts, TikTok, Facebook Reels).
Nhiệm vụ: Phân tích danh sách link/nội dung nguồn bên dưới, tạo kế hoạch đăng bài tối ưu.
Tone giọng yêu cầu: {tone}.
Hashtags mặc định cần kết hợp: {default_hashtags}.

Yêu cầu cho từng phần tử:
1. source_url: Giữ nguyên link nguồn.
2. title: Tiêu đề video giật tít, tò mò, chuẩn SEO, KHÔNG vượt quá 95 ký tự.
3. caption: Lời mở đầu lôi cuốn, tóm tắt hấp dẫn kèm câu kêu gọi tương tác (CTA).
4. hashtags: Chọn 3-5 hashtag trending liên quan trực tiếp đến nội dung + các hashtag mặc định. Định dạng: #tag1 #tag2 #tag3.
5. platform: youtube hoặc tiktok hoặc facebook.
6. scheduled_at: Lập lịch rải đều các bài vào các khung giờ vàng (11:30 trưa hoặc 19:30 tối), bắt đầu từ {start}.
7. processing: object gồm {{ "aspect_ratio": "9:16", "subtitles": true, "translate": true, "remove_watermark": true }}.

Chỉ trả về duy nhất một mảng JSON (JSON array), không markdown, không giải thích.
Nguồn: {json.dumps(sources, ensure_ascii=False)}"""

    try:
        from core.direct_ai_provider import dispatch_chat_completion
        result = dispatch_chat_completion(model, [{"role": "user", "content": prompt}], temperature=0.4, max_tokens=4096, timeout=90)
        text = (((result.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.I | re.M).strip()
        plan = json.loads(text)
        if not isinstance(plan, list):
            raise ValueError("AI không trả về danh sách kế hoạch")
        return jsonify({"ok": True, "plan": plan})
    except Exception as exc:
        LOGGER.warning("scheduler ai-plan failed: %s", exc)
        return jsonify({"ok": False, "error": f"AI chưa thể lập lịch: {exc}"}), 502


@bp.route("/api/scheduler/stats")
def stats():
    conn = _db()
    rows = conn.execute("SELECT status, COUNT(*) AS total FROM schedule_items GROUP BY status").fetchall()
    conn.close()
    counts = {r["status"]: r["total"] for r in rows}
    return jsonify({"ok": True, "counts": counts, "total": sum(counts.values())})


# ── AI TÌM KIẾM TRENDING & GỢI Ý VIDEO VIRAL ────────────────────────────────

@bp.route("/api/scheduler/trending_hot", methods=["GET"])
def trending_hot():
    """Return top trending niches and search tags."""
    hot_topics = [
        {"id": "douyin_food", "label": "Ẩm thực đường phố Douyin", "query": "ẩm thực đường phố ăn vặt viral", "platform": "douyin"},
        {"id": "movie_recap", "label": "Review phim tóm tắt kịch tính", "query": "review phim tóm tắt kịch tính hay nhất", "platform": "douyin"},
        {"id": "life_hacks", "label": "Mẹo vặt cuộc sống thông minh", "query": "mẹo vặt cuộc sống thông minh hữu ích", "platform": "tiktok"},
        {"id": "ai_tech", "label": "Công nghệ AI & Xu hướng tương lai", "query": "công nghệ AI ứng dụng thú vị mới", "platform": "youtube"},
        {"id": "funny_pets", "label": "Thú cưng vui nhộn & siêu hài", "query": "thú cưng mèo chó hài hước vui nhộn", "platform": "tiktok"},
        {"id": "transformation", "label": "Biến hình & Trang điểm đỉnh cao", "query": "biến hình cosplay makeup ấn tượng", "platform": "douyin"},
    ]
    return jsonify({"ok": True, "topics": hot_topics})


def _resolve_search_url(url: str) -> str:
    """Resolve a search URL (e.g. douyin.com/search/... or youtube.com/results) into a direct video URL."""
    url = (url or "").strip()
    if not url or ("/search" not in url and "search_query=" not in url and "search?q=" not in url):
        return url

    query = ""
    if "/search/" in url:
        query = urllib.parse.unquote(url.split("/search/")[1].split("?")[0].strip("/"))
    elif "search_query=" in url:
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        query = (params.get("search_query") or [""])[0]
    elif "q=" in url:
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        query = (params.get("q") or [""])[0]

    if not query:
        return url

    try:
        import yt_dlp
        ydl_opts = {
            "quiet": True,
            "extract_flat": "in_playlist",
            "skip_download": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            res = ydl.extract_info(f"ytsearch1:{query} shorts", download=False)
            entries = res.get("entries") or []
            if entries and entries[0].get("id"):
                return f"https://www.youtube.com/shorts/{entries[0]['id']}"
    except Exception as exc:
        LOGGER.debug("resolve_search_url fallback skipped: %s", exc)

    return url


@bp.route("/api/scheduler/trending_search", methods=["POST"])
def trending_search():
    """Use AI and search index to discover REAL viral videos with direct playable URLs."""
    data = request.get_json(silent=True) or {}
    query = (data.get("query") or "").strip()
    platform_pref = (data.get("platform") or "all").strip().lower()
    limit = min(max(int(data.get("limit") or 6), 2), 12)

    if not query:
        query = "video ngắn triệu view viral hot nhất"

    real_videos = []

    # 1. Fetch real active videos using yt-dlp search
    try:
        import yt_dlp
        ydl_opts = {
            "quiet": True,
            "extract_flat": "in_playlist",
            "skip_download": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            yt_res = ydl.extract_info(f"ytsearch{min(limit, 4)}:{query} shorts", download=False)
            entries = yt_res.get("entries") or []
            for e in entries:
                vid_id = e.get("id")
                if vid_id:
                    real_videos.append({
                        "title": e.get("title") or query,
                        "topic": "Xu hướng Shorts",
                        "platform": "youtube",
                        "viral_score": 96,
                        "viral_reason": f"Video Shorts thực tế đang được đề xuất mạnh trên YouTube về chủ đề {query}.",
                        "video_concept": "Nội dung ngắn dạng dọc, tiết tấu nhanh, tương tác người xem cao.",
                        "suggested_hashtags": "#shorts #xuhuong #fyp #viral #video",
                        "video_url": f"https://www.youtube.com/shorts/{vid_id}",
                    })
    except Exception as e:
        LOGGER.debug("yt-dlp trending search error: %s", e)

    # 2. AI Prompt requiring STRICT direct video links
    prompt = f"""Bạn là một chuyên gia săn video xu hướng (Trending Video Intelligence) trên TikTok, Douyin và YouTube Shorts.
Chủ đề cần tìm kiếm: "{query}"
Nền tảng ưu tiên: {platform_pref} (all = tìm cả Douyin, TikTok, YouTube Shorts).
Số lượng video gợi ý: {limit} video.

Nhiệm vụ: Cung cấp {limit} video / ý tưởng clip đang cực kỳ thịnh hành (viral) triệu view liên quan đến chủ đề trên.

YÊU CẦU QUAN TRỌNG VỀ ĐƯỜNG LINK VIDEO:
- Trường "video_url" BẮT BUỘC PHẢI LÀ ĐƯỜNG LINK VIDEO TRỰC TIẾP CỤ THỂ ĐỂ TẢI VÀ XỬ LÝ ĐƯỢC:
  + Nếu YouTube: dạng https://www.youtube.com/shorts/... hoặc https://www.youtube.com/watch?v=...
  + Nếu TikTok: dạng https://www.tiktok.com/@username/video/7285623419087457541
  + Nếu Douyin: dạng https://www.douyin.com/video/7388045672230194468 hoặc https://v.douyin.com/...
- TUYỆT ĐỐI KHÔNG ĐƯỢC TRẢ VỀ LINK TÌM KIẾM (như /search/ hay /tag/ hay /hashtag/).

Yêu cầu định dạng: Trả về DUY NHẤT một JSON array chứa các đối tượng:
- "title": Tiêu đề video hấp dẫn, giật tít thu hút người xem (tiếng Việt, dưới 90 ký tự).
- "topic": Phân loại chủ đề ngắn gọn (ví dụ: Ẩm thực, Review, Giải trí, Mẹo hay...).
- "platform": Chọn 'douyin' hoặc 'tiktok' hoặc 'youtube'.
- "viral_score": Điểm số viral ước tính từ 88 đến 99 (số nguyên).
- "viral_reason": Nhận định sắc bén 1-2 câu của AI tại sao video này lại thu hút người xem và lên xu hướng.
- "video_concept": Tóm tắt nội dung 1-2 câu về kịch bản, cảnh mở đầu (hook) và điểm nhấn của clip.
- "suggested_hashtags": 3-5 hashtag thịnh hành nhất cho video này (dạng #tag1 #tag2 #tag3).
- "video_url": Link video cụ thể trực tiếp (KHÔNG PHẢI LINK SEARCH).

Chỉ trả về cú pháp JSON array hợp lệ, không kèm văn bản giải thích hay markdown code fence."""

    try:
        from core.direct_ai_provider import dispatch_chat_completion
        model = "gemini-3.8-flash-high"
        result = dispatch_chat_completion(model, [{"role": "user", "content": prompt}], temperature=0.6, max_tokens=3000, timeout=60)
        text = (((result.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.I | re.M).strip()
        ai_items = json.loads(text)
        if isinstance(ai_items, list):
            # Clean up and ensure direct video links
            for item in ai_items:
                v_url = (item.get("video_url") or item.get("sample_url") or "").strip()
                if "/search" in v_url or "search?q=" in v_url:
                    v_url = _resolve_search_url(v_url)
                item["video_url"] = v_url
                item["sample_url"] = v_url

            # Merge real videos with AI recommendations
            combined = real_videos + [x for x in ai_items if x.get("video_url")]
            seen_urls = set()
            unique_items = []
            for it in combined:
                u = it.get("video_url")
                if u and u not in seen_urls:
                    seen_urls.add(u)
                    unique_items.append(it)

            items = unique_items[:limit] if unique_items else ai_items[:limit]
        else:
            items = real_videos[:limit]

        # Assign unique ID to each result
        for idx, item in enumerate(items):
            item["id"] = f"trend_{idx}_{uuid.uuid4().hex[:8]}"

        return jsonify({"ok": True, "results": items, "query": query})
    except Exception as exc:
        LOGGER.warning("trending_search failed: %s", exc)
        if real_videos:
            for idx, item in enumerate(real_videos):
                item["id"] = f"trend_{idx}_{uuid.uuid4().hex[:8]}"
            return jsonify({"ok": True, "results": real_videos[:limit], "query": query})
        return jsonify({"ok": False, "error": f"Lỗi tìm kiếm trending AI: {exc}"}), 502



# One persistent, ordered queue: prepare immediately, publish only when due.
_schedule_worker_lock = threading.Lock()
_schedule_worker = None

def _schedule_tick():
    conn = _db()
    rows = conn.execute("SELECT id, status, scheduled_at FROM schedule_items WHERE status IN ('queued','planned','ready') ORDER BY CASE WHEN scheduled_at='' THEN 1 ELSE 0 END, scheduled_at, created_at, rowid").fetchall()
    conn.close()
    now = datetime.now().astimezone()
    for row in rows:
        if row['status'] == 'ready' and row['scheduled_at']:
            try:
                due = datetime.fromisoformat(row['scheduled_at'])
                if due.tzinfo is None:
                    from zoneinfo import ZoneInfo
                    due = due.replace(tzinfo=ZoneInfo('Asia/Ho_Chi_Minh'))
                if due <= now:
                    _run_publishing_job(row['id'])
                    return True
            except ValueError:
                continue
    for row in rows:
        if row['status'] in {'queued', 'planned'}:
            _run_processing_job(row['id'])
            return True
    return False

def _start_schedule_worker():
    global _schedule_worker
    with _schedule_worker_lock:
        if _schedule_worker and _schedule_worker.is_alive():
            return
        def run():
            import time
            conn = _db()
            conn.execute("UPDATE schedule_items SET status='queued' WHERE status='processing'")
            conn.execute("UPDATE schedule_items SET status='failed', error='Phiên đăng bị gián đoạn. Kiểm tra bài đã đăng trước khi thử lại.' WHERE status='publishing'")
            conn.commit()
            conn.close()
            while True:
                try:
                    if _schedule_tick():
                        continue
                except Exception:
                    LOGGER.exception('Schedule queue failed')
                time.sleep(5)
        _schedule_worker = threading.Thread(target=run, name='publishing-schedule', daemon=True)
        _schedule_worker.start()

@bp.before_app_request
def _ensure_schedule_worker():
    from flask import current_app
    if not current_app.testing:
        _start_schedule_worker()
