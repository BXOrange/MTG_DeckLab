import { getDeckPrintingOptions } from './api.js';
import { escapeHtml } from './cardTile.js';
import { t } from './i18n.js';

export function openDeckPrintingDialog(name, currentId, onSelect) {
  const dialog = document.createElement('dialog');
  dialog.className = 'deck-printing-dialog';
  dialog.setAttribute('aria-labelledby', 'deck-printing-title');
  dialog.innerHTML = `
    <h2 id="deck-printing-title">${escapeHtml(t('deckImport.artworkForCard', { name }))}</h2>
    <p role="status">${t('deckImport.artworkLoading')}</p>
    <div class="deck-printing-options"></div>
    <form method="dialog" class="deck-printing-actions">
      ${currentId ? `<button type="button" class="default-printing">${t('deckImport.artworkDefault')}</button>` : ''}
      <button>${t('common.close')}</button>
    </form>`;

  function select(id) {
    dialog.close();
    onSelect(id);
  }

  dialog.querySelector('.default-printing')?.addEventListener('click', () => select(null));
  dialog.addEventListener('close', () => dialog.remove(), { once: true });
  document.body.append(dialog);
  dialog.showModal();

  getDeckPrintingOptions(name).then((result) => {
    if (!dialog.open) return;
    const options = result?.printings || [];
    dialog.querySelector('[role="status"]').textContent = !result ? t('deckImport.artworkFailed')
      : options.length ? '' : t('deckImport.artworkEmpty');
    const grid = dialog.querySelector('.deck-printing-options');
    for (const printing of options) {
      const button = document.createElement('button');
      button.type = 'button';
      button.setAttribute('aria-pressed', String(printing.id === currentId));
      const image = document.createElement('img');
      image.src = printing.preview;
      image.alt = '';
      image.loading = 'lazy';
      const label = document.createElement('span');
      label.textContent = `${printing.edition} · #${printing.collectorNumber}`;
      button.append(image, label);
      button.addEventListener('click', () => select(printing.id));
      grid.append(button);
    }
  });
}
