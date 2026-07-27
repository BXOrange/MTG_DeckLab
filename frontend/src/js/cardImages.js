// Resolves card artwork via the backend's lazy card cache
// (POST /api/cards/resolve + GET /api/cards/{id}/image) instead of
// calling Scryfall directly from the browser. The backend downloads and
// caches both the card data and the image on first request, so repeat
// lookups (by anyone, not just this browser tab) are served locally —
// see docs/concepts/06_CARD_GRAPHICS_AND_LAZY_LOADING.md,
// docs/Reference/08_CARD_CACHE_EXPORT_IMPORT.md. This module still keeps its own
// per-session Map so a page that renders the same deck repeatedly
// doesn't even re-issue the /resolve call.

import { resolveCards, cardImageUrl } from './api.js';

// name.toLowerCase() -> {small, normal, backSmall, backNormal, card} | null
// (null = not found; backSmall/backNormal are null for a card with no back
// face). `card` is the full resolved card dict — kept alongside the image
// URLs so a detail view (deckImportView.js's "Detailansicht" toggle) can
// read mana cost/oracle text/etc. from the same resolve call, without a
// second round trip for data goldfishView.js doesn't need.
const cache = new Map();

/**
 * @param {string[]} names Card names to resolve (deck-import spelling).
 * @returns {Promise<Map<string, {small: string, normal: string, backSmall: (string|null), backNormal: (string|null), card: object}>>} keyed by lowercase name
 */
export async function resolveCardImages(names) {
  const uniqueNames = Array.from(new Set(names.map((n) => n.trim()).filter(Boolean)));
  const missing = uniqueNames.filter((n) => !cache.has(n.toLowerCase()));

  if (missing.length) {
    const result = await resolveCards(missing);
    if (result) {
      for (const [name, card] of Object.entries(result.cards)) {
        const entry = {
          small: cardImageUrl(card.id, 'small'),
          normal: cardImageUrl(card.id, 'normal'),
          backSmall: card.has_back_face ? cardImageUrl(card.id, 'small', 'back') : null,
          backNormal: card.has_back_face ? cardImageUrl(card.id, 'normal', 'back') : null,
          card,
        };
        cache.set(name.toLowerCase(), entry);
        // A transformed battlefield permanent's `name` (GameObject.to_dict)
        // is its *back* face's name, not the deck-list name this was
        // resolved by — index the same entry under the back name too, so
        // a board tile can still find it (and its front-face `small`/
        // `normal`) after the permanent flips. Same physical card either
        // way (RULE 712.2), just a second lookup key onto one entry.
        if (card.has_back_face && card.back_name) {
          cache.set(card.back_name.toLowerCase(), entry);
        }
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
 * Seed the cache directly with an already-known entry, bypassing a
 * `/resolve` round trip — for data that didn't come from `resolveCards`
 * (e.g. a deck's producible tokens, fetched via a separate endpoint) but
 * should still be findable by `getResolvedCard` (the hover-detail tooltip
 * reads only this cache, see cardHoverDetail.js).
 * @param {string} name
 * @param {{small: string, normal: string, card: object}} entry
 */
export function cacheResolvedCard(name, entry) {
  cache.set(name.trim().toLowerCase(), entry);
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

/**
 * Whether `resolveCardImages` has confirmed this exact name matches no
 * card (as opposed to not having been resolved yet, e.g. a request
 * still in flight) — `cache` stores `null` specifically for that
 * confirmed case, `undefined`/missing for "don't know yet".
 * @param {string} name
 * @returns {boolean}
 */
export function isConfirmedNotFound(name) {
  return cache.get(name.trim().toLowerCase()) === null;
}

/**
 * Resolve card art for `names` and preload every image into the browser's
 * own cache (a plain `new Image()` fetch, not just the URL lookup above),
 * so a view that renders these cards right after can show them
 * immediately instead of popping in one by one. Used by the goldfish
 * "loading" screen before a game starts (start = "everything is already
 * in memory").
 * @param {string[]} names
 * @param {(loaded: number, total: number) => void} [onProgress]
 * @returns {Promise<Map<string, {small: string, normal: string, card: object}>>}
 */
export async function preloadCardImages(names, onProgress) {
  const resolved = await resolveCardImages(names);
  // A DFC's back face (`backSmall`) is preloaded too — it's reachable
  // mid-game either by an actual transform or by the board's "show other
  // face" flip button, and either way should already be warm by then.
  const urls = Array.from(resolved.values())
    .flatMap((entry) => [entry.small, entry.backSmall])
    .filter(Boolean);
  const total = urls.length;
  let loaded = 0;
  onProgress?.(loaded, total);
  if (!total) return resolved;
  await Promise.all(
    urls.map(
      (url) =>
        new Promise((resolve) => {
          const img = new Image();
          img.onload = img.onerror = () => {
            loaded += 1;
            onProgress?.(loaded, total);
            resolve();
          };
          img.src = url;
        })
    )
  );
  return resolved;
}
