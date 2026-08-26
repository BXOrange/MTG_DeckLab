// "Profil" tab: the player name, persisted in a cookie (settings.js), plus
// two player-scoped preferences that build on it:
//
//   Mehrspieler-Standardeinstellungen  client-local defaults (cookie, same
//     as auto-pass in Einstellungen) applied to a table this player *hosts*
//     — multiplayerView.js's createGame() reads them right after
//     POST /api/multiplayer/games and applies them via setMultiplayerOptions,
//     the same host-only route the Setup screen's option rows already use.
//   Lieblingsdecks  server-side (services/player_assets.py, keyed by this
//     player name, same storage as sleeves/token art), since two players
//     favoriting different decks out of one shared, unowned deck list can't
//     live as a flag on the Deck itself. Read by goldfishView.js and
//     multiplayerView.js's deck pickers to list favorites first.
//
// The player name is also the identity key player_assets.py stores
// uploaded token art / sleeves under (see connectionSettingsView.js), so
// this remains the one field the rest of the app treats as "who you are".

import { getSettings, saveSettings, ensureClientToken } from './settings.js';
import { fetchGameFormats, listSavedDecks, listFavoriteDecks, addFavoriteDeck, removeFavoriteDeck } from './api.js';
import { MULLIGAN_LABELS, SEAT_COUNTS } from './mulligan.js';
import { escapeHtml } from './cardTile.js';

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
        sieht ihn nicht. Eigene Token-Bilder und Karten-Sleeves (Tab "Einstellungen") sowie der
        Mehrspieler-Modus sind unter diesem Namen gespeichert. Beim Speichern erhält dieser
        Browser außerdem eine eigene, unsichtbare Kennung (90 Tage gültig, verlängert sich bei
        jedem Speichern) — so belegt ein zweiter Browser mit demselben Namen nicht denselben
        Platz am Tisch. Wird die Kennung 90 Tage lang nicht genutzt, gelten Name und hochgeladene
        Bilder/Sleeves als verwaist und werden vom Server gelöscht.
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

  nameInput.value = getSettings().playerName;

  saveBtn.addEventListener('click', () => {
    const saved = saveSettings({ playerName: nameInput.value });
    nameInput.value = saved.playerName;
    // PLR-4: mint/renew this browser's identity token alongside the name,
    // so a second browser saving the same name doesn't take this seat over.
    ensureClientToken();
    loadFavorites(); // the favorites list is keyed by the (now possibly new) name
  });

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
  loadFavorites();

  container.addEventListener('view-shown', () => {
    nameInput.value = getSettings().playerName;
    if (!formatsLoaded) loadFormats();
    else applyMpDefaultsToForm();
    loadFavorites();
  });
}

// Deck ids are server-generated UUIDs (no quotes/backslashes), so a minimal
// escape is enough for the attribute selector above.
function cssEscape(value) {
  return String(value).replace(/["\\]/g, '\\$&');
}
