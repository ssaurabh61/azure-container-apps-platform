document.addEventListener('DOMContentLoaded', () => {
  const catalogGrid = document.getElementById('catalog-grid');
  const searchInput = document.getElementById('search-input');
  const categoryTabs = document.getElementById('category-tabs');
  const totalAppsEl = document.getElementById('total-apps');

  let allApps = [];
  let currentCategory = 'all';
  let searchQuery = '';

  async function fetchApps() {
    try {
      const res = await fetch('data/apps.json');
      if (!res.ok) throw new Error('Failed to load apps directory');
      allApps = await res.json();
      render();
    } catch (err) {
      catalogGrid.innerHTML = `
        <div style="grid-column: 1/-1; text-align: center; padding: 3rem; color: var(--text-dim);">
          Unable to load applications catalog: ${err.message}
        </div>
      `;
    }
  }

  function render() {
    const filtered = allApps.filter(app => {
      const matchesCategory = (currentCategory === 'all' || app.category.toLowerCase() === currentCategory.toLowerCase());
      const query = searchQuery.toLowerCase();
      const matchesSearch = !query || 
        app.name.toLowerCase().includes(query) ||
        app.description.toLowerCase().includes(query) ||
        (app.tags && app.tags.some(t => t.toLowerCase().includes(query)));
      return matchesCategory && matchesSearch;
    });

    totalAppsEl.textContent = allApps.length;

    if (!filtered.length) {
      catalogGrid.innerHTML = `
        <div style="grid-column: 1/-1; text-align: center; padding: 4rem; color: var(--text-dim);">
          No applications found matching your criteria.
        </div>
      `;
      return;
    }

    catalogGrid.innerHTML = filtered.map(app => `
      <a href="${escapeHtml(app.url)}" class="app-card" target="_blank" rel="noopener noreferrer">
        <div>
          <div class="app-header">
            <div class="app-icon">${app.icon || '⚡'}</div>
            <span class="app-badge">${escapeHtml(app.badge || 'Active')}</span>
          </div>
          <h3 class="app-title">${escapeHtml(app.name)}</h3>
          <p class="app-desc">${escapeHtml(app.description)}</p>
        </div>
        <div class="app-footer">
          <span class="app-category">${escapeHtml(app.category)}</span>
          <span class="app-link-arrow">→</span>
        </div>
      </a>
    `).join('');
  }

  // Category Filtering
  categoryTabs.addEventListener('click', (e) => {
    if (e.target.classList.contains('tab-btn')) {
      document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
      e.target.classList.add('active');
      currentCategory = e.target.getAttribute('data-category');
      render();
    }
  });

  // Search Input
  searchInput.addEventListener('input', (e) => {
    searchQuery = e.target.value.trim();
    render();
  });

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  fetchApps();
});
