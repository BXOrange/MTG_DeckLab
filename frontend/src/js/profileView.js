// "Profil" tab: everything player-facing, in six tabs (VIS-21, VIS-23), in this order:
//
//   Account-Login          login / signup / "Passwort vergessen" / account deletion
//                          (accountView.js). The only tab usable while logged out; the others
//                          are shown disabled with a login hint and follow the login state live.
//   Sessions/Einladungen   own sessions, logout-all, invitations (accountView.js)
//   Passwort ändern        password change with the strength meter (accountView.js)
//   Multiplayer-Einstellungen
//                          client-local defaults (cookie) applied to a table this player
//                          *hosts* -- multiplayerView.js's createGame() reads them right after
//                          POST /api/multiplayer/games and applies them via
//                          setMultiplayerOptions, the same host-only route the Setup screen's
//                          option rows already use.
//   Sleeves/Token-Bilder   server-side player assets (services/player_assets.py), owned by the
//                          signed-in account (PLR-16).
//   Lieblingsdecks         the favorite-deck checklist (own tab since VIS-23), same ownership.
//
// There is no free-text player name: the account name is the only one (VIS-21), and a seat
// without a login is "Player" (auth.js FALLBACK_PLAYER_NAME). The last selected tab is
// remembered per browser in a cookie (settings.js). The "Einstellungen" tab
// (connectionSettingsView.js) is only the server address.

import { getSettings, saveSettings } from './settings.js';
import { getAuth, subscribeAuth, isAuthReady, FALLBACK_PLAYER_NAME } from './auth.js';
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
import { escapeAttr } from './gameSetup.js';
import { t, tPlural } from './i18n.js';
import { renderAccountPanel, ACCOUNT_SECTIONS } from './accountView.js';

// UI-only sentinel (never sent to the backend as a token_name): selecting it
// reveals a free-text input, for a token that's neither in the curated
// catalogue nor meant to be the generic fallback.
const CUSTOM_TOKEN_VALUE = '__custom__';

function tokenNameLabel(tokenName) {
  return tokenName === GENERIC_TOKEN_KEY ? t('profile.tokens.generic') : tokenName;
}

//: The Profil tabs in display order (VIS-21). `loginOnly` tabs are disabled while logged out.
const PROFILE_TABS = Object.freeze([
  { id: 'account', labelKey: 'profile.tabs.account', loginOnly: false },
  { id: 'sessions', labelKey: 'profile.tabs.sessions', loginOnly: true },
  { id: 'password', labelKey: 'profile.tabs.password', loginOnly: true },
  { id: 'multiplayer', labelKey: 'profile.tabs.multiplayer', loginOnly: true },
  { id: 'assets', labelKey: 'profile.tabs.assets', loginOnly: true },
  { id: 'favorites', labelKey: 'profile.tabs.favorites', loginOnly: true },
]);
const DEFAULT_PROFILE_TAB = PROFILE_TABS[0].id;

export function renderProfileView(container) {
  container.innerHTML = `
    <div class="connection-settings-panel profile-view-panel">
      <h2>${t('profile.title')}</h2>

      <div class="account-tabs profile-tabs" role="tablist">
        ${PROFILE_TABS.map(
          (tab) =>
            `<button type="button" role="tab" class="account-tab profile-tab" id="profile-tab-${tab.id}" data-profile-tab="${tab.id}" aria-controls="profile-panel-${tab.id}">${t(tab.labelKey)}</button>`,
        ).join('')}
      </div>
      <p class="hint" id="profile-tabs-hint" hidden>${escapeHtml(t('profile.tabs.loginHint', { fallback: FALLBACK_PLAYER_NAME }))}</p>

      <div class="profile-panel" id="profile-panel-account" role="tabpanel" aria-labelledby="profile-tab-account">
        <div id="profile-account"></div>
      </div>
      <div class="profile-panel" id="profile-panel-sessions" role="tabpanel" aria-labelledby="profile-tab-sessions" hidden>
        <div id="profile-sessions"></div>
      </div>
      <div class="profile-panel" id="profile-panel-password" role="tabpanel" aria-labelledby="profile-tab-password" hidden>
        <div id="profile-password"></div>
      </div>

      <div class="profile-panel" id="profile-panel-multiplayer" role="tabpanel" aria-labelledby="profile-tab-multiplayer" hidden>
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

      </div>

      <div class="profile-panel" id="profile-panel-assets" role="tabpanel" aria-labelledby="profile-tab-assets" hidden>
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

      </div>

      <div class="profile-panel" id="profile-panel-favorites" role="tabpanel" aria-labelledby="profile-tab-favorites" hidden>
      <div class="deck-section">
        <h3>${t('profile.favorites.heading')}</h3>
        <p class="hint">${t('profile.favorites.hint')}</p>
        <div id="profile-favorite-decks"><p class="empty-state"><span class="spinner" aria-hidden="true"></span>${t('common.loading')}</p></div>
      </div>
      </div>
    </div>
  `;

  renderAccountPanel(container.querySelector('#profile-account'), { section: ACCOUNT_SECTIONS.LOGIN });
  renderAccountPanel(container.querySelector('#profile-sessions'), { section: ACCOUNT_SECTIONS.SESSIONS });
  renderAccountPanel(container.querySelector('#profile-password'), { section: ACCOUNT_SECTIONS.PASSWORD });
  const formatSelect = container.querySelector('#profile-mp-format');
  const seatsSelect = container.querySelector('#profile-mp-seats');
  const mulliganSelect = container.querySelector('#profile-mp-mulligan');
  const takebacksInput = container.querySelector('#profile-mp-takebacks');
  const randomSeatingInput = container.querySelector('#profile-mp-random-seating');
  const randomStartInput = container.querySelector('#profile-mp-random-start');
  const favoritesEl = container.querySelector('#profile-favorite-decks');

  const tokenImagesList = container.querySelector('#token-images-list');
  const tokenImageForm = container.querySelector('#token-image-form');
  const sleevesList = container.querySelector('#sleeves-list');
  const sleeveForm = container.querySelector('#sleeve-form');

  // --- Tabs ------------------------------------------------------------------

  const tabButtons = [...container.querySelectorAll('[data-profile-tab]')];
  const tabsHint = container.querySelector('#profile-tabs-hint');
  const isSignedInNow = () => Boolean(getAuth()?.authenticated);
  // The tab the viewer chose (or the remembered one); what is shown may differ while logged out.
  let wantedTab = DEFAULT_PROFILE_TAB;
  let activeTab = DEFAULT_PROFILE_TAB;

  function selectTab(id, { remember = true } = {}) {
    const tab = PROFILE_TABS.find((candidate) => candidate.id === id) || PROFILE_TABS[0];
    wantedTab = tab.id;
    // A login-only tab can never be shown without a login; fall back to Account-Login. The
    // wanted tab is kept, so it returns once a login (or the first auth answer) arrives.
    activeTab = tab.loginOnly && !isSignedInNow() ? DEFAULT_PROFILE_TAB : tab.id;
    for (const button of tabButtons) {
      const selected = button.dataset.profileTab === activeTab;
      button.classList.toggle('active', selected);
      button.setAttribute('aria-selected', String(selected));
      container.querySelector(`#profile-panel-${button.dataset.profileTab}`).hidden = !selected;
    }
    if (remember) saveSettings({ profileTab: activeTab });
  }

  // Disabled (visible, not selectable) while logged out; follows the login state live.
  function applyTabAvailability() {
    const signedIn = isSignedInNow();
    for (const tab of PROFILE_TABS) {
      const button = container.querySelector(`#profile-tab-${tab.id}`);
      button.disabled = tab.loginOnly && !signedIn;
      button.title = button.disabled ? t('profile.tabs.disabledTitle') : '';
    }
    tabsHint.hidden = signedIn || !isAuthReady();
    selectTab(wantedTab, { remember: false });
  }

  for (const button of tabButtons) {
    button.addEventListener('click', () => {
      if (!button.disabled) selectTab(button.dataset.profileTab);
    });
  }
  wantedTab = getSettings().profileTab;
  applyTabAvailability();

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

  // Assets belong to the signed-in account (PLR-16): the server resolves the owner from the
  // session, so these lists need a login, not a profile name.
  const isSignedIn = () => Boolean(getAuth()?.authenticated);
  const loginRequiredHtml = () => `<p class="empty-state">${escapeHtml(t('common.loginRequired'))}</p>`;

  async function loadTokenImages() {
    if (!isSignedIn()) {
      tokenImagesList.innerHTML = loginRequiredHtml();
      return;
    }
    const images = await listTokenImages();
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
        <img src="${escapeAttr(tokenImageUrl(img.token_name))}" alt="${escapeHtml(tokenNameLabel(img.token_name))}" loading="lazy" />
        <span>${escapeHtml(tokenNameLabel(img.token_name))}</span>
        <button type="button" class="delete-token-image-btn" data-token-name="${escapeHtml(img.token_name)}">${escapeHtml(t('common.delete'))}</button>
      </div>`
      )
      .join('');
    tokenImagesList.querySelectorAll('.delete-token-image-btn').forEach((btn) => {
      btn.addEventListener('click', async () => {
        btn.disabled = true;
        await deleteTokenImage(btn.dataset.tokenName);
        loadTokenImages();
      });
    });
  }

  async function loadSleeves() {
    if (!isSignedIn()) {
      sleevesList.innerHTML = loginRequiredHtml();
      return;
    }
    const sleeves = await listSleeves();
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
        <img src="${escapeAttr(sleeveImageUrl(s.sleeve_id))}" alt="${escapeHtml(s.label)}" loading="lazy" />
        <span>${escapeHtml(s.label)}</span>
        <button type="button" class="delete-sleeve-btn" data-sleeve-id="${escapeHtml(s.sleeve_id)}">${escapeHtml(t('common.delete'))}</button>
      </div>`
      )
      .join('');
    sleevesList.querySelectorAll('.delete-sleeve-btn').forEach((btn) => {
      btn.addEventListener('click', async () => {
        btn.disabled = true;
        await deleteSleeve(btn.dataset.sleeveId);
        loadSleeves();
      });
    });
  }

  tokenImageForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!isSignedIn()) {
      window.alert(t('common.loginRequired'));
      return;
    }
    const tokenNameSelect = container.querySelector('#token-image-name');
    const customNameInput = container.querySelector('#token-image-custom-name');
    const fileInput = container.querySelector('#token-image-file');
    const file = fileInput.files[0];
    const tokenName =
      tokenNameSelect.value === CUSTOM_TOKEN_VALUE ? customNameInput.value.trim() : tokenNameSelect.value;
    if (!tokenName || !file) return;
    const res = await uploadTokenImage(tokenName, file);
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
    if (!isSignedIn()) {
      window.alert(t('common.loginRequired'));
      return;
    }
    const labelInput = container.querySelector('#sleeve-label');
    const fileInput = container.querySelector('#sleeve-file');
    const file = fileInput.files[0];
    if (!labelInput.value.trim() || !file) return;
    const res = await uploadSleeve(labelInput.value.trim(), file);
    if (!res.ok) {
      window.alert(t('profile.tokens.uploadFailed', { status: res.status }));
      return;
    }
    sleeveForm.reset();
    loadSleeves();
  });

  // --- Favorite decks ------------------------------------------------------

  async function loadFavorites() {
    if (!isSignedIn()) {
      favoritesEl.innerHTML = loginRequiredHtml();
      return;
    }
    favoritesEl.innerHTML = `<p class="empty-state"><span class="spinner" aria-hidden="true"></span>${t('common.loading')}</p>`;
    const [decks, favoriteIds] = await Promise.all([listSavedDecks(), listFavoriteDecks()]);
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
        if (el.checked) await addFavoriteDeck(deckId);
        else await removeFavoriteDeck(deckId);
        el.disabled = false;
      });
    });
  }

  loadFormats();
  loadKnownTokenTypes();
  loadTokenImages();
  loadSleeves();
  loadFavorites();

  // A login/logout in the account panel changes whose assets these are.
  subscribeAuth(() => {
    applyTabAvailability();
    loadTokenImages();
    loadSleeves();
    loadFavorites();
  });

  container.addEventListener('view-shown', () => {
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
