// "Einstellungen" tab: live backend connection status, manual connection
// test, data updates and optional server-wide LLM configuration.
// Everything player-facing (name, multiplayer preferences,
// uploaded token art / sleeves, favorite decks) lives on the "Profil" tab
// (profileView.js) — plus the UI language switch (i18n.js), which persists
// the choice in a cookie and reloads the page so the whole app is in one
// language.

import { getSettings, saveSettings } from './settings.js';
import {
  getComboDatabaseStatus,
  getLLMSettings,
  fetchLLMModels,
  saveLLMSettings,
  testLLMConnection,
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
    <div class="connection-settings-groups">
    <div class="connection-settings-panel">
      <h2>${t('settings.title')}</h2>
      <p class="server-status" id="connection-settings-status"></p>

      <div class="import-actions">
        <button id="test-connection-btn" type="button">${t('settings.testConnection')}</button>
      </div>
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
      <section class="connection-settings-panel llm-settings-panel" aria-labelledby="llm-settings-heading">
        <h2 id="llm-settings-heading">${t('settings.llm.heading')}</h2>
        <p class="hint">${t('settings.llm.hint')}</p>
        <label><input id="llm-enabled" type="checkbox" /> ${t('settings.llm.enabled')}</label>
        <label for="llm-provider">${t('settings.llm.provider')}</label>
        <select id="llm-provider"><option value="anthropic">Claude / Anthropic</option><option value="compatible">${t('settings.llm.compatible')}</option></select>
        <label for="llm-base-url">${t('settings.llm.endpoint')}</label>
        <input id="llm-base-url" type="url" placeholder="https://api.anthropic.com/v1" />
        <label for="llm-model">${t('settings.llm.model')}</label>
        <select id="llm-model"></select>
        <input id="llm-custom-model" type="text" hidden aria-label="${t('settings.llm.manualModel')}" />
        <button id="llm-reload-models" type="button">${t('settings.llm.reloadModels')}</button>
        <p id="llm-model-status" class="server-status" aria-live="polite"></p>
        <label for="llm-api-key">${t('settings.llm.key')}</label>
        <input id="llm-api-key" type="password" autocomplete="new-password" />
        <p class="hint" id="llm-key-status"></p>
        <label><input id="llm-clear-key" type="checkbox" /> ${t('settings.llm.clearKey')}</label>
        <label for="llm-calls">${t('settings.llm.calls')}</label>
        <input id="llm-calls" type="number" min="1" max="32" value="8" />
        <label for="llm-timeout">${t('settings.llm.timeout')}</label>
        <input id="llm-timeout" type="number" min="1" max="30" value="15" />
        <div class="import-actions">
          <button id="llm-save" type="button" disabled>${t('settings.llm.save')}</button>
          <button id="llm-test" type="button" disabled>${t('settings.llm.test')}</button>
        </div>
        <p id="llm-status" class="server-status" aria-live="polite"></p>
      </section>
    </div>
  `;

  const statusEl = container.querySelector('#connection-settings-status');
  const testBtn = container.querySelector('#test-connection-btn');
  const langSelect = container.querySelector('#lang-select');
  const themeSelect = container.querySelector('#theme-select');
  const showOpponentHand = container.querySelector('#show-opponent-hand');
  const compactView = container.querySelector('#compact-view');
  const updateCardsBtn = container.querySelector('#update-card-pool-btn');
  const updateCombosBtn = container.querySelector('#update-combo-database-btn');
  const updateCardsStatus = container.querySelector('#update-card-pool-status');
  const updateCombosStatus = container.querySelector('#update-combo-database-status');

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

  const llm = (id) => container.querySelector(`#llm-${id}`);
  const CUSTOM_MODEL = '__manual_model__';
  let modelRequest = 0;
  let modelTimer = null;
  function chosenModel() {
    return llm('model').value === CUSTOM_MODEL ? llm('custom-model').value.trim() : llm('model').value;
  }
  function showModels(models, selected = chosenModel(), preserveManual = false) {
    const manual = preserveManual && llm('model').value === CUSTOM_MODEL;
    const options = [new Option(t('settings.llm.selectModel'), '')];
    const available = models.map((m) => new Option(m.name === m.id ? m.id : `${m.name} (${m.id})`, m.id));
    if (selected && !models.some((m) => m.id === selected)) available.unshift(new Option(selected, selected));
    options.push(...available, new Option(t('settings.llm.manualModel'), CUSTOM_MODEL));
    llm('model').replaceChildren(...options);
    llm('model').value = manual ? CUSTOM_MODEL : selected || '';
    llm('custom-model').hidden = !manual;
  }
  async function loadModels() {
    clearTimeout(modelTimer);
    const request = ++modelRequest;
    llm('reload-models').disabled = true;
    setUpdateStatus(llm('model-status'), 'pending', t('settings.llm.loadingModels'));
    const result = await fetchLLMModels({
      provider: llm('provider').value, base_url: llm('base-url').value,
      api_key: llm('api-key').value, clear_api_key: llm('clear-key').checked,
    });
    if (request !== modelRequest) return;
    llm('reload-models').disabled = false;
    if (result.ok) {
      showModels(result.data.models, chosenModel(), true);
      setUpdateStatus(llm('model-status'), result.data.models.length ? 'ok' : 'warning',
        result.data.models.length ? t('settings.llm.modelsLoaded', { count: result.data.models.length }) : t('settings.llm.noModels'));
    } else {
      setUpdateStatus(llm('model-status'), 'warning', t('settings.llm.modelsFailed', { error: llmError(result) }));
    }
  }
  function scheduleModels(clearSelection = false) {
    ++modelRequest; // invalidate a response from the previous endpoint/key immediately
    clearTimeout(modelTimer);
    if (clearSelection) showModels([], '');
    modelTimer = setTimeout(loadModels, 200);
  }
  showModels([], '');
  llm('model').addEventListener('change', () => {
    llm('custom-model').hidden = llm('model').value !== CUSTOM_MODEL;
    if (!llm('custom-model').hidden) llm('custom-model').focus();
  });
  llm('reload-models').addEventListener('click', loadModels);
  llm('base-url').addEventListener('change', () => scheduleModels(true));
  llm('api-key').addEventListener('change', () => scheduleModels());
  llm('clear-key').addEventListener('change', () => scheduleModels());
  function fillLLM(data) {
    llm('enabled').checked = data.enabled;
    llm('provider').value = data.provider;
    llm('base-url').value = data.base_url;
    showModels([], data.model);
    llm('calls').value = data.bot_calls_per_turn;
    llm('timeout').value = data.timeout_seconds;
    llm('api-key').value = '';
    llm('clear-key').checked = false;
    llm('key-status').textContent = t(data.api_key_configured ? 'settings.llm.keySet' : 'settings.llm.keyMissing');
    llm('save').disabled = false;
    llm('test').disabled = !data.ready;
    scheduleModels();
  }
  function llmError(result) {
    return typeof result.data?.detail === 'string' ? result.data.detail : t('common.serverUnreachable');
  }
  async function loadLLMSettings() {
    llm('save').disabled = true;
    llm('test').disabled = true;
    const result = await getLLMSettings();
    if (result.ok) fillLLM(result.data);
    else setUpdateStatus(llm('status'), 'warning', t('settings.llm.failed', { error: llmError(result) }));
  }
  loadLLMSettings();
  llm('provider').addEventListener('change', () => {
    llm('base-url').value = llm('provider').value === 'anthropic'
      ? 'https://api.anthropic.com/v1'
      : 'https://api.openai.com/v1';
    scheduleModels(true);
  });
  llm('save').addEventListener('click', async () => {
    llm('save').disabled = true;
    const result = await saveLLMSettings({
      enabled: llm('enabled').checked, provider: llm('provider').value,
      base_url: llm('base-url').value, model: chosenModel(),
      api_key: llm('api-key').value, clear_api_key: llm('clear-key').checked,
      bot_calls_per_turn: Number(llm('calls').value), timeout_seconds: Number(llm('timeout').value),
    });
    llm('save').disabled = false;
    if (result.ok) {
      fillLLM(result.data);
      setUpdateStatus(llm('status'), 'ok', t('settings.llm.saved'));
    } else setUpdateStatus(llm('status'), 'warning', t('settings.llm.failed', { error: llmError(result) }));
  });
  llm('test').addEventListener('click', async () => {
    llm('test').disabled = true;
    setUpdateStatus(llm('status'), 'pending', t('settings.llm.working'));
    const result = await testLLMConnection();
    llm('test').disabled = false;
    setUpdateStatus(llm('status'), result.ok ? 'ok' : 'warning', result.ok ? t('settings.llm.connected') : t('settings.llm.failed', { error: llmError(result) }));
  });

  function renderStatus() {
    const status = getConnectionStatus();
    statusEl.textContent = STATUS_LABELS[status] ? t(STATUS_LABELS[status]) : status;
    statusEl.className = `server-status ${status === 'connected' ? 'ok' : status === 'checking' ? 'pending' : 'warning'}`;
  }
  renderStatus();
  subscribeConnectionStatus(renderStatus);

  testBtn.addEventListener('click', () => {
    refreshConnectionStatus();
  });

  // Language changes apply immediately as a page-mode switch. Persist the cookie and reload so
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
