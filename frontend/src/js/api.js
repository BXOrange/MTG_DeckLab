// Client for the backend's decklist and card-cache APIs (POST /api/decks,
// GET/POST /api/cards/*). Card lookups (mana cost, oracle text, images) go
// through the backend's CardDatabase/ImageCache now (see cardImages.js)
// instead of calling Scryfall directly from the browser — see
// docs/concepts/06_CARD_GRAPHICS_AND_LAZY_LOADING.md,
// docs/Reference/08_CARD_CACHE_EXPORT_IMPORT.md.
//
// Requests use the page's backend origin through getServerUrl(), with
// explicit development/deployment defaults defined in settings.js.

import { getServerUrl } from './settings.js';
import { t } from './i18n.js';

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
 * @param {boolean} [isCube] Skip Commander structural/legality checks (a card
 *   pool, not a real deck) — see `models/deck.py`'s `is_cube`.
 * @returns {Promise<{ok: true, deck: object} | {ok: false, error: string}>}
 */
export async function submitDeck(sections, isCube = false) {
  let response;
  try {
    response = await fetch(`${getServerUrl()}/api/decks`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...sections, isCube }),
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
    return { ok: false, error: t('api.invalidResponsePreview') };
  }
}

/**
 * Server-side Archidekt import proxy (GET /api/import/archidekt/{deckId}).
 * Unlike Moxfield (tried and reverted twice — genuinely Cloudflare-
 * blocked, see docs/implementation-state/Done_Backend.md "Import — follow-up from the
 * frontend"), Archidekt's API has no such protection.
 * @param {string} deckIdOrUrl Bare Archidekt deck id, or a full
 *   archidekt.com/decks/{id}/{slug} URL pasted from the browser — the
 *   backend extracts the id either way.
 * @returns {Promise<{ok: true, name: string, commanderText: string, mainboardText: string, sideboardText: string} | {ok: false, error: string}>}
 */
export async function importArchidektDeck(deckIdOrUrl) {
  let response;
  try {
    response = await fetch(`${getServerUrl()}/api/import/archidekt/${encodeURIComponent(deckIdOrUrl)}`);
  } catch {
    return { ok: false, error: 'Server nicht erreichbar.' };
  }

  if (!response.ok) {
    let detail = `Archidekt-Import fehlgeschlagen (HTTP ${response.status}).`;
    try {
      const body = await response.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* non-JSON error body — keep the generic message */
    }
    return { ok: false, error: detail };
  }

  try {
    return { ok: true, ...(await response.json()) };
  } catch {
    return { ok: false, error: t('api.invalidResponse') };
  }
}

/**
 * URL for a cached card image. The backend downloads and caches the
 * image on first request (GET /api/cards/{id}/image) — this just builds
 * the URL, it doesn't fetch anything itself; the <img> tag does that.
 * @param {string} cardId Scryfall id (Card.id from a resolved card).
 * @param {'small'|'normal'|'large'|'png'} size
 * @param {'front'|'back'} [face] Back face of a double-faced card
 *   (transform / modal DFC) — only valid when the card `has_back_face`.
 */
export function cardImageUrl(cardId, size = 'normal', face = 'front') {
  const faceParam = face === 'back' ? '&face=back' : '';
  return `${getServerUrl()}/api/cards/${encodeURIComponent(cardId)}/image?size=${size}${faceParam}`;
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
 * Cards currently in the backend's local cache.
 * @param {'all'|'decks'} [scope] 'decks' narrows to cards referenced by a saved deck.
 * @returns {Promise<object[] | null>} null on network/server failure
 */
export async function listCachedCards(scope = 'all') {
  let response;
  try {
    response = await fetch(`${getServerUrl()}/api/cards?scope=${scope}`);
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
 * Parser/engine coverage aggregated by set (GET /api/cards/coverage-by-set),
 * for the Engine-Status tab's "Abdeckung nach Set" table.
 * @returns {Promise<{setCode: string, total: number, covered: number, fraction: number}[] | null>} null on network/server failure
 */
export async function listCoverageBySet() {
  let response;
  try {
    response = await fetch(`${getServerUrl()}/api/cards/coverage-by-set`);
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
 * Refreshes the complete Scryfall Oracle-card pool via the backend's
 * established bulk-import script.
 * @returns {Promise<{ok: true, cachedCardCount: number} | {ok: false, error: string}>}
 */
export async function updateCardPool() {
  let response;
  try {
    response = await fetch(`${getServerUrl()}/api/cards/update`, { method: 'POST' });
  } catch {
    return { ok: false, error: t('common.serverUnreachable') };
  }
  if (!response.ok) {
    try {
      const body = await response.json();
      return { ok: false, error: body?.detail || `HTTP ${response.status}` };
    } catch {
      return { ok: false, error: `HTTP ${response.status}` };
    }
  }
  try {
    return { ok: true, ...(await response.json()) };
  } catch {
    return { ok: false, error: t('api.invalidResponse') };
  }
}

/**
 * Update the local Commander Spellbook SQLite snapshot.
 * @returns {Promise<{ok: true, summary: object} | {ok: false, error: string}>}
 */
export async function updateComboDatabase() {
  let response;
  try {
    response = await fetch(`${getServerUrl()}/api/combos/update`, { method: 'POST' });
  } catch {
    return { ok: false, error: t('common.serverUnreachable') };
  }
  if (!response.ok) {
    try {
      const body = await response.json();
      return { ok: false, error: body?.detail || `HTTP ${response.status}` };
    } catch {
      return { ok: false, error: `HTTP ${response.status}` };
    }
  }
  try {
    return { ok: true, summary: await response.json() };
  } catch {
    return { ok: false, error: t('api.invalidResponse') };
  }
}

/**
 * Read the local Commander Spellbook snapshot state without initializing it.
 * @returns {Promise<object | null>} null on network/server failure
 */
export async function getComboDatabaseStatus() {
  let response;
  try {
    response = await fetch(`${getServerUrl()}/api/combos/status`);
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
 * Lazily initialize the local combo database if needed and find variants
 * whose named card uses are contained in the deck.
 * @param {{name: string, quantity: number}[]} cards
 * @returns {Promise<{combos: object[], database: object} | null>} null on request failure
 */
export async function findDeckCombos(cards) {
  let response;
  try {
    response = await fetch(`${getServerUrl()}/api/combos/matches`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cards }),
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
 * Save a new deck, or update one already saved (pass its `id` back).
 * @param {{id?: string, name: string, commanderText: string, mainboardText: string, sideboardText: string, sleeveId?: string | null, author?: string | null, isCube?: boolean}} deck
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
 * How many of a saved deck's cards the rules engine doesn't model yet
 * (GET /api/decks/{id}/coverage) — a goldfishing readiness note, not a
 * legality gate.
 * @param {string} deckId
 * @returns {Promise<{unmodeledCount: number, unmodeledCardNames: string[]} | null>} null on failure
 */
export async function getDeckCoverage(deckId) {
  let response;
  try {
    response = await fetch(`${getServerUrl()}/api/decks/${encodeURIComponent(deckId)}/coverage`);
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

/**
 * The tokens a deck can produce, so the loading screen can preload their art
 * before the match starts. Returns `{tokens: [{id, name, image_small, …}]}`.
 * @param {{deckId?: string, commanderText?: string, mainboardText?: string, sideboardText?: string}} payload
 */
export async function fetchDeckTokens(payload) {
  return gameRequest('POST', '/api/game/deck-tokens', payload);
}

/**
 * Every token in the repo's curated catalogue (deck-independent), for the
 * "known token type" dropdown in Settings' token-image upload form.
 * @returns {Promise<{ok: boolean, status: number, data: {tokens: Array<{id, name, type_line, image_small}>}|null}>}
 */
export async function fetchKnownTokenTypes() {
  return gameRequest('GET', '/api/game/tokens');
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

/**
 * The RULE 8/9 formats a game can be started in (PLR-13) — shared by the
 * Goldfisch start screen and the Multiplayer Setup table options.
 * @returns {Promise<{ok: boolean, status: number, data: {formats: Array<{name, label, starting_life, starting_hand, singleton, variants}>, default: string}|null}>}
 */
export async function fetchGameFormats() {
  return gameRequest('GET', '/api/game/formats');
}

// --- Solo vs. bots (api/solo.py) ----------------------------------------
// The Multiplayer engine (real turns, RULE 117 priority, redacted views)
// minus the lobby: one human, 1-3 bots, plain REST like goldfish. Same
// {ok, status, data} shape. The bot kinds come from `fetchBotKinds`
// (/api/multiplayer/bots) — a property of the backend, not of the lobby.

/**
 * Start a solo game.
 * @param {{deckId: string, opponents: Array<{kind: string, deckId: string}>,
 *   gameFormat?: string, mulliganStyle?: string,
 *   startingPlayer?: "you"|"random"}} payload
 */
export async function startSolo(payload) {
  return gameRequest('POST', '/api/solo/start', payload);
}

/** Apply one action (from `legal_actions`) as the human; the bots answer. */
export async function sendSoloAction(sessionId, action) {
  return gameRequest('POST', `/api/solo/${encodeURIComponent(sessionId)}/action`, action);
}

/** RULE 104.3a: the human concedes the solo game. */
export async function concedeSolo(sessionId) {
  return gameRequest('POST', `/api/solo/${encodeURIComponent(sessionId)}/concede`, {});
}

/** Reset a solo game to its opening state. */
export async function restartSolo(sessionId) {
  return gameRequest('POST', `/api/solo/${encodeURIComponent(sessionId)}/restart`, {});
}

/** The human's current view (reload / tab re-open). */
export async function getSoloView(sessionId) {
  return gameRequest('GET', `/api/solo/${encodeURIComponent(sessionId)}`);
}

/** Drop a solo game session on the server. */
export async function endSolo(sessionId) {
  return gameRequest('DELETE', `/api/solo/${encodeURIComponent(sessionId)}`);
}

// --- ANA-4: dynamic (simulated) deck analysis -----------------------------
// Backend: mtg_analyzer/api/dynamic_analysis.py. A simulation runs as a
// background job (it can take tens of seconds) — start it, then poll
// getDynamicAnalysisJob until `status` is no longer "running".

/**
 * Start a headless goldfish-simulation job. Same deck-source shape as
 * `startGoldfish` (a saved `deckId` or decklist text), plus which bot
 * drives the matches and how many to run.
 * @param {{deckId?: string, commanderText?: string, mainboardText?: string,
 *          sideboardText?: string, botKind: string, numMatches: number,
 *          maxTurns: number, favoriteCards?: string[]}} payload
 *   `favoriteCards` falls back to the saved deck's own `favoriteCards` when
 *   `deckId` is given and this is omitted (`api/dynamic_analysis.py`).
 * @returns {Promise<{ok: boolean, status: number, data: {jobId: string}|null}>}
 */
export async function startDynamicAnalysis(payload) {
  return gameRequest('POST', '/api/analysis/dynamic', payload);
}

/**
 * Poll a simulation job's status/progress/result.
 * @param {string} jobId
 * @returns {Promise<{ok: boolean, status: number, data: {status: string, completed: number, total: number, result: object|null, error: string|null}|null}>}
 */
export async function getDynamicAnalysisJob(jobId) {
  return gameRequest('GET', `/api/analysis/dynamic/${encodeURIComponent(jobId)}`);
}

// --- Archetype catalogue + likelihood analysis ----------------------------
// Backend: mtg_analyzer/api/archetypes.py, mtg_analyzer/data/archetypes
// .json. The catalogue (labels/descriptions/etc.) and the scoring logic
// both live server-side — this module only renders what it fetches, no
// archetype data or scoring math on the frontend.

/**
 * The full archetype catalogue (id/label/description/...), for the
 * deck-edit archetype picker and for label lookups elsewhere (saved-decks
 * badges).
 * @returns {Promise<{ok: boolean, status: number, data: object[]|null}>}
 */
export async function listArchetypes() {
  return gameRequest('GET', '/api/archetypes');
}

/**
 * Score a deck against the archetype catalogue. Same deck-source shape as
 * `startDynamicAnalysis` (a saved `deckId` or decklist text).
 * @param {{deckId?: string, commanderText?: string, mainboardText?: string,
 *          sideboardText?: string}} payload
 * @returns {Promise<{ok: boolean, status: number, data: {suggestions: object[], typalSignals: object[]}|null}>}
 */
export async function analyzeArchetypes(payload) {
  return gameRequest('POST', '/api/archetypes/analyze', payload);
}

// --- Multiplayer lobby + shared games (UC4) -------------------------------
// Backend: mtg_analyzer/api/multiplayer.py. Same {ok, status, data} shape as
// the game-session helpers above. Every call identifies the caller by the
// server-assigned lobby `playerId` (from /ws/lobby's welcome message, or
// `connectToLobby` as a fallback) — never by the display name, which is
// free text and not unique.

/** Register with the lobby without a WebSocket (fallback / first contact). */
export async function connectToLobby(name, playerId = null, clientToken = null) {
  return gameRequest('POST', '/api/multiplayer/connect', { name, playerId, clientToken });
}

/** Everyone connected and every table (players + games). */
export async function fetchLobby() {
  return gameRequest('GET', '/api/multiplayer/lobby');
}

/** Open a new table; the caller becomes its host and first seat. */
export async function createMultiplayerGame(playerId, name = '', numPlayers = 2) {
  return gameRequest('POST', '/api/multiplayer/games', { playerId, name, numPlayers });
}

/** Take a seat at a forming table. */
export async function joinMultiplayerGame(gameId, playerId) {
  return gameRequest('POST', `/api/multiplayer/games/${encodeURIComponent(gameId)}/join`, { playerId });
}

/** Watch a table instead of playing it (public board, no hands). */
export async function observeMultiplayerGame(gameId, playerId) {
  return gameRequest('POST', `/api/multiplayer/games/${encodeURIComponent(gameId)}/observe`, { playerId });
}

/** Give up a seat (or stop watching). */
export async function leaveMultiplayerGame(gameId, playerId) {
  return gameRequest('POST', `/api/multiplayer/games/${encodeURIComponent(gameId)}/leave`, { playerId });
}

/** Pick a seat's deck from the decks saved on the server.
 *
 * `seatId` picks for someone else's seat — only ever a bot's, and only as
 * the host, since a bot has no client to choose for itself.
 */
export async function setMultiplayerDeck(gameId, playerId, deckId, seatId = null) {
  return gameRequest('POST', `/api/multiplayer/games/${encodeURIComponent(gameId)}/deck`, { playerId, deckId, seatId });
}

/** Paint a seat's board banner (`bannerColors.js` for the palette).
 *
 * `color` is a banner key — WUBRG letters in any order, or `'c'` for the
 * grey colourless banner; the server normalizes it. `seatId` targets a
 * bot's seat, host only, exactly like `setMultiplayerDeck`.
 */
export async function setMultiplayerBannerColor(gameId, playerId, color, seatId = null) {
  return gameRequest('POST', `/api/multiplayer/games/${encodeURIComponent(gameId)}/banner`, { playerId, color, seatId });
}

/** The bot kinds a seat can be filled with (backend services/bots.py). */
export async function fetchBotKinds() {
  return gameRequest('GET', '/api/multiplayer/bots');
}

/** Host only: seat a bot of `kind` at the table. */
export async function addMultiplayerBot(gameId, playerId, kind) {
  return gameRequest('POST', `/api/multiplayer/games/${encodeURIComponent(gameId)}/bots`, { playerId, kind });
}

/** Host only: take a bot back off the table. */
export async function removeMultiplayerBot(gameId, playerId, botId) {
  return gameRequest('POST', `/api/multiplayer/games/${encodeURIComponent(gameId)}/bots/remove`, { playerId, botId });
}

/** Host only: change the table's shared settings (mulligan style, seats). */
export async function setMultiplayerOptions(gameId, playerId, options) {
  return gameRequest('POST', `/api/multiplayer/games/${encodeURIComponent(gameId)}/options`, { playerId, ...options });
}

/** Accept (or un-accept) the table as configured. */
export async function setMultiplayerReady(gameId, playerId, ready = true) {
  return gameRequest('POST', `/api/multiplayer/games/${encodeURIComponent(gameId)}/ready`, { playerId, ready });
}

/** Everyone accepted — resolve the decks and start the real game. */
export async function startMultiplayerGame(gameId, playerId) {
  return gameRequest('POST', `/api/multiplayer/games/${encodeURIComponent(gameId)}/start`, { playerId });
}

/** This player's own (server-redacted) view of a running game. */
export async function fetchMultiplayerGame(gameId, playerId) {
  return gameRequest(
    'GET',
    `/api/multiplayer/games/${encodeURIComponent(gameId)}?player_id=${encodeURIComponent(playerId)}`,
  );
}

/** Apply one action as this seat. */
export async function sendMultiplayerAction(gameId, playerId, action) {
  return gameRequest('POST', `/api/multiplayer/games/${encodeURIComponent(gameId)}/action`, { playerId, action });
}

/** RULE 104.3a: leave the game. */
export async function concedeMultiplayerGame(gameId, playerId) {
  return gameRequest('POST', `/api/multiplayer/games/${encodeURIComponent(gameId)}/concede`, { playerId });
}

/** Undo back through this seat's own last move (UC4 Setup's take-back budget). */
export async function takeBackMultiplayerMove(gameId, playerId) {
  return gameRequest('POST', `/api/multiplayer/games/${encodeURIComponent(gameId)}/takeback`, { playerId });
}

/**
 * The legacy seat-less multiplayer entry point — still a 501 by design (a
 * game needs seats, which only the lobby has). Kept for the Engine-Status
 * page's route probe.
 */
export async function startMultiplayer() {
  return gameRequest('POST', '/api/game/multiplayer', {});
}

/**
 * Start a Replay / Puzzle session. Pass a full `Replay` descriptor to
 * load a saved/exported board, or `null` to start blank with `numPlayers`
 * (1 = solo puzzle, 2 = with an opponent).
 * @param {object|null} replay
 * @param {number} numPlayers
 */
export async function startReplay(replay, numPlayers = 1) {
  return gameRequest('POST', '/api/game/replay', { replay, numPlayers });
}

/**
 * Serialize a session's board to a portable descriptor (for download). Works
 * for a goldfish session too, so a goldfish position can be exported.
 * @param {string} sessionId
 */
export async function exportReplay(sessionId) {
  return gameRequest('GET', `/api/game/${encodeURIComponent(sessionId)}/replay-export`);
}

/**
 * PLR-6: store (or, `draft: null`, clear) the caller's in-progress,
 * not-yet-submitted UI selection (mid-cast targeting, a half-assembled
 * block) so it survives a reconnect instead of just being lost. Quiet —
 * this never triggers a broadcast to other players (see gameBoardView.js).
 * @param {string} sessionId
 * @param {string|null} playerId omit for solo modes (the one real player)
 * @param {object|null} draft
 */
export async function saveUiDraft(sessionId, playerId, draft) {
  return gameRequest('POST', `/api/game/${encodeURIComponent(sessionId)}/ui-draft`, {
    playerId: playerId ?? undefined,
    draft,
  });
}

// --- Per-player custom art: token images + card-back "sleeves" ------------
// Backend: mtg_analyzer/api/player_assets.py. Keyed by player name (see
// settings.js getPlayerName()) rather than a session, so any client asking
// for that name gets the same images back — that's what lets an opponent
// see them too, once multiplayer (currently a 501 stub) is wired up.

/**
 * Reserved `token_name` value for a player's "generic" token image — the
 * fallback art for any token with neither a real Scryfall image nor its own
 * uploaded art (mainly ad hoc tokens an effect synthesizes inline, e.g. a
 * bare "1/1 white Soldier", which have no catalogue entry to name exactly).
 * Never a real token name (those never start with "__"), so it can't collide.
 */
export const GENERIC_TOKEN_KEY = '__generic__';

/**
 * URL for a player's uploaded art for a token with no real Scryfall art.
 * `tokenName` is a query param, not a path segment — token names can
 * contain a literal "/" (e.g. "Soldier 1/1"), which a percent-encoded
 * path segment can't round-trip through routing.
 */
export function tokenImageUrl(playerName, tokenName) {
  return `${getServerUrl()}/api/players/${encodeURIComponent(playerName)}/token-images/image?token_name=${encodeURIComponent(tokenName)}`;
}

/** @returns {Promise<Array<{token_name: string, updated_at: string}> | null>} null on failure */
export async function listTokenImages(playerName) {
  let response;
  try {
    response = await fetch(`${getServerUrl()}/api/players/${encodeURIComponent(playerName)}/token-images`);
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

/** @returns {Promise<{ok: boolean, status: number, data: object|null}>} */
export async function uploadTokenImage(playerName, tokenName, file) {
  const form = new FormData();
  form.append('token_name', tokenName);
  form.append('file', file);
  return uploadRequest(`/api/players/${encodeURIComponent(playerName)}/token-images`, form);
}

/** @returns {Promise<boolean>} whether it was actually deleted */
export async function deleteTokenImage(playerName, tokenName) {
  return deleteRequest(
    `/api/players/${encodeURIComponent(playerName)}/token-images?token_name=${encodeURIComponent(tokenName)}`
  );
}

/** URL for one of a player's uploaded card-back sleeve designs. */
export function sleeveImageUrl(playerName, sleeveId) {
  return `${getServerUrl()}/api/players/${encodeURIComponent(playerName)}/sleeves/${encodeURIComponent(sleeveId)}/image`;
}

/** @returns {Promise<Array<{sleeve_id: string, label: string, updated_at: string}> | null>} null on failure */
export async function listSleeves(playerName) {
  let response;
  try {
    response = await fetch(`${getServerUrl()}/api/players/${encodeURIComponent(playerName)}/sleeves`);
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

/** @returns {Promise<{ok: boolean, status: number, data: object|null}>} */
export async function uploadSleeve(playerName, label, file) {
  const form = new FormData();
  form.append('label', label);
  form.append('file', file);
  return uploadRequest(`/api/players/${encodeURIComponent(playerName)}/sleeves`, form);
}

/** @returns {Promise<boolean>} whether it was actually deleted */
export async function deleteSleeve(playerName, sleeveId) {
  return deleteRequest(`/api/players/${encodeURIComponent(playerName)}/sleeves/${encodeURIComponent(sleeveId)}`);
}

// -- Favorite decks (Profil tab) ---------------------------------------------
// Starred `Deck.id`s, per player name — read by savedDecksView.js's siblings
// (goldfishView.js/multiplayerView.js) to list favorites first.

/** @returns {Promise<string[] | null>} deck ids, null on failure */
export async function listFavoriteDecks(playerName) {
  let response;
  try {
    response = await fetch(`${getServerUrl()}/api/players/${encodeURIComponent(playerName)}/favorite-decks`);
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

/** @returns {Promise<{ok: boolean, status: number, data: object|null}>} */
export async function addFavoriteDeck(playerName, deckId) {
  return gameRequest('POST', `/api/players/${encodeURIComponent(playerName)}/favorite-decks`, { deckId: deckId });
}

/** @returns {Promise<boolean>} whether it was actually removed */
export async function removeFavoriteDeck(playerName, deckId) {
  return deleteRequest(
    `/api/players/${encodeURIComponent(playerName)}/favorite-decks/${encodeURIComponent(deckId)}`
  );
}

async function uploadRequest(path, form) {
  let response;
  try {
    response = await fetch(`${getServerUrl()}${path}`, { method: 'POST', body: form });
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

async function deleteRequest(path) {
  let response;
  try {
    response = await fetch(`${getServerUrl()}${path}`, { method: 'DELETE' });
  } catch {
    return false;
  }
  return response.ok;
}

// Server-side LLM credentials are write-only; they never enter cookies.
export async function getLLMSettings() {
  return gameRequest('GET', '/api/llm/settings');
}
export async function saveLLMSettings(payload) {
  return gameRequest('PUT', '/api/llm/settings', payload);
}
export async function testLLMConnection() {
  return gameRequest('POST', '/api/llm/test', {});
}
export async function analyzeNarrativeDeck(deckId, payload = {}) {
  return gameRequest('POST', `/api/decks/${encodeURIComponent(deckId)}/analyze`, payload);
}
export async function getNarrativeDeckAnalysis(deckId) {
  return gameRequest('GET', `/api/decks/${encodeURIComponent(deckId)}/analysis`);
}

export async function fetchLLMModels(payload = {}) {
  return gameRequest('POST', '/api/llm/models', payload);
}
