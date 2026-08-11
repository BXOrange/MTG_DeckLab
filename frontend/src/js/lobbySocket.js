// WebSocket client for the backend's /ws/lobby (mtg_analyzer/api/
// multiplayer_ws.py). One connection per browser tab, opened the first time
// the Multiplayer tab is visited and held for the rest of the session — it
// *is* the presence signal, so closing it removes the player from the lobby.
//
// It carries three kinds of push:
//   welcome              — the playerId (the handle every REST call uses),
//                          whether this was a reclaim, plus the lobby.
//   lobby_update         — a fresh snapshot whenever anything changes.
//   game_update          — one table's state plus *this client's own* view
//                          of it (their hand, not the opponent's — the
//                          redaction happens server-side, see
//                          services/game_session.py).
//   player_disconnected  — somebody's socket went away; their seat is held
//   player_reconnected     for a grace period and they can walk back into it.
//   disconnected         — *this* client is being dropped by the server, with
//                          a reason ("idle", "replaced", "timeout").
//
// Reconnects with backoff. The reclaim is by **player name** (the Profil
// tab): the server holds a disconnected player's seat for a grace period and
// hands it back to whoever comes back under that name, so a page reload
// doesn't cost you a game. Uses the same user-configurable backend address
// as api.js (settings.js), translated to a ws(s):// URL.

import { getServerUrl } from './settings.js';

const RECONNECT_DELAYS_MS = [1000, 2000, 5000, 10000];

// PLR-5: a periodic `ping` counts as liveness server-side (`api/
// multiplayer_ws.py`'s `_handle`), same as a real game action — well under
// the default 120s idle timeout, so a player who is genuinely still at the
// tab but just thinking a move over doesn't get disconnected (and
// immediately auto-reconnected) for it.
const PING_INTERVAL_MS = 30000;

function lobbySocketUrl(name, playerId, clientToken) {
  const url = new URL('/ws/lobby', getServerUrl());
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  url.searchParams.set('name', name || 'Spieler');
  if (playerId) url.searchParams.set('player_id', playerId);
  if (clientToken) url.searchParams.set('client_token', clientToken);
  return url.toString();
}

/**
 * Connect to the lobby and stay connected.
 * @param {{
 *   name: string,
 *   playerId?: string|null,
 *   clientToken?: string|null,
 *   onWelcome?: (playerId: string, lobby: object, reclaimed: boolean) => void,
 *   onLobby?: (lobby: object) => void,
 *   onGame?: (message: {game: object, view: object|null}) => void,
 *   onPeerPresence?: (playerId: string, connected: boolean, message: object) => void,
 *   onDropped?: (reason: string) => void,
 *   onStatus?: (connected: boolean, droppedReason: string|null) => void,
 * }} handlers
 */
export function connectLobbySocket(handlers = {}) {
  let playerId = handlers.playerId || null;
  const clientToken = handlers.clientToken || null;
  let socket = null;
  let attempt = 0;
  let closed = false;
  let pingTimer = null;
  //: Why the server last dropped us, if it told us ('idle'/'replaced'/…).
  let droppedReason = null;
  // Presence is re-sent on every (re)connect: the server only knows where a
  // client is because the client says so, and a reconnect starts it back at
  // the default "online".
  let presence = 'online';

  function open() {
    if (closed) return;
    socket = new WebSocket(lobbySocketUrl(handlers.name, playerId, clientToken));

    socket.addEventListener('open', () => {
      attempt = 0;
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
        handlers.onWelcome?.(message.player_id, message.lobby, message.reclaimed);
      } else if (message.type === 'lobby_update') {
        handlers.onLobby?.(message.lobby);
      } else if (message.type === 'game_update') {
        handlers.onGame?.(message);
      } else if (message.type === 'player_disconnected') {
        handlers.onPeerPresence?.(message.player_id, false, message);
      } else if (message.type === 'player_reconnected') {
        handlers.onPeerPresence?.(message.player_id, true, message);
      } else if (message.type === 'disconnected') {
        // The server is dropping *us* (idle, or another tab took the name
        // over). Remember why, so the reconnect below can explain itself
        // instead of the UI silently flickering.
        droppedReason = message.reason || 'closed';
        handlers.onDropped?.(droppedReason);
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
