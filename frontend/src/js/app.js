import { renderDeckImportView } from './deckImportView.js';
import { createGoldfishView } from './goldfishView.js';
import { createReplayView } from './replayView.js';
import { renderMultiplayerView } from './multiplayerView.js';
import { renderCachedCardsView } from './cachedCardsView.js';
import { renderSavedDecksView } from './savedDecksView.js';
import { renderAnalyzeView } from './analyzeView.js';
import { renderConnectionSettingsView } from './connectionSettingsView.js';
import { renderImplementationStatusView } from './implementationStatusView.js';
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
const navGroups = document.querySelectorAll('.nav-group');
const views = {
  import: document.getElementById('view-import'),
  savedDecks: document.getElementById('view-saved-decks'),
  analyze: document.getElementById('view-analyze'),
  goldfish: document.getElementById('view-goldfish'),
  replay: document.getElementById('view-replay'),
  multiplayer: document.getElementById('view-multiplayer'),
  cache: document.getElementById('view-cache'),
  connection: document.getElementById('view-connection'),
  status: document.getElementById('view-status'),
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
  for (const group of navGroups) {
    const hasActive = group.querySelector('.tab-button.active') !== null;
    if (hasActive) group.classList.add('expanded');
    group.querySelector('.nav-group-toggle').classList.toggle('has-active', hasActive);
  }
}

tabButtons.forEach((btn) => {
  btn.addEventListener('click', () => showTab(btn.dataset.tab));
});

navGroups.forEach((group) => {
  const toggle = group.querySelector('.nav-group-toggle');
  toggle.addEventListener('click', () => group.classList.toggle('expanded'));
});

const importView = renderDeckImportView(views.import, { onDeckLoaded: () => showTab('goldfish') });

// The goldfish controller persists across tab switches (its session lives
// inside), so it's created once here rather than per view-shown.
const goldfish = createGoldfishView();
goldfish.mount(views.goldfish);
views.goldfish.addEventListener('view-shown', () => goldfish.onShown());

// The Replay/Puzzle controller likewise persists across tab switches so an
// in-progress board isn't dropped when navigating away.
const replay = createReplayView();
replay.mount(views.replay);
views.replay.addEventListener('view-shown', () => replay.onShown());
renderMultiplayerView(views.multiplayer);

renderCachedCardsView(views.cache);
const analyzeView = renderAnalyzeView(views.analyze);
renderSavedDecksView(views.savedDecks, {
  onLoadDeck: (deck) => {
    importView.loadDeck(deck);
    showTab('import');
  },
  onAnalyzeDeck: (deck) => {
    analyzeView.loadDeck(deck);
    showTab('analyze');
  },
});
renderConnectionSettingsView(views.connection);
renderImplementationStatusView(views.status);

showTab('import');
