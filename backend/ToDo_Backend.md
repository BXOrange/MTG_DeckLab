# Backend TODO

Status: `mtg_analyzer/models/card.py` (Phase 1, Card Model) plus a
FastAPI HTTP server with `POST /api/decks` and the `GET/POST
/api/cards/*` family below — see
[../IMPLEMENTATION_STATUS.md](../IMPLEMENTATION_STATUS.md). The
frontend (`../frontend/`) now resolves card data/images through this
API (`frontend/src/js/cardImages.js`, `api.js`) instead of calling
Scryfall directly from the browser; `POST /api/decks` itself is still
mock-parsed client-side first, with the server call as confirmation.
See `../docs/IMPLEMENTATION_GUIDE.md` for the original phase-by-phase
plan this roughly follows.

## HTTP API foundation (blocks everything below)

- [x] Pick and set up a server framework — FastAPI + uvicorn
      (`mtg_analyzer/api/app.py`), CORS open to any localhost port for
      the static frontend dev server.
- [x] `POST /api/decks`: parse + structurally validate a decklist
      server-side (`mtg_analyzer/api/decks.py`, backed by the new
      `DecklisteParser` below). Mirrors `frontend/src/js/parser.js`'s
      request/response shape so the client can post its existing
      `{commanderText, mainboardText, sideboardText}` body unchanged —
      but the frontend doesn't call it yet, it's still mock-only.
- [x] Real Commander legality in that endpoint — color identity, ban
      list, partner rules (`mtg_analyzer/services/commander_legality.py`,
      see "Validator" below). Resolves commander + deck card names via
      the `LazyCardLoader` and appends its errors to the structural
      validation's; if a commander name itself fails to resolve, the
      real checks are skipped (rather than run against an incomplete
      color identity) and a warning is added instead.
- [x] `GET /api/cards`: list every card currently in the local cache
      (`CardDatabase.list_cards`) — backs the frontend's "Karten-Cache"
      tab.
- [x] `GET /api/cards/search?name=`: resolve a single card by exact
      name (`mtg_analyzer/api/cards.py`), backed by the `LazyCardLoader`
      below — checks the SQLite cache first, falls back to Scryfall,
      stores the result.
- [x] `POST /api/cards/resolve`: resolve many card names in one round
      trip (body `{"names": [...]}`, response `{"cards": {name:
      cardDict}, "notFound": [...]}`) — what the frontend actually
      calls for a whole decklist, so it isn't one HTTP request per card.
- [x] `GET /api/cards/{card_id}/image?size=`: serve a card image,
      downloading it to `backend/cache/images/` on first request
      (`mtg_analyzer/api/images.py`, `services/image_cache.py`). The
      frontend now uses this instead of fetching from Scryfall directly
      (`frontend/src/js/cardImages.js`, `api.js`).
- [x] `POST /api/decks/save`, `GET /api/decks`, `GET /api/decks/{id}`,
      `DELETE /api/decks/{id}`: persist a decklist
      (`mtg_analyzer/api/saved_decks.py`, `services/deck_database.py`)
      — see "Deck persistence" below. Distinct from `POST /api/decks`
      above, which only parses/validates and stores nothing.
- [x] `WebSocket /ws/game/{game_id}` connection plumbing
      (`mtg_analyzer/api/game_ws.py`): accepts connections grouped by
      `game_id`, relays a `player_action` message to every connection
      in that game as a `game_state_update`. No game engine exists yet
      (see "Game Engine"/"Rules Engine" below), so there's no
      validation and no server-held `GameState` — this is transport
      only, a stand-in for "the server processed the action" so the
      wire protocol could be built end-to-end before the real engine
      exists. The frontend's play area (`frontend/src/js/boardEngine.js`)
      still isn't wired to this (see
      `../frontend/ToDo_Frontend.md` "Game engine hookup") — that's a
      separate, larger step once there's real state to swap in.

## Data Layer (Phase 1, docs/IMPLEMENTATION_GUIDE.md)

- [x] `DecklisteParser`: parse decklist text server-side
      (`mtg_analyzer/parser/deckliste_parser.py`), ported line-for-line
      from the frontend's own parser (multiple qty formats, tag/set
      suffix stripping, structural Commander validation).
- [x] `Validator`: real Commander legality —
      `mtg_analyzer/services/commander_legality.py`, wired into
      `POST /api/decks` (see "HTTP API foundation" above). Checks:
      color identity (union of all commanders' identity vs. every
      other resolved card's), a hand-maintained banned-card list (no
      live source — Scryfall's per-printing `legalities` isn't fetched
      today, so this needs manual updates against
      <https://mtgcommander.net/index.php/banned-list/>), and Partner
      pairing (plain "Partner" pairs with any other plain-Partner card;
      "Partner with X" only pairs with that specifically named card,
      reciprocally — the two are distinguished via `partner_with`
      even though `has_partner` is set for both, see
      `scryfall_client._has_partner`). Doesn't yet cover Backgrounds or
      "Friends forever" pairing, or commander-type eligibility (must be
      a legendary creature or explicitly say it can be a commander) —
      only what was structurally missing (color identity/ban
      list/partner) is covered.
      Verified specifically for Hybrid mana (e.g. `{W/U}` in a casting
      cost, or in an activated ability's cost), Phyrexian mana (e.g.
      `{B/P}`, payable with life instead of a colored pip), and MDFCs
      (modal double-faced cards, e.g. "Valki, God of Lies // Tibalt,
      Cosmic Impostor") — `test_scryfall_client.py`/`test_api_decks.py`.
      All three turned out to already be correct for granted, since
      `color_identity` is read straight from Scryfall's own precomputed,
      whole-card field (`card_from_scryfall_data`) rather than derived
      from the app's own flattened `mana_cost` dict (which *does* lose
      the hybrid/Phyrexian distinction, see "Mana cost model" below —
      that limitation turned out to be unrelated to color identity).
      Chasing this down a real bug in card *resolution*, not color
      identity: `LazyCardLoader`/`CardDatabase` matched Scryfall results
      back to requested names by exact string match only, so an MDFC
      referenced by its front-face name alone (e.g. "Valki, God of
      Lies" — how decklists conventionally write these, and how
      Scryfall's own `/cards/collection` accepts them) resolved
      correctly against Scryfall but then silently vanished — not
      returned, and not reported as not-found either, since Scryfall
      *did* find it under its full combined name. Fixed by aliasing
      results to the front-face name too, in both `LazyCardLoader.load_cards`
      (first resolution) and `CardDatabase.get_card` (repeat lookups,
      via a `LIKE 'name // %'` match, so those also hit the cache
      instead of re-fetching every time).
      `check_commander_legality` returns a `CommanderLegalityResult`
      (not a plain `list[str]`) — `errors` (unchanged, prose for the
      existing issue list) plus `banned_card_names`/
      `color_identity_violation_names`, so a caller can flag the exact
      offending cards without parsing error text. Surfaced on
      `POST /api/decks`'s response as `validation.bannedCardNames`/
      `validation.colorIdentityViolationNames` (`DeckValidationResult`
      in `deckliste_parser.py`, defaulted to `[]` there since that
      module only has names/quantities — populated afterwards in
      `api/decks.py` once cards are resolved). Frontend:
      `deckImportView.js` marks matching cards with a ❗ (distinct from
      🛑 "not found" above — these are real, resolved cards, just not
      Commander-legal) in both the plain list and the detail-mode tile
      (`cardTile.js`'s `renderCardTile` gained an `illegalReason`
      option). Deliberately doesn't touch the "Karten-Cache" tab/
      `CardDatabase` at all — that's a raw, commander-agnostic card
      browser, nothing to flag there since there's no commander to
      compare against and invalid cards must stay cached (a banned or
      off-color card is still a perfectly valid, real card the cache
      should keep serving).
- [ ] `GameState` / `Player` / `ManaPool` models (docs/07 PART 2).
- [x] `CardDatabase` + Scryfall integration + `LazyCardLoader`
      (docs/06, docs/IMPLEMENTATION_GUIDE.md Week 2 Day 4-5):
      `mtg_analyzer/services/card_database.py` (SQLite, one row per
      card storing its `to_dict()` JSON so the schema stays in sync
      with `Card`), `scryfall_client.py` (`ScryfallIntegration`,
      batches lookups via Scryfall's `/cards/collection`), and
      `lazy_card_loader.py` (`LazyCardLoader`: DB first, Scryfall only
      for misses, persists what it fetches). Exposed via
      `GET /api/cards/search` above; not yet wired into
      `POST /api/decks` or Commander legality — see `Validator` above.
      Card images are a separate on-disk cache (`services/image_cache.py`,
      `GET /api/cards/{id}/image` above) keyed by the same Scryfall id
      rather than a stored path — see docs/08_CARD_CACHE_EXPORT_IMPORT.md
      for the on-disk layout and how to export/import the whole cache.

## Mana cost model (Backlog)

The `Card.mana_cost` dict (`mtg_analyzer/models/card.py`) only tracks a
plain per-symbol pip count — `{"W": n, "U": n, ..., "C": n}` — with no
concept of *how* a symbol can be paid. Two real cost shapes get
flattened into that and lose information as a result:

- [ ] **Hybrid mana** (`{W/U}`, `{2/W}`, ...): `_parse_mana_cost`
      (`mtg_analyzer/services/scryfall_client.py`) splits on "/" and
      keeps whichever half matches a known color/colorless letter, so
      `{W/U}` becomes a plain `"W": 1` pip — indistinguishable from an
      actual `{W}` symbol. The "or" is gone: nothing records that this
      pip could instead be paid with `U` (or, for `{2/W}`, with 2
      generic mana).
- [ ] **Phyrexian mana** (`{W/P}`, ...): same flattening — becomes a
      plain `"W": 1` pip, losing that it can alternatively be paid with
      2 life.

Doesn't matter yet because nothing pays costs today — the frontend's
"Karten-Cache" tab just displays pips as colored emoji
(`frontend/src/js/cachedCardsView.js`) and happens to not need the
distinction. It will matter once real cost payment exists: `ManaPool`
(docs/07 PART 2) and casting (RULE 601, RULE 504,
docs/02 R2.1–R2.8, "Rules Engine" below) need to know the *actual*
legal ways to pay a cost, not just a flattened color tally. At that
point this likely needs a real per-symbol cost representation (e.g. a
list of symbols, each tagged as plain/hybrid/Phyrexian with its
alternatives) rather than the current flat dict, which is a breaking
change to `Card.mana_cost`'s shape — plan for updating
`to_dict`/`from_dict`, the Scryfall parser, and every test fixture that
hardcodes a `mana_cost` dict when it happens.

## Configuration (Backlog)

- [ ] On-disk paths (`CACHE_ROOT`/`DEFAULT_DB_PATH` in
      `card_database.py`, `DATA_ROOT`/`DEFAULT_DECKS_DB_PATH` in
      `deck_database.py`) are hard-coded module constants with no
      override hook. Came up concretely: verifying a change against a
      real running server means pointing it at these same fixed,
      repo-relative paths as any dev instance you might have running —
      there's no way to redirect a one-off/test server elsewhere, so
      the two can collide (a cleanup between test runs can wipe a dev
      server's actual cache/saved decks out from under it).
      Pull these — and any other scattered constants worth it, e.g.
      `scryfall_client.py`'s `_USER_AGENT`/`_MIN_REQUEST_INTERVAL_SECONDS`,
      `image_cache.py`'s `_USER_AGENT` — into one config module (e.g.
      `mtg_analyzer/config.py`), reading overrides from environment
      variables (e.g. `MTG_CACHE_DIR`, `MTG_DATA_DIR`) with the current
      hard-coded values as defaults. `api/dependencies.py`'s singletons
      would read from there instead of importing the path constants
      directly.

## Rules Engine (Phase 2)

- [ ] Effect system: `GameEffect`, `StaticEffect`, `TriggeredAbility`,
      `ReplacementEffect`, `ActivatedAbility` (docs/07 PART 2).
- [ ] `EffectRegistry` + core effects (damage, draw, discard, destroy,
      counter, search).
- [ ] Replacement effect stacking, RULE 616 (docs/07 PART 3).
- [ ] Phases/steps as sequences, RULE 500 (docs/07 PART 1).
- [ ] Casting (RULE 601), Stack (RULE 608), Mana (RULE 504), Priority
      (RULE 117), Triggered Abilities (RULE 603/607), State-Based
      Actions (RULE 704) — docs/02 R2.1–R2.8.

## Game Engine (Phase 3)

- [ ] Turn/phase/step loop, event system (docs/02 R4.1).
- [ ] Action validation: legal-actions-for-player logic
      (docs/05_GAME_UI_AND_CARD_INTERACTION.md PART 3) — the frontend
      has no equivalent today; any hand card can be "played" locally
      with zero rule checks.
- [ ] Goldfisch mode (UC3): single-player game against real rules.
- [ ] Multiplayer game session + priority system (UC4).

## LLM Deck Analysis (UC2)

- [ ] `POST /api/decks/{id}/analyze`: Claude API integration, prompt
      templates, structured output parsing, caching (docs/02 UC2,
      docs/04 Phase 6). `Deck.analysis_id` (see "Deck persistence"
      above) is already reserved to link a saved deck to whatever this
      produces — no `Analysis` model/table exists yet, design that
      alongside this endpoint rather than assuming the reserved field's
      shape is final.

## Auth & persistence

- [ ] User accounts, login/signup (docs/04 PART 4 REST endpoints).
- [x] Deck persistence (save/load instead of re-parsing every time):
      `mtg_analyzer/models/deck.py` (`Deck`, identified by a
      server-generated UUID — `name` is just a label, not unique, so
      two saved decks may share one), `services/deck_database.py`
      (`DeckDatabase`, SQLite, same "JSON blob per row" pattern as
      `CardDatabase`), exposed via `saved_decks.py` above. Stores raw
      decklist text only (re-parsed on demand via the existing
      `DecklisteParser`) rather than persisting derived/parsed data
      that could drift from the parser's current behavior. Lives under
      `backend/data/` — unlike `backend/cache/` (Scryfall data, always
      re-fetchable, see docs/08), this has no upstream source to
      regenerate from, so **don't delete it casually**; still
      gitignored like `cache/` since it's local dev state, not
      committed data.
      `Deck.analysis_id` is a reserved (currently unused) hook for "LLM
      Deck Analysis" below to link a deck to its analysis once that
      exists — treat its shape (single id vs. something richer) as
      provisional until that feature actually needs it.
- [ ] No user accounts yet (see above), so saved decks aren't scoped to
      an owner — anyone hitting the API sees every saved deck. Revisit
      once auth exists.
- [ ] Game history / session persistence.

## Bot AI (UC5)

- [ ] Greedy bot strategy (docs/02 UC5) once the game engine exists.

## Import — follow-up from the frontend

- [ ] Server-side Moxfield import proxy
      (`GET /api/import/moxfield/{deckId}`), tried client-side and
      reverted (see `../frontend/ToDo_Frontend.md` "Import — follow-ups"):
      Moxfield's Cloudflare protection returned HTTP 403 on every
      plain request tried by hand, including from a browser origin.
      A server-side fetch removes the browser-CORS obstacle but still
      isn't guaranteed to get past bot protection — may need
      browser-like request headers or a headless-browser fallback.
