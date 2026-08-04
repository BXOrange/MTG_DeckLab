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
const AUTO_SKIP_EMPTY_COOKIE = 'mtg_auto_skip_empty';
const SHOW_OPPONENT_HAND_COOKIE = 'mtg_show_opponent_hand';
//: PLR-13 + "Player Settings" defaults for a *newly created* multiplayer
//: table (Profil tab) — applied once, right after `POST /api/multiplayer/games`
//: (see multiplayerView.js's createGame), not read by the engine itself.
const MP_DEFAULT_FORMAT_COOKIE = 'mtg_mp_default_format';
const MP_DEFAULT_MULLIGAN_COOKIE = 'mtg_mp_default_mulligan';
const MP_DEFAULT_SEATS_COOKIE = 'mtg_mp_default_seats';
const MP_DEFAULT_TAKEBACKS_COOKIE = 'mtg_mp_default_takebacks';
const MP_DEFAULT_RANDOM_SEATING_COOKIE = 'mtg_mp_default_random_seating';
const MP_DEFAULT_RANDOM_START_COOKIE = 'mtg_mp_default_random_start';
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

/** Pass instantly through priority windows offering nothing but "pass".
 *
 * The sibling of auto-pass rather than the same thing: auto-pass is a
 * countdown you can interrupt because there *was* something you could have
 * done, while this one only fires in windows where `legal_actions` holds
 * literally no other option — so there is nothing to interrupt, and it
 * runs on your own turn too. Off by default: it changes how the board
 * feels, and a player should ask for that.
 */
export function getAutoSkipEmpty() {
  return getCookie(AUTO_SKIP_EMPTY_COOKIE) === '1';
}

/** Whether an opponent's (face-down) hand is drawn card-by-card.
 *
 * RULE 400.2 means the cards themselves never reach this client — the
 * choice is only whether to draw N card backs or just say "N". Off by
 * default: the backs are a row of nothing, and they cost the board a lot
 * of vertical space on a two-player screen.
 */
export function getShowOpponentHand() {
  return getCookie(SHOW_OPPONENT_HAND_COOKIE) === '1';
}

//: Seats a newly created table opens with, absent a saved preference —
//: same default `multiplayerView.js`'s "Neues Spiel" form already used.
export const DEFAULT_MP_SEATS = 2;

export function getMpDefaultFormat() {
  return getCookie(MP_DEFAULT_FORMAT_COOKIE) || 'commander';
}

export function getMpDefaultMulliganStyle() {
  return getCookie(MP_DEFAULT_MULLIGAN_COOKIE) || 'london';
}

export function getMpDefaultSeats() {
  const value = Math.floor(Number(getCookie(MP_DEFAULT_SEATS_COOKIE)));
  return Number.isFinite(value) && value >= 2 && value <= 4 ? value : DEFAULT_MP_SEATS;
}

export function getMpDefaultTakebacks() {
  const value = Math.floor(Number(getCookie(MP_DEFAULT_TAKEBACKS_COOKIE)));
  return Number.isFinite(value) && value >= 0 ? Math.min(value, 20) : 0;
}

export function getMpDefaultRandomizeSeating() {
  return getCookie(MP_DEFAULT_RANDOM_SEATING_COOKIE) === '1';
}

export function getMpDefaultRandomStartingPlayer() {
  return getCookie(MP_DEFAULT_RANDOM_START_COOKIE) === '1';
}

export function getSettings() {
  return {
    serverUrl: getServerUrl(),
    playerName: getPlayerName(),
    autoPass: getAutoPassEnabled(),
    autoPassSeconds: getAutoPassSeconds(),
    autoPassScope: getAutoPassScope(),
    autoSkipEmpty: getAutoSkipEmpty(),
    showOpponentHand: getShowOpponentHand(),
    mpDefaultFormat: getMpDefaultFormat(),
    mpDefaultMulliganStyle: getMpDefaultMulliganStyle(),
    mpDefaultSeats: getMpDefaultSeats(),
    mpDefaultTakebacks: getMpDefaultTakebacks(),
    mpDefaultRandomizeSeating: getMpDefaultRandomizeSeating(),
    mpDefaultRandomStartingPlayer: getMpDefaultRandomStartingPlayer(),
  };
}

/**
 * @param {{serverUrl?: string, playerName?: string, autoPass?: boolean,
 *          autoPassSeconds?: number, autoPassScope?: string,
 *          autoSkipEmpty?: boolean, showOpponentHand?: boolean,
 *          mpDefaultFormat?: string, mpDefaultMulliganStyle?: string,
 *          mpDefaultSeats?: number, mpDefaultTakebacks?: number,
 *          mpDefaultRandomizeSeating?: boolean,
 *          mpDefaultRandomStartingPlayer?: boolean}} patch
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
  if (patch.autoSkipEmpty !== undefined) {
    setCookie(AUTO_SKIP_EMPTY_COOKIE, patch.autoSkipEmpty ? '1' : '0', COOKIE_MAX_AGE_DAYS);
  }
  if (patch.showOpponentHand !== undefined) {
    setCookie(SHOW_OPPONENT_HAND_COOKIE, patch.showOpponentHand ? '1' : '0', COOKIE_MAX_AGE_DAYS);
  }
  if (patch.mpDefaultFormat !== undefined) {
    setCookie(MP_DEFAULT_FORMAT_COOKIE, patch.mpDefaultFormat, COOKIE_MAX_AGE_DAYS);
  }
  if (patch.mpDefaultMulliganStyle !== undefined) {
    setCookie(MP_DEFAULT_MULLIGAN_COOKIE, patch.mpDefaultMulliganStyle, COOKIE_MAX_AGE_DAYS);
  }
  if (patch.mpDefaultSeats !== undefined) {
    const seats = Math.min(4, Math.max(2, Math.floor(Number(patch.mpDefaultSeats)) || DEFAULT_MP_SEATS));
    setCookie(MP_DEFAULT_SEATS_COOKIE, String(seats), COOKIE_MAX_AGE_DAYS);
  }
  if (patch.mpDefaultTakebacks !== undefined) {
    const takebacks = Math.min(20, Math.max(0, Math.floor(Number(patch.mpDefaultTakebacks)) || 0));
    setCookie(MP_DEFAULT_TAKEBACKS_COOKIE, String(takebacks), COOKIE_MAX_AGE_DAYS);
  }
  if (patch.mpDefaultRandomizeSeating !== undefined) {
    setCookie(MP_DEFAULT_RANDOM_SEATING_COOKIE, patch.mpDefaultRandomizeSeating ? '1' : '0', COOKIE_MAX_AGE_DAYS);
  }
  if (patch.mpDefaultRandomStartingPlayer !== undefined) {
    setCookie(MP_DEFAULT_RANDOM_START_COOKIE, patch.mpDefaultRandomStartingPlayer ? '1' : '0', COOKIE_MAX_AGE_DAYS);
  }
  return getSettings();
}
