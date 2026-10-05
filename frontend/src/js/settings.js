// Client preferences persist in cookies. API and WebSocket clients derive
// their backend address from the page origin (with development/deployment
// defaults below); an old server-address cookie no longer overrides it.

import { getCookie, setCookie } from './cookies.js';

const PLAYER_NAME_COOKIE = 'mtg_player_name';
const CLIENT_TOKEN_COOKIE = 'mtg_client_token';
//: The player's preferred per-priority auto-pass countdown, in seconds
//: (0 = off). On the board the countdown length is a *server* value
//: (`view.priority.timer_seconds`); this cookie is only the client-side
//: preference used where the client gets to pick — Solo vs. Bots passes it
//: to `POST /api/solo/start` as `spellTimerSeconds`. Cookie name kept from
//: the retired auto-pass feature for continuity.
const PASS_TIMER_SECONDS_COOKIE = 'mtg_auto_pass_seconds';
const BOT_SPEED_MS_COOKIE = 'mtg_bot_speed_ms';
const SHOW_OPPONENT_HAND_COOKIE = 'mtg_show_opponent_hand';
const COMPACT_VIEW_COOKIE = 'mtg_compact_view';
//: VIS-12: the player's standing priority stops (`{own: [...], opponent:
//: [...]}` step names), re-sent to the server once per game — the server
//: keeps them per game, this is only so they needn't be set again each time.
const PRIORITY_STOPS_COOKIE = 'mtg_priority_stops';
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

//: PLR-4: how long this browser's identity token stays valid without being
//: renewed — mirrors the backend's sliding `CLIENT_TOKEN_VALIDITY_SECONDS`
//: (config.py). Every time the Profil tab's "Speichern" mints/renews the
//: cookie, both clocks reset together.
const CLIENT_TOKEN_VALIDITY_DAYS = 90;

//: Per-priority auto-pass countdown (RULE 117): how long you get to decide
//: whether to respond before priority passes for you. The default matches
//: the backend's own (`config.MULTIPLAYER_SPELL_TIMER_SECONDS`), and 0
//: turns it off (pass by hand only).
export const DEFAULT_PASS_TIMER_SECONDS = 20;
//: Bounds — 0 is allowed (off); the ceiling matches the backend's
//: `MAX_SPELL_TIMER_SECONDS`.
export const MIN_PASS_TIMER_SECONDS = 0;
export const MAX_PASS_TIMER_SECONDS = 600;

//: VIS-7: how long the shared board waits between revealing consecutive
//: rail-stack ghosts synthesised from `move_log` entries that arrived in
//: the same view (almost always a bot's whole turn, batched by `run_bots`
//: before the broadcast — see gameBoardView.js's `applyView`). ``0``
//: reproduces the old "all at once" behaviour. Only three presets — this is
//: a pacing preference, not a value worth fine-tuning.
export const DEFAULT_BOT_SPEED_MS = 900;
export const BOT_SPEED_MS_OPTIONS = [0, 900, 2000];

//: setup/start.py's own --port default for the frontend static server.
//: Opened directly at this port (the --frontend-only dev path, no backend
//: proxy in front of it — see api/frontend_proxy.py), window.location.origin
//: would be the frontend's own origin, not the backend's, so that one case
//: keeps the old hardcoded guess instead.
const FRONTEND_DEV_PORT = 8765;

//: Same override convention as the rest of the frontend (see api.js) — set
//: window.MTG_API_BASE_URL before app.js loads (e.g. in index.html) to
//: change the deployment default. Absent that, default
//: to the page's own origin: the backend now reverse-proxies the frontend
//: (api/frontend_proxy.py), so browser and backend are always same-origin
//: through that path — local or over the LAN, whatever host/port the page
//: was actually loaded from. Falls back to the pre-proxy localhost:8000
//: guess only when loaded directly off the frontend's own dev port, where
//: window.location.origin would point at the frontend, not the backend.
const DEFAULT_SERVER_URL =
  window.MTG_API_BASE_URL ||
  (window.location.port === String(FRONTEND_DEV_PORT)
    ? 'http://localhost:8000'
    : window.location.origin);

function normalizeServerUrl(url) {
  const trimmed = (url || '').trim();
  if (!trimmed) return DEFAULT_SERVER_URL;
  return trimmed.replace(/\/+$/, '');
}

export function getServerUrl() {
  return normalizeServerUrl(DEFAULT_SERVER_URL);
}

export function getPlayerName() {
  return getCookie(PLAYER_NAME_COOKIE) || '';
}

/** This browser's PLR-4 identity token, or `''` if it has never saved one
 * (a fresh browser, or one that predates this feature) — read-only, use
 * `ensureClientToken()` to mint/renew it. */
export function getClientToken() {
  return getCookie(CLIENT_TOKEN_COOKIE) || '';
}

/**
 * Mint this browser's identity token if it doesn't have one yet, or renew
 * its validity window if it does; returns the token either way.
 *
 * Distinct from the player *name*: the name is what's shown at the table,
 * the token (a random UUID, never shown anywhere) is what lets the server
 * tell two browsers that happen to share a name apart instead of merging
 * them into one seat (`services/lobby.py`'s `client_token` — PLR-4). Called
 * from the Profil tab's "Speichern" button, same moment the name is saved,
 * so a player who has never touched Profil (and so never sends a token)
 * still gets the original name-only reconnect behaviour.
 */
export function ensureClientToken() {
  const token = getClientToken() || crypto.randomUUID();
  setCookie(CLIENT_TOKEN_COOKIE, token, CLIENT_TOKEN_VALIDITY_DAYS);
  return token;
}

/** The client-side preferred auto-pass countdown (seconds; 0 = off). */
export function getPassTimerSeconds() {
  const raw = getCookie(PASS_TIMER_SECONDS_COOKIE);
  if (raw === null || raw === undefined || raw === '') return DEFAULT_PASS_TIMER_SECONDS;
  const value = Number(raw);
  if (!Number.isFinite(value) || value < 0) return DEFAULT_PASS_TIMER_SECONDS;
  return Math.min(MAX_PASS_TIMER_SECONDS, Math.max(MIN_PASS_TIMER_SECONDS, Math.round(value)));
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

export function getCompactView() {
  return getCookie(COMPACT_VIEW_COOKIE) === '1';
}

/** VIS-7: the configured delay (ms) between staggered move-feed reveals. */
export function getBotSpeedMs() {
  const raw = getCookie(BOT_SPEED_MS_COOKIE);
  if (raw === null) return DEFAULT_BOT_SPEED_MS;
  const value = Number(raw);
  return BOT_SPEED_MS_OPTIONS.includes(value) ? value : DEFAULT_BOT_SPEED_MS;
}

/** VIS-12: the saved standing stops, or null when none were ever set. */
export function getStopsPref() {
  try {
    const parsed = JSON.parse(getCookie(PRIORITY_STOPS_COOKIE) || 'null');
    return Array.isArray(parsed?.own) && Array.isArray(parsed?.opponent)
      ? { own: parsed.own, opponent: parsed.opponent }
      : null;
  } catch {
    return null;
  }
}

export function setStopsPref(stops) {
  setCookie(PRIORITY_STOPS_COOKIE, JSON.stringify({ own: stops.own, opponent: stops.opponent }), COOKIE_MAX_AGE_DAYS);
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
    playerName: getPlayerName(),
    clientToken: getClientToken(),
    passTimerSeconds: getPassTimerSeconds(),
    showOpponentHand: getShowOpponentHand(),
    compactView: getCompactView(),
    botSpeedMs: getBotSpeedMs(),
    mpDefaultFormat: getMpDefaultFormat(),
    mpDefaultMulliganStyle: getMpDefaultMulliganStyle(),
    mpDefaultSeats: getMpDefaultSeats(),
    mpDefaultTakebacks: getMpDefaultTakebacks(),
    mpDefaultRandomizeSeating: getMpDefaultRandomizeSeating(),
    mpDefaultRandomStartingPlayer: getMpDefaultRandomStartingPlayer(),
  };
}

/**
 * @param {{playerName?: string,
 *          passTimerSeconds?: number, showOpponentHand?: boolean,
 *          compactView?: boolean,
 *          botSpeedMs?: number,
 *          mpDefaultFormat?: string, mpDefaultMulliganStyle?: string,
 *          mpDefaultSeats?: number, mpDefaultTakebacks?: number,
 *          mpDefaultRandomizeSeating?: boolean,
 *          mpDefaultRandomStartingPlayer?: boolean}} patch
 */
export function saveSettings(patch) {
  if (patch.playerName !== undefined) {
    setCookie(PLAYER_NAME_COOKIE, patch.playerName.trim(), COOKIE_MAX_AGE_DAYS);
  }
  if (patch.passTimerSeconds !== undefined) {
    const raw = Number(patch.passTimerSeconds);
    const seconds = Math.min(
      MAX_PASS_TIMER_SECONDS,
      Math.max(MIN_PASS_TIMER_SECONDS, Number.isFinite(raw) ? Math.round(raw) : DEFAULT_PASS_TIMER_SECONDS),
    );
    setCookie(PASS_TIMER_SECONDS_COOKIE, String(seconds), COOKIE_MAX_AGE_DAYS);
  }
  if (patch.showOpponentHand !== undefined) {
    setCookie(SHOW_OPPONENT_HAND_COOKIE, patch.showOpponentHand ? '1' : '0', COOKIE_MAX_AGE_DAYS);
  }
  if (patch.compactView !== undefined) {
    setCookie(COMPACT_VIEW_COOKIE, patch.compactView ? '1' : '0', COOKIE_MAX_AGE_DAYS);
  }
  if (patch.botSpeedMs !== undefined) {
    const speed = BOT_SPEED_MS_OPTIONS.includes(Number(patch.botSpeedMs))
      ? Number(patch.botSpeedMs)
      : DEFAULT_BOT_SPEED_MS;
    setCookie(BOT_SPEED_MS_COOKIE, String(speed), COOKIE_MAX_AGE_DAYS);
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
