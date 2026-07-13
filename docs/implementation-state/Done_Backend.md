# Backend — Done

Completed backend work, split out of
[`../../backend/ToDo_Backend.md`](../../backend/ToDo_Backend.md) (which now
holds only open items). Section headers mirror the ToDo file so a
`Done_Backend.md "<section>"` reference in the code lands here. Remaining
work: [10_COMPLETION_ROADMAP.md](10_COMPLETION_ROADMAP.md).
The original Weeks 1–4 roadmap is archived at
[history/IMPLEMENTATION_STATUS.md](history/IMPLEMENTATION_STATUS.md).

## HTTP API foundation

- [x] Pick and set up a server framework — FastAPI + uvicorn
      (`mtg_analyzer/api/app.py`), CORS open to any localhost port for
      the static frontend dev server.
- [x] `POST /api/decks`: parse + structurally validate a decklist
      server-side (`mtg_analyzer/api/decks.py`, backed by the
      `DecklisteParser` below). Mirrors `frontend/src/js/parser.js`'s
      request/response shape so the client can post its existing
      `{commanderText, mainboardText, sideboardText}` body unchanged.
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
- [x] `GET /api/decks/{id}/validation`: Commander legality of a *saved*
      deck (`saved_decks.py`) — parses + resolves + validates it, sharing
      the exact logic of `POST /api/decks` via
      `services/deck_validation.py` (`validate_deck_sections`/
      `apply_legality`, extracted so the three call sites can't drift).
      Backs the frontend's saved-deck legality badge and the goldfish
      deck picker. `POST /api/game/goldfish` also runs it and **refuses
      to start an illegal deck** (422) — only legal decks may goldfish
      (docs/02 UC3), enforced server-side, not just in the UI.
- [x] `WebSocket /ws/game/{game_id}` connection plumbing
      (`mtg_analyzer/api/game_ws.py`): accepts connections grouped by
      `game_id`, relays a `player_action` message to every connection
      in that game as a `game_state_update`. Transport only — no
      server-held `GameState`. Solo play now goes through the REST
      game-session API (`api/game.py`, `frontend/src/js/goldfishView.js`);
      this WebSocket is kept for the eventual multiplayer push channel,
      not yet wired into the UI (see ToDo "Multiplayer game session").

## Data Layer

- [x] `DecklisteParser`: parse decklist text server-side
      (`mtg_analyzer/parser/deckliste_parser.py`), ported line-for-line
      from the frontend's own parser (multiple qty formats, tag/set
      suffix stripping, structural Commander validation). Also strips
      foil/star markers (`★`/`☆`, e.g. "Sol Ring ★") that otherwise break
      name resolution — mirrored in `frontend/src/js/parser.js`, and the
      import view scrubs them from the textareas too.
- [x] `Validator`: real Commander legality —
      `mtg_analyzer/services/commander_legality.py`, wired into
      `POST /api/decks`. Checks: color identity (union of all commanders'
      identity vs. every other resolved card's), a hand-maintained
      banned-card list (no live source — Scryfall's per-printing
      `legalities` isn't fetched today, so this needs manual updates
      against <https://mtgcommander.net/index.php/banned-list/>), and
      Partner pairing (plain "Partner" pairs with any other plain-Partner
      card; "Partner with X" only pairs with that specifically named card,
      reciprocally — distinguished via `partner_with` even though
      `has_partner` is set for both, see `scryfall_client._has_partner`).
      Doesn't yet cover Backgrounds or "Friends forever" pairing, or
      commander-type eligibility (must be a legendary creature or
      explicitly say it can be a commander).
      Hybrid/Phyrexian/MDFC color identity was verified
      (`test_scryfall_client.py`/`test_api_decks.py`) — all correct for
      free, since `color_identity` is read straight from Scryfall's own
      precomputed whole-card field (`card_from_scryfall_data`) rather than
      derived from the flattened `mana_cost` dict.
      Card *resolution* by front-face and full combined name for
      double-faced cards was fixed in `LazyCardLoader.load_cards` /
      `CardDatabase.get_card`: decklists write these by front face alone
      ("Valki, God of Lies") *or* the full "Front // Back" name
      ("Wear // Tear", pathways, "Halvar…") with single or double slash,
      and Scryfall's `/cards/collection` only matches a *face* name. The
      loader always queries by front face (any slash/spacing) and maps
      the result back to whatever name was requested, so all of these
      resolve; the DB cache matches both directions too
      (`test_lazy_card_loader.py`, `test_card_database.py`).
      `check_commander_legality` returns a `CommanderLegalityResult`
      (not a plain `list[str]`) — `errors` plus `banned_card_names`/
      `color_identity_violation_names`, surfaced on `POST /api/decks` as
      `validation.bannedCardNames`/`.colorIdentityViolationNames`, so the
      frontend can mark the exact offending cards (❗) individually.
- [x] `GameState` / `Player` / `ManaPool` models (docs/07 PART 2):
      `mtg_analyzer/models/game_state.py` (`GameState` + `StackItem`,
      the shared battlefield/stack, turn/phase/step/priority pointers,
      and a light event bus — `fire_event`/`subscribe` — that the rules
      engine hangs trigger collection off; `to_dict` is JSON-safe for
      the WebSocket wire protocol), `models/player.py` (`Player`: life,
      per-player zones as `GameObject` lists, `ManaPool`, per-turn land
      counter, `player_effects` for player-level static/replacement/
      win-condition effects), `models/mana_pool.py` (`ManaPool` — tally
      per `W/U/B/R/G/C` plus a backtracking `can_pay`/`pay` solver for a
      `ManaCost`), plus `models/game_object.py` (`Zone` enum +
      `GameObject`: one *instance* of a `Card` in play, with its own id,
      tapped/summoning-sick/damage/counter state, and the effect lists
      the engine reads) and `models/events.py` (`GameEvent`/`EventType`).
- [x] `CardDatabase` + Scryfall integration + `LazyCardLoader`
      (docs/06, docs/implementation-state/IMPLEMENTATION_GUIDE.md Week 2 Day 4-5):
      `mtg_analyzer/services/card_database.py` (SQLite, one row per
      card storing its `to_dict()` JSON so the schema stays in sync
      with `Card`), `scryfall_client.py` (`ScryfallIntegration`,
      batches lookups via Scryfall's `/cards/collection`), and
      `lazy_card_loader.py` (`LazyCardLoader`: DB first, Scryfall only
      for misses, persists what it fetches). Card images are a separate
      on-disk cache (`services/image_cache.py`) keyed by Scryfall id —
      see docs/Reference/08_CARD_CACHE_EXPORT_IMPORT.md.

## Mana cost model

The `Card.mana_cost` dict only tracks a plain per-symbol pip count with
no concept of *how* a symbol can be paid. Both lossy cost shapes are now
modeled faithfully:

- [x] **Hybrid mana** (`{W/U}`, `{2/W}`, ...) and
- [x] **Phyrexian mana** (`{W/P}`, ...): rather than change
      `Card.mana_cost`'s lossy dict, a new `mana_cost_string` field was
      added to `Card` (the raw Scryfall cost, populated in
      `scryfall_client.py`), and a real per-symbol model built on top:
      `mtg_analyzer/models/mana_cost.py` (`ManaCost.parse` → a list of
      `ManaSymbol`s, each tagged generic/variable/color/colorless/
      hybrid/mono-hybrid/Phyrexian, exposing its `payment_options()`).
      `ManaPool.can_pay`/`pay` solve payment including hybrid choice and
      Phyrexian life payment (`test_mana_cost.py`, `test_mana_pool.py`).
      **Bug fixed:** `pay()` correctly computed the life a Phyrexian pip
      cost, but `RulesEngine.cast_spell` discarded that return value
      instead of applying it, so paying life for `{W/P}` never actually
      drained any (RULE 119.4). Fixed via a new shared `RulesEngine.
      lose_life(player, amount, cause="effect")` choke point (mirrors the
      existing `gain_life`) — every life-loss path (damage's RULE 120.3
      translation, a life-paid cost, a future direct life-loss effect)
      routes through it instead of touching `player.lose_life`/firing
      `LIFE_LOST` ad hoc, so none can forget to fire the event again.
      `cause` ("damage"/"cost"/"effect") is metadata only — nothing in the
      rules distinguishes *why* life was lost for trigger purposes, this
      is just for logging/UI and a future hook. `deal_damage` calls it
      with `cause="damage"`; Phyrexian payment with `cause="cost"`. Tests:
      `test_phyrexian_mana_payment_drains_life`,
      `test_deal_damage_fires_life_lost_with_damage_cause`,
      `test_phyrexian_mana_payment_fires_life_lost_with_cost_cause`,
      `test_rules_engine_lose_life_is_the_shared_choke_point`.
      Stale cached rows (saved before `mana_cost_string` existed)
      deserialize with `""`, which is ambiguous (a land is free; a stale
      Sol Ring is not) — reading it as free let such cards be cast for no
      mana. `ManaCost.from_card` (used by `RulesEngine.mana_cost_of`)
      reconstructs a plain cost from the flat pip tally +
      `converted_mana_cost` when the raw string is missing, so the card
      still costs its real total/colors; hybrid/Phyrexian nuance stays
      unavailable for those stale rows until they're refetched — see
      "Self-healing stale cache rows" below (formerly a ToDo backlog item;
      resolved rather than left as manual backfill work).
- [x] **Self-healing stale cache rows**: schema versioning (below) already
      wipes the *whole* card cache when `models/card.py` changes shape, so
      a genuinely pre-existing stale row can't survive a deployed schema
      change past the first backend start. But a row can still end up
      without `mana_cost_string` some other way post-reconcile — e.g.
      importing an old docs/08 cache export into an already-reconciled DB.
      `Card.has_mana_cost_data` (`models/card.py`) flags this: Scryfall
      gives every non-land an explicit cost string (even a free one is
      `"{0}"`, never blank), so a non-land with a blank
      `mana_cost_string` means the row predates that field, not that the
      card is actually free. `LazyCardLoader.load_cards` treats such a hit
      as a miss and refetches it from Scryfall — healing the DB row in
      place via the normal `save_card` — while falling back to the stale
      copy (not "not found") if that refetch doesn't come back, so a
      previously-working card never regresses. Land rows with a
      legitimately blank cost are left alone. Tests:
      `test_lazy_card_loader.py::TestStaleCachedRows`.
- [x] **X-spell casting** (RULE 601.2b): `{X}` parses to a `VARIABLE`
      symbol worth 0 until announced. `ManaCost.has_variable`/`.with_x(x)`
      resolve every `{X}` in a cost to the chosen value (a copy — the
      parsed cost itself is untouched); `RulesEngine.cast_spell` and
      `GameEngine.can_cast`/`cast_spell` take an `x` argument and apply it
      before the `ManaPool` payment check, and `StackItem.x` records the
      announced value. `GameEngine.legal_actions`' `cast_spell` entries
      flag `has_x`/`max_x` (the highest X currently payable, found by
      scanning down from the pool's total mana) so the UI knows to prompt
      for a value instead of casting outright; `GameSession._dispatch`
      reads `x` off the action dict (default 0). Tests:
      `test_mana_cost.py` (`with_x`/`has_variable`), `test_game_engine.py`
      (`test_x_spell_*`).

## Data model / cache schema versioning

- [x] Detect when a database's on-disk format has drifted from the code
      (`services/schema_version.py`). Both SQLite DBs store `to_dict()`
      JSON blobs, so a model change silently strands old rows — the
      "Sol Ring cast for free" bug (a cached card missing the
      later-added `mana_cost_string`) was exactly this. A SHA-256 over
      the source files defining each DB's stored format is stamped into a
      `schema_meta` table; on open (first access at backend start, since
      the DBs are process-wide singletons) the stored hash is compared to
      the code's. Policy differs per DB: the disposable **card cache**
      clears itself on mismatch (re-fetchable from Scryfall; hash covers
      `models/card.py` + `card_database.py`), while the irreplaceable
      **deck store** never wipes — it records the new hash and warns
      (hash covers `models/deck.py` + `deck_database.py`). Tests:
      `test_schema_version.py`.

## Rules Engine (Phase 2)

Under `mtg_analyzer/game/` (see its `__init__.py` for the map), driven by
the Phase-1 models. Tests: `test_game_engine.py`.

- [x] Effect system: `GameEffect`, `StaticEffect`, `TriggeredAbility`,
      `ReplacementEffect`, `ActivatedAbility` (docs/07 PART 2) —
      `game/effects.py`, plus `WinConditionEffect` (docs/07 PART 9) and a
      `GameContext` facade effects act through so their consequences route
      back through the engine's primitives.
- [x] `EffectRegistry` + core effects — `game/effects.py`:
      `DealDamageEffect`/`DrawCardEffect`/`DiscardEffect`/`DestroyEffect`
      registered by name (the hybrid class+registry design, docs/07
      PART 4). (Oracle-text→effect *parser* is still open — see ToDo.)
- [x] Replacement effect stacking, RULE 616 (docs/07 PART 3) —
      `RulesEngine.apply_replacements`: rewrites an event through each
      applicable replacement at most once (draw→draw-2→mill chains work,
      as does full prevention). Multi-effect ordering is deterministic
      discovery order for now, not the affected player's choice.
- [x] Phases/steps as sequences, RULE 500 (docs/07 PART 1) —
      `game/phases.py` (`TurnSequence`/`GamePhase`/`GameStep`,
      `default_turn_sequence()`); the engine walks it and consults skip
      effects per step (docs/07 PART 8) instead of hardcoding.
- [x] Casting (RULE 601), Stack (RULE 608 LIFO), Mana (RULE 504),
      Priority (RULE 117), Triggered Abilities (RULE 603/607),
      State-Based Actions (RULE 704) — `game/rules_engine.py`. SBAs cover
      life≤0 loss, empty-library draw loss, 0-toughness, lethal damage,
      and the legend rule. Trigger ordering is APNAP by controller only.
- [x] Mana abilities on tap (RULE 605) — `game/mana_abilities.py`
      (`mana_options`): a permanent's tap ability is modeled as a list of
      mutually-exclusive production options (`{colour: count}`). Basics,
      dual/tri lands ("{T}: Add {W} or {U}."), multi-pip (`{C}{C}`), and
      "add one mana of any colour" all parse. `GameEngine.tap_for_mana`
      takes an `option_index`, so a **dual land makes one chosen colour,
      not both** (the bug it fixes); `legal_actions` exposes the options
      per source so the UI can prompt. Tests: `test_mana_abilities.py`.
- [x] Interactive stack (RULE 608): casting now *leaves the spell on the
      stack* instead of auto-resolving, and `GameEngine.pass_priority`
      resolves the top object one at a time — so instants can be cast in
      response before it resolves. The turn loop still auto-resolves the
      stack when advancing a step (all players pass). `resolve_until_stable`
      stops on a pending choice. Tests: `test_game_engine.py`,
      `test_game_session.py`.
- [x] Library search (RULE 701.19) + a general pending-choice mechanism —
      `SearchLibraryEffect` (type-restricted: "Land"/"Creature"/subtype),
      `RulesEngine.request_search`/`resolve_search_choice`. Because *which*
      card is a player choice, the effect opens a `state.pending_choice`
      (JSON-able, travels with rewind snapshots and serializes to the UI);
      the engine pauses resolving until the session answers with a
      `choose`/`decline` action, then moves the card (to hand or
      battlefield) and shuffles. Tests: `test_game_engine.py`.
- [x] More one-shot effects: `GainLifeEffect`, `CounterSpellEffect`
      (removes a spell from the stack to its owner's graveyard, RULE
      701.5), registered in the `EffectRegistry` alongside damage/draw/
      discard/destroy/search.

## Game Engine (Phase 3)

`mtg_analyzer/game/game_engine.py`, tests in `test_game_engine.py`.

- [x] Turn/phase/step loop, event system (docs/02 R4.1) — `run_turn`
      walks the `TurnSequence`, runs step bodies (untap, first-turn
      draw-skip, simplified combat damage, cleanup discard-to-7), opens
      priority windows, and empties mana between steps (RULE 500.4).
- [x] Action validation: legal-actions-for-player logic
      (docs/05 PART 3) — `legal_actions(player)` returns the validated
      set (play land, cast at correct timing/affordability, tap for mana,
      declare attacker, pass), plus per-action `can_*` guards. Wired to
      the frontend goldfish board via the session API.
- [x] Goldfisch mode (UC3): single-player game against real rules —
      exposed as a server-held **game session**
      (`services/game_session.py` `GameSession`/`GameSessionManager`,
      REST in `api/game.py`), on top of an interactive stepping API on
      the engine (`start`/`advance_step`/`auto_play_step`). Adds
      **Restart** and **Rewind** (undo the last move(s)), both via full
      `GameState.clone()` snapshots (`Card.__deepcopy__` shares immutable
      card defs so clones stay cheap, and the step cursor travels with
      each snapshot so a mid-turn undo doesn't jump turns). Endpoints:
      `POST /api/game/goldfish` (from `deckId` or decklist text),
      `GET /api/game/{id}`, `POST /api/game/{id}/action`, `.../rewind`,
      `.../restart`, `DELETE /api/game/{id}`. Tests:
      `test_game_session.py`, `test_api_game.py`.
- [x] Mulligan/setup phase (London mulligan) gating a goldfish game
      before it's playable: `GameSession(require_setup=True)` (only set
      by `GameSessionManager.create_goldfish` — tests building a session
      directly still get the old ungated behaviour) starts with
      `setup.complete = False` and only `mulligan`/`keep_hand` as legal
      actions. `mulligan` reshuffles the hand back and draws a fresh 7,
      incrementing `mulligan_count`; `keep_hand` requires bottoming
      exactly `mulligan_count` chosen cards (`bottom_instance_ids`) before
      normal play unlocks. `restart()` re-enters the setup phase. View
      gains a `setup: {complete, mulligan_count}` field.
- [x] Replay / Puzzle mode: the goldfish's sibling — build an
      arbitrary board (1 player = puzzle, or 2 = with an opponent) and
      play from it, plus JSON save/load. Reuses `GameSession` with
      `mode="replay"`/`require_setup=False`; a family of `edit_*`
      actions (`_edit_dispatch` in `services/game_session.py`) mutate
      state directly — add/remove/move objects across every zone (**tokens**
      only to the battlefield — they cease to exist elsewhere, RULE 111.7),
      tap, transform (flip), set object counters, set life, **poison**
      (new `Player.poison`, 10 ⇒ SBA loss), generic player counters
      (energy/experience — new `Player.counters`), commander damage, and
      turn/phase/active player. Save/load uses a **re-resolvable
      descriptor** (`services/replay.py`: `serialize_replay` /
      `build_replay_engine` / `blank_replay` — models have no
      `from_dict`, so cards are stored by id/name and rebuilt from the
      cache; tokens carry a self-describing block). Endpoints:
      `POST /api/game/replay` (blank `numPlayers` or a loaded
      `replay` descriptor) and `GET /api/game/{id}/replay-export`
      (works for a goldfish session too, so a goldfish position can be
      exported and re-opened here). Tests: `test_replay.py`.

## Auth & persistence

- [x] Deck persistence (save/load instead of re-parsing every time):
      `mtg_analyzer/models/deck.py` (`Deck`, identified by a
      server-generated UUID — `name` is just a label, not unique),
      `services/deck_database.py` (`DeckDatabase`, SQLite, same "JSON
      blob per row" pattern as `CardDatabase`), exposed via
      `saved_decks.py`. Stores raw decklist text only (re-parsed on demand
      via `DecklisteParser`) rather than derived data that could drift.
      Lives under `backend/data/` — unlike `backend/cache/`, this has no
      upstream source to regenerate from, so **don't delete it casually**;
      still gitignored as local dev state. `Deck.analysis_id` is a
      reserved (currently unused) hook for the LLM analysis feature (ToDo).
- [x] Cached `color_identity`/`commanders` on a saved `Deck` (RULE 903.4
      for the color-identity definition) — computing them needs resolved
      `Card` data (a Scryfall/cache lookup per card), too costly to redo on
      every saved-decks list render, so they're derived once and persisted
      rather than recomputed on every read like the rest of the model.
      `services/deck_validation.py`'s `compute_deck_identity(parsed,
      resolved)` unions the commanders' own color identity when every
      commander resolved, else falls back to the union across every
      resolved card in the deck (no commander section, or an unresolved
      one). `api/saved_decks.py`'s `_ensure_identity` fills both in lazily
      on `GET /api/decks` / `GET /api/decks/{id}` the first time they're
      `None` and persists the result; `POST /api/decks/save` resets both to
      `None` only when the decklist text sections actually changed (kept
      otherwise, e.g. a sleeve-only re-save). An empty list is a real,
      computed answer (colorless deck / no commander), distinct from "not
      computed yet". Feeds the frontend's client-side deck-analysis
      heuristics (`Done_Frontend.md` "Deck analysis (UC2)") rather than a
      new endpoint. Tests: `test_api_saved_decks.py`, `test_deck_model.py`.
