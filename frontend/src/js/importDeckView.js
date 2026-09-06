import { importArchidektDeck } from './api.js';
import { t } from './i18n.js';

/**
 * "Import Deck" tab: pull a public decklist from an external deck builder
 * (currently Archidekt only — Moxfield was tried client- and server-side
 * and reverted both times, genuinely Cloudflare-blocked; see
 * docs/implementation-state/Done_Backend.md "Import — follow-up from the frontend"). On a
 * successful import, hands the decklist text sections to `onImported`
 * (app.js loads them into the "Deck editieren" tab and switches to it);
 * on failure, the error stays on this page instead.
 * @param {{onImported?: (deck: {name: string, commanderText: string, mainboardText: string, sideboardText: string}) => void}} [options]
 */
export function renderImportDeckView(container, { onImported } = {}) {
  container.innerHTML = `
    <div class="import-panel">
      <div class="import-input">
        <h2>${t('import.title')}</h2>
        <p class="hint">${t('import.hint')}</p>

        <div class="deck-section">
          <label for="archidekt-input">${t('import.archidektLabel')}</label>
          <div class="save-deck-controls">
            <input id="archidekt-input" type="text" placeholder="https://archidekt.com/decks/…" />
            <button id="archidekt-import-btn" type="button" class="primary">${t('import.button')}</button>
          </div>
          <p class="server-status" id="archidekt-status"></p>
        </div>
      </div>
    </div>
  `;

  const input = container.querySelector('#archidekt-input');
  const btn = container.querySelector('#archidekt-import-btn');
  const statusEl = container.querySelector('#archidekt-status');

  async function importDeck() {
    const deckIdOrUrl = input.value.trim();
    if (!deckIdOrUrl) return;

    btn.disabled = true;
    statusEl.textContent = t('import.importing');
    statusEl.className = 'server-status pending';

    const result = await importArchidektDeck(deckIdOrUrl);
    btn.disabled = false;

    if (!result.ok) {
      statusEl.textContent = result.error;
      statusEl.className = 'server-status warning';
      return;
    }

    input.value = '';
    statusEl.textContent = '';
    statusEl.className = 'server-status';
    onImported?.(result);
  }

  btn.addEventListener('click', importDeck);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') importDeck();
  });
}
