// User-configurable connection settings (backend server address, player
// name), persisted in a cookie so they survive a reload without needing
// an account/backend of their own. api.js and gameSocket.js read the
// server address through getServerUrl() instead of a fixed constant, so
// changing it here (see connectionSettingsView.js) takes effect
// immediately for the next request/connection, no reload needed.

import { getCookie, setCookie } from './cookies.js';

const SERVER_URL_COOKIE = 'mtg_server_url';
const PLAYER_NAME_COOKIE = 'mtg_player_name';
const COOKIE_MAX_AGE_DAYS = 365;

//: Same default/override convention as the rest of the frontend (see
//: api.js) — set window.MTG_API_BASE_URL before app.js loads (e.g. in
//: index.html) to change the out-of-the-box default without a cookie.
const DEFAULT_SERVER_URL = window.MTG_API_BASE_URL || 'http://localhost:8000';

function normalizeServerUrl(url) {
  const trimmed = (url || '').trim();
  if (!trimmed) return DEFAULT_SERVER_URL;
  return trimmed.replace(/\/+$/, '');
}

export function getServerUrl() {
  return normalizeServerUrl(getCookie(SERVER_URL_COOKIE));
}

export function getPlayerName() {
  return getCookie(PLAYER_NAME_COOKIE) || '';
}

export function getSettings() {
  return { serverUrl: getServerUrl(), playerName: getPlayerName() };
}

/** @param {{serverUrl?: string, playerName?: string}} patch */
export function saveSettings(patch) {
  if (patch.serverUrl !== undefined) {
    setCookie(SERVER_URL_COOKIE, normalizeServerUrl(patch.serverUrl), COOKIE_MAX_AGE_DAYS);
  }
  if (patch.playerName !== undefined) {
    setCookie(PLAYER_NAME_COOKIE, patch.playerName.trim(), COOKIE_MAX_AGE_DAYS);
  }
  return getSettings();
}
