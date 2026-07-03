# Backend TODO

Status: only `mtg_analyzer/models/card.py` exists (Phase 1, Card Model
— see [../IMPLEMENTATION_STATUS.md](../IMPLEMENTATION_STATUS.md)).
There is no HTTP server yet at all — the frontend
(`../frontend/`) currently runs entirely against client-side mocks and
talks directly to Scryfall for card art, with no backend in the loop.
Everything below is not yet implemented. See
`../docs/IMPLEMENTATION_GUIDE.md` for the original phase-by-phase plan
this roughly follows.

## HTTP API foundation (blocks everything below)

- [ ] Pick and set up a server framework (Flask/FastAPI per
      docs/04_SERVER_CLIENT_ARCHITECTURE.md) — nothing is installed
      yet (`requirements.txt` only has `pytest`).
- [ ] `POST /api/decks`: parse + validate a decklist server-side
      (backs the frontend's `frontend/src/js/parser.js`, which today
      only does client-side structural checks).
- [ ] `GET /api/cards/search`, card resolution by name → mana cost,
      type_line, oracle_text, power/toughness, image URIs. The
      frontend currently fetches images directly from Scryfall
      client-side (`frontend/src/js/cardImages.js`) as a stopgap —
      once this exists, that call can move server-side and return
      richer data in one round trip.
- [ ] `WebSocket /ws/game/{game_id}` once a game engine exists (see
      below) — the frontend's play area (`frontend/src/js/boardEngine.js`)
      is a local-only mock specifically because this doesn't exist.

## Data Layer (Phase 1, docs/IMPLEMENTATION_GUIDE.md)

- [ ] `DecklisteParser`: parse decklist text server-side (multiple
      formats), independent of the frontend's own parser.
- [ ] `Validator`: real Commander legality — color identity, ban list,
      partner rules. The frontend only checks card count / singleton /
      exactly-one-commander locally, nothing that needs real card data.
- [ ] `GameState` / `Player` / `ManaPool` models (docs/07 PART 2).
- [ ] `CardDatabase` + Scryfall integration + `LazyCardLoader`
      (docs/06, docs/IMPLEMENTATION_GUIDE.md Week 2 Day 4-5) — local
      persistence so card lookups don't hit Scryfall on every request.

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
      docs/04 Phase 6).

## Auth & persistence

- [ ] User accounts, login/signup (docs/04 PART 4 REST endpoints).
- [ ] Deck persistence (save/load instead of re-parsing every time).
- [ ] Game history / session persistence.

## Bot AI (UC5)

- [ ] Greedy bot strategy (docs/02 UC5) once the game engine exists.

## Import — follow-up from the frontend

- [ ] Server-side Moxfield import proxy
      (`GET /api/import/moxfield/{deckId}`), tried client-side and
      reverted (see `../frontend/TODO.md` "Import — follow-ups"):
      Moxfield's Cloudflare protection returned HTTP 403 on every
      plain request tried by hand, including from a browser origin.
      A server-side fetch removes the browser-CORS obstacle but still
      isn't guaranteed to get past bot protection — may need
      browser-like request headers or a headless-browser fallback.
