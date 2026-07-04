// Resolves card artwork via the backend's lazy card cache
// (POST /api/cards/resolve + GET /api/cards/{id}/image) instead of
// calling Scryfall directly from the browser. The backend downloads and
// caches both the card data and the image on first request, so repeat
// lookups (by anyone, not just this browser tab) are served locally —
// see docs/06_CARD_GRAPHICS_AND_LAZY_LOADING.md,
// docs/08_CARD_CACHE_EXPORT_IMPORT.md. This module still keeps its own
// per-session Map so a page that renders the same deck repeatedly
// doesn't even re-issue the /resolve call.

import { resolveCards, cardImageUrl } from './api.js';

// name.toLowerCase() -> {small, normal, card} | null (null = not found).
// `card` is the full resolved card dict — kept alongside the image URLs
// so a detail view (deckImportView.js's "Detailansicht" toggle) can read
// mana cost/oracle text/etc. from the same resolve call, without a
// second round trip for data boardView.js doesn't need.
const cache = new Map();

/**
 * @param {string[]} names Card names to resolve (deck-import spelling).
 * @returns {Promise<Map<string, {small: string, normal: string, card: object}>>} keyed by lowercase name
 */
export async function resolveCardImages(names) {
  const uniqueNames = Array.from(new Set(names.map((n) => n.trim()).filter(Boolean)));
  const missing = uniqueNames.filter((n) => !cache.has(n.toLowerCase()));

  if (missing.length) {
    const result = await resolveCards(missing);
    if (result) {
      for (const [name, card] of Object.entries(result.cards)) {
        cache.set(name.toLowerCase(), {
          small: cardImageUrl(card.id, 'small'),
          normal: cardImageUrl(card.id, 'normal'),
          card,
        });
      }
      for (const name of result.notFound) {
        cache.set(name.toLowerCase(), null);
      }
    }
    // On a null result (server unreachable), leave `missing` names
    // unresolved rather than caching them as "not found" — a later call
    // (e.g. after the backend comes back) can still resolve them.
  }

  const resolved = new Map();
  for (const name of uniqueNames) {
    const entry = cache.get(name.toLowerCase());
    if (entry) resolved.set(name.toLowerCase(), entry);
  }
  return resolved;
}

/**
 * The full resolved card dict for a name, if `resolveCardImages` has
 * already fetched it this session — otherwise null (not yet resolved,
 * or resolved as "not found").
 * @param {string} name
 * @returns {object | null}
 */
export function getResolvedCard(name) {
  return cache.get(name.trim().toLowerCase())?.card ?? null;
}
