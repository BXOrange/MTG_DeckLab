import { parseDeckSections, SAMPLE_COMMANDER, SAMPLE_MAINBOARD, SAMPLE_SIDEBOARD } from './parser.js';
import { setState } from './state.js';
import { newBoardFromDeck } from './boardEngine.js';
import { resolveCardImages } from './cardImages.js';
import { submitDeck } from './api.js';

export function renderDeckImportView(container, { onDeckLoaded } = {}) {
  container.innerHTML = `
    <div class="import-panel">
      <div class="import-input">
        <h2>Deckliste einlesen</h2>
        <p class="hint">
          Jede Karte als eigene Zeile, z.B. "1 Sol Ring" oder "4x Mountain".
          Die Zuordnung ergibt sich aus dem Abschnitt, in den du einträgst.
        </p>

        <div class="deck-section">
          <label for="commander-textarea">Commander</label>
          <textarea id="commander-textarea" rows="2"
            placeholder="1 Krenko, Mob Boss"></textarea>
        </div>

        <div class="deck-section">
          <label for="mainboard-textarea">Mainboard</label>
          <textarea id="mainboard-textarea" rows="12"
            placeholder="1 Sol Ring&#10;62 Mountain"></textarea>
        </div>

        <div class="deck-section">
          <label for="sideboard-textarea">Sideboard</label>
          <textarea id="sideboard-textarea" rows="3"
            placeholder="1 Negate"></textarea>
        </div>

        <div class="import-actions">
          <button id="parse-btn" type="button" class="primary">Deckliste parsen</button>
          <button id="sample-btn" type="button">Beispieldeck laden</button>
        </div>
      </div>
      <div class="import-result" id="import-result">
        <p class="empty-state">Noch keine Deckliste eingelesen.</p>
      </div>
    </div>
  `;

  const commanderTextarea = container.querySelector('#commander-textarea');
  const mainboardTextarea = container.querySelector('#mainboard-textarea');
  const sideboardTextarea = container.querySelector('#sideboard-textarea');
  const resultEl = container.querySelector('#import-result');

  container.querySelector('#sample-btn').addEventListener('click', () => {
    commanderTextarea.value = SAMPLE_COMMANDER;
    mainboardTextarea.value = SAMPLE_MAINBOARD;
    sideboardTextarea.value = SAMPLE_SIDEBOARD;
  });

  let latestRequestId = 0;

  container.querySelector('#parse-btn').addEventListener('click', () => {
    const requestId = ++latestRequestId;
    const sections = {
      commanderText: commanderTextarea.value,
      mainboardText: mainboardTextarea.value,
      sideboardText: sideboardTextarea.value,
    };

    // Optimistic local parse: instant feedback while the authoritative
    // server response (below) is in flight. Same shape either way, so
    // the board/state code doesn't care which one it's looking at.
    const localDeck = parseDeckSections(sections);
    setState({ deck: localDeck, board: newBoardFromDeck(localDeck) });
    renderResult(resultEl, localDeck, onDeckLoaded, { pending: true });

    // Fire and forget: images arrive later and re-render the board via
    // the shared state subscription (see boardView.js).
    const cardNames = [...localDeck.commanders, ...localDeck.mainDeck].map((c) => c.name);
    resolveCardImages(cardNames).then((imageCache) => setState({ imageCache }));

    submitDeck(sections).then((result) => {
      if (requestId !== latestRequestId) return; // superseded by a later parse click

      if (!result.ok) {
        renderResult(resultEl, localDeck, onDeckLoaded, { warning: result.error });
        return;
      }
      setState({ deck: result.deck, board: newBoardFromDeck(result.deck) });
      renderResult(resultEl, result.deck, onDeckLoaded, { serverConfirmed: true });
    });
  });
}

function renderResult(resultEl, deck, onDeckLoaded, meta = {}) {
  const { commanders, mainDeck, sideboard, totalCount, parseErrors, validation } = deck;

  const statusClass = validation.isLegal ? 'status-ok' : 'status-error';
  const statusText = validation.isLegal ? 'Legal (strukturell)' : 'Nicht legal';

  const serverStatusHtml = meta.pending
    ? '<p class="server-status pending">Wird serverseitig geprüft …</p>'
    : meta.warning
      ? `<p class="server-status warning">${escapeHtml(meta.warning)}</p>`
      : meta.serverConfirmed
        ? '<p class="server-status ok">Serverseitig geprüft.</p>'
        : '';

  const listItems = (cards) =>
    cards
      .slice()
      .sort((a, b) => a.name.localeCompare(b.name))
      .map((c) => `<li><span class="qty">${c.qty}x</span> ${escapeHtml(c.name)}</li>`)
      .join('');

  const issueList = (items, className) =>
    items.length
      ? `<ul class="${className}">${items.map((e) => `<li>${escapeHtml(e)}</li>`).join('')}</ul>`
      : '';

  resultEl.innerHTML = `
    <div class="deck-summary">
      <h2>Deck-Übersicht</h2>
      ${serverStatusHtml}
      <p><strong>${totalCount}</strong> Karten gesamt · Status:
        <span class="${statusClass}">${statusText}</span>
      </p>

      ${issueList(parseErrors, 'issue-list parse-errors')}
      ${issueList(validation.errors, 'issue-list validation-errors')}
      ${issueList(validation.warnings, 'issue-list validation-warnings')}

      <h3>Commander (${commanders.reduce((s, c) => s + c.qty, 0)})</h3>
      <ul class="card-list">${listItems(commanders) || '<li class="empty-state">–</li>'}</ul>

      <h3>Hauptdeck (${mainDeck.reduce((s, c) => s + c.qty, 0)})</h3>
      <ul class="card-list scrollable">${listItems(mainDeck) || '<li class="empty-state">–</li>'}</ul>

      ${sideboard.length ? `
        <h3>Sideboard (${sideboard.reduce((s, c) => s + c.qty, 0)})</h3>
        <ul class="card-list">${listItems(sideboard)}</ul>
      ` : ''}

      <button id="goto-board-btn" type="button" class="primary"
        ${meta.serverConfirmed ? '' : 'disabled'}
        title="${meta.serverConfirmed ? '' : 'Erst verfügbar, sobald das Deck serverseitig geprüft wurde.'}"
      >Zur Spielfläche →</button>
    </div>
  `;

  resultEl.querySelector('#goto-board-btn').addEventListener('click', () => {
    onDeckLoaded?.();
  });
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}
