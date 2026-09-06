// Shared "is the configured backend reachable" status, polled
// periodically via GET /api/health (api.js's checkHealth) so any number
// of views (header indicator, connection settings tab) can display it
// without each running their own poll. Minimal pub/sub, same pattern as
// state.js.

import { checkHealth } from './api.js';
import { t } from './i18n.js';

const POLL_INTERVAL_MS = 5000;

/** @typedef {'checking' | 'connected' | 'disconnected'} ConnectionStatus */

/** @type {ConnectionStatus} */
let status = 'checking';
const listeners = new Set();

function setStatus(next) {
  if (status === next) return;
  status = next;
  for (const listener of listeners) listener(status);
}

/** @returns {ConnectionStatus} */
export function getConnectionStatus() {
  return status;
}

/** @param {(status: ConnectionStatus) => void} listener */
export function subscribeConnectionStatus(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Re-check now (e.g. right after the server address setting changes). */
export async function refreshConnectionStatus() {
  setStatus('checking');
  const ok = await checkHealth();
  setStatus(ok ? 'connected' : 'disconnected');
  return ok;
}

refreshConnectionStatus();
setInterval(refreshConnectionStatus, POLL_INTERVAL_MS);

/**
 * Render a compact "dot + label" connection indicator into `container`,
 * kept in sync with the shared status for as long as the page lives.
 */
export function renderConnectionIndicator(container) {
  function render() {
    const current = getConnectionStatus();
    container.innerHTML = `
      <span class="connection-indicator ${current}" title="${t('header.connectionTitle')}">
        <span class="connection-dot"></span>
        ${t(`connection.${current}`)}
      </span>
    `;
  }
  render();
  subscribeConnectionStatus(render);
}
