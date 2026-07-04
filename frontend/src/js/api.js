// Client for the backend's decklist and card-cache APIs (POST /api/decks,
// GET/POST /api/cards/*). Card lookups (mana cost, oracle text, images) go
// through the backend's CardDatabase/ImageCache now (see cardImages.js)
// instead of calling Scryfall directly from the browser — see
// docs/06_CARD_GRAPHICS_AND_LAZY_LOADING.md,
// docs/08_CARD_CACHE_EXPORT_IMPORT.md.
//
// The backend address is user-configurable at runtime (see settings.js,
// connectionSettingsView.js) rather than a fixed constant, so every call
// here resolves it fresh via getServerUrl() instead of reading it once at
// module load.

import { getServerUrl } from './settings.js';

/**
 * Whether the configured backend address is reachable (GET /api/health).
 * @returns {Promise<boolean>}
 */
export async function checkHealth() {
  try {
    const response = await fetch(`${getServerUrl()}/api/health`);
    if (!response.ok) return false;
    const body = await response.json();
    return body.status === 'ok';
  } catch {
    return false;
  }
}

/**
 * @param {{commanderText: string, mainboardText: string, sideboardText: string}} sections
 * @returns {Promise<{ok: true, deck: object} | {ok: false, error: string}>}
 */
export async function submitDeck(sections) {
  let response;
  try {
    response = await fetch(`${getServerUrl()}/api/decks`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(sections),
    });
  } catch {
    return { ok: false, error: 'Server nicht erreichbar – lokale Vorschau wird verwendet.' };
  }

  if (!response.ok) {
    return { ok: false, error: `Server-Fehler (${response.status}) – lokale Vorschau wird verwendet.` };
  }

  try {
    return { ok: true, deck: await response.json() };
  } catch {
    return { ok: false, error: 'Ungültige Server-Antwort – lokale Vorschau wird verwendet.' };
  }
}

/**
 * URL for a cached card image. The backend downloads and caches the
 * image on first request (GET /api/cards/{id}/image) — this just builds
 * the URL, it doesn't fetch anything itself; the <img> tag does that.
 * @param {string} cardId Scryfall id (Card.id from a resolved card).
 * @param {'small'|'normal'|'large'|'png'} size
 */
export function cardImageUrl(cardId, size = 'normal') {
  return `${getServerUrl()}/api/cards/${encodeURIComponent(cardId)}/image?size=${size}`;
}

/**
 * Resolve many card names in one round trip via the backend's lazy card
 * cache (checks its DB first, fetches only unknown names from Scryfall).
 * @param {string[]} names
 * @returns {Promise<{cards: Record<string, object>, notFound: string[]} | null>} null on network/server failure
 */
export async function resolveCards(names) {
  if (!names.length) return { cards: {}, notFound: [] };

  let response;
  try {
    response = await fetch(`${getServerUrl()}/api/cards/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ names }),
    });
  } catch {
    return null;
  }

  if (!response.ok) return null;

  try {
    return await response.json();
  } catch {
    return null;
  }
}

/**
 * Every card currently in the backend's local cache.
 * @returns {Promise<object[] | null>} null on network/server failure
 */
export async function listCachedCards() {
  let response;
  try {
    response = await fetch(`${getServerUrl()}/api/cards`);
  } catch {
    return null;
  }

  if (!response.ok) return null;

  try {
    return await response.json();
  } catch {
    return null;
  }
}

/**
 * Save a new deck, or update one already saved (pass its `id` back).
 * @param {{id?: string, name: string, commanderText: string, mainboardText: string, sideboardText: string}} deck
 * @returns {Promise<object | null>} the saved deck (with its id), or null on failure
 */
export async function saveDeck(deck) {
  let response;
  try {
    response = await fetch(`${getServerUrl()}/api/decks/save`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(deck),
    });
  } catch {
    return null;
  }

  if (!response.ok) return null;

  try {
    return await response.json();
  } catch {
    return null;
  }
}

/**
 * Every saved deck (name, text sections, timestamps — not full card data), newest first.
 * @returns {Promise<object[] | null>} null on network/server failure
 */
export async function listSavedDecks() {
  let response;
  try {
    response = await fetch(`${getServerUrl()}/api/decks`);
  } catch {
    return null;
  }

  if (!response.ok) return null;

  try {
    return await response.json();
  } catch {
    return null;
  }
}

/**
 * @param {string} deckId
 * @returns {Promise<object | null>} null if not found or on network/server failure
 */
export async function getSavedDeck(deckId) {
  let response;
  try {
    response = await fetch(`${getServerUrl()}/api/decks/${encodeURIComponent(deckId)}`);
  } catch {
    return null;
  }

  if (!response.ok) return null;

  try {
    return await response.json();
  } catch {
    return null;
  }
}

/**
 * Commander legality of a saved deck (GET /api/decks/{id}/validation).
 * @param {string} deckId
 * @returns {Promise<{isLegal: boolean, errors: string[], warnings: string[], bannedCardNames: string[], colorIdentityViolationNames: string[]} | null>} null on failure
 */
export async function getDeckValidation(deckId) {
  let response;
  try {
    response = await fetch(`${getServerUrl()}/api/decks/${encodeURIComponent(deckId)}/validation`);
  } catch {
    return null;
  }
  if (!response.ok) return null;
  try {
    return await response.json();
  } catch {
    return null;
  }
}

/**
 * @param {string} deckId
 * @returns {Promise<boolean>} whether the deck was actually deleted
 */
export async function deleteSavedDeck(deckId) {
  let response;
  try {
    response = await fetch(`${getServerUrl()}/api/decks/${encodeURIComponent(deckId)}`, {
      method: 'DELETE',
    });
  } catch {
    return false;
  }
  return response.ok;
}

// --- Game sessions (goldfish / multiplayer stub) --------------------------
// Backend: mtg_analyzer/api/game.py. Unlike the helpers above (which return
// the payload or null), these return {ok, status, data} so callers can tell
// a 404/422/501 apart from a network failure and surface the detail (e.g.
// the 422 notFound list, or the 501 multiplayer stub message).

async function gameRequest(method, path, body) {
  let response;
  try {
    response = await fetch(`${getServerUrl()}${path}`, {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    return { ok: false, status: 0, data: null };
  }
  let data = null;
  try {
    data = await response.json();
  } catch {
    /* empty/invalid body — leave data null */
  }
  return { ok: response.ok, status: response.status, data };
}

/**
 * Start a solo goldfish game from a decklist (UC3). Returns the initial
 * session view on success; on 422 the data carries a `detail.notFound`.
 * @param {{commanderText?: string, mainboardText?: string, deckId?: string, shuffle?: boolean, startingLife?: number, startingHand?: number}} payload
 */
export async function startGoldfish(payload) {
  return gameRequest('POST', '/api/game/goldfish', payload);
}

/** Apply one action (from the session's legal_actions) to a game. */
export async function sendGameAction(sessionId, action) {
  return gameRequest('POST', `/api/game/${encodeURIComponent(sessionId)}/action`, action);
}

/** Undo the last `steps` move(s) in a goldfish game. */
export async function rewindGame(sessionId, steps = 1) {
  return gameRequest('POST', `/api/game/${encodeURIComponent(sessionId)}/rewind`, { steps });
}

/** Reset a goldfish game to its opening state. */
export async function restartGame(sessionId) {
  return gameRequest('POST', `/api/game/${encodeURIComponent(sessionId)}/restart`, {});
}

/** Drop a game session on the server. */
export async function endGame(sessionId) {
  return gameRequest('DELETE', `/api/game/${encodeURIComponent(sessionId)}`);
}

/** Multiplayer is a backend stub (501) — used to show a "coming soon" note. */
export async function startMultiplayer() {
  return gameRequest('POST', '/api/game/multiplayer', {});
}
