"""Patch story.js: remove auto-first-chapter import, load last page instead."""
import re

filepath = r"c:\Users\QUANG HUAN\PycharmProjects\toolvideo\static\js\story.js"

with open(filepath, 'r', encoding='utf-8') as f:
    src = f.read()

OLD = """    try {
      const r = await API.post('/api/story/novel/chapters', { url: novel.url, page: 1 }, { silent: true });
      if (!r.ok) throw new Error(r.error || 'Tải chi tiết thất bại');
      
      if (desc) desc.textContent = r.description || '(Không có mô tả)';
      _totalChaptersPages = parseInt(r.total_pages, 10) || 1;
      _selectedNovelPage = 1;
      _chaptersCache[1] = r.chapters;

      // Populate legacy select
      if (select) {
        select.replaceChildren();
        r.chapters.forEach(c => {
          select.appendChild(_el('option', { value: c.url }, c.title));
        });
      }

      if (meta) meta.textContent = `(Trang 1/${_totalChaptersPages} - ${r.chapters.length} ch.)`;

      // Render grid and pagination
      _renderChaptersGrid(1);
      _renderChaptersPagination();

      // Automatically select and load the first chapter on page 1
      if (r.chapters && r.chapters.length > 0) {
        _loadChapterByUrl(r.chapters[0].url, r.chapters[0].title);
      }
    } catch (e) {
      _toast(String(e.message || e), 'error');
      if (desc) desc.textContent = 'Lỗi tải chi tiết: ' + (e.message || e);
    }"""

NEW = """    try {
      // Bước 1: Tải trang 1 để lấy metadata (mô tả, tổng số trang)
      const r = await API.post('/api/story/novel/chapters', { url: novel.url, page: 1 }, { silent: true });
      if (!r.ok) throw new Error(r.error || 'Tải chi tiết thất bại');

      if (desc) desc.textContent = r.description || '(Không có mô tả)';
      _totalChaptersPages = parseInt(r.total_pages, 10) || 1;
      _chaptersCache[1] = r.chapters;

      // Bước 2: Tải trang cuối để hiển thị chương mới nhất
      const lastPage = _totalChaptersPages;
      if (lastPage > 1) {
        if (meta) meta.textContent = `Đang tải trang cuối (${lastPage})...`;
        try {
          const rLast = await API.post('/api/story/novel/chapters', { url: novel.url, page: lastPage }, { silent: true });
          if (rLast.ok && rLast.chapters && rLast.chapters.length > 0) {
            _chaptersCache[lastPage] = rLast.chapters;
            _selectedNovelPage = lastPage;
            if (select) {
              select.replaceChildren();
              rLast.chapters.forEach(c => {
                select.appendChild(_el('option', { value: c.url }, c.title));
              });
            }
            if (meta) meta.textContent = `(Trang ${lastPage}/${lastPage} - ${rLast.chapters.length} ch. mới nhất)`;
            _renderChaptersGrid(lastPage);
            _renderChaptersPagination();
            return; // Không auto-import chương nào
          }
        } catch (_lastErr) { /* fallback trang 1 */ }
      }

      // Fallback: 1 trang duy nhất
      _selectedNovelPage = 1;
      if (select) {
        select.replaceChildren();
        r.chapters.forEach(c => {
          select.appendChild(_el('option', { value: c.url }, c.title));
        });
      }
      if (meta) meta.textContent = `(Trang 1/${_totalChaptersPages} - ${r.chapters.length} ch.)`;
      _renderChaptersGrid(1);
      _renderChaptersPagination();
      // Không auto-import chương nào
    } catch (e) {
      _toast(String(e.message || e), 'error');
      if (desc) desc.textContent = 'Lỗi tải chi tiết: ' + (e.message || e);
    }"""

# Normalize line endings for matching
src_normalized = src.replace('\r\n', '\n').replace('\r', '\n')
old_normalized = OLD.replace('\r\n', '\n').replace('\r', '\n')

if old_normalized in src_normalized:
    patched = src_normalized.replace(old_normalized, NEW, 1)
    # Write back with original line endings (CRLF for Windows)
    with open(filepath, 'w', encoding='utf-8', newline='\r\n') as f:
        f.write(patched)
    print("SUCCESS: Patched selectNovel - removed auto-import, added last-page load")
else:
    print("ERROR: Old code block not found. Searching for partial match...")
    # Try to find the key line
    lines = src_normalized.split('\n')
    for i, line in enumerate(lines):
        if 'Automatically select and load the first chapter' in line:
            print(f"  Found target at line {i+1}: {line!r}")
    print(f"  Total file chars: {len(src_normalized)}")
