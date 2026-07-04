import { parseDeckSections, SAMPLE_COMMANDER, SAMPLE_MAINBOARD, SAMPLE_SIDEBOARD } from './parser.js';
import { setState } from './state.js';
import { newBoardFromDeck } from './boardEngine.js';
import { resolveCardImages, getResolvedCard, isConfirmedNotFound } from './cardImages.js';
import { submitDeck, saveDeck } from './api.js';
import { renderCardTile, renderCardTilePlaceholder, renderCardTileNotFound, escapeHtml } from './cardTile.js';

/**
 * @param {{onDeckLoaded?: () => void}} [options]
 * @returns {{loadDeck: (savedDeck: object) => void}} lets other views
 *   (savedDecksView.js) load a saved deck into this one's textareas.
 */
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

        <div class="deck-section save-deck-row">
          <label for="deck-name-input">Deckname (zum Speichern)</label>
          <div class="save-deck-controls">
            <input id="deck-name-input" type="text" placeholder="z.B. Krenko Goblins" />
            <button id="save-deck-btn" type="button">Speichern</button>
          </div>
          <p class="server-status" id="save-status"></p>
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
  const nameInput = container.querySelector('#deck-name-input');
  const saveStatusEl = container.querySelector('#save-status');
  const resultEl = container.querySelector('#import-result');

  // Set once a deck has been saved/loaded, so a later "Speichern" click
  // updates that same saved deck instead of creating a duplicate. Reset
  // by loading the sample deck or a *different* saved deck.
  let savedDeckId = null;
  // The last rendered deck + render metadata, kept so the "Detailansicht"
  // toggle and late-arriving card data can re-render without re-parsing.
  let lastDeck = null;
  let lastMeta = {};
  let detailMode = false;

  function currentSections() {
    return {
      commanderText: commanderTextarea.value,
      mainboardText: mainboardTextarea.value,
      sideboardText: sideboardTextarea.value,
    };
  }

  function showResult(deck, meta) {
    lastDeck = deck;
    lastMeta = meta;
    renderResult(resultEl, deck, {
      onDeckLoaded,
      meta,
      detailMode,
      onToggleDetailMode: (checked) => {
        detailMode = checked;
        // Re-render via showResult (not a direct renderResult call) so
        // this new render's checkbox also gets a working
        // onToggleDetailMode closure — a direct renderResult call here
        // previously omitted it, so only the *first* toggle ever did
        // anything: every render after that had a checkbox wired to
        // nothing, since its "change" handler's onToggleDetailMode was
        // undefined.
        if (lastDeck) showResult(lastDeck, lastMeta);
        // Switching modes changes the result panel's height a lot
        // (tiles vs. plain rows) — without this, the page can be left
        // scrolled past the now-shorter/taller content, looking like
        // the toggle "didn't do anything" even though it re-rendered.
        resultEl.scrollIntoView({ block: 'start', behavior: 'smooth' });
      },
    });
  }

  function refreshResult() {
    if (lastDeck) showResult(lastDeck, lastMeta);
  }

  container.querySelector('#sample-btn').addEventListener('click', () => {
    commanderTextarea.value = SAMPLE_COMMANDER;
    mainboardTextarea.value = SAMPLE_MAINBOARD;
    sideboardTextarea.value = SAMPLE_SIDEBOARD;
    savedDeckId = null;
    nameInput.value = '';
    saveStatusEl.textContent = '';
    saveStatusEl.className = 'server-status';
  });

  let latestRequestId = 0;

  function parseCurrentSections() {
    const requestId = ++latestRequestId;
    const sections = currentSections();

    // Optimistic local parse: instant feedback while the authoritative
    // server response (below) is in flight. Same shape either way, so
    // the board/state code doesn't care which one it's looking at.
    const localDeck = parseDeckSections(sections);
    setState({ deck: localDeck, board: newBoardFromDeck(localDeck) });
    showResult(localDeck, { pending: true });

    // Fire and forget: images (and, for the detail view, full card
    // data) arrive later and re-render via the shared state
    // subscription (board) or refreshResult() (import result panel).
    // Sideboard included too — otherwise its cards never resolve in the
    // detail view (permanently stuck on the "Lädt …" placeholder).
    const cardNames = [...localDeck.commanders, ...localDeck.mainDeck, ...localDeck.sideboard].map((c) => c.name);
    resolveCardImages(cardNames).then((imageCache) => {
      setState({ imageCache });
      if (requestId === latestRequestId) refreshResult();
    });

    submitDeck(sections).then((result) => {
      if (requestId !== latestRequestId) return; // superseded by a later parse click

      if (!result.ok) {
        showResult(localDeck, { warning: result.error });
        return;
      }
      setState({ deck: result.deck, board: newBoardFromDeck(result.deck) });
      showResult(result.deck, { serverConfirmed: true });
    });
  }

  container.querySelector('#parse-btn').addEventListener('click', parseCurrentSections);

  container.querySelector('#save-deck-btn').addEventListener('click', async () => {
    saveStatusEl.textContent = 'Speichert …';
    saveStatusEl.className = 'server-status pending';

    const saved = await saveDeck({ id: savedDeckId ?? undefined, name: nameInput.value, ...currentSections() });

    if (!saved) {
      saveStatusEl.textContent = 'Speichern fehlgeschlagen – Server nicht erreichbar.';
      saveStatusEl.className = 'server-status warning';
      return;
    }

    savedDeckId = saved.id;
    saveStatusEl.textContent = 'Gespeichert.';
    saveStatusEl.className = 'server-status ok';
  });

  function loadDeck(savedDeck) {
    savedDeckId = savedDeck.id;
    nameInput.value = savedDeck.name || '';
    commanderTextarea.value = savedDeck.commanderText || '';
    mainboardTextarea.value = savedDeck.mainboardText || '';
    sideboardTextarea.value = savedDeck.sideboardText || '';
    saveStatusEl.textContent = '';
    saveStatusEl.className = 'server-status';
    parseCurrentSections();
  }

  return { loadDeck };
}

function renderResult(resultEl, deck, { onDeckLoaded, meta = {}, detailMode, onToggleDetailMode }) {
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

  // Which specific cards the server flagged as banned / outside the
  // commander's color identity (mtg_analyzer.services.commander_legality
  // via POST /api/decks) — a name can be in both. Distinct from
  // isConfirmedNotFound (a card the backend has no data for at all);
  // these are real, resolved cards that just aren't Commander-legal.
  const bannedNames = new Set(validation.bannedCardNames || []);
  const colorViolationNames = new Set(validation.colorIdentityViolationNames || []);
  const illegalReason = (name) => {
    if (bannedNames.has(name)) return 'banned';
    if (colorViolationNames.has(name)) return 'colorIdentity';
    return null;
  };
  const ILLEGAL_TITLES = {
    banned: 'Auf der Commander-Bannliste',
    colorIdentity: 'Farbidentität passt nicht zum Commander',
  };

  const renderCards = (cards) => {
    const sorted = cards.slice().sort((a, b) => a.name.localeCompare(b.name));
    if (!sorted.length) return '<p class="empty-state">–</p>';

    if (!detailMode) {
      const items = sorted
        .map((c) => {
          const notFound = isConfirmedNotFound(c.name);
          const reason = notFound ? null : illegalReason(c.name);
          const cls = notFound ? ' class="card-not-found"' : reason ? ' class="card-illegal"' : '';
          const title = notFound
            ? ' title="Karte nicht gefunden – Name prüfen"'
            : reason
              ? ` title="${escapeHtml(ILLEGAL_TITLES[reason])}"`
              : '';
          const marker = notFound ? '🛑 ' : reason ? '❗ ' : '';
          return `<li data-hover-card="${escapeHtml(c.name)}"${cls}${title}><span class="qty">${c.qty}x</span> ${marker}${escapeHtml(c.name)}</li>`;
        })
        .join('');
      return `<ul class="card-list">${items}</ul>`;
    }

    const tiles = sorted
      .map((c) => {
        const card = getResolvedCard(c.name);
        if (card) return renderCardTile(card, { qty: c.qty, illegalReason: illegalReason(c.name) });
        if (isConfirmedNotFound(c.name)) return renderCardTileNotFound(c.name, { qty: c.qty });
        return renderCardTilePlaceholder(c.name, { qty: c.qty });
      })
      .join('');
    return `<div class="card-tile-grid">${tiles}</div>`;
  };

  // The scroll box's own height adapts to viewport size (see .scrollable
  // in main.css) rather than a fixed pixel value, and gets more room in
  // detail mode since tiles are much taller per row than plain text rows.
  const scrollable = (cards) =>
    `<div class="scrollable${detailMode ? ' detail-mode' : ''}">${renderCards(cards)}</div>`;

  const issueList = (items, className) =>
    items.length
      ? `<ul class="${className}">${items.map((e) => `<li>${escapeHtml(e)}</li>`).join('')}</ul>`
      : '';

  // Consolidated view of every not-found name across all three
  // sections, in addition to the inline 🛑 markers in the lists
  // themselves below — resolution runs async (resolveCardImages), so
  // this can still be empty on the very first render and fill in once
  // that call comes back (refreshResult() re-renders after it does).
  const notFoundNames = Array.from(
    new Set(
      [...commanders, ...mainDeck, ...sideboard]
        .map((c) => c.name)
        .filter((name) => isConfirmedNotFound(name))
    )
  );
  const notFoundHtml = notFoundNames.length
    ? `<ul class="issue-list not-found-list">${notFoundNames
        .map((name) => `<li>🛑 ${escapeHtml(name)} – nicht gefunden, Name prüfen</li>`)
        .join('')}</ul>`
    : '';

  resultEl.innerHTML = `
    <div class="deck-summary">
      <div class="deck-summary-header">
        <h2>Deck-Übersicht</h2>
        <label class="detail-toggle">
          <input type="checkbox" id="detail-mode-checkbox" ${detailMode ? 'checked' : ''} />
          Detailansicht (Bilder &amp; Eigenschaften)
        </label>
      </div>
      ${serverStatusHtml}
      <p><strong>${totalCount}</strong> Karten gesamt · Status:
        <span class="${statusClass}">${statusText}</span>
      </p>

      ${issueList(parseErrors, 'issue-list parse-errors')}
      ${issueList(validation.errors, 'issue-list validation-errors')}
      ${issueList(validation.warnings, 'issue-list validation-warnings')}
      ${notFoundHtml}

      <h3>Commander (${commanders.reduce((s, c) => s + c.qty, 0)})</h3>
      ${renderCards(commanders)}

      <h3>Hauptdeck (${mainDeck.reduce((s, c) => s + c.qty, 0)})</h3>
      ${scrollable(mainDeck)}

      ${sideboard.length ? `
        <h3>Sideboard (${sideboard.reduce((s, c) => s + c.qty, 0)})</h3>
        ${scrollable(sideboard)}
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

  resultEl.querySelector('#detail-mode-checkbox').addEventListener('change', (event) => {
    onToggleDetailMode?.(event.target.checked);
  });

  // Belt-and-suspenders against scroll anchoring: these are fresh DOM
  // nodes each render and so already start at scrollTop 0, but some
  // browsers try to preserve a scrollable ancestor's visual position
  // across a layout shift this large (tiles collapsing back to rows).
  resultEl.querySelectorAll('.scrollable').forEach((el) => {
    el.scrollTop = 0;
  });
}
