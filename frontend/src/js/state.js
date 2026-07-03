// Minimal pub/sub store shared between the deck-import view and the
// game-board view. Kept intentionally tiny (no framework) — this is the
// seam where a later step can swap in real backend/WebSocket state.

let state = {
  deck: null, // result of parseDeckSections()
  board: null, // mock game-board state, see boardEngine.js
  imageCache: new Map(), // card name (lowercase) -> {small, normal}, see cardImages.js
};

const listeners = new Set();

export function getState() {
  return state;
}

export function setState(patch) {
  state = { ...state, ...patch };
  for (const listener of listeners) listener(state);
}

export function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
