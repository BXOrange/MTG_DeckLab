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
  getComboDatabaseStatus,
  updateCardPool,
  updateComboDatabase,
} from './api.js';
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
        <h3>${t('settings.data.heading')}</h3>
        <p class="hint">${t('settings.data.hint')}</p>
        <div class="import-actions">
          <button id="update-card-pool-btn" type="button">${t('settings.data.updateCards')}</button>
          <p class="server-status" id="update-card-pool-status" aria-live="polite"></p>
        </div>
        <div class="import-actions">
          <button id="update-combo-database-btn" type="button">${t('settings.data.updateCombos')}</button>
          <p class="server-status" id="update-combo-database-status" aria-live="polite"></p>
        </div>
      </div>

      <div class="deck-section">
        <label for="lang-select">${t('settings.language')}</label>
        <select id="lang-select">${langOptions}</select>
      </div>

      <div class="deck-section">
        <label for="theme-select">${t('settings.theme')}</label>
        <select id="theme-select">${themeOptions}</select>
        <p class="hint">${t('settings.themeHint')}</p>
      </div>

      <div class="deck-section">
        <h3>${t('settings.board.heading')}</h3>
        <p class="hint">${t('settings.board.hint')}</p>
        <label class="mp-inline-option">
          <input type="checkbox" id="show-opponent-hand" />
          ${t('settings.board.showOpponentHand')}
        </label>
        <label class="mp-inline-option">
          <input type="checkbox" id="compact-view" />
          ${t('settings.board.compactView')}
        </label>
      </div>
    </div>
  `;

  const statusEl = container.querySelector('#connection-settings-status');
  const urlInput = container.querySelector('#server-url-input');
  const saveBtn = container.querySelector('#save-settings-btn');
  const testBtn = container.querySelector('#test-connection-btn');
  const langSelect = container.querySelector('#lang-select');
  const themeSelect = container.querySelector('#theme-select');
  const showOpponentHand = container.querySelector('#show-opponent-hand');
  const compactView = container.querySelector('#compact-view');
  const updateCardsBtn = container.querySelector('#update-card-pool-btn');
  const updateCombosBtn = container.querySelector('#update-combo-database-btn');
  const updateCardsStatus = container.querySelector('#update-card-pool-status');
  const updateCombosStatus = container.querySelector('#update-combo-database-status');

  urlInput.value = getSettings().serverUrl;
  langSelect.value = getLang();
  themeSelect.value = getVisualTheme();
  showOpponentHand.checked = getSettings().showOpponentHand;
  compactView.checked = getSettings().compactView;

  function setUpdateStatus(element, state, message) {
    element.textContent = message;
    element.className = `server-status ${state}`;
  }

  async function runDataUpdate(button, status, operation, successMessage) {
    button.disabled = true;
    setUpdateStatus(status, 'pending', t('settings.data.updating'));
    try {
      const result = await operation();
      if (!result.ok) {
        setUpdateStatus(status, 'warning', t('settings.data.failed', { error: result.error }));
        return;
      }
      setUpdateStatus(status, 'ok', successMessage(result));
    } catch (error) {
      setUpdateStatus(
        status,
        'warning',
        t('settings.data.failed', {
          error: error instanceof Error ? error.message : String(error),
        })
      );
    } finally {
      button.disabled = false;
    }
  }

  updateCardsBtn.addEventListener('click', () =>
    runDataUpdate(
      updateCardsBtn,
      updateCardsStatus,
      updateCardPool,
      (result) => t('settings.data.cardsUpdated', { count: result.cachedCardCount })
    )
  );
  updateCombosBtn.addEventListener('click', () =>
    runDataUpdate(
      updateCombosBtn,
      updateCombosStatus,
      updateComboDatabase,
      (result) =>
        t('settings.data.combosUpdated', {
          count: result.summary.variantCount,
          added: result.summary.added,
          changed: result.summary.changed,
          removed: result.summary.removed,
        })
    )
  );
  getComboDatabaseStatus().then((status) => {
    if (updateCombosBtn.disabled) return;
    if (!status) {
      setUpdateStatus(updateCombosStatus, 'warning', t('settings.data.statusUnavailable'));
    } else if (!status.initialized) {
      setUpdateStatus(updateCombosStatus, 'pending', t('settings.data.notLoaded'));
    } else {
      setUpdateStatus(
        updateCombosStatus,
        'ok',
        t('settings.data.comboStatus', {
          count: status.variantCount,
          timestamp: status.sourceTimestamp || '—',
        })
      );
    }
  });

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

  showOpponentHand.addEventListener('change', () => {
    saveSettings({ showOpponentHand: showOpponentHand.checked });
  });
  compactView.addEventListener('change', () => {
    saveSettings({ compactView: compactView.checked });
    window.dispatchEvent(new Event('compact-view-changed'));
  });
}
