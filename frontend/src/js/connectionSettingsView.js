// "Einstellungen" tab: configure the backend server address, persisted
// in a cookie (settings.js/cookies.js) so it survives a reload. Shows the
// same live connection status as the header indicator (connectionStatus.js)
// plus a manual re-check button. The player name itself lives on the
// "Profil" tab (profileView.js); the player-asset sections below still key
// off it via getSettings().playerName.

import { getSettings, saveSettings } from './settings.js';
import {
  getConnectionStatus,
  subscribeConnectionStatus,
  refreshConnectionStatus,
} from './connectionStatus.js';
import {
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
import { escapeHtml } from './cardTile.js';

const GENERIC_TOKEN_LABEL = 'Generisch (alle Token ohne eigenes Bild)';
// UI-only sentinel (never sent to the backend as a token_name): selecting it
// reveals a free-text input, for a token that's neither in the curated
// catalogue nor meant to be the generic fallback.
const CUSTOM_TOKEN_VALUE = '__custom__';

function tokenNameLabel(tokenName) {
  return tokenName === GENERIC_TOKEN_KEY ? GENERIC_TOKEN_LABEL : tokenName;
}

const STATUS_LABELS = {
  checking: 'Prüfe Verbindung …',
  connected: 'Verbunden',
  disconnected: 'Nicht erreichbar',
};

export function renderConnectionSettingsView(container) {
  container.innerHTML = `
    <div class="connection-settings-panel">
      <h2>Einstellungen</h2>
      <p class="server-status" id="connection-settings-status"></p>

      <div class="deck-section">
        <label for="server-url-input">Server-Adresse</label>
        <input id="server-url-input" type="text" placeholder="http://localhost:8000" />
      </div>

      <div class="import-actions">
        <button id="save-settings-btn" type="button" class="primary">Speichern</button>
        <button id="test-connection-btn" type="button">Verbindung testen</button>
      </div>
      <p class="hint">
        Änderungen gelten sofort für neue Anfragen und werden im Browser (Cookie) gespeichert —
        nicht serverseitig, ein anderer Browser/Rechner sieht sie nicht.
      </p>

      <div class="deck-section">
        <h3>Multiplayer: Auto-Pass</h3>
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
        <h3>Multiplayer: Spielfeld</h3>
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
        <div id="token-images-list" class="player-asset-grid"><p class="empty-state">Lädt …</p></div>
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
        <div id="sleeves-list" class="player-asset-grid"><p class="empty-state">Lädt …</p></div>
        <form id="sleeve-form" class="player-asset-form">
          <input type="text" id="sleeve-label" placeholder="Name (z. B. Blauer Drache)" required />
          <input type="file" id="sleeve-file" accept="image/png,image/jpeg,image/webp,image/gif" required />
          <button type="submit" class="primary">Hochladen</button>
        </form>
      </div>
    </div>
  `;

  const statusEl = container.querySelector('#connection-settings-status');
  const urlInput = container.querySelector('#server-url-input');
  const saveBtn = container.querySelector('#save-settings-btn');
  const testBtn = container.querySelector('#test-connection-btn');
  const tokenImagesList = container.querySelector('#token-images-list');
  const tokenImageForm = container.querySelector('#token-image-form');
  const sleevesList = container.querySelector('#sleeves-list');
  const sleeveForm = container.querySelector('#sleeve-form');

  const autoPassToggle = container.querySelector('#auto-pass-toggle');
  const autoPassSeconds = container.querySelector('#auto-pass-seconds');
  const autoPassScope = container.querySelector('#auto-pass-scope');
  const autoSkipEmpty = container.querySelector('#auto-skip-empty');
  const showOpponentHand = container.querySelector('#show-opponent-hand');

  const settings = getSettings();
  urlInput.value = settings.serverUrl;
  autoPassToggle.checked = settings.autoPass;
  autoPassSeconds.value = settings.autoPassSeconds;
  autoPassSeconds.disabled = !settings.autoPass;
  autoPassScope.value = settings.autoPassScope;
  autoSkipEmpty.checked = settings.autoSkipEmpty;
  showOpponentHand.checked = settings.showOpponentHand;

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

  function renderStatus() {
    const status = getConnectionStatus();
    statusEl.textContent = STATUS_LABELS[status] ?? status;
    statusEl.className = `server-status ${status === 'connected' ? 'ok' : status === 'checking' ? 'pending' : 'warning'}`;
  }
  renderStatus();
  subscribeConnectionStatus(renderStatus);

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

  loadKnownTokenTypes();
  loadTokenImages();
  loadSleeves();

  saveBtn.addEventListener('click', () => {
    const saved = saveSettings({ serverUrl: urlInput.value });
    urlInput.value = saved.serverUrl; // reflect normalization (trimmed/no trailing slash)
    refreshConnectionStatus();
  });

  testBtn.addEventListener('click', () => {
    refreshConnectionStatus();
  });

  // The player name is edited on the "Profil" tab, not here — refresh the
  // asset lists on every reveal in case it changed since this view last drew.
  container.addEventListener('view-shown', () => {
    loadTokenImages();
    loadSleeves();
  });
}
