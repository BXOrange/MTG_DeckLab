// Client for the backend's decklist API (POST /api/decks). This is the
// first backend integration (see frontend/TODO.md "Backend integration");
// card lookups (mana cost, oracle text, images) still go straight to
// Scryfall via cardImages.js since the backend has no card-search
// endpoint yet.
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
