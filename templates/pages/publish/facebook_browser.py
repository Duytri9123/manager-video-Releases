"""Facebook Page publishing through an isolated Playwright browser session."""
from __future__ import annotations

import asyncio
import hashlib
import re
import shutil
import threading
import time
import uuid
from pathlib import Path

from flask import jsonify, request
from core_app import ROOT
from core.publish_history import record

_sessions = {}
_lock = threading.Lock()
_profiles = ROOT / '.facebook_browser_profiles'


def _profile(account):
    return _profiles / hashlib.sha256(account.encode('utf-8')).hexdigest()[:16]


def _update(sid, **values):
    with _lock:
        _sessions[sid].update(values)


def _start(kind, data):
    sid = uuid.uuid4().hex[:12]
    with _lock:
        _sessions[sid] = {'status': 'starting', 'done': False, 'error': '', 'url': ''}
    def run():
        try:
            asyncio.run(_run(sid, kind, data))
        except Exception as exc:
            _update(sid, status='error', done=True, error=str(exc))
            if kind == 'upload':
                record('facebook', 'failed', video_path=data.get('video_path', ''),
                       title=data.get('caption', ''), account=data.get('page_id', ''), error=str(exc), source='browser')
    threading.Thread(target=run, daemon=True).start()
    return sid


async def _run(sid, kind, data):
    from playwright.async_api import async_playwright
    account = str(data.get('account_id') or 'default')
    profile = _profile(account)
    profile.mkdir(parents=True, exist_ok=True)
    session_profile = ROOT / '.facebook_browser_sessions' / sid
    user_dir = profile
    if kind == 'upload':
        shutil.copytree(profile, session_profile, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('Cache', 'Code Cache', 'GPUCache', 'Singleton*', 'lockfile'))
        user_dir = session_profile
    try:
        async with async_playwright() as playwright:
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir=str(user_dir), headless=False, no_viewport=True, locale='vi-VN',
                args=['--start-maximized'])
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                target = 'https://www.facebook.com/' if kind == 'login' else (
                    f"https://business.facebook.com/latest/composer?asset_id={data['page_id']}")
                _update(sid, status='opening')
                await page.goto(target, wait_until='domcontentloaded', timeout=60000)
                if kind == 'login':
                    deadline = time.time() + 600
                    while time.time() < deadline:
                        if 'login' not in page.url and await page.locator('[aria-label="Account"], [aria-label="Tài khoản"], [role="navigation"]').count():
                            (profile / '.connected').write_text('1', encoding='ascii')
                            _update(sid, status='ready', done=True)
                            return
                        _update(sid, status='waiting_login')
                        await asyncio.sleep(2)
                    raise TimeoutError('Chưa đăng nhập Facebook trong 10 phút.')

                _update(sid, status='preparing')
                if 'login' in page.url:
                    _update(sid, status='waiting_login')
                    deadline = time.time() + 600
                    while time.time() < deadline and 'login' in page.url:
                        await asyncio.sleep(2)
                    if 'login' in page.url:
                        raise TimeoutError('Chưa đăng nhập Facebook trong 10 phút.')
                    await page.goto(target, wait_until='domcontentloaded', timeout=60000)
                video = Path(data['video_path'])
                file_input = page.locator('input[type="file"][accept*="video"], input[type="file"]').first
                try:
                    await file_input.wait_for(state='attached', timeout=30000)
                    await file_input.set_input_files(str(video), timeout=30000)
                except Exception:
                    _update(sid, status='ready', error='Hãy chọn video và hoàn tất bài đăng trong trình duyệt.')
                    await _wait_for_close(page)
                    return
                caption = str(data.get('caption') or '')
                if caption:
                    for selector in ('[role="textbox"][contenteditable="true"]', 'textarea'):
                        field = page.locator(selector).first
                        if await field.count():
                            await field.fill(caption)
                            break
                _update(sid, status='ready')
                if data.get('auto_publish'):
                    button = page.get_by_role('button', name=re.compile(r'^(Publish|Share now|Post|Đăng|Chia sẻ ngay)$', re.I)).last
                    try:
                        await button.wait_for(state='visible', timeout=120000)
                        await button.click(timeout=30000)
                        _update(sid, status='submitted', done=True, url='')
                        record('facebook', 'submitted', video_path=str(video), title=caption,
                               account=data.get('page_id', ''), source='browser')
                    except Exception as exc:
                        _update(sid, status='ready', error=f'Chưa thể tự bấm Đăng: {exc}. Hãy hoàn tất trong trình duyệt.')
                await _wait_for_close(page)
            finally:
                await context.close()
    finally:
        if kind == 'upload':
            shutil.rmtree(session_profile, ignore_errors=True)


async def _wait_for_close(page):
    deadline = time.time() + 1800
    while time.time() < deadline and not page.is_closed():
        await asyncio.sleep(2)


def register(bp):
    @bp.route('/api/facebook_browser/status')
    def status():
        sid = str(request.args.get('session_id') or '')
        if sid:
            with _lock:
                item = _sessions.get(sid)
                return jsonify({'ok': bool(item), **(dict(item) if item else {'error': 'Phiên không tồn tại'})})
        account = str(request.args.get('account_id') or 'default')
        return jsonify({'ok': True, 'connected': (_profile(account) / '.connected').exists()})

    @bp.route('/api/facebook_browser/login', methods=['POST'])
    def login():
        return jsonify({'ok': True, 'session_id': _start('login', request.get_json(silent=True) or {})})

    @bp.route('/api/facebook_browser/upload', methods=['POST'])
    def upload():
        data = request.get_json(silent=True) or {}
        video = Path(str(data.get('video_path') or ''))
        if not video.is_file() or video.suffix.lower() not in {'.mp4', '.mov', '.webm'}:
            return jsonify({'ok': False, 'error': 'File video không hợp lệ'}), 400
        if not str(data.get('page_id') or '').isdigit():
            return jsonify({'ok': False, 'error': 'Chọn Facebook Page hợp lệ'}), 400
        data['video_path'] = str(video.resolve())
        return jsonify({'ok': True, 'session_id': _start('upload', data)})
