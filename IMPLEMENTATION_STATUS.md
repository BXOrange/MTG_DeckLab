# Implementation Status

> This file tracks the original **phase roadmap**. For the current
> **rules-engine feature coverage** (which keywords, static/activated/triggered
> abilities, effects, and layers are actually implemented) see the in-app
> **"Engine-Status"** tab (`frontend/src/js/implementationStatusView.js`) and
> the [`CLAUDE.md`](CLAUDE.md) project wiki.

## Phase 1: Data Layer (Weeks 1-2)
- [x] Week 1, Day 1-2: Card Model
- [x] Week 1, Day 3-5: DecklisteParser (structural validation only —
      real Commander legality still needs a CardDatabase)
- [ ] Week 2, Day 1-2: GameState Model
- [x] Week 2, Day 3-5: Database & Scryfall — `CardDatabase` (SQLite),
      `ScryfallIntegration`, `LazyCardLoader`, `ImageCache`
      (backend/mtg_analyzer/services/), cached under `backend/cache/`
      (gitignored; export/import: docs/08_CARD_CACHE_EXPORT_IMPORT.md).
      Commander legality and wiring this into `POST /api/decks` are
      still open (see backend/ToDo_Backend.md)
- [x] HTTP API foundation: FastAPI server, `POST /api/decks`,
      `GET /api/cards`, `GET /api/cards/search`,
      `POST /api/cards/resolve`, `GET /api/cards/{id}/image`
      (docs/04_SERVER_CLIENT_ARCHITECTURE.md PART 7 Phase 1)
- [x] Deck persistence — `Deck` model (UUID-identified, `name` just a
      label) + `DeckDatabase` (SQLite, `backend/data/`, NOT disposable
      unlike `backend/cache/`) + `POST /api/decks/save`,
      `GET /api/decks`, `GET /api/decks/{id}`, `DELETE /api/decks/{id}`.
      Reserves `Deck.analysis_id` for the future LLM analysis feature
      (see backend/Done_Backend.md "Deck persistence"; the analysis
      feature itself is backend/ToDo_Backend.md "LLM Deck Analysis").
- [x] Frontend consumes the above instead of calling Scryfall directly
      (`frontend/src/js/api.js`, `cardImages.js`) and adds a
      "Karten-Cache" tab (`cachedCardsView.js`) to browse everything
      currently cached. Verified via API replay against a running
      backend; not yet confirmed with an actual browser render — see
      frontend/ToDo_Frontend.md "Cleanup / polish".
- [x] Frontend consumes deck persistence too: a "Gespeicherte Decks" tab
      (`savedDecksView.js`) plus a save/update control on "Deck
      importieren" (`deckImportView.js`), and a "Detailansicht" toggle
      that renders the deck's card lists as image/mana-cost/oracle-text
      tiles (`cardTile.js`, shared with the Karten-Cache tab) instead of
      plain name+qty rows. Same browser-verification caveat as above.
- [x] Tests passing
- [x] All code committed

## Phase 2: Rules Engine (Weeks 3-4)
- [ ] Effect System
- [ ] Replacement Stacking
- [ ] Phase Engine
- [ ] Tests passing
