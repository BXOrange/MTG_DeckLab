// First import: pins i18n init order — its module top-level reads the
// language cookie and stamps <html lang> before any view module runs.
import { applyStaticI18n, t } from './i18n.js';
import { renderDeckImportView } from './deckImportView.js';
import { renderImportDeckView } from './importDeckView.js';
import { createGoldfishView } from './goldfishView.js';
import { createSoloView } from './soloView.js';
import { createReplayView } from './replayView.js';
import { createMultiplayerView } from './multiplayerView.js';
import { renderCachedCardsView } from './cachedCardsView.js';
import { renderSavedDecksView } from './savedDecksView.js';
import { renderAnalyzeView } from './analyzeView.js';
import { renderConnectionSettingsView } from './connectionSettingsView.js';
import { renderProfileView } from './profileView.js';
import { renderImplementationStatusView } from './implementationStatusView.js';
import { renderConnectionIndicator } from './connectionStatus.js';
import { initCardHoverDetail } from './cardHoverDetail.js';

applyStaticI18n();
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
  importDeck: document.getElementById('view-import-deck'),
  savedDecks: document.getElementById('view-saved-decks'),
  analyze: document.getElementById('view-analyze'),
  goldfish: document.getElementById('view-goldfish'),
  solo: document.getElementById('view-solo'),
  replay: document.getElementById('view-replay'),
  mpSetup: document.getElementById('view-mp-setup'),
  mpBoard: document.getElementById('view-mp-board'),
  cache: document.getElementById('view-cache'),
  connection: document.getElementById('view-connection'),
  profile: document.getElementById('view-profile'),
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
  // Multiplayer presence: being in one of its tabs is "verfügbar", anywhere
  // else is "online" (see services/lobby.py). Only the multiplayer
  // controller cares, and only once it exists — this runs on the initial
  // showTab() call below too, before it's created.
  if (tabName !== 'mpSetup' && tabName !== 'mpBoard') multiplayerRef?.onHidden();
}

//: Set once the controller below is built; `showTab` runs before that.
let multiplayerRef = null;

tabButtons.forEach((btn) => {
  btn.addEventListener('click', () => {
    if (btn.disabled) return;
    showTab(btn.dataset.tab);
  });
});

navGroups.forEach((group) => {
  const toggle = group.querySelector('.nav-group-toggle');
  toggle.addEventListener('click', () => group.classList.toggle('expanded'));
});

const importView = renderDeckImportView(views.import, { onDeckLoaded: () => showTab('goldfish') });
renderImportDeckView(views.importDeck, {
  onImported: (deck) => {
    importView.loadDeck(deck);
    showTab('import');
  },
});

// The goldfish controller persists across tab switches (its session lives
// inside), so it's created once here rather than per view-shown.
const goldfish = createGoldfishView();
goldfish.mount(views.goldfish);
views.goldfish.addEventListener('view-shown', () => goldfish.onShown());

// "Solo gegen Bots": the Multiplayer rules engine (real turns, priority,
// hidden hands) driven against bots only — no lobby, no socket. Its own
// persistent controller, same lifecycle as the goldfish one.
const solo = createSoloView();
solo.mount(views.solo);
views.solo.addEventListener('view-shown', () => solo.onShown());

// The Replay/Puzzle controller likewise persists across tab switches so an
// in-progress board isn't dropped when navigating away.
const replay = createReplayView();
replay.mount(views.replay);
views.replay.addEventListener('view-shown', () => replay.onShown());
// Multiplayer is one controller behind two tabs: "Setup" (the lobby and
// game configuration) and "Board" (the shared game). The Board tab starts
// disabled — there is nothing to render without a game — and the controller
// enables it via `onBoardAvailable` once this client is at a table. Like the
// goldfish/replay controllers it persists across tab switches, since the
// lobby WebSocket it holds *is* this client's presence.
const mpBoardTab = document.querySelector('.tab-button[data-tab="mpBoard"]');
const multiplayer = createMultiplayerView({
  onBoardAvailable: (available) => {
    mpBoardTab.disabled = !available;
    mpBoardTab.title = available ? '' : t('nav.mpBoardDisabledHint');
    // Don't strand the user on a tab that just went away.
    if (!available && mpBoardTab.classList.contains('active')) showTab('mpSetup');
  },
  onEnterBoard: () => showTab('mpBoard'),
});
multiplayerRef = multiplayer;
multiplayer.mountSetup(views.mpSetup);
multiplayer.mountBoard(views.mpBoard);
views.mpSetup.addEventListener('view-shown', () => multiplayer.onShown('setup'));
views.mpBoard.addEventListener('view-shown', () => multiplayer.onShown('board'));

renderCachedCardsView(views.cache);
const analyzeView = renderAnalyzeView(views.analyze);
views.analyze.addEventListener('view-shown', () => analyzeView.onShown());
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
renderProfileView(views.profile);
renderImplementationStatusView(views.status);

showTab('savedDecks');
