"""Facebook Page video upload using server-requested byte ranges."""


def upload_video_chunks(client, url, path, metadata):
    size = path.stat().st_size
    if size <= 0:
        raise RuntimeError("File video rỗng.")
    token = metadata['access_token']

    def post(data, files=None):
        response = client.post(url, data=dict(data, access_token=token), files=files, timeout=600)
        if response.status_code == 413:
            raise RuntimeError("HTTP 413: phía nhận từ chối kích thước gói upload; chưa xác định giới hạn video.")
        try:
            body = response.json()
        except ValueError:
            raise RuntimeError(f"Facebook trả về HTTP {response.status_code}, không có phản hồi JSON hợp lệ.") from None
        if not isinstance(body, dict):
            raise RuntimeError("Phản hồi upload Facebook không hợp lệ.")
        if body.get('error'):
            error = body['error']
            raise RuntimeError(f"Facebook: {error.get('message', 'Upload thất bại')} (code={error.get('code', '')})")
        if not 200 <= response.status_code < 300:
            raise RuntimeError(f"Upload Facebook thất bại: HTTP {response.status_code}.")
        return body

    state = post({'upload_phase': 'start', 'file_size': size})
    session = state.get('upload_session_id')
    video = state.get('video_id')
    if not session or not video:
        raise RuntimeError("Facebook không trả về phiên upload/video ID.")
    sent = 0
    with path.open('rb') as source:
        while True:
            start, end = int(state['start_offset']), int(state['end_offset'])
            if start != sent or not 0 <= start <= end <= size:
                raise RuntimeError("Mốc dữ liệu upload không khớp; dừng để tránh thiếu nội dung.")
            if start == end:
                if sent != size:
                    raise RuntimeError("Facebook kết thúc phiên khi chưa nhận đủ video.")
                break
            source.seek(start)
            chunk = source.read(end - start)
            if len(chunk) != end - start:
                raise RuntimeError("File video thay đổi hoặc không đọc đủ dữ liệu.")
            state = post({'upload_phase': 'transfer', 'upload_session_id': session,
                          'start_offset': start},
                         {'video_file_chunk': ('chunk.mp4', chunk, 'video/mp4')})
            if int(state['start_offset']) != end:
                raise RuntimeError("Facebook chưa xác nhận đủ phần dữ liệu vừa gửi.")
            sent = end
            yield {'sent': sent, 'total': size}
    result = post(dict(metadata, upload_phase='finish', upload_session_id=session))
    if result.get('success') is not True:
        raise RuntimeError("Đã gửi dữ liệu nhưng Facebook chưa xác nhận hoàn tất; kiểm tra Page trước khi thử lại.")
    yield {'video_id': str(video)}
