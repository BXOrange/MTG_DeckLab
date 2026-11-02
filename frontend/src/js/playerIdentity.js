// BUG-39: the multiplayer identity of this browser tab -- the public lobby
// `playerId` plus the server-minted secret that proves it is really ours.
//
// The server hands the secret out only in the `/ws/lobby` welcome message
// (or `POST /api/multiplayer/connect`) and requires it on every multiplayer
// request (`X-Player-Secret` header, added in api.js) and for reclaiming a
// player by id. It is a credential, not a preference, so it deliberately
// does not go into a cookie (cookies are sent with every request and live
// for days): it lives in `sessionStorage`, which survives a page refresh of
// this tab (so the seat is reclaimed) but not a closed tab or another tab
// (which then falls back to the longer-lived client token, or joins as a
// new player).

const IDENTITY_KEY = 'mtg_mp_identity';

let memory = { playerId: null, secret: null };

function readStorage() {
  try {
    const raw = window.sessionStorage.getItem(IDENTITY_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    if (parsed && typeof parsed.playerId === 'string' && typeof parsed.secret === 'string') {
      return { playerId: parsed.playerId, secret: parsed.secret };
    }
  } catch {
    /* storage blocked or corrupt -- fall back to memory */
  }
  return null;
}

/** The identity this tab last received from the server, or nulls. */
export function getPlayerIdentity() {
  if (memory.secret) return memory;
  return readStorage() || memory;
}

/** Remember the identity the server just handed us. */
export function setPlayerIdentity(playerId, secret) {
  memory = { playerId: playerId || null, secret: secret || null };
  try {
    if (playerId && secret) {
      window.sessionStorage.setItem(IDENTITY_KEY, JSON.stringify(memory));
    } else {
      window.sessionStorage.removeItem(IDENTITY_KEY);
    }
  } catch {
    /* in-memory copy still works for this page load */
  }
}
