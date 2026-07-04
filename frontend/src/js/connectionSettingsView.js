// "Verbindung" tab: configure the player name and backend server
// address, persisted in a cookie (settings.js/cookies.js) so they
// survive a reload. Shows the same live connection status as the
// header indicator (connectionStatus.js) plus a manual re-check button.

import { getSettings, saveSettings } from './settings.js';
import {
  getConnectionStatus,
  subscribeConnectionStatus,
  refreshConnectionStatus,
} from './connectionStatus.js';

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
        <label for="player-name-input">Spielername</label>
        <input id="player-name-input" type="text" placeholder="z.B. Alex" />
      </div>

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
    </div>
  `;

  const statusEl = container.querySelector('#connection-settings-status');
  const nameInput = container.querySelector('#player-name-input');
  const urlInput = container.querySelector('#server-url-input');
  const saveBtn = container.querySelector('#save-settings-btn');
  const testBtn = container.querySelector('#test-connection-btn');

  const settings = getSettings();
  nameInput.value = settings.playerName;
  urlInput.value = settings.serverUrl;

  function renderStatus() {
    const status = getConnectionStatus();
    statusEl.textContent = STATUS_LABELS[status] ?? status;
    statusEl.className = `server-status ${status === 'connected' ? 'ok' : status === 'checking' ? 'pending' : 'warning'}`;
  }
  renderStatus();
  subscribeConnectionStatus(renderStatus);

  saveBtn.addEventListener('click', () => {
    const saved = saveSettings({ playerName: nameInput.value, serverUrl: urlInput.value });
    urlInput.value = saved.serverUrl; // reflect normalization (trimmed/no trailing slash)
    refreshConnectionStatus();
  });

  testBtn.addEventListener('click', () => {
    refreshConnectionStatus();
  });
}
