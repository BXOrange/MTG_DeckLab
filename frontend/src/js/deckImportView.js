import {
  parseDeckSections,
  parseMoxfieldExport,
  buildMoxfieldSections,
  isCommanderCandidate,
  canPairAsCommanders,
  SAMPLE_COMMANDER,
  SAMPLE_MAINBOARD,
  SAMPLE_SIDEBOARD,
} from './parser.js';
import { setState } from './state.js';
import { resolveCardImages, getResolvedCard, isConfirmedNotFound } from './cardImages.js';
import { submitDeck, saveDeck, listSleeves, listArchetypes } from './api.js';
import { getPlayerName } from './settings.js';
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
          Ein kompletter Moxfield-Export lässt sich auch als Ganzes ins
          Mainboard-Feld einfügen — Commander und Sideboard werden dann
          automatisch erkannt und in ihre Felder verschoben.
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
            <input id="deck-author-input" type="text" placeholder="Autor (optional)" />
            <button id="update-deck-btn" type="button">Aktualisieren</button>
            <button id="save-new-deck-btn" type="button">Als neues speichern</button>
            <label class="deck-cube-toggle" title="Kartensammlung statt echtes Deck: 100-Karten-/Singleton-Regel und Commander-Legalität (Bannliste, Farbidentität) werden nicht geprüft.">
              <input id="deck-cube-checkbox" type="checkbox" /> Als Collection behandeln
            </label>
            <select id="deck-sleeve-select" title="Karten-Sleeve für dieses Deck">
              <option value="">Kein Sleeve</option>
            </select>
            <select id="deck-archetype-1-select" title="Archetyp 1 (optional)">
              <option value="">Kein Archetyp</option>
            </select>
            <select id="deck-archetype-2-select" title="Archetyp 2 (optional)">
              <option value="">Kein Archetyp</option>
            </select>
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
  const authorInput = container.querySelector('#deck-author-input');
  const cubeCheckbox = container.querySelector('#deck-cube-checkbox');
  const sleeveSelect = container.querySelector('#deck-sleeve-select');
  const archetype1Select = container.querySelector('#deck-archetype-1-select');
  const archetype2Select = container.querySelector('#deck-archetype-2-select');
  const saveStatusEl = container.querySelector('#save-status');
  const resultEl = container.querySelector('#import-result');

  // Sleeve list is re-fetched whenever this tab becomes visible (cheap
  // call, keeps a sleeve just uploaded in Einstellungen selectable right
  // away) while preserving whatever the select currently has chosen.
  async function refreshSleeveOptions(preserveSelectedId) {
    const selectedId = preserveSelectedId !== undefined ? preserveSelectedId : sleeveSelect.value;
    const playerName = getPlayerName();
    const sleeves = playerName ? await listSleeves(playerName) : [];
    const options = ['<option value="">Kein Sleeve</option>'];
    for (const s of sleeves || []) {
      const selected = s.sleeve_id === selectedId ? ' selected' : '';
      options.push(`<option value="${escapeHtml(s.sleeve_id)}"${selected}>${escapeHtml(s.label)}</option>`);
    }
    sleeveSelect.innerHTML = options.join('');
  }
  container.addEventListener('view-shown', () => refreshSleeveOptions());

  // The archetype catalogue (mtg_analyzer/data/archetypes.json, served via
  // GET /api/archetypes) is static reference data, not player-scoped like
  // sleeves — fetched once rather than on every 'view-shown'. `loadDeck`
  // may run before this resolves (or the reverse), so the two selects'
  // desired values are tracked separately from the options list itself and
  // (re-)applied from `pendingArchetypeSelection` whichever finishes last.
  let pendingArchetypeSelection = ['', ''];
  function applyArchetypeSelection([a1, a2]) {
    pendingArchetypeSelection = [a1 || '', a2 || ''];
    archetype1Select.value = pendingArchetypeSelection[0];
    archetype2Select.value = pendingArchetypeSelection[1];
  }
  async function loadArchetypeCatalogue() {
    const res = await listArchetypes();
    const catalogue = res.ok ? res.data || [] : [];
    const options = ['<option value="">Kein Archetyp</option>']
      .concat(catalogue.map((a) => `<option value="${escapeHtml(a.id)}">${escapeHtml(a.label)}</option>`))
      .join('');
    archetype1Select.innerHTML = options;
    archetype2Select.innerHTML = options;
    applyArchetypeSelection(pendingArchetypeSelection);
  }
  loadArchetypeCatalogue();

  // Card names the user starred in the detail-view card grid
  // (Deck.favoriteCards) — kept here rather than in cardTile.js, which only
  // owns each tile's own DOM state (see its `card-tile-favorite-toggle`
  // event). Seeded from a loaded deck, reset on "Beispieldeck laden".
  let favoriteCards = new Set();
  resultEl.addEventListener('card-tile-favorite-toggle', (event) => {
    const { name, favorite } = event.detail || {};
    if (!name) return;
    if (favorite) favoriteCards.add(name);
    else favoriteCards.delete(name);
  });
  // The plain-text list view (detailMode off) has no per-tile DOM to
  // delegate a toggle through like cardTile.js's tiles do, so its star
  // button just flips the shared `favoriteCards` set directly and
  // re-renders — see the `.card-list-favorite` button built in
  // `renderCards` below.
  resultEl.addEventListener('click', (event) => {
    const button = event.target.closest('.card-list-favorite');
    if (!button) return;
    const name = button.dataset.favoriteCard;
    if (!name) return;
    if (favoriteCards.has(name)) favoriteCards.delete(name);
    else favoriteCards.add(name);
    refreshResult();
  });

  // Set once a deck has been saved/loaded. "Aktualisieren" overwrites
  // that saved deck; "Als neues speichern" always creates a fresh deck
  // (leaving the loaded one untouched) and then points savedDeckId at the
  // new copy. Split into two explicit buttons because a single "Speichern"
  // that silently overwrote the loaded deck after e.g. a commander change
  // was surprising and destructive. Reset (update disabled) by loading the
  // sample deck.
  let savedDeckId = null;
  const updateDeckBtn = container.querySelector('#update-deck-btn');

  function updateSaveButtons() {
    // "Aktualisieren" only makes sense once there's a saved deck to target.
    updateDeckBtn.disabled = savedDeckId == null;
    updateDeckBtn.title = savedDeckId == null
      ? 'Erst verfügbar, sobald ein Deck geladen oder als neues gespeichert wurde.'
      : 'Das geladene/gespeicherte Deck überschreiben.';
  }
  updateSaveButtons();
  // The last rendered deck + render metadata, kept so the "Detailansicht"
  // toggle and late-arriving card data can re-render without re-parsing.
  let lastDeck = null;
  let lastMeta = {};
  let detailMode = false;
  // How large the detail-view card tiles render (`.card-tile-grid`'s zoom
  // modifier class, see main.css) — starts compact so a big deck's
  // "Hauptdeck" grid doesn't force endless scrolling; a zoom step up is
  // still one click away.
  let tileZoom = 'compact';

  // Foil/star markers ("Sol Ring ★") aren't part of a card name and break
  // resolution. Strip them from the entered text so what we parse, submit,
  // and save is clean; `sanitizeInputs` also rewrites the textareas so the
  // user sees the cleaned list.
  const stripStars = (text) => (text || '').replace(/[★☆]/g, '');

  function sanitizeInputs() {
    for (const el of [commanderTextarea, mainboardTextarea, sideboardTextarea]) {
      const cleaned = stripStars(el.value);
      if (cleaned !== el.value) el.value = cleaned;
    }
  }

  function currentSections() {
    return {
      commanderText: stripStars(commanderTextarea.value),
      mainboardText: stripStars(mainboardTextarea.value),
      sideboardText: stripStars(sideboardTextarea.value),
    };
  }

  function showResult(deck, meta) {
    lastDeck = deck;
    lastMeta = meta;
    renderResult(resultEl, deck, {
      onDeckLoaded,
      meta,
      detailMode,
      tileZoom,
      isFavorite: (name) => favoriteCards.has(name),
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
      onZoomChange: (level) => {
        tileZoom = level;
        if (lastDeck) showResult(lastDeck, lastMeta);
      },
    });
  }

  function refreshResult() {
    if (lastDeck) showResult(lastDeck, lastMeta);
  }

  // Pasting a full Moxfield export (rather than just a mainboard snippet)
  // into the Mainboard field auto-splits it into all three textareas.
  // Gated on the export's own "SIDEBOARD:" header — the only unambiguous
  // signal that this is a whole export and not, say, someone pasting 40
  // ordinary mainboard lines.
  //
  // Moxfield prints no header for the commander(s) at all, so telling
  // them apart from the mainboard needs a real oracle-text/type-line
  // check, not a text heuristic: resolve the first (and, if it pairs,
  // second) body line's real card data and ask "is this actually
  // commander-eligible" (legendary creature / "can be your commander" /
  // Partner) — the same question the backend's commander_legality.py
  // asks once the deck is saved. Renders the sideboard-only split
  // immediately for instant feedback, then refines the commander/
  // mainboard boundary once that lookup resolves (typically a cached,
  // sub-second call via resolveCardImages).
  async function detectMoxfieldCommanderCount(bodyLines) {
    if (!bodyLines.length) return 0;
    const candidates = bodyLines.slice(0, 2).map((l) => l.name);
    const resolved = await resolveCardImages(candidates);
    const cardA = resolved.get(candidates[0].toLowerCase())?.card;
    if (!isCommanderCandidate(cardA)) return 0;
    if (candidates.length < 2) return 1;
    const cardB = resolved.get(candidates[1].toLowerCase())?.card;
    if (cardB && isCommanderCandidate(cardB) && canPairAsCommanders(cardA, cardB)) return 2;
    return 1;
  }

  mainboardTextarea.addEventListener('paste', (event) => {
    const text = event.clipboardData?.getData('text');
    if (!text || !/^\s*sideboard:?\s*$/im.test(text)) return;
    event.preventDefault();

    const parsed = parseMoxfieldExport(text);
    const draft = buildMoxfieldSections(parsed, 0);
    commanderTextarea.value = draft.commanderText;
    mainboardTextarea.value = draft.mainboardText;
    sideboardTextarea.value = draft.sideboardText;

    detectMoxfieldCommanderCount(parsed.bodyLines).then((commanderCount) => {
      if (!commanderCount) return;
      const final = buildMoxfieldSections(parsed, commanderCount);
      commanderTextarea.value = final.commanderText;
      mainboardTextarea.value = final.mainboardText;
    });
  });

  container.querySelector('#sample-btn').addEventListener('click', () => {
    commanderTextarea.value = SAMPLE_COMMANDER;
    mainboardTextarea.value = SAMPLE_MAINBOARD;
    sideboardTextarea.value = SAMPLE_SIDEBOARD;
    savedDeckId = null;
    updateSaveButtons();
    nameInput.value = '';
    authorInput.value = '';
    cubeCheckbox.checked = false;
    sleeveSelect.value = '';
    applyArchetypeSelection(['', '']);
    favoriteCards = new Set();
    saveStatusEl.textContent = '';
    saveStatusEl.className = 'server-status';
  });

  let latestRequestId = 0;

  function parseCurrentSections() {
    const requestId = ++latestRequestId;
    sanitizeInputs(); // strip foil stars from the textareas before parsing
    const sections = currentSections();
    const isCube = cubeCheckbox.checked;

    // Optimistic local parse: instant feedback while the authoritative
    // server response (below) is in flight.
    const localDeck = parseDeckSections({ ...sections, isCube });
    setState({ deck: localDeck });
    showResult(localDeck, { pending: true, isCube });

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

    submitDeck(sections, isCube).then((result) => {
      if (requestId !== latestRequestId) return; // superseded by a later parse click

      if (!result.ok) {
        showResult(localDeck, { warning: result.error, isCube });
        return;
      }
      setState({ deck: result.deck });
      showResult(result.deck, { serverConfirmed: true, isCube });
    });
  }

  container.querySelector('#parse-btn').addEventListener('click', parseCurrentSections);

  async function doSave({ update }) {
    // update=true overwrites the loaded/saved deck (sends its id);
    // update=false always creates a new deck (no id) and adopts its id.
    saveStatusEl.textContent = update ? 'Aktualisiert …' : 'Speichert …';
    saveStatusEl.className = 'server-status pending';

    const id = update ? savedDeckId ?? undefined : undefined;
    const saved = await saveDeck({
      id,
      name: nameInput.value,
      author: authorInput.value.trim() || null,
      isCube: cubeCheckbox.checked,
      sleeveId: sleeveSelect.value || null,
      archetypes: [archetype1Select.value, archetype2Select.value].filter(Boolean),
      favoriteCards: [...favoriteCards],
      ...currentSections(),
    });

    if (!saved) {
      saveStatusEl.textContent = 'Speichern fehlgeschlagen – Server nicht erreichbar.';
      saveStatusEl.className = 'server-status warning';
      return;
    }

    savedDeckId = saved.id;
    updateSaveButtons();
    saveStatusEl.textContent = update ? 'Aktualisiert.' : 'Als neues Deck gespeichert.';
    saveStatusEl.className = 'server-status ok';
  }

  updateDeckBtn.addEventListener('click', () => doSave({ update: true }));
  container.querySelector('#save-new-deck-btn').addEventListener('click', () => doSave({ update: false }));

  function loadDeck(savedDeck) {
    savedDeckId = savedDeck.id;
    updateSaveButtons();
    nameInput.value = savedDeck.name || '';
    authorInput.value = savedDeck.author || '';
    cubeCheckbox.checked = !!savedDeck.isCube;
    refreshSleeveOptions(savedDeck.sleeveId || '');
    applyArchetypeSelection(savedDeck.archetypes || []);
    favoriteCards = new Set(savedDeck.favoriteCards || []);
    commanderTextarea.value = savedDeck.commanderText || '';
    mainboardTextarea.value = savedDeck.mainboardText || '';
    sideboardTextarea.value = savedDeck.sideboardText || '';
    saveStatusEl.textContent = '';
    saveStatusEl.className = 'server-status';
    parseCurrentSections();
  }

  return { loadDeck };
}

//: Card-tile grid sizes for the detail view's zoom control — id -> the
//: `.card-tile-grid` modifier class (main.css) and its select label.
//: "compact" is the default (see `tileZoom` above): a 220px minimum tile
//: fits far fewer columns than the art actually needs, so bigger decks
//: forced a lot of scrolling before this existed.
const TILE_ZOOM_LEVELS = [
  { id: 'compact', label: 'Kompakt' },
  { id: 'medium', label: 'Mittel' },
  { id: 'large', label: 'Groß' },
];

function zoomControlHtml(tileZoom) {
  const options = TILE_ZOOM_LEVELS
    .map((l) => `<option value="${l.id}" ${l.id === tileZoom ? 'selected' : ''}>${l.label}</option>`)
    .join('');
  return `
    <label class="zoom-toggle">
      Kartengröße
      <select id="tile-zoom-select">${options}</select>
    </label>
  `;
}

function renderResult(resultEl, deck, { onDeckLoaded, meta = {}, detailMode, tileZoom = 'compact', onToggleDetailMode, onZoomChange, isFavorite }) {
  const { commanders, mainDeck, sideboard, totalCount, parseErrors, validation } = deck;

  const statusClass = meta.isCube ? 'status-ok' : validation.isLegal ? 'status-ok' : 'status-error';
  const statusText = meta.isCube ? '🧊 Collection (keine Legalitätsprüfung)' : validation.isLegal ? 'Legal (strukturell)' : 'Nicht legal';

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
          const isFav = isFavorite ? isFavorite(c.name) : false;
          const favButton = `<button type="button" class="card-list-favorite${isFav ? ' is-favorite' : ''}"
             data-favorite-card="${escapeHtml(c.name)}" aria-pressed="${isFav}"
             title="Favorit markieren/entfernen" aria-label="Favorit markieren/entfernen">${isFav ? '★' : '☆'}</button>`;
          return `<li data-hover-card="${escapeHtml(c.name)}"${cls}${title}>${favButton}<span class="qty">${c.qty}x</span> ${marker}${escapeHtml(c.name)}</li>`;
        })
        .join('');
      return `<ul class="card-list">${items}</ul>`;
    }

    const tiles = sorted
      .map((c) => {
        const card = getResolvedCard(c.name);
        if (card) {
          return renderCardTile(card, {
            qty: c.qty,
            illegalReason: illegalReason(c.name),
            favorite: isFavorite ? isFavorite(c.name) : false,
          });
        }
        if (isConfirmedNotFound(c.name)) return renderCardTileNotFound(c.name, { qty: c.qty });
        return renderCardTilePlaceholder(c.name, { qty: c.qty });
      })
      .join('');
    return `<div class="card-tile-grid zoom-${tileZoom}">${tiles}</div>`;
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
        <div class="deck-summary-header-controls">
          <label class="detail-toggle">
            <input type="checkbox" id="detail-mode-checkbox" ${detailMode ? 'checked' : ''} />
            Detailansicht (Bilder &amp; Eigenschaften)
          </label>
          ${detailMode ? zoomControlHtml(tileZoom) : ''}
        </div>
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

      <button id="goto-goldfish-btn" type="button" class="primary"
        ${meta.serverConfirmed ? '' : 'disabled'}
        title="${meta.serverConfirmed ? '' : 'Erst verfügbar, sobald das Deck serverseitig geprüft wurde.'}"
      >Zum Goldfisch-Modus →</button>
    </div>
  `;

  resultEl.querySelector('#goto-goldfish-btn').addEventListener('click', () => {
    onDeckLoaded?.();
  });

  resultEl.querySelector('#detail-mode-checkbox').addEventListener('change', (event) => {
    onToggleDetailMode?.(event.target.checked);
  });

  resultEl.querySelector('#tile-zoom-select')?.addEventListener('change', (event) => {
    onZoomChange?.(event.target.value);
  });

  // Belt-and-suspenders against scroll anchoring: these are fresh DOM
  // nodes each render and so already start at scrollTop 0, but some
  // browsers try to preserve a scrollable ancestor's visual position
  // across a layout shift this large (tiles collapsing back to rows).
  resultEl.querySelectorAll('.scrollable').forEach((el) => {
    el.scrollTop = 0;
  });
}
