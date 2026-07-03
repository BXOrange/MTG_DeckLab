// Fetches card artwork from Scryfall's public API for display on the
// play area. Scryfall explicitly serves CORS headers for browser use
// (verified by hand: `access-control-allow-origin: *` on both
// /cards/named and /cards/collection), unlike Moxfield's API.
//
// Uses the /cards/collection batch endpoint (up to 75 identifiers per
// request — see https://scryfall.com/docs/api/cards/collection)
// instead of one request per card, and caches results for the session
// so repeated deck loads / re-renders don't refetch known cards.

const COLLECTION_ENDPOINT = 'https://api.scryfall.com/cards/collection';
const BATCH_SIZE = 75; // Scryfall's documented per-request limit
const BATCH_DELAY_MS = 100; // be polite between sequential batch requests

const cache = new Map(); // name.toLowerCase() -> {small, normal} | null (null = not found)

function pickImageUris(card) {
  // Double-faced/transform cards carry images per face instead of top-level.
  return card.image_uris || card.card_faces?.[0]?.image_uris || null;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function fetchBatch(names) {
  let response;
  try {
    response = await fetch(COLLECTION_ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ identifiers: names.map((name) => ({ name })) }),
    });
  } catch {
    // Offline / blocked — leave these names unresolved. Callers fall
    // back to a text-only card display.
    return;
  }

  if (!response.ok) return;

  let data;
  try {
    data = await response.json();
  } catch {
    return;
  }

  for (const card of data.data || []) {
    const uris = pickImageUris(card);
    cache.set(card.name.toLowerCase(), uris ? { small: uris.small, normal: uris.normal } : null);
  }
  for (const notFound of data.not_found || []) {
    if (notFound.name) cache.set(notFound.name.toLowerCase(), null);
  }
}

/**
 * @param {string[]} names Card names to resolve (deck-import spelling).
 * @returns {Promise<Map<string, {small: string, normal: string}>>} keyed by lowercase name
 */
export async function resolveCardImages(names) {
  const uniqueNames = Array.from(new Set(names.map((n) => n.trim()).filter(Boolean)));
  const missing = uniqueNames.filter((n) => !cache.has(n.toLowerCase()));

  for (let i = 0; i < missing.length; i += BATCH_SIZE) {
    if (i > 0) await sleep(BATCH_DELAY_MS);
    await fetchBatch(missing.slice(i, i + BATCH_SIZE));
  }

  const result = new Map();
  for (const name of uniqueNames) {
    const entry = cache.get(name.toLowerCase());
    if (entry) result.set(name.toLowerCase(), entry);
  }
  return result;
}
