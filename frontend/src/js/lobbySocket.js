// WebSocket client for the backend's /ws/lobby (mtg_analyzer/api/
// multiplayer_ws.py). One connection per browser tab, opened the first time
// the Multiplayer tab is visited and held for the rest of the session — it
// *is* the presence signal, so closing it removes the player from the lobby.
//
// It carries three kinds of push:
//   welcome              — the playerId (the handle every REST call names),
//                          the server-issued tabId, whether this was a reclaim,
//                          plus the lobby.
//   lobby_update         — a fresh snapshot whenever anything changes.
//   game_update          — one table's state plus *this client's own* view
//                          of it (their hand, not the opponent's — the
//                          redaction happens server-side, see
//                          services/game_session.py).
//   player_disconnected  — somebody's socket went away; their seat is held
//   player_reconnected     for a grace period and they can walk back into it.
//   disconnected         — *this* client is being dropped by the server, with
//                          a reason ("idle", "replaced", "timeout", ... or a
//                          final one such as "parallel_session").
//
// Identity is the signed-in account (PLR-9c): the session cookie authenticates the
// upgrade, the first frame (`auth`) carries this tab's server-issued tabId and the session
// CSRF proof -- no name, secret or client token. The server allows one socket per account;
// a second tab is closed with `parallel_session`, which (like the other final reasons
// below) is reported through `onBlocked` and never retried. Any other loss reconnects with
// backoff and walks back into the held seat. Uses the same user-configurable backend
// address as api.js (settings.js), translated to a ws(s):// URL.

import { getServerUrl } from './settings.js';
import { getPlayerIdentity, setPlayerIdentity } from './playerIdentity.js';
import { getAuth, refreshAuth } from './auth.js';

const RECONNECT_DELAYS_MS = [1000, 2000, 5000, 10000];

// PLR-5: a periodic `ping` counts as liveness server-side (`api/
// multiplayer_ws.py`'s `_handle`), same as a real game action — well under
// the default 120s idle timeout, so a player who is genuinely still at the
// tab but just thinking a move over doesn't get disconnected (and
// immediately auto-reconnected) for it.
const PING_INTERVAL_MS = 30000;

//: Close reasons after which the server will not take this tab back by itself:
//: retrying would only be refused again (a parallel session) or needs the person
//: to act first (sign in, reload).
const FINAL_REASONS = new Set([
  'parallel_session', 'unauthenticated', 'session_ended', 'auth_required', 'rate_limited',
]);
//: Reasons that mean the account session is gone: re-read the account so the UI shows the login.
const SESSION_REASONS = new Set(['unauthenticated', 'session_ended']);

function lobbySocketUrl() {
  const url = new URL('/ws/lobby', getServerUrl());
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  return url.toString();
}

/**
 * Connect to the lobby and stay connected.
 * @param {{
 *   onWelcome?: (playerId: string, lobby: object, reclaimed: boolean) => void,
 *   onLobby?: (lobby: object) => void,
 *   onGame?: (message: {game: object, view: object|null}) => void,
 *   onPeerPresence?: (playerId: string, connected: boolean, message: object) => void,
 *   onDropped?: (reason: string, serverMessage?: string) => void,
 *   onBlocked?: (reason: string, serverMessage?: string) => void,
 *   onStatus?: (connected: boolean, droppedReason: string|null) => void,
 * }} handlers
 */
export function connectLobbySocket(handlers = {}) {
  // A refreshed tab keeps its ids (sessionStorage); the account decides who we are.
  let playerId = getPlayerIdentity().playerId || null;
  let socket = null;
  let attempt = 0;
  let closed = false;
  let pingTimer = null;
  //: Why the server last dropped us, if it told us ('idle'/'replaced'/…).
  let droppedReason = null;
  //: Set when the server refused this tab for good (a FINAL_REASONS value): no reconnect.
  let blockedReason = null;
  // Presence is re-sent on every (re)connect: the server only knows where a
  // client is because the client says so, and a reconnect starts it back at
  // the default "online".
  let presence = 'online';

  function open() {
    if (closed) return;
    socket = new WebSocket(lobbySocketUrl());

    socket.addEventListener('open', () => {
      attempt = 0;
      // First frame: this tab's server-issued id (if it has one) and the session CSRF
      // proof. The server closes a socket that does not send it within a few seconds.
      const frame = { type: 'auth' };
      const tabId = getPlayerIdentity().tabId;
      if (tabId) frame.tab_id = tabId;
      const csrf = getAuth().csrf_token;
      if (csrf) frame.csrf_token = csrf;
      send(frame);
      handlers.onStatus?.(true, droppedReason);
      droppedReason = null;
      send({ type: 'presence', state: presence });
      // The server pushes our own game on connect, but ask anyway: this
      // path also runs after a *reconnect*, where the board we're holding
      // is however many moves stale.
      send({ type: 'subscribe_game' });
      clearInterval(pingTimer);
      pingTimer = setInterval(() => send({ type: 'ping' }), PING_INTERVAL_MS);
    });

    socket.addEventListener('close', () => {
      clearInterval(pingTimer);
      pingTimer = null;
      if (blockedReason) return; // already reported through onBlocked
      handlers.onStatus?.(false, droppedReason);
      if (closed) return;
      const delay = RECONNECT_DELAYS_MS[Math.min(attempt, RECONNECT_DELAYS_MS.length - 1)];
      attempt += 1;
      setTimeout(open, delay);
    });

    socket.addEventListener('message', (event) => {
      let message;
      try {
        message = JSON.parse(event.data);
      } catch {
        return; // Not JSON — ignore rather than throw from an event listener.
      }
      if (message.type === 'welcome') {
        playerId = message.player_id;
        setPlayerIdentity(message.player_id, message.tab_id);
        handlers.onWelcome?.(message.player_id, message.lobby, message.reclaimed);
      } else if (message.type === 'lobby_update') {
        handlers.onLobby?.(message.lobby);
      } else if (message.type === 'game_update') {
        handlers.onGame?.(message);
      } else if (message.type === 'player_disconnected') {
        handlers.onPeerPresence?.(message.player_id, false, message);
      } else if (message.type === 'player_reconnected') {
        handlers.onPeerPresence?.(message.player_id, true, message);
      } else if (message.type === 'liveness') {
        // Single-session lock (PLR-9c): a reconnecting tab asks whether we are still here.
        send({ type: 'alive' });
      } else if (message.type === 'disconnected') {
        // The server is dropping *us* (idle, a parallel session, a finished session).
        // Remember why, so the UI can explain itself instead of silently flickering.
        droppedReason = message.reason || 'closed';
        if (FINAL_REASONS.has(droppedReason)) {
          blockedReason = droppedReason;
          closed = true;
          clearInterval(pingTimer);
          pingTimer = null;
          if (SESSION_REASONS.has(droppedReason)) refreshAuth();
          handlers.onBlocked?.(droppedReason, message.message);
          return;
        }
        handlers.onDropped?.(droppedReason, message.message);
      }
    });
  }

  function send(message) {
    if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(message));
  }

  /** Tell the server where this client is: 'available' (in the lobby) or 'online'. */
  function setPresence(state) {
    presence = state;
    send({ type: 'presence', state });
  }

  /** Ask for a fresh push of the current game (e.g. after a reload). */
  function resubscribe() {
    send({ type: 'subscribe_game' });
  }

  function close() {
    closed = true;
    clearInterval(pingTimer);
    pingTimer = null;
    socket?.close();
  }

  open();
  return { setPresence, resubscribe, close, getPlayerId: () => playerId };
}
