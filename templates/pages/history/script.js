/* ── History page ────────────────────────────────────────────────────────── */
async function loadHistory() {
  const rows = await API.get('/api/history');
  const tbody = document.getElementById('history-body');
  if (!tbody) return;
  if (!rows || !rows.length) {
    tbody.innerHTML = '<tr><td colspan="5">' + t('lbl_no_history') + '</td></tr>';
    return;
  }
  tbody.innerHTML = rows.map(r =>
    '<tr><td>' + r.time + '</td><td>' + escHtml(r.url) + '</td><td>' + r.type + '</td><td>' + r.total + '</td><td>' + r.success + '</td></tr>'
  ).join('');
}

async function clearHistory() {
  if (!confirm(t('confirm_clear_history'))) return;
  await API.post('/api/history/clear', {});
  loadHistory();
  toast(t('toast_history_cleared'), 'success');
}
