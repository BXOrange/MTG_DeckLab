// "Profil" tab: everything player-facing. The player name, persisted in a
// cookie (settings.js), plus the player-scoped preferences and assets that
// build on it:
//
//   Mehrspieler-Standardeinstellungen  client-local defaults (cookie, same
//     as auto-pass below) applied to a table this player *hosts* —
//     multiplayerView.js's createGame() reads them right after
//     POST /api/multiplayer/games and applies them via setMultiplayerOptions,
//     the same host-only route the Setup screen's option rows already use.
//   Mehrspieler: Auto-Pass / Spielfeld  this browser's own play-comfort
//     toggles (cookie), also adjustable directly on the board mid-game.
//   Eigene Token-Bilder / Karten-Sleeves  server-side player assets
//     (services/player_assets.py), keyed by this player name so a
//     multiplayer opponent's client can fetch them too.
//   Lieblingsdecks  server-side (services/player_assets.py, keyed by this
//     player name, same storage as sleeves/token art), since two players
//     favoriting different decks out of one shared, unowned deck list can't
//     live as a flag on the Deck itself. Read by goldfishView.js and
//     multiplayerView.js's deck pickers to list favorites first.
//
// The player name is the one field the rest of the app treats as "who you
// are" — the identity key player_assets.py stores everything under. The
// "Einstellungen" tab (connectionSettingsView.js) is now only the server
// address.

import { getSettings, saveSettings, ensureClientToken } from './settings.js';
import {
  fetchGameFormats,
  listSavedDecks,
  listFavoriteDecks,
  addFavoriteDeck,
  removeFavoriteDeck,
  listTokenImages,
  uploadTokenImage,
  deleteTokenImage,
  tokenImageUrl,
  listSleeves,
  uploadSleeve,
  deleteSleeve,
  sleeveImageUrl,
  fetchKnownTokenTypes,
  GENERIC_TOKEN_KEY,
} from './api.js';
import { MULLIGAN_LABELS, SEAT_COUNTS } from './mulligan.js';
import { escapeHtml } from './cardTile.js';

const GENERIC_TOKEN_LABEL = 'Generisch (alle Token ohne eigenes Bild)';
// UI-only sentinel (never sent to the backend as a token_name): selecting it
// reveals a free-text input, for a token that's neither in the curated
// catalogue nor meant to be the generic fallback.
const CUSTOM_TOKEN_VALUE = '__custom__';

function tokenNameLabel(tokenName) {
  return tokenName === GENERIC_TOKEN_KEY ? GENERIC_TOKEN_LABEL : tokenName;
}

export function renderProfileView(container) {
  container.innerHTML = `
    <div class="connection-settings-panel">
      <h2>Profil</h2>

      <div class="deck-section">
        <label for="profile-name-input">Spielername</label>
        <input id="profile-name-input" type="text" placeholder="z.B. Alex" />
      </div>

      <div class="import-actions">
        <button id="save-profile-btn" type="button" class="primary">Speichern</button>
      </div>
      <p class="hint">
        Wird im Browser (Cookie) gespeichert — nicht serverseitig, ein anderer Browser/Rechner
        sieht ihn nicht. Eigene Token-Bilder, Karten-Sleeves und der Mehrspieler-Modus sind unter
        diesem Namen gespeichert. Beim Speichern erhält dieser Browser außerdem eine eigene,
        unsichtbare Kennung (90 Tage gültig, verlängert sich bei jedem Speichern) — so belegt ein
        zweiter Browser mit demselben Namen nicht denselben Platz am Tisch. Wird die Kennung
        90 Tage lang nicht genutzt, gelten Name und hochgeladene Bilder/Sleeves als verwaist und
        werden vom Server gelöscht.
      </p>

      <div class="deck-section">
        <h3>Mehrspieler: Standardeinstellungen</h3>
        <p class="hint">
          Werden übernommen, sobald du selbst einen neuen Tisch eröffnest (Tab "Multiplayer") —
          am Tisch selbst bleiben sie jederzeit als Host änderbar.
        </p>
        <div class="mp-option-row">
          <label for="profile-mp-format">Format</label>
          <select id="profile-mp-format"><option>Lädt …</option></select>
        </div>
        <div class="mp-option-row">
          <label for="profile-mp-seats">Plätze</label>
          <select id="profile-mp-seats">
            ${SEAT_COUNTS.map((n) => `<option value="${n}">${n} Spieler</option>`).join('')}
          </select>
        </div>
        <div class="mp-option-row">
          <label for="profile-mp-mulligan">Mulligan-Regel</label>
          <select id="profile-mp-mulligan">
            ${Object.entries(MULLIGAN_LABELS)
              .map(([value, label]) => `<option value="${value}">${escapeHtml(label)}</option>`)
              .join('')}
          </select>
        </div>
        <div class="mp-option-row">
          <label for="profile-mp-takebacks">Take-backs je Spieler</label>
          <input id="profile-mp-takebacks" type="number" min="0" max="20" />
        </div>
        <div class="mp-option-row">
          <label>Auslosen</label>
          <label class="mp-option-check">
            <input id="profile-mp-random-seating" type="checkbox" />
            Sitzordnung (Regel 103.1)
          </label>
          <label class="mp-option-check">
            <input id="profile-mp-random-start" type="checkbox" />
            Startspieler (Regel 103.2)
          </label>
        </div>
      </div>

      <div class="deck-section">
        <h3>Mehrspieler: Auto-Pass</h3>
        <p class="hint">
          Im Mehrspieler-Modus wird die Priorität (Regel 117) wirklich reihum
          weitergegeben. Damit ein Spiel, in dem niemand reagieren will, nicht
          zäh wird, kann automatisch gepasst werden. Der Countdown läuft nur,
          solange du nichts anfasst — jede Aktion auf dem Spielfeld stoppt ihn.
          Auch während einer Partie direkt am Spielfeld änderbar.
        </p>
        <label class="mp-inline-option">
          <input type="checkbox" id="auto-pass-toggle" />
          Automatisch passen
        </label>
        <div class="mp-option-row">
          <label for="auto-pass-seconds">Bedenkzeit</label>
          <input id="auto-pass-seconds" type="number" min="1" max="60" /> Sekunden
        </div>
        <div class="mp-option-row">
          <label for="auto-pass-scope">Gilt für</label>
          <select id="auto-pass-scope">
            <option value="opponent">nur gegnerische Züge (empfohlen)</option>
            <option value="always">alle Züge, auch meine eigenen</option>
          </select>
        </div>
        <label class="mp-inline-option" title="Anders als Automatisch passen: kein Countdown, und es greift nur, wenn dir wirklich nichts anderes als 'Passen' offensteht (z. B. im gegnerischen Zug ohne Instant in der Hand). Sobald eine echte Aktion angeboten wird, bist du sofort wieder am Zug.">
          <input type="checkbox" id="auto-skip-empty" />
          Sofort passen, wenn nichts zu tun ist
        </label>
      </div>

      <div class="deck-section">
        <h3>Mehrspieler: Spielfeld</h3>
        <p class="hint">
          Die Handkarten deines Gegners verlassen den Server nie (Regel 400.2) —
          die Frage ist nur, ob das Spielfeld die Anzahl als verdeckte Karten
          zeichnet oder bloß als Zahl. Auch direkt am Spielfeld umschaltbar.
        </p>
        <label class="mp-inline-option">
          <input type="checkbox" id="show-opponent-hand" />
          Gegnerische Hand als verdeckte Karten zeigen
        </label>
      </div>

      <div class="deck-section player-assets-section">
        <h3>Eigene Token-Bilder</h3>
        <p class="hint">
          Bilder für bekannte Token-Arten, ein "generisches" Bild für alle Token ohne eigenes
          Bild (z. B. selbst erzeugte "1/1 Soldier"), oder über "Andere" ein eigener Token-Name —
          gespeichert unter deinem Spielernamen auf dem Server, damit sie auch ein Gegner im
          Mehrspieler-Modus sieht.
        </p>
        <div id="token-images-list" class="player-asset-grid"><p class="empty-state"><span class="spinner" aria-hidden="true"></span>Lädt …</p></div>
        <form id="token-image-form" class="player-asset-form">
          <select id="token-image-name" required><option value="">Token-Art lädt …</option></select>
          <input type="text" id="token-image-custom-name" placeholder="Token-Name (z. B. Soldier 1/1)" style="display: none" />
          <input type="file" id="token-image-file" accept="image/png,image/jpeg,image/webp,image/gif" required />
          <button type="submit" class="primary">Hochladen</button>
        </form>
      </div>

      <div class="deck-section player-assets-section">
        <h3>Karten-Sleeves</h3>
        <p class="hint">
          Eigene Kartenrückseiten — im Tab "Gespeicherte Decks" einem Deck zuweisbar.
        </p>
        <div id="sleeves-list" class="player-asset-grid"><p class="empty-state"><span class="spinner" aria-hidden="true"></span>Lädt …</p></div>
        <form id="sleeve-form" class="player-asset-form">
          <input type="text" id="sleeve-label" placeholder="Name (z. B. Blauer Drache)" required />
          <input type="file" id="sleeve-file" accept="image/png,image/jpeg,image/webp,image/gif" required />
          <button type="submit" class="primary">Hochladen</button>
        </form>
      </div>

      <div class="deck-section">
        <h3>Lieblingsdecks</h3>
        <p class="hint">
          Erscheinen im Goldfisch-Modus und in der Mehrspieler-Lobby zuerst in der Deck-Auswahl.
        </p>
        <div id="profile-favorite-decks"><p class="empty-state"><span class="spinner" aria-hidden="true"></span>Lädt …</p></div>
      </div>
    </div>
  `;

  const nameInput = container.querySelector('#profile-name-input');
  const saveBtn = container.querySelector('#save-profile-btn');
  const formatSelect = container.querySelector('#profile-mp-format');
  const seatsSelect = container.querySelector('#profile-mp-seats');
  const mulliganSelect = container.querySelector('#profile-mp-mulligan');
  const takebacksInput = container.querySelector('#profile-mp-takebacks');
  const randomSeatingInput = container.querySelector('#profile-mp-random-seating');
  const randomStartInput = container.querySelector('#profile-mp-random-start');
  const favoritesEl = container.querySelector('#profile-favorite-decks');

  const autoPassToggle = container.querySelector('#auto-pass-toggle');
  const autoPassSeconds = container.querySelector('#auto-pass-seconds');
  const autoPassScope = container.querySelector('#auto-pass-scope');
  const autoSkipEmpty = container.querySelector('#auto-skip-empty');
  const showOpponentHand = container.querySelector('#show-opponent-hand');

  const tokenImagesList = container.querySelector('#token-images-list');
  const tokenImageForm = container.querySelector('#token-image-form');
  const sleevesList = container.querySelector('#sleeves-list');
  const sleeveForm = container.querySelector('#sleeve-form');

  nameInput.value = getSettings().playerName;

  saveBtn.addEventListener('click', () => {
    const saved = saveSettings({ playerName: nameInput.value });
    nameInput.value = saved.playerName;
    // PLR-4: mint/renew this browser's identity token alongside the name,
    // so a second browser saving the same name doesn't take this seat over.
    ensureClientToken();
    loadFavorites(); // the favorites list is keyed by the (now possibly new) name
    loadTokenImages();
    loadSleeves();
  });

  // --- Multiplayer default settings --------------------------------------

  function applyMpDefaultsToForm() {
    const s = getSettings();
    seatsSelect.value = String(s.mpDefaultSeats);
    mulliganSelect.value = s.mpDefaultMulliganStyle;
    takebacksInput.value = String(s.mpDefaultTakebacks);
    randomSeatingInput.checked = s.mpDefaultRandomizeSeating;
    randomStartInput.checked = s.mpDefaultRandomStartingPlayer;
    if (formatSelect.querySelector(`option[value="${cssEscape(s.mpDefaultFormat)}"]`)) {
      formatSelect.value = s.mpDefaultFormat;
    }
  }

  let formatsLoaded = false;
  async function loadFormats() {
    const res = await fetchGameFormats();
    const formats = res.ok ? res.data?.formats || [] : [];
    formatSelect.innerHTML = formats.length
      ? formats.map((f) => `<option value="${escapeHtml(f.name)}">${escapeHtml(f.label)}</option>`).join('')
      : '<option value="commander">Commander</option>';
    formatsLoaded = true;
    applyMpDefaultsToForm();
  }

  formatSelect.addEventListener('change', () => saveSettings({ mpDefaultFormat: formatSelect.value }));
  seatsSelect.addEventListener('change', () => saveSettings({ mpDefaultSeats: seatsSelect.value }));
  mulliganSelect.addEventListener('change', () => saveSettings({ mpDefaultMulliganStyle: mulliganSelect.value }));
  takebacksInput.addEventListener('change', () => {
    const saved = saveSettings({ mpDefaultTakebacks: takebacksInput.value });
    takebacksInput.value = String(saved.mpDefaultTakebacks);
  });
  randomSeatingInput.addEventListener('change', () =>
    saveSettings({ mpDefaultRandomizeSeating: randomSeatingInput.checked }),
  );
  randomStartInput.addEventListener('change', () =>
    saveSettings({ mpDefaultRandomStartingPlayer: randomStartInput.checked }),
  );

  // --- Auto-pass / board comfort toggles -------------------------------

  const s = getSettings();
  autoPassToggle.checked = s.autoPass;
  autoPassSeconds.value = s.autoPassSeconds;
  autoPassSeconds.disabled = !s.autoPass;
  autoPassScope.value = s.autoPassScope;
  autoSkipEmpty.checked = s.autoSkipEmpty;
  showOpponentHand.checked = s.showOpponentHand;

  // Saved on change rather than behind the "Speichern" button: these only
  // affect this browser's own play, and a setting you toggled but didn't
  // save is exactly the kind of thing that bites mid-game.
  autoPassToggle.addEventListener('change', () => {
    const saved = saveSettings({ autoPass: autoPassToggle.checked });
    autoPassSeconds.disabled = !saved.autoPass;
  });
  autoPassSeconds.addEventListener('change', () => {
    autoPassSeconds.value = saveSettings({ autoPassSeconds: autoPassSeconds.value }).autoPassSeconds;
  });
  autoSkipEmpty.addEventListener('change', () => {
    saveSettings({ autoSkipEmpty: autoSkipEmpty.checked });
  });
  showOpponentHand.addEventListener('change', () => {
    saveSettings({ showOpponentHand: showOpponentHand.checked });
  });
  autoPassScope.addEventListener('change', () => {
    saveSettings({ autoPassScope: autoPassScope.value });
  });

  // --- Token images / sleeves -----------------------------------------

  // The "known token type" dropdown — deck-independent (GET /api/game/tokens,
  // the repo's curated catalogue), so a player picks an exact name instead of
  // retyping one by hand. The "generic" entry is a client-side addition (not
  // part of the catalogue): its uploaded image is the fallback art for any
  // token with neither real art nor its own upload (mostly ad hoc tokens an
  // effect synthesizes inline, which have no catalogue entry to pick).
  async function loadKnownTokenTypes() {
    const select = container.querySelector('#token-image-name');
    const res = await fetchKnownTokenTypes();
    const names = res.ok ? (res.data?.tokens || []).map((t) => t.name) : [];
    const uniqueNames = [...new Set(names)].sort((a, b) => a.localeCompare(b));
    select.innerHTML = [
      `<option value="${escapeHtml(GENERIC_TOKEN_KEY)}">${escapeHtml(GENERIC_TOKEN_LABEL)}</option>`,
      ...uniqueNames.map((n) => `<option value="${escapeHtml(n)}">${escapeHtml(n)}</option>`),
      `<option value="${CUSTOM_TOKEN_VALUE}">Andere (Name eingeben) …</option>`,
    ].join('');
  }

  // Toggle the free-text name field alongside the dropdown — only needed
  // (and only required) when "Andere …" is picked.
  function updateCustomTokenNameVisibility() {
    const select = container.querySelector('#token-image-name');
    const customInput = container.querySelector('#token-image-custom-name');
    const isCustom = select.value === CUSTOM_TOKEN_VALUE;
    customInput.style.display = isCustom ? '' : 'none';
    customInput.required = isCustom;
    customInput.disabled = !isCustom;
    if (!isCustom) customInput.value = '';
  }

  // Both asset kinds are keyed by the *saved* player name (getSettings(),
  // not the live input) since that's what the game board actually looks up.
  async function loadTokenImages() {
    const name = getSettings().playerName;
    if (!name) {
      tokenImagesList.innerHTML = '<p class="empty-state">Erst oben einen Spielernamen speichern.</p>';
      return;
    }
    const images = await listTokenImages(name);
    if (images === null) {
      tokenImagesList.innerHTML = '<p class="server-status warning">Server nicht erreichbar.</p>';
      return;
    }
    if (!images.length) {
      tokenImagesList.innerHTML = '<p class="empty-state">Noch keine Token-Bilder hochgeladen.</p>';
      return;
    }
    tokenImagesList.innerHTML = images
      .map(
        (t) => `
      <div class="player-asset-tile">
        <img src="${tokenImageUrl(name, t.token_name)}" alt="${escapeHtml(tokenNameLabel(t.token_name))}" loading="lazy" />
        <span>${escapeHtml(tokenNameLabel(t.token_name))}</span>
        <button type="button" class="delete-token-image-btn" data-token-name="${escapeHtml(t.token_name)}">Löschen</button>
      </div>`
      )
      .join('');
    tokenImagesList.querySelectorAll('.delete-token-image-btn').forEach((btn) => {
      btn.addEventListener('click', async () => {
        btn.disabled = true;
        await deleteTokenImage(name, btn.dataset.tokenName);
        loadTokenImages();
      });
    });
  }

  async function loadSleeves() {
    const name = getSettings().playerName;
    if (!name) {
      sleevesList.innerHTML = '<p class="empty-state">Erst oben einen Spielernamen speichern.</p>';
      return;
    }
    const sleeves = await listSleeves(name);
    if (sleeves === null) {
      sleevesList.innerHTML = '<p class="server-status warning">Server nicht erreichbar.</p>';
      return;
    }
    if (!sleeves.length) {
      sleevesList.innerHTML = '<p class="empty-state">Noch keine Sleeves hochgeladen.</p>';
      return;
    }
    sleevesList.innerHTML = sleeves
      .map(
        (s) => `
      <div class="player-asset-tile">
        <img src="${sleeveImageUrl(name, s.sleeve_id)}" alt="${escapeHtml(s.label)}" loading="lazy" />
        <span>${escapeHtml(s.label)}</span>
        <button type="button" class="delete-sleeve-btn" data-sleeve-id="${escapeHtml(s.sleeve_id)}">Löschen</button>
      </div>`
      )
      .join('');
    sleevesList.querySelectorAll('.delete-sleeve-btn').forEach((btn) => {
      btn.addEventListener('click', async () => {
        btn.disabled = true;
        await deleteSleeve(name, btn.dataset.sleeveId);
        loadSleeves();
      });
    });
  }

  tokenImageForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = getSettings().playerName;
    if (!name) {
      window.alert('Bitte zuerst oben einen Spielernamen speichern.');
      return;
    }
    const tokenNameSelect = container.querySelector('#token-image-name');
    const customNameInput = container.querySelector('#token-image-custom-name');
    const fileInput = container.querySelector('#token-image-file');
    const file = fileInput.files[0];
    const tokenName =
      tokenNameSelect.value === CUSTOM_TOKEN_VALUE ? customNameInput.value.trim() : tokenNameSelect.value;
    if (!tokenName || !file) return;
    const res = await uploadTokenImage(name, tokenName, file);
    if (!res.ok) {
      window.alert(`Hochladen fehlgeschlagen (${res.status}).`);
      return;
    }
    tokenImageForm.reset();
    updateCustomTokenNameVisibility();
    loadTokenImages();
  });

  container.querySelector('#token-image-name').addEventListener('change', updateCustomTokenNameVisibility);

  sleeveForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = getSettings().playerName;
    if (!name) {
      window.alert('Bitte zuerst oben einen Spielernamen speichern.');
      return;
    }
    const labelInput = container.querySelector('#sleeve-label');
    const fileInput = container.querySelector('#sleeve-file');
    const file = fileInput.files[0];
    if (!labelInput.value.trim() || !file) return;
    const res = await uploadSleeve(name, labelInput.value.trim(), file);
    if (!res.ok) {
      window.alert(`Hochladen fehlgeschlagen (${res.status}).`);
      return;
    }
    sleeveForm.reset();
    loadSleeves();
  });

  // --- Favorite decks ------------------------------------------------------

  async function loadFavorites() {
    const playerName = getSettings().playerName;
    if (!playerName) {
      favoritesEl.innerHTML = '<p class="empty-state">Erst oben einen Spielernamen speichern.</p>';
      return;
    }
    favoritesEl.innerHTML = '<p class="empty-state"><span class="spinner" aria-hidden="true"></span>Lädt …</p>';
    const [decks, favoriteIds] = await Promise.all([listSavedDecks(), listFavoriteDecks(playerName)]);
    if (decks === null || favoriteIds === null) {
      favoritesEl.innerHTML = '<p class="server-status warning">Server nicht erreichbar.</p>';
      return;
    }
    if (!decks.length) {
      favoritesEl.innerHTML =
        '<p class="empty-state">Noch keine gespeicherten Decks — im Tab "Deck importieren" eines anlegen.</p>';
      return;
    }
    const favoriteSet = new Set(favoriteIds);
    favoritesEl.innerHTML = `<ul class="profile-favorite-deck-list">${decks
      .map((d) => {
        const name = (d.name || '').trim() || 'Unbenanntes Deck';
        return `<li>
          <label>
            <input type="checkbox" data-favorite-deck="${escapeHtml(d.id)}" ${favoriteSet.has(d.id) ? 'checked' : ''} />
            ${escapeHtml(name)}
          </label>
        </li>`;
      })
      .join('')}</ul>`;
    favoritesEl.querySelectorAll('[data-favorite-deck]').forEach((el) => {
      el.addEventListener('change', async () => {
        el.disabled = true;
        const deckId = el.dataset.favoriteDeck;
        if (el.checked) await addFavoriteDeck(playerName, deckId);
        else await removeFavoriteDeck(playerName, deckId);
        el.disabled = false;
      });
    });
  }

  loadFormats();
  loadKnownTokenTypes();
  loadTokenImages();
  loadSleeves();
  loadFavorites();

  container.addEventListener('view-shown', () => {
    nameInput.value = getSettings().playerName;
    if (!formatsLoaded) loadFormats();
    else applyMpDefaultsToForm();
    loadTokenImages();
    loadSleeves();
    loadFavorites();
  });
}

// Deck ids are server-generated UUIDs (no quotes/backslashes), so a minimal
// escape is enough for the attribute selector above.
function cssEscape(value) {
  return String(value).replace(/["\\]/g, '\\$&');
}
