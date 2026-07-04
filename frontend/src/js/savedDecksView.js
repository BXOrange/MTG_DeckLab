// "Gespeicherte Decks" tab: browse, load, and delete decks saved via
// POST /api/decks/save (mtg_analyzer DeckDatabase). Lazy by design, same
// as cachedCardsView.js: nothing is fetched until the tab is opened.

import { listSavedDecks, getSavedDeck, deleteSavedDeck, getDeckValidation } from './api.js';
import { escapeHtml } from './cardTile.js';

/**
 * @param {{onLoadDeck?: (deck: object) => void}} [options] Called with
 *   the full saved deck (including decklist text) when "Laden" is clicked.
 */
export function renderSavedDecksView(container, { onLoadDeck } = {}) {
  container.innerHTML = `
    <div class="saved-decks-panel">
      <div class="cache-toolbar">
        <h2>Gespeicherte Decks</h2>
        <button id="refresh-saved-decks-btn" type="button">Aktualisieren</button>
        <span class="cache-count"></span>
      </div>
      <div id="saved-decks-result"><p class="empty-state">Lade gespeicherte Decks …</p></div>
    </div>
  `;

  const resultEl = container.querySelector('#saved-decks-result');
  const countEl = container.querySelector('.cache-count');
  const refreshBtn = container.querySelector('#refresh-saved-decks-btn');

  let latestRequestId = 0;

  async function load() {
    const requestId = ++latestRequestId;
    resultEl.innerHTML = '<p class="empty-state">Lade gespeicherte Decks …</p>';
    countEl.textContent = '';

    const decks = await listSavedDecks();
    if (requestId !== latestRequestId) return; // superseded by a later refresh click

    if (decks === null) {
      resultEl.innerHTML = '<p class="server-status warning">Server nicht erreichbar.</p>';
      return;
    }

    countEl.textContent = `${decks.length} gespeichertes Deck(s)`;

    if (!decks.length) {
      resultEl.innerHTML =
        '<p class="empty-state">Noch keine Decks gespeichert – im Tab "Deck importieren" einen Namen vergeben und speichern.</p>';
      return;
    }

    resultEl.innerHTML = decks.map(renderDeckRow).join('');

    // Legality is computed server-side (resolves cards), so fetch it per
    // deck and fill each row's badge as answers arrive. Illegal decks get
    // a 🛑 + the reasons; legal ones a subtle ✅.
    for (const deck of decks) {
      getDeckValidation(deck.id).then((validation) => {
        if (requestId !== latestRequestId) return; // list refreshed meanwhile
        updateLegalityBadge(deck.id, validation);
      });
    }

    resultEl.querySelectorAll('.load-deck-btn').forEach((btn) => {
      btn.addEventListener('click', async () => {
        btn.disabled = true;
        const deck = await getSavedDeck(btn.dataset.deckId);
        btn.disabled = false;
        if (!deck) {
          window.alert('Deck konnte nicht geladen werden – Server nicht erreichbar oder Deck wurde gelöscht.');
          return;
        }
        onLoadDeck?.(deck);
      });
    });

    resultEl.querySelectorAll('.delete-deck-btn').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const name = btn.dataset.deckName || 'dieses Deck';
        if (!window.confirm(`"${name}" wirklich löschen?`)) return;
        btn.disabled = true;
        const deleted = await deleteSavedDeck(btn.dataset.deckId);
        if (!deleted) {
          btn.disabled = false;
          window.alert('Löschen fehlgeschlagen – Server nicht erreichbar.');
          return;
        }
        load();
      });
    });
  }

  function updateLegalityBadge(deckId, validation) {
    const el = resultEl.querySelector(`.saved-deck-legality[data-deck-id="${cssEscape(deckId)}"]`);
    if (!el) return;
    if (validation === null) {
      el.className = 'saved-deck-legality unknown';
      el.textContent = 'Legalität nicht prüfbar';
      el.removeAttribute('title');
      return;
    }
    if (validation.isLegal) {
      el.className = 'saved-deck-legality legal';
      el.textContent = '✅ legal';
      el.removeAttribute('title');
      return;
    }
    const reasons = (validation.errors || []).join('\n') || 'Deck ist nicht legal.';
    el.className = 'saved-deck-legality illegal';
    el.textContent = '🛑 nicht legal';
    el.title = reasons;
  }

  refreshBtn.addEventListener('click', load);

  // Only load the first time this view is shown, not eagerly at startup.
  let loaded = false;
  container.addEventListener('view-shown', () => {
    if (loaded) return;
    loaded = true;
    load();
  });
}

function renderDeckRow(deck) {
  const created = formatTimestamp(deck.createdAt);
  const name = deck.name?.trim() || 'Unbenanntes Deck';

  return `
    <div class="saved-deck-row">
      <div class="saved-deck-info">
        <strong>${escapeHtml(name)}</strong>
        <span class="saved-deck-meta">Gespeichert: ${escapeHtml(created)}</span>
        <span class="saved-deck-legality checking" data-deck-id="${escapeHtml(deck.id)}">Prüfe Legalität …</span>
      </div>
      <div class="saved-deck-actions">
        <button type="button" class="load-deck-btn" data-deck-id="${deck.id}">Laden</button>
        <button type="button" class="delete-deck-btn" data-deck-id="${deck.id}" data-deck-name="${escapeHtml(name)}">Löschen</button>
      </div>
    </div>
  `;
}

// Deck ids are server-generated UUIDs (no quotes/backslashes), so a
// minimal escape is enough for the attribute selector above.
function cssEscape(value) {
  return String(value).replace(/["\\]/g, '\\$&');
}

function formatTimestamp(isoString) {
  const date = new Date(isoString);
  return Number.isNaN(date.getTime()) ? isoString : date.toLocaleString('de-DE');
}
