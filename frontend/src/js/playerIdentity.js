// The multiplayer identity of this browser tab (PLR-9c): the public lobby `playerId` and the
// server-issued `tabId` of the single-session lock.
//
// Neither is a credential. Who you are is the signed-in account (session cookie); the lobby
// player id is public (every snapshot lists it) and the tab id only lets *this* tab reconnect
// over its own dead socket -- a copied or guessed one never evicts a live tab
// (`api/multiplayer_ws.py`). Both live in `sessionStorage`, which survives a refresh of this
// tab but is empty in a new tab or after a browser restart (the plan documents that: the old
// socket then blocks until its keep-alive window passes).

const IDENTITY_KEY = 'mtg_mp_identity';

let memory = { playerId: null, tabId: null };

function readStorage() {
  try {
    const raw = window.sessionStorage.getItem(IDENTITY_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    if (parsed && typeof parsed.playerId === 'string') {
      return { playerId: parsed.playerId, tabId: typeof parsed.tabId === 'string' ? parsed.tabId : null };
    }
  } catch {
    /* storage blocked or corrupt -- fall back to memory */
  }
  return null;
}

/** The identity this tab last received from the server, or nulls. */
export function getPlayerIdentity() {
  if (memory.playerId) return memory;
  return readStorage() || memory;
}

/** Remember the identity the server just handed us (call with no arguments to forget it). */
export function setPlayerIdentity(playerId, tabId) {
  memory = { playerId: playerId || null, tabId: tabId || null };
  try {
    if (playerId) {
      window.sessionStorage.setItem(IDENTITY_KEY, JSON.stringify(memory));
    } else {
      window.sessionStorage.removeItem(IDENTITY_KEY);
    }
  } catch {
    /* in-memory copy still works for this page load */
  }
}
