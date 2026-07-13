// WebSocket client for the backend's /ws/game/{game_id} — connection
// plumbing only (see docs/implementation-state/Done_Backend.md "HTTP API foundation",
// docs/concepts/04_SERVER_CLIENT_ARCHITECTURE.md PART 4 "WebSocket Messages").
//
// This relay predates the real engine: the server just echoes a sent
// player_action back to every connection on the same game_id as a
// game_state_update, without validating or executing anything. Solo play
// now goes through the REST game-session API instead (see goldfishView.js
// / api/game.py); this WebSocket is kept for the eventual multiplayer
// push channel (an opponent's moves), not yet wired into the UI.
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
