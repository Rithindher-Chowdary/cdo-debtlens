/* main.js — Shared client-side utilities */

// ─── Sidebar toggle (mobile) ──────────────────────────────
const hamburger = document.getElementById('hamburger');
const sidebar   = document.getElementById('sidebar');
const main      = document.getElementById('mainContent');

if (hamburger) {
  hamburger.addEventListener('click', () => {
    sidebar.classList.toggle('open');
  });
  // Close on outside click
  document.addEventListener('click', e => {
    if (!sidebar.contains(e.target) && !hamburger.contains(e.target)) {
      sidebar.classList.remove('open');
    }
  });
}

// ─── Sidebar stats ────────────────────────────────────────
async function loadSidebarStats() {
  try {
    const data = await fetch('/api/stats').then(r => r.json());
    const tot  = document.getElementById('statTotal');
    const avg  = document.getElementById('statAvg');
    if (tot) tot.textContent = data.total_assessments ?? '0';
    if (avg) avg.textContent = data.avg_score != null ? parseFloat(data.avg_score).toFixed(0) : '—';
  } catch (e) {}
}
loadSidebarStats();

// ─── Flash auto-dismiss ───────────────────────────────────
document.querySelectorAll('.flash').forEach(el => {
  setTimeout(() => {
    el.style.transition = 'opacity .4s';
    el.style.opacity = '0';
    setTimeout(() => el.remove(), 400);
  }, 4000);
});
