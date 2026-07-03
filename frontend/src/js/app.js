import { renderDeckImportView } from './deckImportView.js';
import { renderBoardView } from './boardView.js';

const tabButtons = document.querySelectorAll('.tab-button');
const views = {
  import: document.getElementById('view-import'),
  board: document.getElementById('view-board'),
};

function showTab(tabName) {
  for (const [name, el] of Object.entries(views)) {
    el.classList.toggle('active', name === tabName);
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

showTab('import');
