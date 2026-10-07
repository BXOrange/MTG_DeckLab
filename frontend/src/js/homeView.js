import { fetchOverviewStats } from './api.js';
import { fmtNumber, t } from './i18n.js';

export function renderHomeView(container) {
  container.innerHTML = `
    <section class="home-page" aria-labelledby="home-title">
      <header class="home-intro">
        <p class="home-eyebrow">${t('home.eyebrow')}</p>
        <h2 id="home-title">${t('home.title')}</h2>
        <p class="home-description">${t('home.description')}</p>
      </header>
      <section class="home-overview" aria-labelledby="home-overview-title">
        <div class="home-overview-heading">
          <h3 id="home-overview-title">${t('home.overviewTitle')}</h3>
          <button id="home-refresh" type="button">${t('home.refresh')}</button>
        </div>
        <p id="home-stats-error" class="home-stats-error" role="status" hidden></p>
        <div class="home-stat-grid" aria-live="polite">
          <article class="home-stat">
            <span class="home-stat-icon" aria-hidden="true">🃏</span>
            <strong data-home-stat="cards">—</strong>
            <span>${t('home.cards')}</span>
          </article>
          <article class="home-stat">
            <span class="home-stat-icon" aria-hidden="true">📚</span>
            <strong data-home-stat="decks">—</strong>
            <span>${t('home.decks')}</span>
          </article>
          <article class="home-stat">
            <span class="home-stat-icon" aria-hidden="true">👥</span>
            <strong data-home-stat="players">—</strong>
            <span>${t('home.players')}</span>
          </article>
        </div>
      </section>
    </section>
  `;

  const refreshButton = container.querySelector('#home-refresh');
  const errorMessage = container.querySelector('#home-stats-error');
  const countElements = Object.fromEntries(
    Array.from(container.querySelectorAll('[data-home-stat]')).map((element) => [element.dataset.homeStat, element]),
  );
  let requestId = 0;

  async function refresh() {
    const currentRequest = ++requestId;
    refreshButton.disabled = true;
    errorMessage.hidden = true;
    for (const element of Object.values(countElements)) element.textContent = '…';

    const result = await fetchOverviewStats();
    if (currentRequest !== requestId) return;
    refreshButton.disabled = false;

    if (!result.ok || !result.data) {
      for (const element of Object.values(countElements)) element.textContent = '—';
      errorMessage.textContent = t('home.statsError');
      errorMessage.hidden = false;
      return;
    }

    for (const [key, element] of Object.entries(countElements)) {
      element.textContent = fmtNumber(result.data[key]);
    }
  }

  refreshButton.addEventListener('click', refresh);
  container.addEventListener('view-shown', refresh);
}
