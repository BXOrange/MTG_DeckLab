import { renderDeckImportView } from './deckImportView.js';
import { renderBoardView } from './boardView.js';
import { renderCachedCardsView } from './cachedCardsView.js';
import { renderSavedDecksView } from './savedDecksView.js';
import { renderAnalyzeView } from './analyzeView.js';
import { renderConnectionSettingsView } from './connectionSettingsView.js';
import { renderConnectionIndicator } from './connectionStatus.js';
import { initCardHoverDetail } from './cardHoverDetail.js';

initCardHoverDetail();
renderConnectionIndicator(document.getElementById('header-connection-status'));

const sidebar = document.getElementById('sidebar');
const sidebarToggle = document.getElementById('sidebar-toggle');
sidebarToggle.addEventListener('click', () => {
  const collapsed = sidebar.classList.toggle('collapsed');
  sidebarToggle.setAttribute('aria-expanded', String(!collapsed));
});

const tabButtons = document.querySelectorAll('.tab-button');
const views = {
  import: document.getElementById('view-import'),
  savedDecks: document.getElementById('view-saved-decks'),
  analyze: document.getElementById('view-analyze'),
  board: document.getElementById('view-board'),
  cache: document.getElementById('view-cache'),
  connection: document.getElementById('view-connection'),
};

function showTab(tabName) {
  for (const [name, el] of Object.entries(views)) {
    const isActive = name === tabName;
    el.classList.toggle('active', isActive);
    // Lets a view lazy-load its data only once it's actually visible
    // (see cachedCardsView.js), rather than fetching at page startup.
    if (isActive) el.dispatchEvent(new CustomEvent('view-shown'));
  }
  for (const btn of tabButtons) {
    btn.classList.toggle('active', btn.dataset.tab === tabName);
  }
}

tabButtons.forEach((btn) => {
  btn.addEventListener('click', () => showTab(btn.dataset.tab));
});

const importView = renderDeckImportView(views.import, { onDeckLoaded: () => showTab('board') });
renderBoardView(views.board);
renderCachedCardsView(views.cache);
renderAnalyzeView(views.analyze);
renderSavedDecksView(views.savedDecks, {
  onLoadDeck: (deck) => {
    importView.loadDeck(deck);
    showTab('import');
  },
});
renderConnectionSettingsView(views.connection);

showTab('import');
