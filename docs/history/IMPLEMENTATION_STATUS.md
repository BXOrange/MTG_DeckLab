# Implementation Status  ·  *(archived roadmap)*

> **📦 Historical record.** This tracked the original Weeks 1–4 **phase
> roadmap**; Phases 1–3 are functionally complete, so it's archived here for
> provenance and no longer maintained. For live status use, in order:
> - **Remaining work, dependency-ordered:**
>   [`docs/10_COMPLETION_ROADMAP.md`](../10_COMPLETION_ROADMAP.md)
> - **Granular open items:** [`backend/ToDo_Backend.md`](../../backend/ToDo_Backend.md),
>   [`frontend/ToDo_Frontend.md`](../../frontend/ToDo_Frontend.md)
> - **User-facing feature coverage:** the in-app **"Engine-Status"** tab
>   (`frontend/src/js/implementationStatusView.js`)
> - **Orientation:** [`CLAUDE.md`](../../CLAUDE.md)

## Phase 1: Data Layer (Weeks 1-2)
- [x] Week 1, Day 1-2: Card Model
- [x] Week 1, Day 3-5: DecklisteParser (structural validation only —
      real Commander legality still needs a CardDatabase)
- [x] Week 2, Day 1-2: GameState Model — `GameState` + `StackItem`
      (`models/game_state.py`), `Player` (`models/player.py`), `ManaPool`
      (`models/mana_pool.py`), `GameObject`/`Zone` (`models/game_object.py`),
      `GameEvent`/`EventType` (`models/events.py`). See
      backend/Done_Backend.md "GameState / Player / ManaPool models".
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
- [x] Effect System — `GameEffect`/`StaticEffect`/`TriggeredAbility`/
      `ReplacementEffect`/`ActivatedAbility` + `EffectRegistry`
      (backend/mtg_analyzer/game/effects.py). See backend/Done_Backend.md
      "Rules Engine (Phase 2)".
- [x] Replacement Stacking — `RulesEngine.apply_replacements` (RULE 616);
      multi-effect ordering is deterministic discovery order, not yet the
      affected player's choice (backend/ToDo_Backend.md).
- [x] Phase Engine — `game/phases.py` `TurnSequence`, walked by the engine
      with per-step skip effects (RULE 500).
- [x] Tests passing — 547 backend tests green (`pytest backend/tests/`).

> Phase 2/3 are functionally **built** (full turn/stack/SBA loop, combat +
> keywords, layer system, activated/triggered/static abilities, targeting,
> mana). The remaining rules-engine work is tracked granularly in
> backend/ToDo_Backend.md ("Rules Engine (Phase 2) — remaining",
> "Card-type & structural coverage") and shown to users in the in-app
> **Engine-Status** tab. The single biggest open piece is the oracle-text →
> effect **NLP parser** (docs/09): without it, spells resolve as no-ops
> unless a card is in the hand-authored `ability_catalogue.py`.
