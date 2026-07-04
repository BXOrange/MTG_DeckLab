// Client for the backend's decklist and card-cache APIs (POST /api/decks,
// GET/POST /api/cards/*). Card lookups (mana cost, oracle text, images) go
// through the backend's CardDatabase/ImageCache now (see cardImages.js)
// instead of calling Scryfall directly from the browser — see
// docs/06_CARD_GRAPHICS_AND_LAZY_LOADING.md,
// docs/08_CARD_CACHE_EXPORT_IMPORT.md.
//
// Assumes the default local dev setup from ../../setup/start.py (backend
// on :8000). Override by setting `window.MTG_API_BASE_URL` before this
// module loads, e.g. in index.html, if the backend runs elsewhere.

const API_BASE_URL = window.MTG_API_BASE_URL || 'http://localhost:8000';

/**
 * @param {{commanderText: string, mainboardText: string, sideboardText: string}} sections
 * @returns {Promise<{ok: true, deck: object} | {ok: false, error: string}>}
 */
export async function submitDeck(sections) {
  let response;
  try {
    response = await fetch(`${API_BASE_URL}/api/decks`, {
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
  return `${API_BASE_URL}/api/cards/${encodeURIComponent(cardId)}/image?size=${size}`;
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
    response = await fetch(`${API_BASE_URL}/api/cards/resolve`, {
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
    response = await fetch(`${API_BASE_URL}/api/cards`);
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
    response = await fetch(`${API_BASE_URL}/api/decks/save`, {
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
    response = await fetch(`${API_BASE_URL}/api/decks`);
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
    response = await fetch(`${API_BASE_URL}/api/decks/${encodeURIComponent(deckId)}`);
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
    response = await fetch(`${API_BASE_URL}/api/decks/${encodeURIComponent(deckId)}`, {
      method: 'DELETE',
    });
  } catch {
    return false;
  }
  return response.ok;
}
