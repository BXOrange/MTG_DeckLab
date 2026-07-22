// User-configurable connection settings (backend server address, player
// name), persisted in a cookie so they survive a reload without needing
// an account/backend of their own. api.js and gameSocket.js read the
// server address through getServerUrl() instead of a fixed constant, so
// changing it here (see connectionSettingsView.js) takes effect
// immediately for the next request/connection, no reload needed.

import { getCookie, setCookie } from './cookies.js';

const SERVER_URL_COOKIE = 'mtg_server_url';
const PLAYER_NAME_COOKIE = 'mtg_player_name';
const AUTO_PASS_COOKIE = 'mtg_auto_pass';
const AUTO_PASS_SECONDS_COOKIE = 'mtg_auto_pass_seconds';
const AUTO_PASS_SCOPE_COOKIE = 'mtg_auto_pass_scope';
const COOKIE_MAX_AGE_DAYS = 365;

//: Multiplayer auto-pass (RULE 117): how long you get to decide whether to
//: respond before priority passes for you. Three seconds is the default —
//: long enough to see that something happened and reach for a card, short
//: enough that a game where nobody ever responds doesn't crawl.
export const DEFAULT_AUTO_PASS_SECONDS = 3;
//: Bounds, so a typo can't make the timer useless in either direction.
export const MIN_AUTO_PASS_SECONDS = 1;
export const MAX_AUTO_PASS_SECONDS = 60;

//: Where auto-pass applies. ``opponent`` (the default) only runs the timer
//: in windows where you are *responding* — someone else's turn — and leaves
//: your own turn entirely under your control, which is what "auto-pass"
//: means in every Magic client. ``always`` also runs it on your own turn,
//: for players who want the game to move at a fixed pace throughout.
export const AUTO_PASS_SCOPES = ['opponent', 'always'];

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

/** Whether priority passes by itself after `getAutoPassSeconds()`. */
export function getAutoPassEnabled() {
  const raw = getCookie(AUTO_PASS_COOKIE);
  return raw === null || raw === undefined || raw === '' ? true : raw === '1';
}

export function getAutoPassSeconds() {
  const value = Number(getCookie(AUTO_PASS_SECONDS_COOKIE));
  if (!Number.isFinite(value) || value <= 0) return DEFAULT_AUTO_PASS_SECONDS;
  return Math.min(MAX_AUTO_PASS_SECONDS, Math.max(MIN_AUTO_PASS_SECONDS, Math.round(value)));
}

export function getAutoPassScope() {
  const raw = getCookie(AUTO_PASS_SCOPE_COOKIE);
  return AUTO_PASS_SCOPES.includes(raw) ? raw : 'opponent';
}

export function getSettings() {
  return {
    serverUrl: getServerUrl(),
    playerName: getPlayerName(),
    autoPass: getAutoPassEnabled(),
    autoPassSeconds: getAutoPassSeconds(),
    autoPassScope: getAutoPassScope(),
  };
}

/**
 * @param {{serverUrl?: string, playerName?: string, autoPass?: boolean,
 *          autoPassSeconds?: number, autoPassScope?: string}} patch
 */
export function saveSettings(patch) {
  if (patch.serverUrl !== undefined) {
    setCookie(SERVER_URL_COOKIE, normalizeServerUrl(patch.serverUrl), COOKIE_MAX_AGE_DAYS);
  }
  if (patch.playerName !== undefined) {
    setCookie(PLAYER_NAME_COOKIE, patch.playerName.trim(), COOKIE_MAX_AGE_DAYS);
  }
  if (patch.autoPass !== undefined) {
    setCookie(AUTO_PASS_COOKIE, patch.autoPass ? '1' : '0', COOKIE_MAX_AGE_DAYS);
  }
  if (patch.autoPassSeconds !== undefined) {
    const seconds = Math.min(
      MAX_AUTO_PASS_SECONDS,
      Math.max(MIN_AUTO_PASS_SECONDS, Math.round(Number(patch.autoPassSeconds) || DEFAULT_AUTO_PASS_SECONDS)),
    );
    setCookie(AUTO_PASS_SECONDS_COOKIE, String(seconds), COOKIE_MAX_AGE_DAYS);
  }
  if (patch.autoPassScope !== undefined && AUTO_PASS_SCOPES.includes(patch.autoPassScope)) {
    setCookie(AUTO_PASS_SCOPE_COOKIE, patch.autoPassScope, COOKIE_MAX_AGE_DAYS);
  }
  return getSettings();
}
