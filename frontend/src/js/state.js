// Minimal pub/sub store for the deck-import view (parsed deck + resolved
// card images). The goldfish board is server-driven (see goldfishView.js)
// and keeps its own state, so it doesn't live here.

let state = {
  deck: null, // result of parseDeckSections()
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
