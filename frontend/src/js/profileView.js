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
import { t, tPlural } from './i18n.js';

// UI-only sentinel (never sent to the backend as a token_name): selecting it
// reveals a free-text input, for a token that's neither in the curated
// catalogue nor meant to be the generic fallback.
const CUSTOM_TOKEN_VALUE = '__custom__';

function tokenNameLabel(tokenName) {
  return tokenName === GENERIC_TOKEN_KEY ? t('profile.tokens.generic') : tokenName;
}

export function renderProfileView(container) {
  container.innerHTML = `
    <div class="connection-settings-panel">
      <h2>${t('profile.title')}</h2>

      <div class="deck-section">
        <label for="profile-name-input">${t('profile.playerName')}</label>
        <input id="profile-name-input" type="text" placeholder="${t('profile.playerNamePlaceholder')}" />
      </div>

      <div class="import-actions">
        <button id="save-profile-btn" type="button" class="primary">${t('common.save')}</button>
      </div>
      <p class="hint">${t('profile.nameHint')}</p>

      <div class="deck-section">
        <h3>${t('profile.mpDefaults.heading')}</h3>
        <p class="hint">${t('profile.mpDefaults.hint')}</p>
        <div class="mp-option-row">
          <label for="profile-mp-format">${t('profile.mpDefaults.format')}</label>
          <select id="profile-mp-format"><option>${t('common.loading')}</option></select>
        </div>
        <div class="mp-option-row">
          <label for="profile-mp-seats">${t('profile.mpDefaults.seats')}</label>
          <select id="profile-mp-seats">
            ${SEAT_COUNTS.map((n) => `<option value="${n}">${escapeHtml(tPlural('profile.mpDefaults.seatOption', n))}</option>`).join('')}
          </select>
        </div>
        <div class="mp-option-row">
          <label for="profile-mp-mulligan">${t('profile.mpDefaults.mulligan')}</label>
          <select id="profile-mp-mulligan">
            ${Object.entries(MULLIGAN_LABELS)
              .map(([value, label]) => `<option value="${value}">${escapeHtml(label)}</option>`)
              .join('')}
          </select>
        </div>
        <div class="mp-option-row">
          <label for="profile-mp-takebacks">${t('profile.mpDefaults.takebacks')}</label>
          <input id="profile-mp-takebacks" type="number" min="0" max="20" />
        </div>
        <div class="mp-option-row">
          <label>${t('profile.mpDefaults.randomize')}</label>
          <label class="mp-option-check">
            <input id="profile-mp-random-seating" type="checkbox" />
            ${t('profile.mpDefaults.randomSeating')}
          </label>
          <label class="mp-option-check">
            <input id="profile-mp-random-start" type="checkbox" />
            ${t('profile.mpDefaults.randomStart')}
          </label>
        </div>
      </div>

      <div class="deck-section">
        <h3>${t('profile.board.heading')}</h3>
        <p class="hint">${t('profile.board.hint')}</p>
        <label class="mp-inline-option">
          <input type="checkbox" id="show-opponent-hand" />
          ${t('profile.board.showOpponentHand')}
        </label>
      </div>

      <div class="deck-section player-assets-section">
        <h3>${t('profile.tokens.heading')}</h3>
        <p class="hint">${t('profile.tokens.hint')}</p>
        <div id="token-images-list" class="player-asset-grid"><p class="empty-state"><span class="spinner" aria-hidden="true"></span>${t('common.loading')}</p></div>
        <form id="token-image-form" class="player-asset-form">
          <select id="token-image-name" required><option value="">${t('profile.tokens.pickKind')}</option></select>
          <input type="text" id="token-image-custom-name" placeholder="${t('profile.tokens.customName')}" style="display: none" />
          <input type="file" id="token-image-file" accept="image/png,image/jpeg,image/webp,image/gif" required />
          <button type="submit" class="primary">${t('common.upload')}</button>
        </form>
      </div>

      <div class="deck-section player-assets-section">
        <h3>${t('profile.sleeves.heading')}</h3>
        <p class="hint">${t('profile.sleeves.hint')}</p>
        <div id="sleeves-list" class="player-asset-grid"><p class="empty-state"><span class="spinner" aria-hidden="true"></span>${t('common.loading')}</p></div>
        <form id="sleeve-form" class="player-asset-form">
          <input type="text" id="sleeve-label" placeholder="${t('profile.sleeves.labelPlaceholder')}" required />
          <input type="file" id="sleeve-file" accept="image/png,image/jpeg,image/webp,image/gif" required />
          <button type="submit" class="primary">${t('common.upload')}</button>
        </form>
      </div>

      <div class="deck-section">
        <h3>${t('profile.favorites.heading')}</h3>
        <p class="hint">${t('profile.favorites.hint')}</p>
        <div id="profile-favorite-decks"><p class="empty-state"><span class="spinner" aria-hidden="true"></span>${t('common.loading')}</p></div>
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

  // --- Board comfort toggles -----------------------------------------
  // (The per-priority countdown is a server setting now — always on, its
  // length set by the host per table / by `config.MULTIPLAYER_SPELL_TIMER`
  // — so there is no auto-pass checkbox here any more.)

  showOpponentHand.checked = getSettings().showOpponentHand;

  // Saved on change rather than behind the "Speichern" button: this only
  // affects this browser's own play.
  showOpponentHand.addEventListener('change', () => {
    saveSettings({ showOpponentHand: showOpponentHand.checked });
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
    const names = res.ok ? (res.data?.tokens || []).map((tok) => tok.name) : [];
    const uniqueNames = [...new Set(names)].sort((a, b) => a.localeCompare(b));
    select.innerHTML = [
      `<option value="${escapeHtml(GENERIC_TOKEN_KEY)}">${escapeHtml(t('profile.tokens.generic'))}</option>`,
      ...uniqueNames.map((n) => `<option value="${escapeHtml(n)}">${escapeHtml(n)}</option>`),
      `<option value="${CUSTOM_TOKEN_VALUE}">${escapeHtml(t('profile.tokens.customOption'))}</option>`,
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
      tokenImagesList.innerHTML = `<p class="empty-state">${t('common.saveNameFirst')}</p>`;
      return;
    }
    const images = await listTokenImages(name);
    if (images === null) {
      tokenImagesList.innerHTML = `<p class="server-status warning">${t('common.serverUnreachable')}</p>`;
      return;
    }
    if (!images.length) {
      tokenImagesList.innerHTML = `<p class="empty-state">${t('profile.tokens.none')}</p>`;
      return;
    }
    tokenImagesList.innerHTML = images
      .map(
        (img) => `
      <div class="player-asset-tile">
        <img src="${tokenImageUrl(name, img.token_name)}" alt="${escapeHtml(tokenNameLabel(img.token_name))}" loading="lazy" />
        <span>${escapeHtml(tokenNameLabel(img.token_name))}</span>
        <button type="button" class="delete-token-image-btn" data-token-name="${escapeHtml(img.token_name)}">${escapeHtml(t('common.delete'))}</button>
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
      sleevesList.innerHTML = `<p class="empty-state">${t('common.saveNameFirst')}</p>`;
      return;
    }
    const sleeves = await listSleeves(name);
    if (sleeves === null) {
      sleevesList.innerHTML = `<p class="server-status warning">${t('common.serverUnreachable')}</p>`;
      return;
    }
    if (!sleeves.length) {
      sleevesList.innerHTML = `<p class="empty-state">${t('profile.sleeves.none')}</p>`;
      return;
    }
    sleevesList.innerHTML = sleeves
      .map(
        (s) => `
      <div class="player-asset-tile">
        <img src="${sleeveImageUrl(name, s.sleeve_id)}" alt="${escapeHtml(s.label)}" loading="lazy" />
        <span>${escapeHtml(s.label)}</span>
        <button type="button" class="delete-sleeve-btn" data-sleeve-id="${escapeHtml(s.sleeve_id)}">${escapeHtml(t('common.delete'))}</button>
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
      window.alert(t('profile.alertSaveNameFirst'));
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
      window.alert(t('profile.tokens.uploadFailed', { status: res.status }));
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
      window.alert(t('profile.alertSaveNameFirst'));
      return;
    }
    const labelInput = container.querySelector('#sleeve-label');
    const fileInput = container.querySelector('#sleeve-file');
    const file = fileInput.files[0];
    if (!labelInput.value.trim() || !file) return;
    const res = await uploadSleeve(name, labelInput.value.trim(), file);
    if (!res.ok) {
      window.alert(t('profile.tokens.uploadFailed', { status: res.status }));
      return;
    }
    sleeveForm.reset();
    loadSleeves();
  });

  // --- Favorite decks ------------------------------------------------------

  async function loadFavorites() {
    const playerName = getSettings().playerName;
    if (!playerName) {
      favoritesEl.innerHTML = `<p class="empty-state">${t('common.saveNameFirst')}</p>`;
      return;
    }
    favoritesEl.innerHTML = `<p class="empty-state"><span class="spinner" aria-hidden="true"></span>${t('common.loading')}</p>`;
    const [decks, favoriteIds] = await Promise.all([listSavedDecks(), listFavoriteDecks(playerName)]);
    if (decks === null || favoriteIds === null) {
      favoritesEl.innerHTML = `<p class="server-status warning">${t('common.serverUnreachable')}</p>`;
      return;
    }
    if (!decks.length) {
      favoritesEl.innerHTML =
        `<p class="empty-state">${t('profile.favorites.noDecks')}</p>`;
      return;
    }
    const favoriteSet = new Set(favoriteIds);
    favoritesEl.innerHTML = `<ul class="profile-favorite-deck-list">${decks
      .map((d) => {
        const name = (d.name || '').trim() || t('common.unnamedDeck');
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
