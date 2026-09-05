// "Einstellungen" tab: configure the backend server address, persisted
// in a cookie (settings.js/cookies.js) so it survives a reload. Shows the
// same live connection status as the header indicator (connectionStatus.js)
// plus a manual re-check button. This tab is now purely about *reaching the
// server* — everything player-facing (name, multiplayer preferences,
// uploaded token art / sleeves, favorite decks) lives on the "Profil" tab
// (profileView.js) — plus the UI language switch (i18n.js), which persists
// the choice in a cookie and reloads the page so the whole app is in one
// language.

import { getSettings, saveSettings } from './settings.js';
import {
  getConnectionStatus,
  subscribeConnectionStatus,
  refreshConnectionStatus,
} from './connectionStatus.js';
import { t, getLang, setLang, LANGUAGES } from './i18n.js';
import { getVisualTheme, setVisualTheme, VISUAL_THEMES } from './theme.js';

const STATUS_LABELS = {
  checking: 'settings.status.checking',
  connected: 'settings.status.connected',
  disconnected: 'settings.status.disconnected',
};

export function renderConnectionSettingsView(container) {
  const langOptions = LANGUAGES.map(
    (l) => `<option value="${l.code}">${l.label}</option>`,
  ).join('');
  const themeOptions = VISUAL_THEMES.map(
    (theme) => `<option value="${theme.code}">${t(theme.labelKey)}</option>`,
  ).join('');
  container.innerHTML = `
    <div class="connection-settings-panel">
      <h2>${t('settings.title')}</h2>
      <p class="server-status" id="connection-settings-status"></p>

      <div class="deck-section">
        <label for="server-url-input">${t('settings.serverAddress')}</label>
        <input id="server-url-input" type="text" placeholder="http://localhost:8000" />
      </div>

      <div class="import-actions">
        <button id="save-settings-btn" type="button" class="primary">${t('settings.saveButton')}</button>
        <button id="test-connection-btn" type="button">${t('settings.testConnection')}</button>
      </div>
      <p class="hint">${t('settings.hintChangesApply')}</p>
      <p class="hint">${t('settings.hintOtherSettings')}</p>

      <div class="deck-section">
        <label for="lang-select">${t('settings.language')}</label>
        <select id="lang-select">${langOptions}</select>
      </div>

      <div class="deck-section">
        <label for="theme-select">${t('settings.theme')}</label>
        <select id="theme-select">${themeOptions}</select>
        <p class="hint">${t('settings.themeHint')}</p>
      </div>
    </div>
  `;

  const statusEl = container.querySelector('#connection-settings-status');
  const urlInput = container.querySelector('#server-url-input');
  const saveBtn = container.querySelector('#save-settings-btn');
  const testBtn = container.querySelector('#test-connection-btn');
  const langSelect = container.querySelector('#lang-select');
  const themeSelect = container.querySelector('#theme-select');

  urlInput.value = getSettings().serverUrl;
  langSelect.value = getLang();
  themeSelect.value = getVisualTheme();

  function renderStatus() {
    const status = getConnectionStatus();
    statusEl.textContent = STATUS_LABELS[status] ? t(STATUS_LABELS[status]) : status;
    statusEl.className = `server-status ${status === 'connected' ? 'ok' : status === 'checking' ? 'pending' : 'warning'}`;
  }
  renderStatus();
  subscribeConnectionStatus(renderStatus);

  saveBtn.addEventListener('click', () => {
    const saved = saveSettings({ serverUrl: urlInput.value });
    urlInput.value = saved.serverUrl; // reflect normalization (trimmed/no trailing slash)
    refreshConnectionStatus();
  });

  testBtn.addEventListener('click', () => {
    refreshConnectionStatus();
  });

  // Language: not wired to "Speichern" (that is server-address only) — a
  // language change is a page-mode switch. Persist the cookie and reload so
  // every string / label map / toLocaleString resolves in one language.
  langSelect.addEventListener('change', () => {
    if (langSelect.value === getLang()) return;
    if (!window.confirm(t('settings.languageChangeConfirm'))) {
      langSelect.value = getLang();
      return;
    }
    setLang(langSelect.value);
    window.location.reload();
  });

  themeSelect.addEventListener('change', () => {
    themeSelect.value = setVisualTheme(themeSelect.value);
  });
}
