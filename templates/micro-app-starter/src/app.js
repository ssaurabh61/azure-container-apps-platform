document.addEventListener('DOMContentLoaded', () => {
  const userNameEl = document.getElementById('user-name');
  const authBadgeEl = document.getElementById('auth-badge');
  const healthStatusEl = document.getElementById('health-status');
  const recordsListEl = document.getElementById('records-list');
  const recordCountEl = document.getElementById('record-count');
  const recordForm = document.getElementById('record-form');
  const recordTitleInput = document.getElementById('record-title');
  const recordCategoryInput = document.getElementById('record-category');

  // 1. Fetch Identity from EasyAuth headers
  async function loadUser() {
    try {
      const res = await fetch('/api/user');
      if (res.ok) {
        const user = await res.json();
        userNameEl.textContent = user.name || 'Anonymous';
        if (user.authenticated) {
          authBadgeEl.textContent = 'Entra ID SSO';
          authBadgeEl.className = 'badge badge-auth';
        } else {
          authBadgeEl.textContent = 'Local Dev';
          authBadgeEl.className = 'badge badge-platform';
        }
      }
    } catch {
      userNameEl.textContent = 'Local Mode';
    }
  }

  // 2. Health check probe
  async function checkHealth() {
    try {
      const res = await fetch('/healthz');
      if (res.ok) {
        const data = await res.json();
        healthStatusEl.textContent = 'Healthy (200 OK)';
        healthStatusEl.style.color = 'var(--accent-emerald)';
      } else {
        healthStatusEl.textContent = 'Degraded';
        healthStatusEl.style.color = 'var(--accent-amber)';
      }
    } catch {
      healthStatusEl.textContent = 'Unreachable';
      healthStatusEl.style.color = 'var(--accent-rose)';
    }
  }

  // 3. Load Persistent Records
  async function loadRecords() {
    try {
      const res = await fetch('/api/records');
      if (!res.ok) throw new Error('Failed to fetch records');
      const records = await res.json();
      renderRecords(records);
    } catch (err) {
      recordsListEl.innerHTML = `<div class="empty-state">Error loading records: ${err.message}</div>`;
    }
  }

  function renderRecords(records) {
    recordCountEl.textContent = `${records.length} item${records.length === 1 ? '' : 's'}`;
    if (!records.length) {
      recordsListEl.innerHTML = '<div class="empty-state">No records found. Create one above to test SQLite persistence.</div>';
      return;
    }

    recordsListEl.innerHTML = records.map(r => `
      <div class="record-item" data-id="${r.id}">
        <div class="record-main">
          <h4>${escapeHtml(r.title)}</h4>
          <div class="record-meta">
            <span class="badge badge-platform">${escapeHtml(r.category)}</span>
            <span class="record-author">By ${escapeHtml(r.created_by)}</span>
            <span>${new Date(r.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
          </div>
        </div>
        <button class="btn-delete" onclick="deleteRecord(${r.id})" title="Delete record">✕</button>
      </div>
    `).join('');
  }

  // 4. Create Record
  recordForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const title = recordTitleInput.value.trim();
    const category = recordCategoryInput.value;
    if (!title) return;

    try {
      const res = await fetch('/api/records', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, category })
      });
      if (res.ok) {
        recordTitleInput.value = '';
        await loadRecords();
      }
    } catch (err) {
      alert(`Could not save record: ${err.message}`);
    }
  });

  // 5. Delete Record
  window.deleteRecord = async (id) => {
    try {
      const res = await fetch(`/api/records/${id}`, { method: 'DELETE' });
      if (res.ok) {
        await loadRecords();
      }
    } catch (err) {
      alert(`Could not delete record: ${err.message}`);
    }
  };

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  // Initial runs & polling
  loadUser();
  checkHealth();
  loadRecords();
  setInterval(loadRecords, 10000); // Poll every 10s for real-time multi-user updates
});
