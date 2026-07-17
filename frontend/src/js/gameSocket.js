// WebSocket client for the backend's /ws/game/{game_id} (see
// docs/implementation-state/Done_Backend.md "HTTP API foundation",
// docs/concepts/04_SERVER_CLIENT_ARCHITECTURE.md PART 4 "WebSocket Messages").
//
// A sent player_action is run server-side through the GameSession
// registered under game_id (the same session a REST
// POST /api/game/goldfish|replay call started) and the resulting session
// view is broadcast to every connection on that game_id as a
// game_state_update (message.view); an illegal action or unknown game_id
// comes back as an error to the sender alone. Solo play still goes through
// the REST game-session API directly (see goldfishView.js / api/game.py);
// this socket is for the eventual interactive multiplayer session
// (pushing an opponent's moves) and isn't wired into any view yet.
//
// Uses the same user-configurable backend address as api.js (see
// settings.js), translated to a ws(s):// URL.

import { getServerUrl, getPlayerName } from './settings.js';

function gameSocketUrl(gameId) {
  const url = new URL(`/ws/game/${encodeURIComponent(gameId)}`, getServerUrl());
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  return url.toString();
}

/**
 * Open a WebSocket connection to /ws/game/{gameId}.
 * @param {string} gameId
 * @param {{
 *   onGameStateUpdate?: (message: object) => void,
 *   onError?: (message: object) => void,
 *   onOpen?: () => void,
 *   onClose?: (event: CloseEvent) => void,
 * }} [handlers]
 * @returns {{
 *   sendPlayerAction: (action: object, playerId?: string) => void,
 *   close: () => void,
 *   socket: WebSocket,
 * }}
 */
export function connectGameSocket(gameId, handlers = {}) {
  const socket = new WebSocket(gameSocketUrl(gameId));

  socket.addEventListener('open', () => handlers.onOpen?.());
  socket.addEventListener('close', (event) => handlers.onClose?.(event));
  socket.addEventListener('message', (event) => {
    let message;
    try {
      message = JSON.parse(event.data);
    } catch {
      return; // Not JSON — ignore rather than throw from an event listener.
    }
    if (message.type === 'game_state_update') {
      handlers.onGameStateUpdate?.(message);
    } else if (message.type === 'error') {
      handlers.onError?.(message);
    }
  });

  function sendPlayerAction(action, playerId = getPlayerName()) {
    if (socket.readyState !== WebSocket.OPEN) return;
    socket.send(
      JSON.stringify({ type: 'player_action', game_id: gameId, player_id: playerId, action })
    );
  }

  function close() {
    socket.close();
  }

  return { sendPlayerAction, close, socket };
}
