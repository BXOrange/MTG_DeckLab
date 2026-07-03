import { renderDeckImportView } from './deckImportView.js';
import { renderBoardView } from './boardView.js';
import { renderCachedCardsView } from './cachedCardsView.js';

const tabButtons = document.querySelectorAll('.tab-button');
const views = {
  import: document.getElementById('view-import'),
  board: document.getElementById('view-board'),
  cache: document.getElementById('view-cache'),
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

renderDeckImportView(views.import, { onDeckLoaded: () => showTab('board') });
renderBoardView(views.board);
renderCachedCardsView(views.cache);

showTab('import');
