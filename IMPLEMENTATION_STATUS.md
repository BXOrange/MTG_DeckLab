# Implementation Status

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
      still open (see backend/TODO.md)
- [x] HTTP API foundation: FastAPI server, `POST /api/decks`,
      `GET /api/cards`, `GET /api/cards/search`,
      `POST /api/cards/resolve`, `GET /api/cards/{id}/image`
      (docs/04_SERVER_CLIENT_ARCHITECTURE.md PART 7 Phase 1)
- [x] Frontend consumes the above instead of calling Scryfall directly
      (`frontend/src/js/api.js`, `cardImages.js`) and adds a
      "Karten-Cache" tab (`cachedCardsView.js`) to browse everything
      currently cached. Verified via API replay against a running
      backend; not yet confirmed with an actual browser render — see
      frontend/TODO.md "Cleanup / polish".
- [x] Tests passing
- [x] All code committed

## Phase 2: Rules Engine (Weeks 3-4)
- [ ] Effect System
- [ ] Replacement Stacking
- [ ] Phase Engine
- [ ] Tests passing
