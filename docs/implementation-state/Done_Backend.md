# Backend — Done

**Worklog** (append-only): completed backend work and *why it was built that
way*. Open work lives in [BACKLOG.md](BACKLOG.md); parser-tail strategy and
worked examples in [PARSER_LONG_TAIL.md](PARSER_LONG_TAIL.md). Remaining
plan: [10_COMPLETION_ROADMAP.md](10_COMPLETION_ROADMAP.md).

Section headers are stable — a `Done_Backend.md "<section>"` reference from
the code lands here. Entries written before 2026-07-27 cite a
`ToDo_Backend.md`/`ToDo_Frontend.md` that no longer exists; both were merged
into `BACKLOG.md`, and those mentions have been repointed there.

## Configuration

- [x] Centralized on-disk paths + small runtime constants into
      `mtg_analyzer/config.py`, overridable via environment variable.
      Previously `CACHE_ROOT`/`DEFAULT_DB_PATH` (`card_database.py`),
      `DATA_ROOT`/`DEFAULT_DECKS_DB_PATH` (`deck_database.py`),
      `DEFAULT_PLAYER_ASSETS_DB_PATH` (`player_assets.py`), and the
      Scryfall/`ImageCache` User-Agent + rate-limit constants
      (`scryfall_client.py`, `image_cache.py`) were each a hard-coded
      module constant with no override hook, so a one-off script or
      test run had no way to avoid colliding with a real dev server's
      cache/saved-decks (a real risk once schema versioning could
      *clear* a stale cache on open, not just read it). `config.py`
      exposes `CACHE_DIR`/`DATA_DIR` (env `MTG_CACHE_DIR`/`MTG_DATA_DIR`),
      the derived `DB_PATH`/`IMAGE_CACHE_DIR`/`DECKS_DB_PATH`/
      `PLAYER_ASSETS_DB_PATH`, and `USER_AGENT`/
      `SCRYFALL_MIN_REQUEST_INTERVAL_SECONDS` (env `MTG_USER_AGENT`/
      `MTG_SCRYFALL_MIN_REQUEST_INTERVAL`), all defaulting to the
      previous hard-coded values. `api/dependencies.py`'s singletons
      now import their paths from `config.py` directly rather than
      from each service module; the service modules keep their old
      constant names (`CACHE_ROOT`, `DEFAULT_DB_PATH`, etc.) as
      backward-compatible aliases onto the `config.py` values, so
      nothing importing them broke. Tests: `test_config.py` (env-var
      overrides, incl. that they flow through to the service modules).

- [x] **Offline startup** (2026-07-28). An audit of what a start actually
      fetches found exactly one internet dependency, and it was in the
      setup scripts rather than the app: `setup/start.py` calls
      `ensure_backend_venv()` on *every* run, and that ran
      `pip install --upgrade pip` unconditionally — a PyPI query on each
      start, `check=True`, so a network outage aborted startup of an
      otherwise fully-installed app. Everything else was already local:
      the frontend loads no external script/stylesheet/font/image
      (`index.html` references only `src/**`, `main.css` uses system font
      stacks) and reaches only the configured backend; card data and art
      come from the on-disk `CardDatabase`/`ImageCache`; tokens, dungeons
      and the RULE 9 variant cards are committed JSON in
      `mtg_analyzer/data/`; and nothing in `api/app.py`'s lifespan or the
      `api/dependencies.py` singletons opens a connection (constructing an
      `httpx.Client` doesn't).
      The fix inverts pip's order: `setup/install.py` now installs
      **offline first** (`pip install --no-index [--find-links wheelhouse]
      -r requirements.txt`), which resolves purely from what's installed
      and so is *guaranteed* connectionless — and, when the venv is
      already complete, is also the fast path (~0.2s vs. several seconds
      of index traffic, so the whole `./start.sh` preamble went from
      network-bound to 0.3s). Only when that fails is an index-using run
      attempted, gated on a 2s TCP probe of `pypi.org:443` rather than on
      pip's own tens-of-seconds retry stall, so "no internet + missing
      dependency" fails immediately with an actionable message instead of
      hanging. The self-upgrade of pip now runs only right after creating
      a brand-new venv, and is non-fatal.
      For the one case that genuinely can't be served locally — a *fresh*
      venv with no network — `python3 setup/install.py --download-wheels`
      caches every requirement as a wheel in `setup/wheels/` (gitignored:
      wheels are OS/arch/Python-version specific, a cache rather than a
      committed asset), and every later install passes `--find-links` at
      it. Verified end-to-end: a brand-new venv installs the full
      requirements set from the wheelhouse with `--no-index`, and the
      backend serves `/api/health` with every outbound HTTP proxy pointed
      at a dead port. Tests:
      `test_setup_offline_start.py` (the happy path issues exactly one
      pip command, it carries `--no-index`, and the network probe is
      never called; no unconditional `--upgrade`; offline + missing
      dependency raises pointing at `--download-wheels`; online falls
      back to an index run; the wheelhouse is only passed when it holds
      wheels).

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
- [x] `WebSocket /ws/game/{game_id}` (`mtg_analyzer/api/game_ws.py`):
      accepts connections grouped by `game_id` and now runs each
      client's `player_action` through the `GameSession` registered
      under that id in the same process-wide `GameSessionManager` the
      REST session API (`api/game.py`) uses (`api/dependencies.
      get_game_session_manager`), broadcasting the resulting session
      view (`GameSession.view()`) to every connection on that `game_id`
      as a `game_state_update`; an unknown `game_id` or a
      `GameActionError` (illegal/malformed action) replies to the
      sender alone. Solo play still goes through the REST game-session
      API directly (`frontend/src/js/goldfishView.js`); this channel is
      what a future interactive multiplayer session would use to push
      an opponent's moves — `create_multiplayer` itself is still a
      stub and the channel isn't wired into any frontend view yet
      (`frontend/src/js/gameSocket.js` exists but is unused — see ToDo
      "Multiplayer game session").

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
      as does full prevention).
- [x] Replacement ordering — interactive, by the affected player (RULE
      616.1e/f), not just deterministic discovery order — `apply_
      replacements` now takes an optional `on_resolved` continuation: when
      exactly one replacement applies at a step it's used automatically
      (unambiguous — the common case, and the whole reason single-effect
      callers/tests keep working unchanged), but when 2+ apply
      simultaneously it opens a `replacement_order` `pending_choice` and
      pauses — `resolve_replacement_order_choice` applies the one picked,
      then re-opens a fresh choice if more still apply (616.1f) or finishes
      and invokes the continuation with the final event. Mirrors RULE
      603.3b's trigger-order pause/resume (`put_triggers_on_stack`/
      `resolve_trigger_order_choice`) but — unlike that opt-in,
      off-by-default flag — is always interactive: replacement collisions
      are rare (they need 2+ conflicting effects actually on the
      battlefield at once) and, when they happen, always meaningful, so
      there's no casual-play case worth deterministic-by-default here.
      `deal_damage`/`_single_draw`/`add_counters`/`create_token` (battlefield
      tokens only) all now route through the continuation form; a
      choice already pending when a second ambiguous event arrives in the
      same synchronous batch (e.g. two blocked attackers' damage in one
      combat-damage step) isn't clobbered — that second event just falls
      back to deterministic discovery order rather than overwriting the
      first choice or silently dropping it. Also added: `EventType.COUNTER`/
      `CREATE_TOKENS` (so counters-being-placed and battlefield token
      creation are "would happen" events replacement effects can see at
      all, alongside the pre-existing `DAMAGE`/`DRAW`), and `source_id`/
      `source_controller_id`/`source_colors`/`combat` on the `DAMAGE` event
      so a replacement can filter by "a source you control"/"a red
      source"/"combat damage". Four new `ReplacementRegistry` families ride
      on top: `double_damage`/`additional_damage` (multiplicative vs.
      additive damage replacement — order genuinely changes the total:
      double-then-add ≠ add-then-double) and `double_counters`/
      `double_tokens`. Hand-authored in `ability_catalogue.py`: Furnace of
      Rath (unscoped `double_damage`), Gratuitous Violence (`double_damage`,
      your combat damage only), Torbran, Thane of Red Fell (`additional_
      damage`, your red sources' damage to an opponent, +2), Doubling
      Season (`double_tokens` + `double_counters` — the counter clause is
      deliberately unscoped, matching the real card doubling an opponent's
      poison counters too), Parallel Lives (`double_tokens` alone — paired
      with Doubling Season as the order-invariant-but-still-must-ask
      616.1e example: both double, so the final token count is the same
      either way, yet the choice is still required). Frontend: the
      `replacement_order` `pending_choice` gets a dedicated drag-and-drop
      popup (`gameBoardView.js` `replacementOrderHtml`/
      `confirmReplacementOrder`) rather than the generic one-button-per-
      option list every other choice kind shares — the only drag-and-drop
      UI in the frontend so far; dragging is a purely client-side
      convenience that then replays the chosen order as a sequence of the
      same single `choose` picks the backend already expects, stopping
      the auto-play (never submitting a stale pick) if the server's
      re-offered option set doesn't match what was dragged. Tests:
      `test_replacement_ordering.py`.
- [x] Layer 6 ability-adding grant of a *non-keyword* ability (RULE
      613.7f) — two real cards, Tyvar Kell ("Elves you control have
      '{T}: Add {B}.'") and Dionus, Elvish Archdruid ("Elves you control
      have '\<a triggered ability\>'"), needed a grant richer than a bare
      keyword slug. New `EffectSpec` types `grant_mana_ability` (`mana`, a
      `mana_options`-shaped list) and `grant_triggered_ability`
      (`trigger_event`, `grant_effects` — nested one-shot-effect specs
      through the same `EffectRegistry` whitelist, `once_per_turn`,
      `optional`, `controllers_turn_only`), docs/11 §6.
      `mana_abilities.mana_options_for(obj)` folds the grant onto the
      permanent's own printed options (`game_engine.py`'s 3 call sites
      switched to it). A granted *triggered* ability needed a genuinely
      new primitive: a stable instance per (granting ability, affected
      object) relationship (`GameState._granted_ability_cache`), rebuilt
      from cache every recompute rather than freshly constructed, so
      per-instance state — `TriggeredAbility.once_per_turn`/
      `_last_triggered_turn` (also new; RULE 603.2) — survives across
      passes; the cache is pruned back to only currently-valid
      relationships every pass, so the grant (and its turn-tracking)
      disappears the instant it stops applying, no separate removal code
      (RULE 613.6). Each grantee gets its *own* scoped instance
      (`continuous._granted_trigger_condition`, matched on the firing
      event's `instance_id`) — without it, e.g. tapping one Elf would
      incorrectly fire every other Elf's copy of the same granted ability
      too. Needed a real primitive that plain didn't exist: a `TAPPED`
      event (RULE 701.21b, "whenever ~ becomes tapped") —
      `RulesEngine.set_tapped` now fires it on a genuine untapped→tapped
      transition (never for a permanent entering already tapped, matching
      the real "becomes tapped" ruling), and the three call sites that
      used to tap a permanent via the bare `GameObject.tap()` (declare
      attackers, `tap_for_mana`, `activate_ability`'s tap cost) now go
      through it. `TapEffect` gained the same untargeted self-acting mode
      `AddCountersEffect` already had (`target_kind=None` → acts on the
      effect's own source, no player choice). Registered: `Tyvar Kell`,
      `Dionus, Elvish Archdruid` (`ability_catalogue.py`) — static clauses
      only; their loyalty abilities/emblem are a separate, unrelated gap.
      Tests: `test_static_ability_grants.py`.
- [x] Phases/steps as sequences, RULE 500 (docs/07 PART 1) —
      `game/phases.py` (`TurnSequence`/`GamePhase`/`GameStep`,
      `default_turn_sequence()`); the engine walks it and consults skip
      effects per step (docs/07 PART 8) instead of hardcoding.
- [x] Casting (RULE 601), Stack (RULE 608 LIFO), Mana (RULE 504),
      Priority (RULE 117), Triggered Abilities (RULE 603/607),
      State-Based Actions (RULE 704) — `game/rules_engine.py`. SBAs cover
      life≤0 loss, empty-library draw loss, 0-toughness, lethal damage,
      and the legend rule. Trigger ordering is APNAP-by-controller by
      default (see the next two entries for the interactive choices layered
      on top).
- [x] Trigger ordering *within* a controller (RULE 603.3b) — when
      `state.interactive_ordering` is on and the active player has two or
      more simultaneous triggers, `put_triggers_on_stack` opens an
      `order_triggers` `pending_choice`; `resolve_trigger_order_choice`
      places them in the chosen order (picked-first → placed-first →
      resolves-last). Off by default so solo goldfishing is unchanged —
      APNAP-by-controller placement (above) is what happens when it's off.
      Tests: `test_ordering.py`.
- [x] Triggered-ability target choice (RULE 115 / 603.3c / 603.5) — a
      triggered ability's own targeting effect used to place blind
      (`_place_trigger` pushed a `TriggeredAbility` with no `targets` at
      all). `put_triggers_on_stack`/`RulesEngine._place_triggers` now
      check each queued trigger's first targeting effect
      (`_trigger_target_spec`) and, if it has one, open a `trigger_target`
      `pending_choice` — one option per legal target, built the same
      `{"id","label","instance_id"?}` shape as search/cascade/discover/
      order_triggers, so the existing generic choice UI renders it with
      zero frontend changes. `resolve_trigger_target_choice` places the
      chosen target (or, for an optional/"you may" ability, honours a
      "decline" option) and resumes whatever else was queued behind it; a
      *required* target with no legal option at all never goes on the
      stack (RULE 603.3c), matching real rules exactly rather than
      resolving with an absent target. Also covers RULE 603.5 for a
      targetless "you may" — previously `TriggeredAbility.optional` was
      carried but never consulted, so e.g. "you may draw a card" always
      just happened; now it opens a plain do/decline choice
      (`_trigger_may_choice`, the `"do"` sentinel
      `resolve_trigger_target_choice` recognizes) before placing. Wired
      into `GameEngine.resolve_pending_choice` (`kind == "trigger_target"`)
      — answered through the same session `choose`/`decline` action as
      every other pending choice. Tests: `test_trigger_targeting.py`.
- [x] **ENG-4** — combining manual trigger-ordering (RULE 603.3b) with a
      targeted/modal/optional trigger among the ordered set. Previously
      `resolve_trigger_order_choice` placed the picked ability with a bare
      `_place_trigger(ability)`, bypassing every pause the deterministic
      path already had — a targeted trigger went on the stack with no
      target at all, "you may" always just happened. Fixed by routing the
      picked ability through `_place_triggers` as a one-item queue
      (`[(ability, event)]`) instead of calling `_place_trigger` directly —
      the *same* mode/target/"you may" pausing the deterministic path uses
      (`_place_or_pause_trigger`) now applies unconditionally, since
      ordering no longer has its own placement branch. The one new piece is
      `_maybe_continue_ordering` (called at the tail of `_place_triggers`'s
      `while queue:` loop, only when it drains without pausing): it resumes
      the ordering flow — re-opens `order_triggers` while 2+ of the active
      player's triggers are still unordered, places the last one directly
      once none remain to choose between (still through `_place_triggers`,
      so still pause-aware), then flushes the non-active-player ("rest")
      queue the same way. It's a no-op outside an ordering sequence
      (`_ordering_active`/`_ordering_rest` are only ever non-empty while one
      is in progress), so the plain APNAP-by-controller path is unaffected.
      Tests: `test_ordering.py`.
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
- [x] Loyalty / planeswalker abilities (RULE 606) — `costs.
      ActivationCost.loyalty` (a signed `[±N]` cost, parsed by
      `_LOYALTY_RE` + the segmenter's `[±N]:` recognition); planeswalkers
      enter with printed starting loyalty (`Card.loyalty`, set in
      `add_to_battlefield`); `GameEngine._can_activate_loyalty` gates to
      sorcery speed + once-per-turn (`activated_loyalty_this_turn`, reset
      at untap); activation pays by changing loyalty counters; combat/
      other damage to a planeswalker removes loyalty (`deal_damage`); the
      0-loyalty SBA (RULE 704.5i) sends it to the graveyard. Tests:
      `test_planeswalker.py`. Not yet: the specific chapter/loyalty
      *effects* beyond what the handler table already covers.
- [x] Aura / Equipment **attachment resolution** (RULE 303 auras, 301.5
      equipment, keyword `equip`/`fortify`/`reconfigure` RULE
      702.6/67/151) — an Aura attaches to its cast-time target on
      resolution (RULE 303.4f, `RulesEngine.resolve_top_of_stack`; fails
      to attach → straight to the graveyard); Equip/Fortify/Reconfigure
      are live sorcery-speed activated abilities
      (`effect_binder._keyword_activated_ability`, untapped/re-payable per
      RULE 301.5c/702.151b); targeting is restricted to what each can
      legally attach to (`targeting.legal_targets`,
      `RulesEngine._attachment_legal` — creatures/artifacts for Equip,
      creatures for Reconfigure, **lands for Fortify** (301.5c — fixed
      2026-07-15: `targeting.py`/`_attachment_legal` recognized
      `equip`/`reconfigure`/`enchant` but had no `fortify` case, so it fell
      through to "any permanent" instead of narrowing to lands; both now
      have an explicit branch, `test_fortify_ability_only_offers_land_
      attachment_targets`), the Aura's `enchant` quality otherwise). RULE
      704.5m/n on the host
      leaving: an Aura goes to the graveyard, an Equipment/Fortification/
      Reconfigure permanent just becomes unattached and stays on the
      battlefield (`RulesEngine._detach_attachments_from`). RULE 702.151b:
      a Reconfigure permanent stops being a creature while attached and
      regains it the moment it's unattached (`GameObject._removed_types`,
      computed in `continuous.recompute`'s layer-4 pass). The attached
      buff/keyword flows through the layer engine via
      `affects="attached_permanent"` (resolves off the ability source's
      own `attached_to`). Tests: `test_game_engine.py` (aura/equipment/
      reconfigure attach+detach+buff tests), `test_continuous.py`.
      Remaining: re-validating an *existing* attachment's legality every
      SBA pass (RULE 704.5m/n also cover a target that stays on the
      battlefield but becomes illegal, e.g. by gaining protection — today
      only "host left the battlefield" is checked).
- [x] Commander tax (RULE 903.8) — `Player.commander_casts` (instance id
      → count) is incremented on a command-zone cast in
      `GameEngine.cast_spell`; `effective_cast_cost` adds `{2}` per
      previous cast via `commander_tax()`, floored generic, and surfaced
      in the cast action (`commander_tax`/`effective_cost`). The counter
      deep-copies with the player for rewind. Tests: `test_game_engine.py`
      `test_commander_tax_adds_two_per_previous_cast`.
- [x] Commander zone-replacement choice (RULE 903.9a/9b, 2026-07-15) —
      previously `_move_to_graveyard`/`counter_spell` *unconditionally*
      diverted a commander straight to the command zone (never actually
      touching the graveyard even briefly, and with no real "may"), while
      `exile()` skipped the diversion entirely (an incorrect docstring
      claimed 903.9 was graveyard/death-only) and `return_to_hand()`
      offered no diversion at all. Replaced with a real, owner-chosen
      `pending_choice`, split along the rule's own two mechanisms:
      **903.9a** (graveyard/exile — a *state-based action*): the commander
      now actually lands in the graveyard/exile first;
      `RulesEngine._flag_commander_zone_choice` marks it eligible, and a new
      `_sba_pass` clause (checked once, right after the legend rule) opens
      a `commander_zone` `pending_choice` the next time SBAs are checked —
      not baked into the move itself. **903.9b** (hand, and — once a
      battlefield→library effect exists — library — a *replacement
      effect*): `return_to_hand()` reuses the same default-then-fixup shape
      the shock-land `land_tapped` choice already established (object
      lands in hand as the "declined" outcome, `pending_choice` opens
      immediately to redirect it). Both share one builder/resolver pair,
      `_commander_zone_choice`/`resolve_commander_zone_choice`
      (`"command"` moves it via `GameState.find_object` + `owner.add_to_zone`;
      anything else leaves it put), wired into `GameEngine.
      resolve_pending_choice`'s dispatch under kind `"commander_zone"`. Also
      now flagged from `mill()`/`discard()`'s direct graveyard writes (a
      commander milled/discarded from hand/library, not just one dying off
      the battlefield). A new `_sba_pass` top-of-loop
      `if self.state.pending_choice: return False` guard stops the SBA
      fixpoint loop cleanly once the choice opens (no prior SBA opened a
      `pending_choice` mid-pass, so this needed adding). Frontend: the
      generic `pending_choice` modal needed no new rendering code (same
      `options`/`kind` shape every other choice uses); `gameBoardView.js`'s
      `CHOICE_ICONS` gained a `commander_zone` entry (👑). Tests:
      `test_game_engine.py`
      (`test_commander_dying_offers_command_zone_choice_and_can_move_there`,
      `test_commander_dying_choice_declined_stays_in_graveyard`,
      `test_countered_commander_spell_offers_command_zone_choice`,
      `test_exiled_commander_offers_command_zone_choice`,
      `test_bounced_commander_offers_command_zone_choice`,
      `test_bounced_commander_choice_declined_stays_in_hand`,
      `test_non_commander_permanent_never_offers_command_zone_choice`).
      Still open: a battlefield→library ("tuck") effect family (no code
      path exists yet for 903.9b's library half to apply to).
- [x] Conditional enters-tapped choice (RULE 614.1 replacement) —
      `ability_catalogue.land_tap_condition(card)` classifies a land's
      tapped-entry clause off its oracle text: `"always"` (plain
      tap-land), `"never"` (no clause, or an unrecognized conditional
      shape — fails safe untapped), `"pay_life"` (shock lands: "you may
      pay N life. If you don't, ~ enters tapped."), `"unless_types"`
      (check lands: "unless you control a/an X [or a/an Y …]"), or
      `"unless_count"` (fast/slow lands: "unless you control N or
      fewer/more other lands"). `RulesEngine.enter_land_tapped`, called
      from `GameEngine.play_land`, resolves the deterministic shapes
      immediately against the board the controller already has
      (evaluated before the land itself joins the battlefield, so "other
      lands" naturally excludes it); a shock land opens a genuine
      `land_tapped` `pending_choice` (tapped by default, as if declined)
      — `resolve_land_tapped_choice("pay")` pays the life
      (`RulesEngine.lose_life`) and flips it untapped, reusing the same
      `pending_choice`/`resolve_pending_choice` plumbing as search/
      cascade/trigger-target choices. Pain lands (no "enters tapped" text
      at all) and other unrecognized conditional shapes are untouched.
      Tests: `test_ability_catalogue.py`.
- [x] "Become a copy of target permanent/creature" (RULE 706/707) — three
      distinct mechanisms, all sharing `game/copy_mechanics.py`'s mutate/
      snapshot/restore primitives (`become_copy`/`snapshot_face`/
      `restore_face`, moved out of `rules_engine.py` so `continuous.py` can
      call them without an import cycle):
      1. **Permanent ETB copy** (Clever Impersonator/Phantasmal Image/Copy
         Artifact) — now wired through **true RULE 614.1c/614.12
         replacement timing**, not the previous ENTERS_BATTLEFIELD-trigger
         simplification: an `enter_replacement` `AbilitySpec`/
         `enter_as_copy` `EffectSpec` binds an `EnterAsCopyReplacement`
         onto `GameObject.enter_as_copy_effects`, and `RulesEngine.
         _resolve_permanent_spell`/`_offer_enter_as_copy` (called from
         `resolve_top_of_stack`) offer/resolve the choice — opening a new
         `enter_as_copy` `pending_choice` if there's a legal target —
         *before* the object is ever added to the battlefield/fires
         ENTERS_BATTLEFIELD, so it's never observably "itself" first (the
         old trigger-based version's actual bug: the fired event carried no
         `instance_id`, so the trigger couldn't even scope to its own
         entry). `resolve_enter_as_copy_choice` finishes the job via
         `copy_mechanics.become_copy`. `create_token`'s token-creation path
         still doesn't offer this (a token copy of one of these cards is a
         known, scoped, undemonstrated-by-any-card gap — see its
         docstring).
      2. **Continuous conditional copy** (Vesuvan Shapeshifter's "as long as
         untapped, ~ is a copy of another target creature") — a genuine new
         RULE 613 **layer 1**, `continuous._apply_copy_layer`: transition-
         only (only mutates on a condition/target *change*, never every
         pass — re-running `become_copy` unconditionally would destroy
         per-turn bookkeeping on the copy's own granted triggered
         abilities) and, per the real card's ruling, permanently "locks in"
         once it copies a creature with no equivalent ability (no "ability
         disappeared → revert" branch). `RulesEngine.set_copy_target`
         (`GameObject.copy_target_id`) and a new `conditional_copy`
         `EffectSpec` → `StaticAbility("copy", …)` drive it.
      3. **Temporary "… until end of turn" copy** (Cursed Mirror) —
         `RulesEngine.become_copy_until_end_of_turn`, reverted by
         `GameEngine._step_cleanup` (RULE 514.2, the same step that already
         ends pump/keyword "until end of turn" effects) via a stashed
         `GameObject._copy_until_eot_base` snapshot.

      `Card.as_copy` (name, mana cost, colours, type/subtypes, rules text,
      P/T, loyalty; RULE 706.2) is the shared copiable-values computation
      underneath all three; everything RULE 706.2 doesn't cover (instance
      id, zone, owner, controller, counters, tapped state, attachments) is
      untouched. Tests: `test_card.py` (`TestAsCopy`),
      `test_ability_catalogue.py`, `test_continuous.py`
      (conditional-copy section), `test_effect_binder.py`,
      `test_effect_families.py` (cleanup-reverts-the-until-EOT-copy),
      `test_game_engine.py` (`test_become_copy_*`, `test_cursed_mirror_*`),
      `test_trigger_targeting.py`.

- [x] **M2 combat-math keywords + hexproof (2026-07-15):** the first
      parametric keywords beyond landwalk to get real behaviour, not just a
      carried parameter. **Annihilator** (702.86), **afflict** (702.130) and
      **bushido** (702.45) are each genuinely triggered abilities, so rather
      than special-casing them procedurally in `game/combat.py` alongside the
      static evasion keywords, `effect_binder._keyword_triggered_abilities`
      synthesizes real `TriggeredAbility` objects at bind time (mirroring
      `_keyword_activated_ability`'s existing Equip/Fortify/Reconfigure
      treatment) — they go through the ordinary stack/priority pipeline, so a
      player can respond to any of them. Afflict/bushido's "becomes blocked"
      half needed a genuinely new hook: `models/events.py` gained
      `EventType.BECOMES_BLOCKED`, fired once per attacker (never once per
      blocker) by `GameEngine.declare_blockers` the moment its `blocked_by`
      transitions from empty to non-empty within one call — distinct from the
      existing per-blocker `BLOCKS` event, which can't express "the attacker
      became blocked" at all. New one-shot effects: `SacrificeEffect`
      (+ `RulesEngine.sacrifice`/`GameContext.sacrifice`, an MVP auto-choice
      mirroring `GameEngine._sacrifice_candidate`'s cost-payment convention)
      and `LoseLifeEffect` (+ `GameContext.lose_life`, a thin wrapper over the
      pre-existing `RulesEngine.lose_life`); bushido reuses the existing
      `PumpEffect` unchanged. Annihilator/afflict resolve "defending player"
      dynamically via a new `effects._defending_player_of` helper reading the
      attacker's `combat_defender` spec (works for both a player and a
      planeswalker defender). Separately, **hexproof** (702.11b) now actually
      gates targeting — `combat.has_hexproof` (reads the parser-bound
      `intrinsic_keywords`, same as every other flag keyword) plugs into
      `targeting._targetable_by` (renamed from `_not_protected`, now covering
      both protection and hexproof at every one of its call sites), excluding
      a hexproof permanent from an *opponent's* target options while leaving
      it targetable by its own controller. **Deliberately deferred**:
      **rampage** (702.23) needs its pump amount to scale with the specific
      block's final blocker count, and `TriggeredAbility` binds one fixed
      `effects` list once at bind-on-load, reused for every firing
      (`RulesEngine._place_trigger` — no per-firing event data reaches
      `apply()`) — a per-event dynamic-amount seam none of the other three
      keywords need; **ward** (702.21) needs a "becomes the target"
      interception point cutting across both `cast_spell` and
      `activate_ability`, architecturally different from "add a new event
      type" (the pay-or-counter mechanics themselves are directly reusable
      from `RulesEngine.counter_unless_pays` — see the next entry, which
      built exactly that). Tracked in `BACKLOG.md`. Tests:
      `test_game_engine.py`
      (`test_annihilator_makes_defending_player_sacrifice_permanents`,
      `test_afflict_causes_defending_player_to_lose_life_on_block`,
      `test_bushido_pumps_the_blocker_when_it_blocks`,
      `test_hexproof_creature_cannot_be_targeted_by_an_opponent`).

- [x] **M2 ward (2026-07-15, revised 2026-07-15):** RULE 702.21's "whenever
      this permanent becomes the target of a spell or ability an opponent
      controls, counter it unless they pay [cost]." First shipped as an
      inline `pending_choice` (a `counter_unless_pays`-style simplification);
      **revised the same day to be genuinely rules-accurate** — RULE 603.3
      says a triggered ability "puts it on the stack... the next time a
      player would receive priority," becoming the topmost object, so both
      players get a normal priority window to respond to it (an instant, an
      activated ability) before it resolves. The inline-choice version
      skipped that window entirely; the fix was to stop resolving ward
      synchronously and instead push a **real `StackItem`**.

      The interception point is the same three call sites as before —
      `RulesEngine.cast_spell`/`cast_without_paying` and `_place_trigger`,
      plus `GameEngine.activate_ability` — each already builds a `StackItem`
      with its final `targets` and calls `RulesEngine.check_ward(item,
      caster)` right after. `check_ward` now pushes one `StackItem` per
      warded target found (`kind="ability"`, `controller_id` = the *warded
      permanent's* controller per RULE 603.3a — the caster only pays it,
      doesn't control it), each wrapping a new `WardEffect(item, caster_id,
      cost)`. It's constructed directly rather than routed through the
      generic `TriggeredAbility`/event-collection pipeline
      (`_collect_triggers`/`put_triggers_on_stack`) — that pipeline binds one
      fixed `effects` list once at bind-on-load and reuses it for every
      firing (the same limitation that deferred rampage, M2 combat-math
      entry above), but ward's effect needs per-firing data (which item,
      which caster) that a bind-once list can't carry, so it's built fresh
      per trigger instead. Since `.append()` puts the ward ability on top and
      `resolve_top_of_stack` pops LIFO, it resolves before the item that
      triggered it with no other change needed — normal `pass_priority`/
      `resolve_until_stable` carries it exactly like any other stack object.
      `WardEffect.apply` calls the new `RulesEngine.resolve_ward_effect`,
      which no-ops if the item already left the stack (RULE 608.2b/603.10
      "look back in time" — e.g. a second simultaneous ward already
      countered it, RULE 702.21c: multiple wards need no special sequencing
      code at all now, since each is its own stack object and the stack
      naturally resolves them one at a time), otherwise opens the same
      pay-or-counter `pending_choice` shape `counter_unless_pays` uses, keyed
      to the *caster* rather than the target's controller.

      **Cost types**: originally mana-only. Ward's cost is now recognized and
      paid through the same vocabulary an activated ability's cost already
      uses (RULE 602.1 mana/pay-life/discard/sacrifice —
      `game/costs.parse_activation_cost`/`ActivationCost`), not a
      `ManaCost`-only path. The parser side needed a fix too: `keywords.py`'s
      shared COST-shape regex only recognizes a `{...}` mana run, so
      "Ward—Discard a card."/"Ward—Pay 3 life."/"Ward—Sacrifice a creature."
      previously fell back to a bare, cost-less keyword spec (silently
      unmodeled). A new Ward-specific fallback regex (`_WARD_TEXT_COST_RE`,
      consulted only when the mana regex finds nothing) captures the free
      text instead, scoped to just Ward — not the ~50 other COST-shaped
      keywords in the table, which are mana-only on every real card and
      didn't need touching. `RulesEngine._can_pay_ward_cost`/`_pay_ward_cost`
      mirror `GameEngine._can_pay_activation_cost`'s per-component checks,
      minus the tap/untap-source and remove-counters pieces (tied to a
      specific permanent's own state, which doesn't apply — a ward cost
      always comes from the caster's own resources).

      Frontend: `gameBoardView.js`'s `CHOICE_ICONS` gained a `ward` entry
      (🛡️); the generic `pending_choice` modal needed no other change (a
      ward ability on the stack renders through the existing stack-item UI
      like any triggered ability, no new rendering code either). Tests:
      `test_game_engine.py`
      (`test_ward_pushes_a_real_stack_item_above_the_spell`,
      `test_ward_paid_lets_the_spell_resolve`,
      `test_ward_declined_counters_the_spell`,
      `test_ward_uncastable_cost_counters_the_spell_without_a_choice`,
      `test_ward_does_not_trigger_against_its_own_controller`,
      `test_ward_triggers_on_a_targeted_activated_ability`,
      `test_ward_pay_life_cost`, `test_ward_discard_cost`,
      `test_ward_sacrifice_cost`,
      `test_ward_sacrifice_cost_unpayable_counters_without_a_choice`,
      `test_ward_two_simultaneous_wards_each_ask_in_turn`,
      `test_ward_one_of_two_simultaneous_wards_declined_counters_the_spell`),
      `test_keyword_catalogue.py`
      (`test_ward_without_a_mana_cost_falls_back_to_free_text`,
      `test_ward_discard_cost_falls_back_to_free_text`,
      `test_ward_sacrifice_cost_falls_back_to_free_text`).

- **Leaves-the-battlefield triggers now "look back in time" (RULE 603.6a,
  2026-07-15):** `RulesEngine._move_to_graveyard`/`exile`/`return_to_hand` used
  to call `state.remove_from_battlefield(obj)` *before* firing
  `LEAVES_BATTLEFIELD`/`DIES` — since `_collect_triggers` only ever scans
  `state.permanents()` (the live battlefield) at the moment an event fires, a
  permanent's own "when this dies"/"when ~ leaves the battlefield" triggered
  ability was structurally unreachable, regardless of the (already-correct)
  RULE 603.1 subject-scoping. Fixed by reordering all three methods to fire
  while the object is still spliced into `self.battlefield`, then remove it —
  the mirror image of `GameState.add_to_battlefield`'s existing
  append-then-fire ordering for `SAGA_CHAPTER`/`CLASS_LEVEL`. No state
  snapshot/clone was needed: `GameObject` instances are never recreated on a
  zone change (the same instance is spliced between zone-list containers), so
  `obj.triggered_abilities` is fully intact at fire time either way.
  `LEAVES_BATTLEFIELD`'s event payload was also thinner than `DIES`'s
  (missing `instance_id`/`controller_id`/`object_types`) and is now enriched
  to match in all three methods, so a `{"subject": "self"}` trigger can match
  on it too. `_detach_attachments_from`'s recursive call into
  `_move_to_graveyard` (an attached Aura dying alongside its host) needed no
  special-casing — the Aura is still on the battlefield when the recursive
  call runs, so the same fixed sequence applies to its own death correctly.
  `EXILE`'s own payload/timing was deliberately left alone (it describes
  arrival in the new zone, not departure, so moving it earlier wouldn't help
  a self-referential "when ~ is exiled" trigger — a distinct, larger feature
  no current oracle-text handler produces anyway). Tests:
  `test_oracle_triggers.py`
  (`test_self_dies_trigger_fires_through_real_destroy_pipeline`,
  `test_self_dies_trigger_fires_through_lethal_damage_sba`,
  `test_self_leaves_battlefield_trigger_fires_on_exile_and_return_to_hand`,
  `test_blood_artist_shaped_group_trigger_fires_once_on_real_death` as a
  no-double-firing regression guard for group-scoped triggers).

- **M2 alt-cost keywords — Kicker/Multikicker, Buyback, Escape, Flashback
  (2026-07-15):** the last open M2 keyword family (`docs/implementation-state/BACKLOG.md`)
  — each was parsed-but-inert in `GameObject.parametric_keywords` before
  this; all four now have real cast-time/resolve-time behaviour.
  **Foundation:** `ManaCost.add(other)` (`models/mana_cost.py`) concatenates
  two costs' symbol lists (unlike `increase_generic`, it carries colored/
  hybrid/Phyrexian pips, not just generic ones) — Kicker/Multikicker/Buyback
  all compose the printed cost with an independent additional cost this way.
  Multikicker's "repeatable" identity survives the `_ALIASES` collapse onto
  plain Kicker (`parser/oracle/catalogue/keywords.py` `parse_keywords`): the
  raw Scryfall name is checked *before* aliasing (the same "check before
  collapse" trick landwalk's `forced_quality` already used), stamping
  `multi=True` into the extracted param dict. New `GameObject` fields
  `kicker_count`/`buyback_paid`/`cast_via_flashback` (`models/game_object.py`)
  carry each cast's paid state, exposed in `to_dict` for the board.
  **Kicker/Multikicker (RULE 702.33):** `GameEngine.cast_spell`/`can_cast`/
  `effective_cast_cost` grow a `kicked: int` parameter following the exact
  shape `x`/`mode` already use — `_kicker_cost`/`max_affordable_kicker`
  mirror `max_affordable_x`'s "scan down from an upper bound" shape;
  `can_cast` rejects `kicked > 1` unless the keyword's own `multi` flag is
  set. `legal_actions`/`_cast_action` surface `has_kicker`/`kicker_cost`/
  `kicker_multi`/`max_kicker`, the same `has_x`/`max_x` treatment. Consuming
  "if this spell was kicked, …" at resolve time is a deliberate follow-up
  (new oracle-parser conditional-clause grammar), not part of this slice —
  see `docs/implementation-state/BACKLOG.md`. **Buyback (RULE 702.27):** an optional
  additional cost the same shape as Kicker; `RulesEngine.
  resolve_top_of_stack` grows an `elif obj.buyback_paid` branch (mirroring
  the pre-existing adventure-snapshot exile branch) that calls
  `RulesEngine.return_to_hand` instead of `_move_to_graveyard` — reusing the
  Unsummon-style bounce helper wholesale, including its commander-zone-choice
  handling, rather than duplicating zone-move logic. **Flashback (RULE
  702.34)/Escape (RULE 702.138):** share one graveyard zone gate —
  `_graveyard_cast_keyword`/`_castable_from_graveyard`
  (`game/game_engine.py`, mirroring `_castable_from_exile`'s "no extra
  per-object flag needed" shape, since either keyword's mere presence is
  enough) feed a fourth `player.graveyard` loop in `legal_actions` and a new
  disjunct in `can_cast`'s `in_castable_zone`. `effective_cast_cost`
  substitutes (not adds) the alternative cost when `obj in player.graveyard`
  — Flashback's own `ManaCost`, or Escape's `ActivationCost.mana` — applied
  *before* the existing reduction/tax so those still layer on top correctly.
  A successful graveyard cast is auto-detected purely from `obj`'s own state
  (no separate "I meant to flashback" flag from the caller needed, same as
  Adventure): `_cast_current_face` reads `_graveyard_cast_keyword(obj)`
  before `RulesEngine.cast_spell` moves it off the graveyard, then sets
  `obj.cast_via_flashback` accordingly; `resolve_top_of_stack` grows an
  `elif obj.cast_via_flashback` branch exiling the spell instead of
  returning it to the graveyard (RULE 702.34a) — Escape has no such clause,
  so an Escaped instant/sorcery falls through to the ordinary graveyard
  branch and an Escaped permanent enters the battlefield exactly like any
  other permanent spell. **Escape's own new cost-grammar work:** its cost is
  "{mana}, Exile N other cards from your graveyard" — the mana-only
  `_auto_regex` COST-shape extractor could only ever see the `{...}` pips,
  silently dropping the exile clause (`test_escape_reads_cost_after_the_dash`
  used to assert exactly that gap). A new always-wins fallback
  (`_ESCAPE_TEXT_COST_RE`, unlike Ward's own fallback which is only
  consulted when the mana regex finds nothing) captures the full clause as
  free text; `game/costs.py` gained `ActivationCost.exile_from_graveyard`
  plus `_EXILE_GRAVEYARD_RE` so `parse_activation_cost` recognizes it
  downstream (`_escape_cost` parses the full clause via the shared
  activated-ability cost grammar, not just `ManaCost`, since Escape's cost
  has a non-mana component). `can_cast` checks
  `len(player.graveyard) - 1 >= exile_from_graveyard` ("N *other* cards" —
  ``obj`` itself doesn't count); `_pay_escape_graveyard_cost` exiles an
  auto-chosen (non-interactive MVP simplification, matching
  `_sacrifice_candidate`'s existing pattern) `count` of the remaining
  graveyard, called *after* the escaping card itself has already left, so it
  can never exile itself. Tests: `test_game_engine.py` ("Kicker /
  Multikicker", "Buyback", "Flashback", "Escape" sections — cast-time
  payment/legality/tracking and resolve-time zone routing, end to end
  through `GameEngine`/`RulesEngine`, not just the parser layer), plus
  `test_keyword_catalogue.py` (Multikicker's `multi` flag, Escape's
  full-clause cost capture).

- **M2 Rampage (RULE 702.23, 2026-07-15) — M2 now fully closed:** the last
  open M2 parametric keyword. Its pump amount scales with the *specific*
  block's final blocker count ("+N/+N for each creature blocking it beyond
  the first"), which a bind-on-load `TriggeredAbility` — one fixed `effects`
  list, reused for every firing — can't carry; the identical "per-firing
  dynamic amount" problem Ward already solved by building its effect
  directly rather than through the generic `_collect_triggers`/
  `TriggeredAbility` event pipeline (see the M2 Ward entry above). New
  `RulesEngine.check_rampage(attacker, blocker_count)` mirrors that: reads
  the `rampage` parametric keyword (already docked by `attach_keyword` like
  any `NUMBER`-shaped keyword — no parser change needed, this was purely an
  engine-side gap), computes `n * max(0, blocker_count - 1)`, and — when
  positive — builds a fresh `TriggeredAbility` with a `PumpEffect` at that
  exact amount and pushes it via the existing `_place_trigger` (so it's a
  real stack object with a normal priority/response window, controlled by
  the attacker's own controller per RULE 603.3a, exactly like the
  annihilator/afflict/bushido triggers `effect_binder._keyword_triggered_
  abilities` builds at bind-on-load — just built per-firing instead). Called
  from `GameEngine.declare_blockers` right where `BECOMES_BLOCKED` fires for
  each newly-blocked attacker — that event already carried a `blocker_count`
  payload (added alongside the afflict/bushido work specifically for this).
  Tests: `test_game_engine.py` (`test_rampage_does_not_trigger_with_only_
  one_blocker`, `test_rampage_pumps_once_per_blocker_beyond_the_first`,
  `test_rampage_goes_on_the_stack_as_a_real_triggered_ability`).

- **Mana-ability costs redone properly (RULE 605.1a/602.1, 2026-07-15):**
  `tap_for_mana` used to only ever tap the source itself — any other cost
  component a mana ability printed was silently free, and a whole-oracle-
  text regex (`game/mana_abilities.py`'s old `mana_options`) meant a
  card's cost text never even reached the engine. Verified against the
  Elf mana-dork family (`tests/test_elf_mana_costs.py`,
  `tests/test_mana_abilities.py`), which turned out to cover an unusually
  wide spread of real cost/production shapes:
  - **Non-tap costs now charged**: `game/costs.py` gained `tap_others`
    ("Tap two/three untapped Elves you control" — Birchlore Rangers,
    Heritage Druid — taps permanents matching a creature type as a cost
    instead of the source's own `{T}`; not gated by the tapped permanents'
    own summoning sickness, since RULE 302.6 only restricts a permanent's
    own {T}-ability) and `add_counters_cost` ("Put a -1/-1 counter on this
    creature" — Devoted Druid's untap ability; always payable, unlike
    `remove_counters`). `game_engine.py` factored the actual charging logic
    out of `activate_ability` into a shared `_pay_activation_cost`, so
    `tap_for_mana` charges a mana ability's **full** cost (mana pips,
    `{T}`/`{Q}`, life, sacrifice, tap_others, add_counters_cost) the same
    way a normal activated ability does — Selvala's `{G}` and Gnarlroot
    Trapper's 1 life are now actually paid, not silently skipped.
    **`tap_others` is a real player choice, not an engine auto-pick**
    (2026-07-15 follow-up, after review caught two bugs in the first cut):
    the printed cost has no "other"/"another" qualifier, so the ability's
    own source is itself an eligible pick (Birchlore Rangers can tap
    itself as one of its own two Elves — confirmed real-card ruling); and
    *which* permanents pay the cost is the player's decision, the same way
    a target is, not something the engine should decide for them.
    `_tap_others_pool` (candidates) / `_resolve_tap_others` (validate a
    pick, or auto-pick the first N when no pick is given — non-interactive
    callers like tests/the goldfish bot) replace the old always-auto-pick
    `_tap_others_candidates`; `can_activate`/`_can_pay_activation_cost`/
    `_pay_activation_cost`/`activate_ability`/`tap_for_mana` all thread an
    optional `tap_choices` (instance ids). `legal_actions`/`_activate_action`
    expose the full eligible pool as `tap_cost: {count, options}` so the UI
    can offer a real choice; the goldfish board reuses its existing
    one-pick-at-a-time target-choice modal (`castTargeting` in
    `gameBoardView.js`, generalised with an `excludePicked` flag so the same
    permanent can't be picked twice) rather than a new widget, translating
    the picks into `tap_choices` instead of `targets` on send.
  - **`mana_abilities.py` rewritten line-by-line** instead of one whole-
    text regex: each `<cost>: Add …` line becomes its own `ManaAbility`
    (cost + options), so one line's cost can no longer bleed into
    another's production, and a line whose text is quoted inside another
    ability ("Each creature you control with a counter on it has '{T}: Add
    {G}.'", Rishkar) is correctly recognised as a *grant* onto other
    objects, not Rishkar's own ability (RULE 613.7f grants stay
    hand-authored in `ability_catalogue.py`, not auto-parsed here).
  - **RULE 605.1a enforced**: a line whose effect mentions "target" is
    never treated as a mana ability, however mana-shaped it looks —
    Deathrite Shaman's graveyard-exile abilities produce mana but target,
    so real Magic makes them stack-using, responds-to-able activated
    abilities instead of a mana ability. Previously they were wrongly
    offered as a free, stack-skipping tap; now they're correctly excluded
    (and not yet re-implemented as the real targeted ability — see
    `docs/implementation-state/BACKLOG.md`).
  - **Variable ("for each"/"equal to … power") amounts**: a new
    `amount_selector` on `ManaAbility`, resolved against the live
    `GameState` at activation time (`resolve_options`/`_resolve_amount`) —
    covers "for each Elf/creature you control" (Elvish Archdruid, Circle of
    Dreams Druid), "for each Elf on the battlefield" (Priest of Titania —
    counts *both* players' Elves, not just yours), "for each +1/+1 counter
    on this creature" (Gyre Sage), "equal to this creature's/~'s power"
    (Viridian Joiner, Marwyn), and "X mana of any one color, where X is the
    number of Elves on the battlefield" (Wirewood Channeler — a variable
    amount *and* a colour choice together, since the same base-options ×
    N scaling covers both). Resolves to a conservative 1× with no
    `GameState` (a bare `Card` query, e.g. the pre-existing
    `mana_options(card)` tests) — no regression for callers that never
    supplied one.
  - **A mana ability's own side effect**: `self_damage` on `ManaAbility`
    for the painland/Elves-of-Deep-Shadow "This creature deals N damage to
    you" rider (RULE 605.1a permits effects beyond producing mana),
    applied via `RulesEngine.deal_damage` right alongside `tap_for_mana`,
    no stack involved.
  - **Devoted Druid's own untap ability** needed a genuinely new effect
    shape: "Untap this creature" has no RULE 115 target at all (unlike
    "untap target permanent"), so `parser/oracle/catalogue/handlers.py`
    gained a `tap_self` handler (`_SELF_SUBJECT` — "~"/"it"/"this
    permanent"/"this creature"/…) alongside the existing targeted `tap`
    one, binding to `TapEffect(target_kind=None)`'s existing self-mode.
    `segmenter._COST_LOOKS_REAL` was extended to recognise "put a … counter
    on …" as a real cost shape too, so the ability segments at all instead
    of falling through unclaimed. (Verified end to end: activating it on a
    vanilla 1/1 correctly kills it via the 0-toughness SBA the instant the
    counter lands — same real-world reason this line combos with
    counter-prevention like Vizier of Remedies rather than being free
    extra mana on its own.)
  - `legal_actions`/the goldfish auto-player were updated to the new
    per-(source, mana-ability-index) shape: each ability's own payability
    gates its offer (so a card whose only ability doesn't tap itself can
    still be offered while tapped), and the greedy auto-player only
    self-taps a plain `{T}`-only ability, leaving anything with a real
    extra cost for the player to choose. `ability_index` threads through
    `game_session.py`'s `tap_for_mana` action and the goldfish board's
    button wiring (`frontend/src/js/gameBoardView.js`), which also now
    shows the ability's full cost label instead of a bare "Tappen" when
    it's more than `{T}`.
  - Still open (see `docs/implementation-state/BACKLOG.md`): mana *spend* restrictions
    ("spend this mana only to cast an Elf creature spell") aren't tracked
    by `ManaPool` at all; "any combination of colours" (Selvala, Gwenna)
    isn't a colour-choice shape this grammar covers; hand-zone mana
    abilities (Elvish Spirit Guide's "Exile this card from your hand:
    Add …") have no activation path since they're not on the battlefield
    at all; and a Leveler's mana ability isn't level-gated (Joraga
    Treespeaker's `{T}: Add {G}{G}.` applies unconditionally instead of
    only at levels 1-4).

- [x] **Modal triggered abilities (RULE 700.2 wrapped in RULE 603,
      2026-07-16):** "When ~ enters, choose one —" on a permanent now
      parses and binds — previously only a modal *spell*'s bare header
      worked (`spec.py`'s `modes` was `spell_effect`-only). `spec.py`
      now allows `modes` on `ability_kind == "triggered"` too.
      `parser/oracle/catalogue/modal.py`'s bullet-collection loop
      (`collect_mode_bodies`) was factored out of `split_modal_block` so
      it can be shared; `gate.py` gained `_split_triggered_modal_block`,
      which reuses `segmenter.py`'s trigger event/condition grammar
      (`_TRIGGER_RE`/`_trigger_event`/`_trigger_condition` — the same
      recognizer an ordinary triggered ability uses) to peel the trigger
      wrapper *before* checking the remainder against
      `MODAL_HEADER_RE`, then reuses the same per-bullet effect parsing
      (`_parse_mode_options`, factored out of `_process_modal_block`) a
      modal spell already had. `effect_binder.py`'s `bind_ability`
      builds each mode's effects onto a new `TriggeredAbility.modes`
      field (`_build_mode_entries`, factored out of `_attach_modes` so
      spell and triggered modes share one binder path) instead of
      `obj.spell_modes`, since a triggered ability's mode is chosen at a
      different time than a spell's.

      **Resolution is a new interactive choice**, not a cast-time
      parameter: RULE 603.3's mode selection happens as the ability is
      put on the stack, so `game/rules_engine.py`'s `_place_triggers`
      now checks `ability.modes` *before* its existing target/"you may"
      checks and opens a `trigger_mode` `pending_choice`
      (`_trigger_mode_choice`/`resolve_trigger_mode_choice`) — generic
      choice UI, no frontend changes needed beyond a cosmetic
      `CHOICE_ICONS` entry (`gameBoardView.js`). Once a mode (or "both",
      RULE 700.2e) is chosen, the *existing* target-choice machinery
      still has to run against that mode's own effects — `_trigger_
      target_spec`/`_place_triggers`'s per-item logic was generalized
      from reading `ability.effects` to taking an arbitrary effects list
      (`_place_or_pause_trigger`, replacing the old inline loop body),
      and `_place_trigger` gained an `effects_override` parameter so the
      placed `StackItem` carries the chosen mode's effects directly
      instead of the `TriggeredAbility` wrapper (`StackItem._derive_
      category` still classifies it as `"triggered_ability"` either way,
      so nothing downstream needed to change). The ability's own shared,
      reused-across-firings `effects` list is never mutated — the chosen
      mode's effects flow through `_pending_trigger_effects`/`effects_
      override` instead, the same "per-firing data without a per-firing
      object" shape `targets` already used.

      **Real-cache yield turned out much smaller than estimated**: the
      pre-implementation processing-list ranking said "33 cards" for
      this shape, but that count came from an *abstracted* clause
      template (`"choose <n> —"`) that collapses this trigger-wrapped
      case together with an unrelated one — a modal *spell* whose header
      parses fine but one of its bullets doesn't (already-unclaimed
      before this fix, for a different reason). A direct scan of the
      live cache for the actual trigger-wrapped shape found only 6 cards
      (Aether Channeler, Ao the Dawn Sky, Atsushi the Blazing Sky,
      Charming Prince, Kura the Boundless Sky, Voracious Hydra), and all
      6 remain `UNMODELED` regardless — each also needs at least one
      other still-missing effect family in one of its modes (a "fight"
      effect, RULE 701.12; a filtered/qualified bounce target like
      "another target nonland permanent"; a flicker/exile-then-return
      effect; "double this creature's own counters"). This fix is
      correctness/architecture that any future modal-trigger card needs,
      not a coverage-% win by itself — see `docs/implementation-state/BACKLOG.md` and
      `10_COMPLETION_ROADMAP.md`'s M1 section for the follow-up effect
      families it exposed. Tests: `test_modal_spells.py` (parser → spec
      → binder → engine, including the `trigger_mode`/`trigger_target`
      choice sequencing and "or both").

- [x] **"Enters with N counters" replacement effect (RULE 614.1-style,
      2026-07-16):** "~ enters (the battlefield) with N/X `<counter-type>`
      counters on it." now parses and resolves. New
      `parser/oracle/catalogue/counters.py` mirrors `catalogue/lands.py`'s
      tapped-entry split: `entry_counters_condition(line)` classifies one
      already-normalized oracle line, `entry_counters(card)` reads it off
      a card's full text. Like tapped-entry, this clause isn't an effect
      spec — `gate.py`'s `_process_line` claims the line without emitting
      one (an ``X`` amount needs the object's *actual* paid X, RULE
      107.3c, which the binder can't precompute onto a reusable spec), and
      `game/ability_catalogue.entry_counters(card)` is the engine-facing
      wrapper, the same split `land_tap_condition` uses — so the shapes
      the gate claims and the shapes the engine resolves can never drift
      apart.

      Resolution is `RulesEngine._apply_entry_counters(obj, x_paid=0)`,
      called at both existing `ability_catalogue.enters_tapped` call
      sites right before the object is added to the battlefield (so the
      counters are present when `ENTERS_BATTLEFIELD` fires and any
      trigger/continuous pass reads them): `_resolve_permanent_spell`'s
      `_finish()` (the cast-resolution path, passing `obj.x_paid` — set
      by `RulesEngine.cast_spell` from the announced X, RULE 601.2b) and
      `create_token`'s battlefield-entry branch (always `x_paid=0` — a
      token was never cast). A fixed amount ("three +1/+1 counters"/"four
      ice counters"/"a charge counter", "a"/"an" folding to 1) or the
      variable "X" (0 if the object didn't just resolve off a cast-for-X)
      works for any counter kind: `+1/+1`, `-1/-1`, or a bare word
      (ice/charge/wish/study/…) — `GameObject.add_counters` already
      handles the kind generically.

      **Real-cache yield correction** (cross-checked against a direct
      scan *before* committing to a number, applying the lesson the
      modal-trigger batch above learned the hard way): the clause
      actually appears on **23 cards**, not the 14 the abstracted
      processing-list template suggested — the abstraction split the
      X-amount and fixed-amount phrasings into two separate templates
      that this one implementation covers together. Of those 23, only
      **2** (Steelbane Hydra, Stonecoil Serpent) had no other unclaimed
      line and so flip to fully `MODELED` immediately (cache-wide: 509 →
      511 modeled, 20.3% → 20.4%); the other 21 — mostly Hydras (Walking
      Ballista, Voracious Hydra, Hangarback Walker, Primordial Hydra,
      Benevolent Hydra, Hungering Hydra, Hydroid Krasis, Kinetic Ooze,
      Lifeblood Hydra, Genesis Hydra, Goldvein Hydra, Ingenious Prodigy,
      The Goose Mother) plus Triskelion/Threefold Thunderhulk/Mossborn
      Hydra/Thing in the Ice/Wishclaw Talisman/Transmogrifying
      Wand/Mana Bloom/Lattice Library — still need one or more *other*
      missing effect families (dies-triggers scaled by counter count,
      upkeep-trigger counter-doubling, "fight", conditional-on-X effects,
      activated abilities that remove a counter as a cost) before they're
      fully modeled. Necessary-but-not-sufficient infrastructure for most
      of them, the same shape the modal-trigger finding above had.
      Tests: `test_oracle_counters.py` (clause recognition + coverage-gate
      integration, incl. a fail-closed "unrelated unclaimed line stays
      unclaimed" case), `test_entry_counters.py` (engine: fixed amount,
      bare-word counter type, X amount uses the paid X, X=0 puts nothing,
      an ordinary creature is unaffected).

- [x] **Fourth land-tapped clause variant (2026-07-16):** "~ enters tapped
      unless your opponents control N or more lands" (the "Turbulent" land
      cycle) — distinct from the three `_UNLESS_*_RE` shapes
      `catalogue/lands.py` already had: `_UNLESS_COUNT_RE`/`_UNLESS_
      BASIC_COUNT_RE` count the *controller's own* other lands, and
      `_UNLESS_OPPONENTS_RE` counts opponent *players*, not their lands.
      New `_UNLESS_OPPONENTS_COUNT_RE`, same `cmp`("le"/"ge")/`count`
      shape `unless_count` already returns, under a new
      `unless_opponents_count` kind. `RulesEngine.enter_land_tapped`
      gained the matching branch: sums lands across every player except
      the controller (unlike the other `unless_count`-family branches,
      which sum the controller's own battlefield) and compares against
      `condition["count"]`.

      Verified against the live cache *before* implementing (applying the
      lesson the previous two batches' yield corrections taught): exactly
      **5 cards** — the Turbulent Fen/Moor/Springs/Steppe/Wilderness
      cycle — each with this as its *only* unclaimed line, so all 5 flip
      to fully `MODELED` (cache-wide: 511 → 516 modeled, 20.4% → 20.6%).
      Unlike the modal-trigger and enters-with-counters batches, this one
      is a clean full-yield fix — no other missing effect family blocks
      any of the 5 cards. Tests: `test_oracle_lands.py` (clause
      recognition + gate-level `MODELED` integration),
      `test_land_tap_conditions.py` (engine: too-few opponent lands stay
      tapped, enough go untapped, the count sums across multiple
      opponents, and the controller's own lands don't count toward it).

- [x] **"Add 1 mana of any color" resolve-time colour choice (2026-07-16):**
      a spell/activated/triggered ability's own bare "Add 1 mana of any
      color." body — distinct from a permanent's *mana ability*
      (`game/mana_abilities.py`), which already supported "any color" via
      its pre-declared tap-for-mana options (a dual land, Elvish
      Harbinger) and needed no changes here. New
      `_ADD_MANA_ANY_COLOR_RE`/`_add_mana_any_color` handler in
      `parser/oracle/catalogue/handlers.py`, tried before the existing
      fixed-pip `_ADD_MANA_RE` (which has no `{…}` symbols to match this
      shape anyway), emits `EffectSpec("add_mana", {"colors": ["any"]})`.
      Deliberately narrow to the singular "1 mana" phrasing — real cards
      templating a multi-mana version always say "any *one* color"
      instead (Wirewood Channeler's `_WHERE_X_RE`-family shape, already
      modeled on the mana-ability side, a different clause), so a bare
      "add 2 mana of any color" is correctly left unclaimed rather than
      guessed at.

      `AddManaEffect` (`game/effects.py`) now treats a `colors` entry of
      `"ANY"` (its constructor already uppercases every entry, so the
      spec's lowercase `"any"` needs no special-casing there) as a
      genuine resolve-time player decision instead of guessing:
      `GameContext.add_mana_any_color` → new
      `RulesEngine.add_mana_any_color` opens an `add_mana_any_color`
      `pending_choice` (W/U/B/R/G options) — the same "an effect opens a
      choice mid-`apply()`, the resolve loop naturally pauses there"
      pattern `request_search`/`counter_unless_pays` already use, not a
      new architecture. `resolve_add_mana_any_color_choice` finishes it;
      a missing/invalid answer defaults to White rather than dropping the
      mana entirely, the same "defaults instead of dropping" treatment
      `resolve_trigger_mode_choice` (the modal-trigger batch above) gives
      a missing mode answer. `GameEngine.resolve_pending_choice` and
      `gameBoardView.js`'s `CHOICE_ICONS` got the matching dispatch/icon
      entries — no other frontend change needed, the choice UI is generic.

      **Real-cache yield: 0 cards** — predicted honestly before starting,
      not a surprise: this was always framed as shared infrastructure
      for Deathrite Shaman (still open, needs a "card in any graveyard"
      target kind next — see `docs/implementation-state/BACKLOG.md`), not a
      coverage-% play. Confirmed against the live cache: every real card
      with this clause (Deathrite Shaman, Crystalline Crawler, Mana
      Bloom, Fertile Ground) is still blocked by a *different* gap on the
      same card — a "remove a counter from ~" activation-cost shape
      `costs.py` doesn't parse yet (Crystalline Crawler, Mana Bloom — the
      same gap Walking Ballista/Triskelion/Wishclaw Talisman/
      Transmogrifying Wand were already found blocked on in earlier
      batches, newly worth prioritizing), the not-yet-built graveyard
      target kind (Deathrite Shaman), or an unrelated triggered-ability
      event shape ("whenever enchanted land is tapped for mana", Fertile
      Ground). Tests: `test_effect_families_wave3.py` (parser recognition
      incl. the narrow-shape negatives, gate-level `MODELED` integration
      on a synthetic card, engine: opens the choice/resolves to the
      chosen colour/defaults to White on a missing answer).

- [x] **Generalized graveyard-card targeting + Deathrite Shaman
      (2026-07-16):** the Regrowth/Reanimate-shaped recursion family
      (`graveyard_creature`) generalized from "creature, your own
      graveyard, return-to-battlefield/hand only" to the full real-card
      vocabulary: **card type** (any card/creature/land/artifact/
      enchantment/instant-or-sorcery/permanent/nonland permanent) ×
      **graveyard scope** (own/"a graveyard" — any single graveyard,
      whosever/an opponent's specifically). New `game/targeting.py`
      tables — `_GRAVEYARD_SCOPE_PREFIXES`, `_GRAVEYARD_TYPE_FILTERS`,
      `_GRAVEYARD_TARGET_KINDS` (their cross product, e.g.
      `any_graveyard_land`/`opponent_graveyard_creature`) — replace the
      old single `if kind == "graveyard_creature"` branch in
      `legal_targets` with one generic branch reading whichever
      graveyard(s) the scope implies (own/all-but-controller's/all) and
      filtering by the type predicate; `_graveyard_label` builds a German
      `TargetSpec.label()` for any combination instead of a static dict.
      No protection/hexproof filtering applies (a graveyard card isn't a
      permanent/spell, so `_targetable_by` doesn't run there).

      **Three new/generalized effects** on the parser side
      (`catalogue/handlers.py`), all sharing a `_graveyard_target_kind
      (type_word, scope_word)` helper that maps a matched clause's
      card-type + scope words onto the right `_GRAVEYARD_TARGET_KINDS`
      member:
      - `return_from_graveyard` (generalized): "return target [type] card
        from [scope] graveyard to the battlefield/your hand/its owner's
        hand" *and* "put target [type] card from [scope] graveyard onto
        the battlefield under **its owner's**  control" (Kenrith-shaped) —
        both land under the card's own owner, so they share one builder.
      - `reanimate_under_your_control` (new): "put target [type] card
        from [scope] graveyard onto the battlefield under **your**
        control" (Reanimate/Rise from the Grave/Virtue of Persistence) —
        a genuinely different effect: the activating player steals
        control regardless of whose graveyard the card came from.
        `ReturnFromGraveyardEffect` gained a `under_your_control: bool`
        flag; when set (and only for `destination="battlefield"` — real
        cards never combine "under your control" with a hand
        destination), `apply()` resolves the effect's own controller and
        passes it through as `RulesEngine.return_from_graveyard`'s new
        `controller_id` param, which stamps `obj.controller_id` before
        the battlefield add (so triggers/layer effects see the new
        controller immediately) while `obj.owner_id` stays untouched
        (RULE 108.4/111.4: control and ownership are independent).
      - `exile_from_graveyard` (new): "exile target [type] card from
        [scope] graveyard" (RULE 701.5a) — the Deathrite Shaman/
        Scavenging Ooze/Lion Sash graveyard-hate family. No new engine
        code needed: `RulesEngine.exile`/`ExileEffect` already move an
        object "from anywhere," including a graveyard.

      **A genuinely missing effect family, surfaced by chasing Deathrite
      Shaman's third ability to a real runtime test rather than stopping
      at the parser claiming it `MODELED`**: "X loses N life" had *no*
      handler or `EffectRegistry` entry at all (not even the plain
      "target player loses N life"/"you lose N life" case — only
      `gain_life` existed). Added `lose_life`/`lose_life_selector`
      handlers (mirroring `gain_life`/`_damage_selector` exactly) and
      registered `LoseLifeEffect` (which already existed, used internally
      by Afflict, but was never reachable from the oracle parser) under
      `"lose_life"`; `_LOSE_LIFE_SELECTORS` gives it the same "each
      opponent"/"each player" mass-effect shape `DealDamageEffect`
      already has (no "each creature" — life loss never targets one).

      **A real, pre-existing correctness bug this surfaced and fixed**:
      `GainLifeEffect`/`LoseLifeEffect`'s "controller, or a target player"
      fallback read `targets[0]` from the ability/spell's *shared* target
      list whenever their own `self.player` wasn't set — silently correct
      only because no card previously combined one of these with an
      unrelated *targeted* effect in the same chain. Deathrite Shaman's
      third ability ("Exile target creature card from a graveyard. You
      gain 2 life.") does exactly that: `targets[0]` was the exiled
      *card*, not a player, crashing `RulesEngine.gain_life` with an
      `AttributeError` the first time the ability actually resolved in a
      test — the parser's fail-closed `MODELED` gate catches missing
      coverage, not a runtime type mismatch inside effects it does claim.
      Newly-unlocked real cards hit the identical shape (Infernal Grasp
      "Destroy target creature. You lose 2 life.", Anguished Unmaking).
      Fixed by dropping the `targets[0]` fallback entirely and using
      `_controller_of(self.source, context)` instead — the same correct
      "effect's own controller, defaulting to the active player" pattern
      `AddManaEffect` already used (which is why *that* effect never hit
      this bug). `LoseLifeEffect`'s `selector="defending_player"`
      (Afflict) path is unaffected — it already resolved via
      `_defending_player_of` before ever reaching the `targets` fallback.

      **Real-cache yield, verified via a true before/after diff** (a
      temporary monkeypatch reconstructing the pre-batch handler table,
      since two batches now touch overlapping files/handler names in the
      same session with no intermediate commit) — **19 cards newly fully
      `MODELED`** (511 → 535 cumulative since Batch 3, this batch alone:
      516 → 535, 20.6% → 21.3%): Deathrite Shaman (the batch's named
      target), Eternal Witness, Regrowth, Sanctum Gargoyle, Trading Post,
      Trash for Treasure, Restoration Seminar, Revolutionist, Pinnacle
      Monk, Bala Ged Recovery, Buried Ruin, Colossal Skyturtle, Siege
      Zombie, Cryptbreaker (the generalized graveyard family), plus — a
      side benefit of the `lose_life` fix alone, no graveyard clause
      involved — Anguished Unmaking, Infernal Grasp, Night's Whisper,
      Read the Bones, Grim Tutor (well-known constructed/Commander
      staples). Many more graveyard-shaped cards (Reanimate, Rise from
      the Grave, Persist, Karmic Guide, Zombify, Puppeteer Clique, …)
      still have the graveyard-targeting line claimed but remain
      `UNMODELED` on a *different* line — a life-total-scaled amount
      ("lose life equal to that card's mana value"), a `-1/-1`-counter
      qualifier, "up to one target", a Leveler-adjacent corpse-counter
      clause, etc. — necessary-but-not-sufficient infrastructure for
      those, same shape as the modal-trigger/enters-with-counters
      findings above.
      Tests: `test_effect_families_wave3.py` (parser recognition for
      every type/scope combination + fail-closed negatives, gate-level
      `MODELED` integration, engine: `under_your_control` steals from an
      opponent's graveyard while leaving ownership alone,
      `LoseLifeEffect` selectors hit the right players, and a full
      Deathrite Shaman oracle-text-to-engine test exercising all three
      abilities — including the interactive `add_mana_any_color` choice
      from the batch before this one).

- [x] **Leveler-gated mana abilities (2026-07-16):** a Leveler's (RULE
      711.4c) own mana ability, printed inside a `LEVEL n-m`/`n+` tier,
      applied unconditionally regardless of the object's actual level —
      Joraga Treespeaker's `{T}: Add {G}{G}.` (its `LEVEL 1-4` tier)
      offered mana at level 0 (before levelling up at all) and stayed
      available forever past level 5, when that tier's text instead
      *grants* the ability to Elves (an unrelated, already-gated layer-6
      static effect) rather than keeping one of its own. The exact
      `min_level`/`max_level` gate `game/continuous.py` already applied to
      a Leveler's *static* tiers (RULE 613.6, "as long as this object's
      own level counter is in range") had never been extended to mana
      abilities, since `mana_abilities.py` reads a card's raw oracle text
      line-by-line with no awareness of `LEVEL` block boundaries at all.

      `ManaAbility` (`game/mana_abilities.py`) gained `min_level`/
      `max_level` fields (`None`/`None` — unconditional — for every
      non-Leveler card, so no behaviour change there). `parse_mana_
      abilities` now branches on `card.is_leveler`: a new
      `_split_leveler_blocks_raw` (mirrors `parser/oracle/catalogue/
      levels.split_leveler_blocks`'s block-splitting logic, but on *raw*,
      mixed-case oracle text — `mana_abilities.py`'s own regexes like
      `_ADD_CLAUSE_RE` are case-sensitive, unlike the normalized/lowercased
      text `levels.py`'s version expects) splits the card into a preamble
      plus its tiers, and the existing per-line parser (factored out
      unchanged as `_parse_mana_ability_lines`) runs once per tier's body
      text, tagging each resulting ability with that tier's range.
      `mana_abilities_for` (the `GameObject`-level, actually-played-with
      entry point) filters through a new `_leveler_tier_active(obj,
      ability)`, reading `obj.counters.get("level", 0)` the same way
      `continuous.py`'s static gate reads a source's own level counter.
      `mana_options(card)` (the card-only, no-game-state display helper
      used for static "what can this card make" UI queries) is
      deliberately left unfiltered — it has no object/level to filter by,
      so it still shows every tier's options, same as showing full card
      text regardless of current game state.

      **Real-cache yield**: exactly **1 card** — Joraga Treespeaker is the
      only Leveler in the entire 2,507-card cache, and the only one with a
      tier-nested mana ability at all (confirming the plan's own framing
      of this as the smallest item in its bucket). Doesn't move the
      parser coverage percentage (mana abilities are recognized outside
      the `MODELED` gate entirely). Tests: `test_mana_abilities.py`'s new
      `TestLevelerGatedManaAbilities` (tier tagging, level 0 has nothing,
      levels 1 and 4 both offer it, level 5+ loses its own ability, and a
      non-Leveler card is unaffected).

- [x] **Mana spend restrictions, RULE 605.3a (2026-07-16):** "Spend this
      mana only to cast a creature spell." was parsed as far as the "Add
      …" clause but the restriction itself was silently dropped —
      `models/mana_pool.py` had no concept of tagged/restricted mana at
      all (a flat `dict[str, int]`), so once a Castle Garenbrig or
      Gnarlroot Trapper's mana landed in the pool it was fungible with
      everything else, payable toward any cost. This was flagged as the
      single largest architectural item left in the whole M1 plan (the
      only one touching the core payment solver rather than just the
      parser front-end).

      **`ManaPool`** (`models/mana_pool.py`) gained a second structure
      alongside the existing flat `self.pool`: `self.restricted`, a list
      of `{"restriction": dict, "amounts": {type: count}}` lots (merged
      in-place when `add`'s `restriction` dict matches an existing lot,
      so the list doesn't grow per mana unit). `ManaPool` itself stays
      completely ignorant of what a restriction dict *means* — the
      "models/ must not import game/" boundary (CLAUDE.md) — it only ever
      calls a caller-supplied `allows_restriction(restriction) -> bool`
      predicate (`can_pay`/`pay`'s new keyword, default `None` = no
      restricted lot usable, so every pre-existing call site is
      unaffected until explicitly updated). `_find_payment`/`_solve`
      (the existing backtracking cost solver) run unchanged against a
      *merged* view (unrestricted + whichever lots the predicate allows);
      actually committing a solved payment now goes through a new
      `_consume`, which drains a usable restricted lot before touching
      unrestricted mana of the same type (restricted mana is otherwise
      simply wasted the next time the pool empties, RULE 500.4 — spending
      it first is always at least as good as spending unrestricted
      instead). `total()`/`empty()` cover both structures; `to_dict()`
      additively includes a `"restricted"` key only when non-empty (no
      frontend display yet — see `docs/implementation-state/BACKLOG.md`).

      **`game/mana_abilities.py`**: `ManaAbility` gained a `restriction`
      field, populated by a new `_parse_restriction` recognizing the
      real-card vocabulary found via a live-cache scan (27 cards contain
      "spend this mana only", `re.search`, case-insensitive) — casting a
      creature/legendary/instant-or-sorcery spell, a named creature type
      ("an Elemental spell", "a Ninja or Turtle spell", "an Elf creature
      spell"), your commander, or paying any cost containing `{X}`;
      several also pair with "... or activate an ability of a
      \<same-type\>" (Castle Garenbrig, Primal Beyond), tagged as
      `allow_ability`. Unrecognized shapes — a land's own "of the *chosen*
      creature type/color" (Cavern of Souls, Secluded Courtyard,
      Unclaimed Territory, Throne of Eldraine — no per-object "chosen
      type" read exists at the mana-ability layer yet) and a
      mana-value-threshold clause (Helga, Troyan) — are left unrestricted,
      fail-soft exactly like every other unrecognized shape in this file;
      not a regression, since the restriction was already silently
      unenforced for them before this batch too. Two new predicate
      builders, `restriction_predicate_for_cast(obj, has_x)` and
      `restriction_predicate_for_activation(source, has_x)`, turn a
      spell/ability-source's printed characteristics
      (`card.is_creature`/`is_legendary`/`is_instant`/`is_sorcery`,
      `obj.is_commander`, `continuous.has_subtype`) into the
      `allows_restriction` predicate `ManaPool` consumes — `has_x` reads
      `ManaCost.has_variable`, which (confirmed) stays `True` after
      `with_x` resolves the announced value, so no separate "did this
      cost print `{X}`" tracking was needed.

      **Wired at every payment call site** that pays *from* a player's
      pool: `GameEngine.tap_for_mana` now tags produced mana with
      `ability.restriction`; `GameEngine.can_cast`/`RulesEngine.cast_spell`
      build a cast-context predicate from the spell object; `GameEngine.
      _can_pay_activation_cost`/`_pay_activation_cost`/`_max_x_for_mana`
      build an activation-context predicate from the ability's `source`
      (covering both real activated abilities and a mana ability's own
      non-`{T}` cost component). Ward/"counter unless pays" costs
      (`RulesEngine._pay_ward_cost`/`resolve_counter_unless_pays_choice`)
      were deliberately left at the `allows_restriction=None` default —
      no printed restriction on any real card covers paying those.

      **Real-cache yield**: of the 27 cards printing a "spend this mana
      only" clause, 9 are granted-ability templates quoted inside another
      permanent's own text ("Artifacts you control have '{T}: Add …'") —
      already excluded from `parse_mana_abilities` entirely by its
      pre-existing quote-skip (a separate, unrelated gap: the granted-
      ability/layer-6 static-grant system doesn't carry a restriction
      through yet either) — and 5 more don't produce any mana option at
      all today regardless of restriction ("any combination of colors",
      "the chosen color" — Batch 7 territory). Of the 18 cards that
      already produce a real `ManaAbility`, **13 now get a correctly
      modeled restriction** (Abundant Countryside, Ancient Ziggurat,
      Beastcaller Savant, Castle Garenbrig, Delighted Halfling,
      Elementalist's Palette, Food Chain, Gnarlroot Trapper, Jeweled
      Lotus, Plaza of Heroes, Primal Beyond, Somberwald Sage, Turtle
      Lair); the remaining 5 (Cavern of Souls, Helga, Secluded Courtyard,
      Troyan, Unclaimed Territory) hit one of the two documented
      unrecognized shapes above and stay unrestricted, same as before.
      Doesn't move the oracle-text parser coverage percentage (mana
      abilities sit outside the `MODELED` gate). Tests: new
      `tests/test_mana_spend_restrictions.py` (35 tests) — `ManaPool`
      lot tagging/consumption-order/emptying, `_parse_restriction` across
      all recognized and deliberately-unrecognized shapes, the predicate
      builders in isolation, and full engine-level end-to-end coverage
      (Gnarlroot Trapper's restricted mana can cast an Elf creature spell
      but not a plain instant; Jeweled Lotus's mana only pays for the
      commander; Castle Garenbrig's restricted mana pays a creature's
      activated ability but not a noncreature source's).

- [x] **"Any combination of colors" mana, RULE 605.1a (2026-07-16):** "Add
      N mana in any combination of colors" (Flamebraider/Gwenna, Eyes of
      Gaea/Smokebraider's fixed "two"; Selvala, Heart of the Wilds'
      variable "X" = the greatest power among creatures you control) is a
      genuinely different shape from "any one colour" (Wirewood Channeler,
      already modeled) — the payer *splits* the resolved total across
      colours instead of picking one colour repeated N times. Previously
      produced no options at all (the "any color"/"any colour" phrase
      match doesn't fire on "any combination of colors"'s different
      wording), fail-soft, not a regression.

      **`game/mana_abilities.py`**: `ManaAbility` gained an
      `any_combination: bool` field. A new `_parse_combination_selector`
      recognizes "\<amount\> mana in any combination of colou?rs[, where X
      is \<subject\>]", turning a spelled-out number word ("two") into a
      new `_resolve_amount` `"literal"` selector kind, or (Selvala's only
      observed `X`-subject) "the greatest power among creatures you
      control" into a new `"greatest_power_control"` kind (max power among
      the controller's creatures on the battlefield, 0 with none, the
      existing conservative-1 default with no `state`). The base
      `options` menu is the same 5-entry per-colour palette as "any one
      colour" (`[{c: 1} for c in WUBRG]`, scaled by the resolved total
      through the existing `amount_selector` machinery) — a caller that
      ignores the split still gets a legal, if inflexible, single-colour
      default via `option_index`, same as before this batch existed. A new
      `validate_color_split(split, total)` validates a caller's chosen
      `{colour: count}` distribution (real WUBRG keys, non-negative
      counts, summing to exactly the ability's resolved total) and drops
      zero-count entries.

      **`GameEngine.tap_for_mana`** gained a `color_split` parameter,
      consulted only when `ability.any_combination` and non-`None`
      (`total = sum(ability.options[0].values())`, validated via
      `validate_color_split`); `None` (every pre-existing caller,
      including the goldfish auto-player) falls back to the existing
      `option_index` single-colour behaviour, so the change is additive.
      `legal_actions`' `tap_for_mana` offer now also stamps
      `any_combination`/`combination_total` on the action dict for a
      future frontend split UI (none exists yet — see
      `docs/implementation-state/BACKLOG.md`; today's board still only offers the
      single-colour buttons). `services/game_session.py`'s `tap_for_mana`
      action handler passes a `color_split` dict straight through
      (`_resolve_color_split`, same defensive-cast convention as
      `_resolve_tap_choices`).

      **Real-cache yield**: of the 5 cards containing "any combination of
      colors" (live-cache scan), 4 are real mana abilities and all 4 now
      parse correctly (Flamebraider, Gwenna Eyes of Gaea, Smokebraider,
      Selvala Heart of the Wilds); the 5th (Realm-Scorcher Hellkite) is a
      triggered ETB effect, not a mana ability, correctly out of scope for
      this file. Doesn't move the oracle-text parser coverage percentage
      (mana abilities sit outside the `MODELED` gate, same as the spend-
      restrictions batch above). Tests: new `tests/test_mana_combination.py`
      (17 tests) — the parser (fixed/variable amount, the unrecognized-
      `X`-subject fail-soft path, resolved scaling against a live
      battlefield), `validate_color_split` in isolation, and engine-level
      `tap_for_mana` coverage (default single-colour, an explicit split,
      a wrong-total split rejected, a non-combination ability ignoring an
      incidental `color_split`, a restriction still tagged onto combination
      mana, and the `legal_actions` offer's new fields).

- [x] **Hand-zone mana abilities, RULE 605.1a (2026-07-16):** "Exile this
      card from your hand: Add …" (Elvish Spirit Guide, Simian Spirit
      Guide) is a mana ability activated straight from a player's hand —
      no battlefield permanent, no {T}, a fundamentally different
      activation surface from every other mana ability this file models.
      `game/costs.py` already parsed the cost shape into
      `ActivationCost.exile_self_from_hand`, but `parse_mana_abilities`
      deliberately skipped any line with it (never a *battlefield* tap
      ability) and nothing else picked such a line up — the ability had
      no activation path whatsoever, a genuinely unprecedented gap (no
      existing "from hand" activation surface to extend — cycling/unearth
      aren't modeled either).

      **`game/mana_abilities.py`**: `_parse_mana_ability_lines` gained a
      `want_hand_exile: bool` parameter — `False` (the default,
      `parse_mana_abilities`'s existing behaviour, unchanged) keeps only
      non-hand-exile lines; `True` inverts the filter. Two new public
      functions, `hand_mana_abilities(card)` and
      `hand_mana_abilities_for(obj, state=None)`, mirror
      `parse_mana_abilities`/`mana_abilities_for` exactly (same
      `ManaAbility` shape, same `resolve_options` scaling machinery, so a
      hand-exile ability can in principle be an "any one colour" or "any
      combination of colours" (Batch 7) choice too, or carry a RULE 605.3a
      restriction, with zero extra code) but select the opposite lines and
      skip Leveler-block splitting (no observed card pairs the two
      shapes) and layer-6 grants (that machinery only ever targets
      battlefield permanents).

      **`GameEngine.activate_hand_mana_ability`** is `tap_for_mana`'s
      hand-zone counterpart: validates `source` is in `player.hand`
      (not the battlefield), looks up the ability via
      `hand_mana_abilities_for`, resolves `option_index`/`color_split`
      exactly like `tap_for_mana` does, then pays the cost via
      `RulesEngine.exile(source)` (the existing general "move to exile
      from anywhere" primitive already handles a hand→exile zone move and
      fires the right event — no new zone-transition code needed) before
      tagging the produced mana into the pool. No `_can_pay_activation_
      cost`/`_pay_activation_cost` reuse: those assume a battlefield
      permanent (`source.tapped`, summoning sickness) and already
      hard-`False` on `exile_self_from_hand` for exactly this reason (see
      their updated comments). Every real printed card's only cost
      component is the exile itself; a future card pairing it with e.g. a
      life payment isn't handled and would need this extended.

      **Wired end to end**: a new `activate_hand_mana` legal-action kind
      (`GameEngine.legal_actions`, mirroring the battlefield `tap_for_mana`
      offer's shape — `options`/`any_combination`/`combination_total`) and
      `services/game_session.py`'s matching action handler. No frontend UI
      yet — see `docs/implementation-state/BACKLOG.md`.

      **Real-cache yield**: of the 6 cards whose oracle text contains
      "exile this card from your hand" (live-cache scan), only 1
      (Simian Spirit Guide) is a genuine hand-zone mana ability; the
      other 5 (Dual Strike, Haunting Voyage, Highway Robbery, Poison the
      Cup, Railway Brawler) are Foretell/Plot reminder text using the same
      phrase for an unrelated alternative-casting cost, correctly not
      matched (no "Add …" clause on those lines at all). Elvish Spirit
      Guide itself isn't in the current cache. Doesn't move the
      oracle-text parser coverage percentage (mana abilities sit outside
      the `MODELED` gate, same as the other mana-ability batches). Tests:
      new `tests/test_hand_mana_abilities.py` (11 tests) — the parser
      split (a card with both a battlefield and a hand-exile line stays
      correctly separated), `any_combination`/restriction threading
      through the hand path, and full engine-level coverage (exile +
      mana production, rejecting a battlefield source, the
      `legal_actions` offer, a combination-ability `color_split`).

- [x] **Regenerate, RULE 701.16 (2026-07-16):** the keyword action — "give a
      permanent a regeneration shield that replaces the next time it would
      be destroyed this turn with: remove it from combat, tap it, remove
      all damage" — modeled end to end rather than as a hand-waved
      "prevent destruction" shortcut, because RULE 701.16c's distinction
      (regeneration only intercepts *destruction*, never sacrifice/0
      toughness/exile/etc.) turned out to already be a latent gap in the
      engine worth closing regardless of Regenerate itself.

      **New `EventType.DESTROY`** (`models/events.py`): `RulesEngine.destroy`
      now fires this pre-emptively and runs it through the existing
      `apply_replacements`/`on_resolved` machinery (the same pattern
      `deal_damage` already used) instead of moving straight to the
      graveyard — a replacement effect gets a chance to intercept it first.
      With no matching replacement, behavior is unchanged and fully
      synchronous, so this is additive to every existing `destroy` caller.

      **`RulesEngine.regenerate(obj)`** appends a `ReplacementEffect` keyed
      on `DESTROY` + a `target_id` match to `obj.replacement_effects`,
      tagged with a `regeneration_shield` marker attribute (the object's
      `replacement_effects` list also holds a card's own permanent,
      bind-time replacement effects — the marker is how cleanup tells them
      apart). On the first `destroy` event it catches, the shield removes
      itself from the list, clears combat state
      (`attacking`/`combat_defender`/`blocking`/`blocked_by`/
      `dealt_deathtouch_damage`), taps the permanent, zeroes
      `damage_marked`, and cancels the event (no move to the graveyard).
      Multiple `regenerate` calls stack independent shields (RULE
      701.16a); two shields simultaneously applicable to the same event is
      genuine RULE 616.1e ambiguity and opens the existing
      `replacement_order` interactive choice, same as any other
      multi-replacement collision this engine already handles
      (`test_replacement_ordering.py`). An unused shield expires at
      `GameEngine._step_cleanup` (RULE 514.2/701.16a "that turn"), swept by
      the same `regeneration_shield` marker.

      **RULE 704.5g's lethal-damage/deathtouch state-based action** now
      calls `destroy(obj)` instead of the raw `_move_to_graveyard(obj)` —
      the classic "regenerate a blocker" use case. RULE 704.5f (0
      toughness) and every other SBA/zone-move that was never "destruction"
      to begin with are untouched.

      **RULE 701.16c fix (a real, if latent, bug this feature exposed):**
      `RulesEngine.sacrifice` (the effect-driven RULE 701.17 auto-picker)
      and `GameEngine`'s two cost-payment sacrifice call sites
      (`_pay_additional_cast_cost`/`_pay_activation_cost`) previously all
      called `RulesEngine.destroy` directly — harmless before regeneration
      existed, but would have let a regeneration shield illegally save a
      sacrificed permanent once it did. All three now call the new public
      `RulesEngine.put_into_graveyard(obj)` (a `_move_to_graveyard` wrapper
      that never fires `DESTROY`), the same non-destruction choke point
      the pre-existing SBA graveyard moves already used internally.

      **`RegenerateEffect`** (`game/effects.py`, registered as
      `EffectRegistry`'s `"regenerate"`) mirrors `TapEffect`'s dual-mode
      shape: `target_kind="creature"` (default, a real RULE 115 target) or
      `target_kind=None` (acts on the effect's own source, no target
      choice — "Regenerate ~."). `GameContext.regenerate` is the matching
      facade delegate.

      **Parser**: `catalogue/handlers.py` gained `"regenerate"` ("regenerate
      target creature") and `"regenerate_self"` ("regenerate ~"/"it"/"this
      creature") handlers, mirroring the existing `tap`/`tap_self` split
      exactly — zero new grammar.

      **Real-cache yield (honest, verified against the live 2,507-card
      cache): zero net coverage-percentage movement (535/2507, 21.3%,
      unchanged before/after).** Of 10 cards whose oracle text contains
      "regenerate", 9 are "Destroy target creature. It can't be
      regenerated." (Terminate/Pongify/Wrath of God-shaped) — a *modifier
      on Destroy*, not a Regenerate ability, and out of this batch's scope.
      The 1 remaining, Ezuri, Renegade Leader ("{G}: Regenerate another
      target Elf"), needs a subtype-filtered + "another"-excluding target
      shape (`targeting.py`/`subgrammars.py` have no "target \<subtype\>"
      grammar for *any* handler yet, not just this one) — fails closed,
      correctly stays unclaimed rather than dropping the filter. Shipped
      anyway per the plan's own framing: a self-contained RULE 701.16
      engine capability usable by future cache growth and hand-authored
      catalogue entries (`ability_catalogue.py`) regardless of today's
      zero-card yield. Tests: new `tests/test_regenerate.py` (17 tests) —
      parser recognition (both forms + the Ezuri fail-closed negative),
      the shield mechanism (absorbs lethal/deathtouch damage, single-use,
      independent stacking + its RULE 616.1e ambiguity choice, a different
      permanent's own shield doesn't leak), the RULE 701.16c sacrifice/0-
      toughness non-interaction (including `GameEngine`'s own cost-sacrifice
      choke point), cleanup-step expiry (and that it doesn't sweep a card's
      unrelated permanent replacement effect), and `RegenerateEffect.apply`
      in both target modes.

- [x] **Batch 11 (2026-07-16): "up to one" targets, "if kicked" additional
      effects, replacement-clause recognition.** Three independent parser/
      engine features from the M1 backlog, shipped together (real-cache
      verification below is honest about which parts actually moved the
      needle).

      **"Up to one" targets (RULE 115.1a, N=1 only):** the shared `TARGET`
      fragment (`parser/oracle/catalogue/subgrammars.py`) grew an optional
      `(?:up to (?:one|1) )?` prefix (its own named group, `up_to_one`,
      sitting *outside* the existing `target` group so `resolve_target_kind`
      keeps seeing exactly the row text it already matched) plus a
      `target_is_optional(m)` helper — so **every** existing `{TARGET}`-based
      handler recognizes "up to one target X" for free, no per-handler
      grammar duplication. Threaded `optional: bool = False` through to
      `EffectSpec.params`/each consuming effect class's constructor
      (`DealDamageEffect`/`DestroyEffect`/`ExileEffect`/`TapEffect`/
      `ReturnToHandEffect`/`AddCountersEffect`/`ReturnFromGraveyardEffect`)
      → `TargetSpec(optional=...)`, which the pre-existing (but previously
      unused by any of these) `optional` field on `TargetSpec` and
      `targeting.all_requirements_satisfiable`/`GameEngine.has_legal_targets`
      already understood correctly — "zero targets" simply never locks a
      cast, and every effect's own `apply()` already treats a `None`
      target as a no-op, so no `apply()` changes were needed at all. The
      graveyard-recursion family's own hand-rolled "return/put target …"
      regexes (not built on the shared `TARGET` fragment) got the same
      prefix added separately (`UP_TO_ONE`, exported from `subgrammars.py`
      for this reuse). Deliberately **N=1 only** — a real "up to
      two/three/N"/"up to X" multi-target choice needs an interactive
      multi-select and per-effect application over a *list* of targets (the
      engine's `targets` list today is one entry *per targeting effect*,
      not per "up to N" slot) — a materially larger feature left for a
      future batch, not attempted here.

      **"If this spell was kicked, \<effect\>." (RULE 702.33b), the
      *additional-effect* shape only:** a new `EffectSpec.condition`
      field (`parser/oracle/spec.py`, parallel to `AbilitySpec.modes`,
      whitelisted to `{"kicked": bool}` via a new `_validate_condition` —
      it can only gate whether an already-whitelisted effect fires, never
      choose *which* effect runs, so it doesn't widen the docs/09 security
      boundary) + a new `game/effects.py` `ConditionalEffect` wrapper
      (checks `self.source.kicker_count`, forwards `target_spec`) that
      `game/effect_binder.py`'s `build_effects` wraps any effect in when
      its spec carries a `condition`. Parser side: `segmenter.py`'s
      `parse_effect_body` gained a `_KICKED_CONDITION_RE` wrapper-peel,
      tried before `match_clause`, so "if this spell was kicked, X" (as its
      own sentence — `_CONNECTORS`'s existing `.` splitter already isolates
      it from a preceding base effect) recursively parses `X` and tags
      the result with `condition={"kicked": True}`. Deliberately **only**
      the "additional effect" shape (Vastwood Surge: a base effect, then a
      second sentence gated on kicked) — "if kicked, it deals N damage
      *instead*" (overriding an *earlier* effect's own amount — Burst
      Lightning/Rite of Replication-shaped) is a different, unmodeled
      grammar; the wrapped inner clause there ("it deals 4 damage
      instead", no target of its own) fails `match_clause` on its own, so
      it fails closed automatically rather than needing a separate check.

      **`AddCountersEffect` gained a mass `selector="each_creature_you_
      control"`** (RULE 601.2c, mirroring `DealDamageEffect.selector`'s
      "no `target_spec` at all" shape, reusing `continuous.
      group_selector_objects`) + a parser handler for "put N +1/+1
      counters on each creature you control" — built specifically to make
      Vastwood Surge's kicked-conditional clause itself recognizable (it
      wasn't, before this).

      **The basic-land search handler learned "up to N" too**
      (`_SEARCH_BASIC_LAND_TAPPED_RE`): "search your library for up to N
      basic land cards, put them onto the battlefield tapped, then
      shuffle" — a pre-existing engine capability
      (`SearchLibraryEffect.count`, "offered one card at a time") that only
      lacked recognition of the plural/count phrasing (previously only "a
      basic land card"/"it" singular matched).

      **Replacement-clause recognition (RULE 614/616), 3 of the 5
      already-bound `ReplacementRegistry` families:** a new
      `parser/oracle/catalogue/replacements.py` (`replacement_clause_specs`,
      wired into `segmenter.segment_line`'s permanent-only static fallback,
      right after `static_effect_specs` — the two shapes never collide) —
      Doubling Season's/Anointed Procession's token-doubling line ("if an
      effect would create 1 or more tokens under your control, it creates
      twice that many of those tokens instead" → `double_tokens`),
      Doubling Season's counter-doubling line (→ `double_counters`), and
      Torbran/Mechanized Warfare's "plus N damage" line, single-colour
      variant only (→ `additional_damage` with `your_sources_only`/
      `to_opponent_only`/`color`) — each a single fixed real-card sentence,
      full-matched exactly like `static_effect_specs`'s sibling handlers.
      **Found and fixed a real bug this exposed**: `gate.py`'s
      `ParseResult.effect_specs` property (the one thing `ability_catalogue.
      specs_for` actually reads) excluded `ability_kind == "replacement"`
      entirely — before this batch nothing ever produced one from oracle
      text, so the gap was latent; now fixed, or none of this would have
      reached `obj.replacement_effects` at all despite the card parsing as
      `MODELED`. `prevent_damage`'s two real cards (Riot Control/Thought
      Lash) are a structurally different *one-shot spell effect* shape (a
      resolving instant grants a temporary shield — Regenerate-shaped, not
      a standing permanent clause) and are explicitly **not** covered here;
      Innkeeper's Talent's differently-scoped counter clause ("on a
      permanent or player") and Mechanized Warfare's compound "a red or
      artifact source" filter both fail closed, correctly unclaimed rather
      than guessed.

      **Real-cache yield (honest, verified against the live cache, which
      grew to 2,869 cards since the last measurement — re-run
      `coverage_over_cards()` before trusting any cached number): 583 →
      594 fully `MODELED` (+11 cards, 20.3% → 20.7%), zero regressions.**
      Gained: Anointed Procession, Doubling Season, Torbran (all
      replacement-clause recognition — Doubling Season itself is also
      hand-authored in `ability_catalogue.py`, so this specifically moves
      the *parser's own* coverage metric, independent of runtime
      behaviour, which was already correct via that hand-authored entry),
      Blighted Woodland/Burnished Hart/Explosive Vegetation/Migration Path
      (the "up to N basic land cards" search-count fix), Germination
      Practicum/Leatherhead, Iron Gator (the new mass counter selector),
      and Vastwood Surge (all three features combined — search-count +
      mass-counter-selector + the kicked conditional together). The
      RULE-115.1a "up to one target" grammar itself, despite being real
      and independently verified (9 clause instances across 9 different
      cards — Chainsaw, Killian Decisive Mentor, The Wandering Emperor,
      Liliana Death Wielder, Loran of the Third Path, Salvation Engine,
      Bottomless Pool, Aerial Extortionist — now parse correctly at the
      clause level), contributed **0** whole-card flips in this
      measurement: every one of those 9 cards has a *different*, separately
      unmodeled clause elsewhere on the same card (goad, a "with a -1/-1
      counter on it" target filter, "fights", Vehicle/Equipment mechanics,
      etc.) — reported transparently rather than claimed as coverage it
      didn't actually move, same as Batch 10's Regenerate. Tests: new
      `tests/test_optional_targets.py` (10), `tests/test_kicked_
      conditional.py` (15), `tests/test_replacement_clause_recognition.py`
      (11), plus one added to `tests/test_effect_families_wave3.py`
      (the search "up to N" recognition) — 37 new tests total.

- [x] **Batch 12 (2026-07-16): parse-on-load memoization, a real Class
      header-regex bug fix, and surveil (RULE 701.31).** Housekeeping +
      one processing-list pickup, per the M1 backlog's A.6/A.8 items.

      **Parse-on-load memoization** (`parser/oracle/gate.py`): `parse_oracle`
      re-ran the full normalise → segment → match pipeline from scratch on
      *every* call, but it's called once per `GameObject` built
      (`ability_catalogue.specs_for`) — so a popular card (Sol Ring, Swords
      to Plowshares, …) got re-parsed identically on every copy, every
      game. The real work moved to a private `_parse_oracle_uncached`;
      the public `parse_oracle` now memoizes its `ParseResult` in an
      unbounded module-level dict keyed by every field the parse actually
      reads (`_parse_cache_key`: name, oracle_text, keywords tuple,
      is_instant/is_sorcery/is_saga/is_leveler/is_class) — **content**-keyed
      rather than name- or object-identity-keyed on purpose, so a fixture
      `Card` built fresh per test (or a real card refetched with updated
      text) can't collide with a stale entry that merely shares a name.
      `CardDatabase.get_card` deserializes a fresh `Card` object from JSON
      on every call (verified by reading it — no existing instance reuse
      to key off of), which is exactly why identity-keying wouldn't have
      worked. Each call returns `copy.deepcopy(cached)`, so a caller can
      still treat the specs as its own — matches `ability_catalogue.
      register`'s pre-existing "factory returns fresh specs each call"
      contract, even though the parse itself now runs at most once per
      distinct input. (Verified, before adding the cache, that nothing
      in the bind path — `build_effects`/`build_replacements`/
      `attach_to_object`/`bind_ability` — mutates an `AbilitySpec`/
      `EffectSpec` in place; `build_effects` already copies each
      `EffectSpec.params` dict via `dict(spec.params)` before constructing
      the `GameEffect`. The deepcopy is a deliberate belt-and-suspenders
      match to the existing registry contract, not a fix for an observed
      mutation bug.) Tests: `tests/test_oracle_pipeline.py` (cache-hit
      counting via `monkeypatch`, independent-copy mutation isolation, and
      two content-collision regression guards — same name/different text,
      same name+text/different `is_instant`).

      **Class (RULE 716.3) level-header regex bug, found while investigating
      the processing-list's "\<cost\>: level \<n\>" entry (9 cards):**
      `catalogue/levels.py`'s `CLASS_LEVEL_RE` assumed the header reads
      "Level N: \<cost\>" (cost *after* the colon) — but every real Class
      card (verified against 4 live cache rows: Advanced Reconstruction,
      Caretaker's Talent, Cleric Class, Cool but Rude) prints the cost
      *first*, e.g. `"{3}{W}: Level 2"`. The regex had never matched a
      single real card — only the hand-written test fixtures in
      `test_card_structures.py`/`test_oracle_pipeline.py`, which
      (independently, since nothing exercised the real templating) used
      the same backwards order and so passed anyway. Fixed the regex
      direction (cost-first) and the two existing fixtures to match real
      cards; `gate.py`'s class-block `raw_text` construction flipped to
      match. This is a **correctness fix, not new coverage**: all 9 real
      Class cards remain `UNMODELED` after the fix too (each has at least
      one other, unrelated unclaimed clause — "whenever N or more cards
      leave/enter", "this ability triggers only once each turn", "when
      this Class becomes level N", cost-reduction scope variants), but the
      level-header line itself is now correctly claimed (confirmed: the
      "\<cost\>: level \<n\>" processing-list entry is gone), which is a
      prerequisite for any of the 9 to ever reach `MODELED` once those
      other gaps close. Added a direct regression test for the regex
      direction (`test_class_level_header_is_cost_first_not_level_first`)
      so a future revert shows up immediately rather than silently
      resurrecting a regex that has never matched a real card.

      **Surveil (RULE 701.31)**, mirroring the existing Scry (RULE 701.18)
      shape exactly: a new `EventType.SURVEIL`, `RulesEngine.surveil`
      (same non-interactive-session resolution as `scry` — no chooser, so
      it performs the always-legal "keep everything on top" outcome and
      fires the event for any "when you surveil" trigger/UI to observe),
      `GameContext.surveil` facade delegate, a new `SurveilEffect`
      (`game/effects.py`, registered as `"surveil"`), and a parser handler
      (`catalogue/handlers.py`, `surveil {NUMBER}` — the same shape as the
      pre-existing `scry {NUMBER}` handler, zero new grammar concepts).
      Benefits every context the shared handler table already covers for
      free: ETB triggers ("when this land enters, surveil 1."), activated
      abilities ("{2}{R}{W}, {T}: Surveil 1."), and spell effects
      ("Surveil 3.").

      **Real-cache yield (honest, verified against the live 2,869-card
      cache — unchanged in size since Batch 11, so directly comparable):
      594 → 613 fully `MODELED` (+19 cards, 20.7% → 21.4%), zero
      regressions.** Gained: 8 identical "tap-land + surveil 1 on enter"
      cycle lands (Commercial District, Elegant Parlor, Hedge Maze, Lush
      Portico, Meticulous Archive, Raucous Theater, Shadowy Backstreet,
      Thundering Falls), 5 identical "tap-land + activated surveil" cycle
      lands (Fields of Strife, Forum of Amity, Paradox Gardens, Spectacle
      Summit, Titan's Grave), and 6 more varied surveil-shaped cards
      (Larder Zombie, Otherworldly Gaze, Sinister Sabotage, Umbral Collar
      Zealot, Undercity Sewers, Underground Mortuary) whose other clauses
      were already covered by existing handlers. The parse-on-load
      memoization and the Class regex fix are both correctness/performance
      work with no direct `MODELED`-count effect of their own (the memo
      cache is referentially transparent by construction; every real Class
      card still has an unrelated gap, as noted above). Tests: 3 new
      (`test_surveil_handler`, `test_surveil_land_etb_trigger_is_fully_
      modeled` in `test_oracle_pipeline.py`,
      `test_surveil_fires_an_event_for_the_controller` in
      `test_effect_families.py`), plus the 4 memoization tests and 1
      Class-regex regression test above — 8 new tests total (Batch 12).

- [x] **Batch 13 (2026-07-17/18): "cEDH staples" cube playability push —
      five subagent waves (2 generic-parser, 3 hand-authored) raising the
      611-card cube pool from 185 to 271 playable.** A large, multi-wave
      effort driven by the two `is_cube` decks ("cEDH staples" /
      "cEDH staples 2", `models/deck.py`), whose 611 distinct real cards
      are all cached but were mostly `UNMODELED`. "Playable" here means
      either fully `MODELED` by the oracle parser *or* hand-authored in
      `game/ability_catalogue.py` — either path gives real board behavior.

      **Phase A (2 waves, generic parser/engine extensions)** targeted the
      reusable clause templates that block 2+ cards each. Wave A1
      (`catalogue/handlers.py` + effect/cost families): colour-restricted
      destroy/counter, the Magecraft trigger family, "win instead of
      drawing from an empty library," an end-step self-sacrifice trigger,
      self-exile/sacrifice, `AbilitySpec.free_cast_condition`,
      `ActivatedAbility.once_per_turn`, non-mana activation costs. Wave A2
      (`catalogue/static_handlers.py` + layer wiring): the "activated
      abilities of artifacts can't be activated" / cast-limit / draw-tax /
      "doesn't untap" / opponents'-permanents-enter-tapped / Blood-Moon
      land-type-overwrite prohibition-and-static families, plus a
      "\<name\> can be your commander" flag. Along the way Wave A2 also
      built several primitives that had been documented as absolute engine
      limits — **phasing** (RULE 702.26, `GameObject.phased_out`, scoped to
      Robe of Stars' single-permanent case), **`{X}` cost threading**
      (`StackItem.x` → `RulesEngine._substitute_x`), **Channel/Cycling**
      (`ActivationCost.discard_self`), **conditional Flash / instant-speed
      loyalty** (`AbilitySpec.conditional_flash`, `game/condition_query.py`),
      **impulsive look** and **impulsive draw**
      (`ImpulsiveLookEffect`/`ImpulsiveDrawEffect`,
      `GameState.temp_play_permissions`), and **board-count cost reduction
      for a card in hand** (`continuous.self_cost_reduction_for`) — each
      narrated in the "Rules Engine (Phase 2)" section and covered by its
      own test file (`test_phasing.py`, `test_x_cost.py`,
      `test_channel_cycling.py`, `test_conditional_flash.py`,
      `test_impulsive_look.py`, `test_impulsive_draw.py`,
      `test_cube_batch_a1.py`, `test_cube_batch_a2.py`).

      **Phase B (3 waves, hand-authored singles + cheap generic pickups)**
      worked the one-of-a-kind backlog. B1 (18/30 cards): 6 via reusable
      parser/engine fixes (Walking Ballista's self-reference regex, a
      mass-untap `TapEffect` selector, the two-card-type enters-tapped
      family, `TargetSpec.max_mana_value`, a `forest` target kind) + 12
      hand-authored (Mana Drain, Corpse Dance, Feed the Swarm, Resculpt,
      Mirage Mirror, Phyrexian Metamorph, Steal Enchantment, Grinding
      Station, Goblin Engineer, Winds of Abandon, Eiganjo's Channel ability,
      Winter Orb's global untap-cap static). B2 (12/30): Temur Sabertooth,
      Helm of Awakening, Brainstorm, a generic `wheel` effect (Timetwister),
      Damn, an activation-cost-reduction primitive (Power Artifact), a
      `"not_you"` group-trigger scope + mass-untap (Seedborn Muse), Nether
      Void, Spellseeker, Windfall, a `blink` primitive (Ephemerate), City of
      Traitors — and fixed **two latent engine bugs** the Nether Void test
      surfaced (stack-item resolution racing a just-opened trigger-target
      `pending_choice`; `_resolve_choice_option` never searching the stack
      for a `kind="spell"` trigger target). B3 (18/29): Elesh Norn's
      two-sided anthem, Paradigm Shift, Spirit of the Labyrinth's `draw_limit`
      static, Beast Within, Toxic Deluge, Goblin Recruiter, Zealous
      Conscripts / Coercive Recruiter's `GainControlUntilEndOfTurnEffect`,
      Endurance, Archivist of Oghma, Leonin Relic-Warder's linked
      exile/return, Borne Upon a Wind, Ponder, Snap, Mirrormade, Geistwave,
      Dockside Extortionist, Nature's Claim. The B3 subagent hit a session
      limit after writing all 18 catalogue entries but before its test
      file; that file (`test_cube_batch_b3.py`, 37 tests) was written
      afterward and surfaced **two more real bugs in the just-shipped B3
      code**: three new effects (`ReturnLinkedExileEffect`,
      `ExileLibraryEffect`, `GraveyardToLibraryBottomRandomEffect`)
      referenced `Zone` without a runtime import (`game/effects.py` only had
      it under `TYPE_CHECKING`), and `game/targeting.py`'s `legal_targets`
      had no `nonland_permanent` branch at all (Geistwave — and any
      `nonland_permanent`-targeting spell — could never find a legal target,
      falling through to `return []`). Both fixed.

      **Cube yield: 185 → 271 / 611 playable (30% → 44%)** — 223
      parser-`MODELED` + 48 hand-catalogued. **Cache-wide MODELED moved
      21.4% → 24.3%** (708 / 2,909) as the generic-parser fixes land in the
      shared front-end. Cards left `UNMODELED` for a genuine, documented
      engine gap (impulsive-draw-from-another-player's-library for Ragavan,
      control-*exchange* for Gilded Drake, coin-flip/random-number for
      Tibalt's Trickery/Wheel of Misfortune, Soulbond/Mutate/Evoke/Bargain
      alt-cost mechanics, board-wide ability-strip for Humility, extra-turn
      for Final Fortune, and more) are each logged one line per card under
      `docs/implementation-state/BACKLOG.md`'s "cEDH staples cube"
      section rather than half-modeled. Full suite: 1457 → 1641 passed,
      zero regressions across all five waves.

- [x] **Batch 14 (2026-07-18): cube playability continuation —
      "destroy/counter target X; its controller creates a token" cluster +
      further singles whose primitives already existed, 271 → 285 playable.**
      A direct-authored (no subagents) continuation of Batch 13, working the
      single-unclaimed-clause tail of the 611-card cube pool. Fourteen cards
      shipped, each with a behavioral test in `tests/test_cube_batch_b4.py`
      (28 tests). The reusable pieces:
      - **`counter_create_token` effect** (`CounterCreateTokenEffect`) — the
        stack-side sibling of Batch 13's `destroy_create_token`: counter a
        target spell, then hand a token to the *countered spell's own
        controller*. Swan Song, Strix Serenade, An Offer You Can't Refuse
        (the last with `count=2` Treasures). Its `card_types`/`noncreature`
        target filter reuses `CounterSpellEffect`'s exactly.
      - **Controller-scoped `nonland_permanent` target kinds**
        (`nonland_permanent_you_control` / `_you_dont_control`,
        `game/targeting.py`) — Cyclonic Rift's base (non-overload) mode and
        Alchemist's Retrieval's base (non-cleave) mode, both via the
        existing `return_to_hand`. Overload/Cleave (alternative costs that
        rewrite the target clause) stay unmodeled — documented drops.
      - **Single-type `artifact`/`enchantment` target kinds** — the
        enter-as-copy candidate pool for Copy Enchantment (reuses the
        `enter_as_copy` mechanism, narrowed from Clever Impersonator's
        over-broad "permanent").
      - **Bare "spells cost {N} more/less to cast" parser** — `_SPELL_COST_
        TAX_RE` (`catalogue/static_handlers.py`) now also matches the
        type-word-less phrasing (Sphere of Resistance), taxing every spell;
        a falsy `spell_type` already meant "all spells" in
        `continuous.cost_reduction_for`. Fully `MODELED` by the parser, not
        hand-authored — the one cache-wide pickup (24.3% → 24.4%).
      - **`ReturnFromGraveyardEffect` extensions** — a `library_top`/
        `library_bottom` destination (Noxious Revival, "put target card from
        a graveyard on top of its owner's library"; `_put_searched_card`
        already handled the zone) and a `lose_life_equal_mv` rider that
        reads the returned card's mana value and charges the caster that much
        life (Reanimate).
      - **`nonland_permanents_you_control` group selector**
        (`continuous.group_selector_objects` + `TapEffect._TAP_SELECTORS`) —
        Dramatic Reversal's mass untap, excluding lands.

      Also authored with pre-existing primitives: Pongify / Rapid
      Hybridization (`destroy_create_token` with `can_be_regenerated=False`),
      Path to Exile (`exile_controller_searches_basic_land`), Gitaxian Probe
      (cantrip — the "look at target player's hand" reveal is a no-op in a
      full-information session, documented drop). Full suite: 1641 → 1669
      passed, zero regressions. The remaining ~326 unplayable cube cards are
      dominated by genuinely-new core primitives (spell-copy-on-stack,
      extra-turn insertion, control-exchange, random numbers, reflexive
      per-firing triggers, alt-casting-costs, devotion, fading, mutate/
      soulbond) — each a real feature, tracked in `BACKLOG.md`'s
      "cEDH staples cube" section.

- [x] **Batches 15–17 (2026-07-18): three new core engine primitives from
      the "cEDH staples cube" gap list, each built generically + tested,
      285 → 288 playable.** A shift from the single-clause-tail grind of
      Batches 13–14 to the *engine primitives* that block whole families of
      cube cards. Direct-authored (no subagents), each batch its own test
      file.
      - **Batch 15 — `EventType.SACRIFICE` (RULE 701.17)** (`models/events.py`,
        `RulesEngine._move_to_graveyard`/`put_into_graveyard`;
        `tests/test_cube_batch_15.py`, 7 tests). A move to the graveyard whose
        cause is a sacrifice now fires a distinct `SACRIFICE` occurrence *in
        addition to* DIES/LEAVES — a sacrificed creature fires both, a
        sacrificed noncreature only SACRIFICE, and a *destroyed* creature
        never fires it. `put_into_graveyard` (the single choke point every
        genuine sacrifice — cost payment, `sacrifice`, `SacrificeSelfEffect`
        — funnels through) passes `cause="sacrifice"`. Mayhem Devil registered
        ("whenever a player sacrifices a permanent, deal 1 to any target");
        unblocks the whole "whenever you sacrifice" family.
      - **Batch 16 — reflexive per-firing "that object" trigger (RULE
        603.3d)** (`TriggeredAbility.reflexive`, `effect_binder`,
        `RulesEngine._place_triggers`; `tests/test_cube_batch_16.py`, 4 tests).
        A `reflexive` triggered ability's single targeting effect acts on the
        exact object that fired the event (resolved from the event's
        ``instance_id`` at placement time and baked in — no `trigger_target`
        choice; a vanished object drops the trigger, RULE 603.3c). The generic
        form of the per-firing "that permanent/spell" reference the bespoke
        `check_ward`/`check_rampage` paths hand-build — "counter that spell",
        "destroy that land". No cube card is registered on it yet (each also
        needs a second gap — see `BACKLOG.md`), but it's proven
        end-to-end through the binder + engine and is reused conceptually by
        Batch 17's copy targeting.
      - **Batch 17 — spell-copy on the stack (RULE 707.10)**
        (`RulesEngine.copy_spell`, `CopySpellEffect`/`copy_spell` effect,
        `GameContext.copy_spell`; `tests/test_cube_batch_17.py`, 7 tests). A
        copy is a fresh token `GameObject` of the spell's copiable card (so
        its resolve-time effects rebind cleanly rather than sharing the
        original's instances), controlled by the copier (RULE 707.10c), keeping
        the original's targets + {X}, pushed above the original so it resolves
        first. A copy of an instant/sorcery applies its effects then is reaped
        by the RULE 704.5d stranded-token SBA; a copy of a permanent spell
        resolves into a token permanent. Dualcaster Mage (Flash from the
        keyword catalogue + ETB "copy target instant or sorcery spell") and
        Flare of Duplication (copy, with its optional sacrifice *alt-cast* cost
        a documented drop) now play. "You may choose new targets for the copy"
        is a documented MVP simplification (keeps the original's targets —
        always legal). Narset's Reversal (needs a bounce-spell-to-hand effect),
        Wandering Archaic (interactive per-opponent "may pay {2}") and
        Reiterate (Buyback) stay deferred.

      Full suite 1669 → 1687 passed, zero regressions; cube pool 285 → 288
      playable. Ten primitive batches were scoped for this effort (see
      `BACKLOG.md`); the remaining seven are being worked through
      one at a time (Batch 20 below).

- [x] **Batch 20 (2026-07-18): the "tapped for mana" event primitive
      (`EventType.TAPPED_FOR_MANA`, RULE 605.1), 288 → 289 playable.**
      (`models/events.py`, `GameEngine.tap_for_mana`,
      `effect_binder._trigger_condition`, `ability_catalogue._price_of_glory`;
      `tests/test_cube_batch_20.py`, 6 tests.) `tap_for_mana` now fires a
      `TAPPED_FOR_MANA` event *after* the mana lands in the pool — off a
      genuine mana-ability tap only, never a plain tap-cost (which fires only
      `TAPPED`) or an attack — carrying the source's ``instance_id``,
      ``object_types`` (so "taps a land"/"taps a nonland permanent" filters via
      the ordinary `"group"` subject machinery), the ``controller_id`` that
      tapped it, and the ``produced`` `{colour: n}` mana. **Price of Glory**
      now plays: it composes three primitives with no bespoke code — the
      `"group"` subject (type `land`, any player), a new `not_controllers_turn`
      trigger predicate (RULE 603.4 intervening-if "if it's not that player's
      turn", the event's controller vs. the live active player), and the
      batch-16 reflexive "destroy *that* land". Deferred on a *second* gap
      each: Kinnan Bonder Prodigy ("add one mana of any type that permanent
      produced" — a dynamic produced-mana amount), Wild Growth (a *triggered
      mana ability*, RULE 605.1b/605.4 — must resolve immediately into the pool,
      not via the stack), Mana Web (tap *all* the player's matching lands).
      Full suite 1687 → 1693 passed, zero regressions.

- [x] **Batches 18–24 (2026-07-18): the remaining six core-engine primitives
      from the "cEDH staples cube" gap list, 289 → 295 playable, suite 1693 →
      1734.** Each built generically, tested in its own file, suite green
      throughout. Also a reusable fix: `ability_catalogue.specs_for` now
      matches a registration keyed on a DFC/MDFC/split card's *front-face*
      name (the card's ``name`` is the combined "Front // Back"), which
      Shatterskull Smashing needs.
      - **Batch 19 — divided damage (RULE 601.2d)** (`DealDamageEffect(divided=
        True)`, ``double_at``; `tests/test_cube_batch_19.py`, 9 tests). The
        total {X} pool splits across the chosen targets (even split — a
        UI-less simplification; total + which permanents take it are exact),
        doubling at a threshold (Shatterskull's X>=6). **Shatterskull Smashing**
        (the sorcery front of the MDFC — casts normally) and **Fire Covenant**
        (with the Toxic-Deluge `pay_life: "x"` cost) now play.
      - **Batch 22 — delayed triggered abilities (RULE 603.7)** (`GameState.
        delayed_triggers` + `DelayedTrigger` + `create_delayed_trigger` effect,
        fired at STEP_BEGIN by `GameEngine._fire_delayed_triggers`;
        `tests/test_cube_batch_22.py`, 8 tests). A resolving spell arms a
        trigger for a future step (``scope`` controller/any, ``step`` ``main``
        matching either main phase, ``capture="target_mana_value"`` for a
        value that must be read before the target leaves, ``min_turn`` to skip
        the current turn). **Mana Drain** upgraded from counter-only to fully
        modeled. The Pacts (interactive pay-or-lose) and Corpse Dance
        (Buyback + reanimation) reuse it but stay deferred.
      - **Batch 18 — extra turns (RULE 500.7)** (`GameState.extra_turns` FIFO
        consumed by `GameEngine.begin_turn` + `take_extra_turn`/`lose_game`
        effects; `tests/test_cube_batch_18.py`, 5 tests). An inserted turn is
        taken right after the current one. **Final Fortune** plays — its "lose
        at that turn's end step" downside is a batch-22 delayed trigger with
        ``min_turn_offset=1`` so it lands on the *extra* turn's end, not the
        casting turn's.
      - **Batch 23 — granted protection (RULE 702.16)** (`GameObject.
        temp_protections` read by `combat.is_protected_from`, granted via the
        interactive `grant_protection` effect / `RulesEngine.grant_protection_
        choice`, cleared at cleanup; `tests/test_cube_batch_23.py`, 9 tests).
        **Mother of Runes** and **Giver of Runes** (its "colorless" option; the
        "another" restriction a documented drop) now play.
      - **Batch 24 — board-wide ability strip (layer 6, RULE 613.7f)**
        (`remove_all_abilities` static → `GameObject.loses_all_abilities`;
        `tests/test_cube_batch_24.py`, 5 tests). Strips every keyword
        (`combat._obj_keywords` → empty) and gates triggered (`_collect_
        triggers`) and activated (`can_activate`) abilities. **Humility** plays
        (strip + layer-7b `pt_set` to base 1/1). Dress Down deferred (adds an
        ETB draw + end-step self-sacrifice).
      - **Batch 21 — reproducible random numbers (RULE 705/706)** (`RulesEngine.
        random_int`/`random_choice`/`coin_flip` off `GameState`'s
        ``(rng_seed, rng_counter)``, survives clone/undo; `tests/test_cube_
        batch_21.py`, 5 tests). No cube card registered — Tibalt's Trickery
        (dig-and-cast-free) and Wheel of Misfortune (secret simultaneous
        multiplayer choice) carry far heavier secondary gaps; the primitive is
        proven directly, ready for a future coin-flip card.

      Full suite 1693 → 1734 passed, zero regressions; cube pool 289 → 295
      playable (+7: Shatterskull, Fire Covenant, Final Fortune, Mother of
      Runes, Giver of Runes, Humility, plus Mana Drain upgraded from partial).
      All ten planned primitive batches (15–24) are now done.

- [x] **Card-pool Batch 1 (2026-07-18): full-universe import + firebreathing /
      until-EOT activated pumps.** First batch of the whole-card-pool modeling
      program (`docs/implementation-state/BACKLOG.md`), run
      against the **full ~34k Oracle universe** now bulk-loaded into the cache
      (`scripts/import_bulk.py` → persistent `RawCardStore`,
      `services/raw_card_store.py`; coverage measured/ranked by
      `scripts/coverage_report.py` over the persistent engineering ledger
      `services/coverage_db.py`, which only re-parses changed cards).
      - **Self-reference fold** (`parser/oracle/normalize._fold_self_reference`):
        modern templating writes an ability's own source as "this creature"/
        "this permanent"/"this artifact"/… rather than repeating the printed
        name. These now fold to the same `~` the card-name fold already emits,
        so every handler that already accepted `~` covers the `this <type>`
        phrasing uniformly (many handlers previously re-listed a subset of
        those nouns as literal alternatives — now redundant but harmless).
        Deliberately excludes "this spell"/"this card"/"this ability" and the
        structured "this Saga"/"this Class" (their own parsing). Bonus: the
        fold *merges* the "this creature"/named-self template variants in the
        ranked backlog, so a later combat-static handler claims both at once.
      - **Firebreathing / until-EOT pumps** — `{cost}: this creature gets
        ±N/±N until end of turn.` and `{cost}: this creature gains <kw> until
        end of turn.` now MODELED with no new effect type (the existing `pump`
        handler + `<cost>: <effect>` activated grammar already handled the
        shape once the subject folded).
      - **Sorcery-speed-only activation marker** (RULE 602.5d) — "Activate only
        as a sorcery." / "… only any time you could cast a sorcery." claimed as
        a `SORCERY_SPEED_MARKER` (`catalogue/handlers.py`), stripped by
        `effect_binder` and folded into `ActivationCost.sorcery_speed_only`
        (already enforced by `GameEngine.can_activate`/`_sorcery_speed_ok`).
        Fail-closed: the subtly-different "only during your turn"/"before
        attackers are declared" windows are left unclaimed, not conflated.
      - `PARSER_VERSION` bumped "2" → "3" (invalidates the ledger's affected
        rows). Tests: `backend/tests/test_firebreathing_family.py` (8 tests,
        parse **and** execute); full suite 1514 → 1522 passed, zero regressions.
      - **Coverage: 6,720 → 7,358 / 34,209 (19.6% → 21.5%, +638 cards).**
      - **Deferred:** monstrosity/adapt (RULE 701.32/701.44) — need a new
        `is_monstrous` flag, a "becomes monstrous" trigger event, and new
        effect types; a clean separate mechanic (~63 cards), not rushed in here.

- [x] **Card-pool Batch 2 (2026-07-19): combat/evasion static-restriction
      family.** `~`/attached-permanent "can't attack"/"can't block"/"can't be
      blocked" and their combinations (RULE 508.1a/509.1a), modeled as
      synthetic layer-6 "keyword" flags — not real RULE 702 keywords, just
      internal markers — reusing the existing `grant_keyword`/
      `activation_prohibition` `StaticAbility` machinery with essentially no
      new engine plumbing:
      - **`cant_attack`/`cant_block`/`cant_be_blocked`** — granted via the
        ordinary `grant_keyword` `EffectSpec` (its factory never validated
        keyword *content*, only `static_handlers._flag_keywords` did at parse
        time — bypassed here since these aren't real keywords), so
        `game/continuous.py`'s layer-6 fold-into-`_granted_keywords` needed
        zero changes. `combat.has(obj, "cant_attack")` etc. read them off the
        same union every real keyword uses. Checked by
        `GameEngine._can_attack` (attack declaration) and `can_block` (both
        the blocker's own "can't block" and the attacker's "can't be
        blocked", the latter alongside the existing `temp_unblockable`/
        landwalk unblockable checks).
      - **`attacks_if_able`** — RULE 508.1a's "must attack" is a
        *requirement*, not a restriction, so it can't reuse a `can_attack`
        gate. `declare_attackers` is additive (the UI declares one creature
        at a time) with no "I'm done" signal, so enforcement lives in a new
        `GameEngine._enforce_attacks_if_able`, called from `advance_step`
        exactly when the step about to be left is `"declare_attackers"` —
        raises if any controlled creature carrying the flag could have
        attacked (`_can_attack`, checked before anything about the
        now-declared combat has changed the board) but wasn't declared.
      - **Activated-ability lock** ("…and its activated abilities can't be
        activated.") — reuses the existing board-wide `activation_prohibition`
        family (RULE 602, Collector Ouphe-shaped) unchanged, just scoped to
        `affects="self"`/`"attached_permanent"` instead of a card-type filter
        — its selector vocabulary already supported that. The "…unless
        they're mana abilities" exemption variant (2 cards) was left
        unclaimed (fail-closed): `activation_prohibited` gates a whole
        *source*, not per-ability, and threading a mana-ability exemption
        through it wasn't worth it for 2 cards.
      - **Regression fix**: Batch 1's self-reference fold folds "this
        creature"/"this artifact"/… to `~`, but `_NO_UNTAP_RE` still matched
        the old literal `"this <type>"` wording — dead ever since, quietly
        dropping 37 cards back to unclaimed. Fixed to match `~`.
      - **`no_untap` generalized** to `affects="attached_permanent"`
        (Paralyzing Grasp-shaped "enchanted creature doesn't untap during its
        controller's untap step") — the factory took a hardcoded
        `affects="self"`, and `continuous.has_no_untap_static` read
        `obj.static_effects` directly rather than the shared
        `affected_objects` selector machinery every other static family
        uses; both changed to the generic form (call site:
        `GameEngine._step_untap`).
      - `PARSER_VERSION` bumped "3" → "4". Tests:
        `backend/tests/test_combat_restriction_family.py` (16 tests, parse
        **and** execute, incl. a real `advance_step`-driven "must attack"
        enforcement test and an Aura-attached grant test); full suite
        1522 → 1538 passed, zero regressions.
      - **Coverage: 7,358 → 7,500 / 34,209 (21.5% → 21.9%, +142 cards)** — well
        under the ~1,326-card upper bound from the batch plan, expected: the
        all-or-nothing coverage gate means most of those cards have other
        unclaimed clauses too (the per-template count is cards *blocked*, not
        cards *unlocked*).
      - **Deliberately deferred** (fail-closed, stay unclaimed): every
        qualified/conditional variant ("can't be blocked by/except
        `<filter>`", "can't attack unless …", "…alone", the mana-ability
        activation exemption) and the large, separate family of *targeted,
        resolve-time* "target creature can't block this turn"
        activated/triggered effects (a genuinely different shape — a one-shot
        effect on another object, not a printed static — its own future batch).

- [x] **(2026-07-19) RULE 400.7 "new object" identity fix — `RulesEngine.
      blink`/`return_from_graveyard`.** Live diagnostic (prompted by a
      question about whether a self-reference correctly stops applying to a
      flickered permanent's *old* board instance) found `blink()` reused the
      same `GameObject` without resetting `temp_power`/`temp_toughness`/
      `temp_keywords` — an "until end of turn" pump survived a flicker — and
      `return_from_graveyard()` never cleared counters at all, so a creature
      that died with +1/+1 counters would bring them back via Reanimate/
      Regrowth; neither reset a stale `controller_id` left over from a
      control-change effect that applied before the object left play.
      - **New `GameObject.reset_as_new_object()`** (`models/game_object.py`)
        is the single shared fix point: clears counters, attachment linkage
        (`attached_to`/`last_unattached_from_id`), control/copy state
        (`control_change_until_eot`/`copy_target_id`/`_copy_base`/
        `_copy_applied_target_id`/`_copy_until_eot_base`/`_control_base`),
        cast-time flags (`kicker_count`/`buyback_paid`/`cast_via_flashback`/
        `adventure_snapshot`/`adventure_castable`/`prepared`/
        `prepared_source_id`), combat state (`attacking`/`combat_defender`/
        `blocking`/`blocked_by`/`dealt_deathtouch_damage`/
        `activated_loyalty_this_turn`), every "until end of turn" grant
        (`temp_power`/`temp_toughness`/`temp_keywords`/`temp_effects`/
        `temp_unblockable`/`temp_protections`), the one-time `renowned` flag
        (RULE 702.112b — a new object hasn't become renowned either),
        `linked_exile_id`, transform state (reverts to the front face, RULE
        711.8), and `summoning_sick`/`tapped`/`turn_entered`/`phased_out`/
        `damage_marked`/`static_trace`. Both `blink()` and
        `return_from_graveyard()` now call it, and both now also reset
        `controller_id` to the object's owner by default (RULE 108.4) rather
        than leaving a stale prior controller in place.
      - **Deliberately does *not* change `instance_id`**: it's this engine's
        bookkeeping handle, not literally RULE 400.7's abstract "object", and
        `effect_binder._subject_condition`'s `"self"` trigger closures
        snapshot it at bind time — churning it would silently break
        "whenever ~ attacks" on the very card the method runs for without a
        full re-bind. RULE 400.7's *observable* consequences (ETB triggers
        refiring, summoning sickness resetting, every buff/counter/
        attachment gone) are fully achieved by the field resets above plus
        the caller's fresh `ENTERS_BATTLEFIELD` event and
        `GameState.add_to_battlefield`'s new timestamp. Also leaves
        `triggered_abilities`/`activated_abilities`/`static_effects`/
        `intrinsic_keywords`/`parametric_keywords` untouched — bound once
        from the card's own printed text, they'd come back byte-identical
        from a re-bind, so there's nothing to "forget" there.
      - Tests: `backend/tests/test_new_object_identity.py` (10 tests,
        incl. a positive check that a self-referential "whenever ~ attacks"
        trigger still fires correctly after blink, proving the
        stable-`instance_id` decision doesn't regress self-scoping); full
        suite 1538 → 1548 passed, zero regressions.

- [x] **Card-pool Batch 3 (2026-07-19): Aura/Equipment attached-permanent
      grants.** Two families:
      - **"You control enchanted creature/permanent."** (Control Magic/Mind
        Control-shaped, RULE 613.2) — the existing `control_change`
        `StaticAbility` (`game/effects.py`) already defaults to
        `affects="attached_permanent"` and a controller of "the source's own
        controller" (exactly "you"), so this needed zero new engine code,
        only the parser row.
      - **Quoted full-ability grants** — `<subject> has "<ability text>"` /
        `<subject> gets +N/+N and has "<ability text>"` (Sword-cycle/
        Assassin Gauntlet/Candlestick-shaped): the quoted body is
        **recursively parsed as an ordinary ability line**
        (`segmenter.segment_line`, imported lazily inside
        `static_handlers._quoted_ability_grant_effects` to avoid a module
        cycle — `segmenter` imports `static_handlers` at module level) and
        wrapped as a `grant_triggered_ability` `EffectSpec` **only** when
        that recursive parse comes back a plain ``{"subject": "self"}``
        trigger on one of `_GRANTABLE_TRIGGER_EVENTS` (ENTERS_BATTLEFIELD/
        DIES/ATTACKS/BLOCKS — the only events whose triggering event carries
        an `instance_id` key, which is what `continuous.
        _granted_trigger_condition` scopes a per-object grant by). Anything
        else about the quoted text is left unclaimed (fail-closed), for real
        gaps this batch deliberately doesn't try to close:
        - An **activated**-ability grant (`"{T}: ~ deals 1 damage…"`) needs a
          real "grant an activated ability" layer-6 engine primitive that
          doesn't exist yet (already tracked: `BACKLOG.md` #35,
          Umbral Mantle).
        - A **DAMAGE**-event grant ("deals combat damage to a player") can't
          even be recursively parsed: "deals combat damage to a player" was
          never added to `segmenter.py`'s own `_TRIGGER_EVENTS` map at all —
          a pre-existing gap in the oracle parser's vocabulary, unrelated to
          grants (the existing hand-authored Sword-cycle equipment in
          `ability_catalogue.py` uses `effect_binder`'s DAMAGE/`source_id`
          trigger-subject support directly, bypassing the parser).
        - A **phase/upkeep**-scoped grant ("at the beginning of your
          upkeep…") is blocked by the *same* pre-existing gap
          `segmenter.py`'s `_PHASE_TRIGGER_RE` docstring already documents:
          only the un-scoped "at the beginning of the upkeep step" form is
          recognized; "your"/"each opponent's" controller-scoping was never
          built, for any card, grant or not.
      - `PARSER_VERSION` bumped "4" → "5". Tests:
        `backend/tests/test_aura_equipment_grant_family.py` (13 tests, parse
        **and** execute — incl. control flipping back when the Aura leaves,
        a granted trigger firing only for its own host and disappearing the
        instant it's unattached, and three explicit fail-closed checks for
        the deferred activated/DAMAGE/phase shapes above); full suite
        1548 → 1561 passed, zero regressions.
      - **Coverage: 7,500 → 7,516 / 34,209 (21.9% → 22.0%, +16 cards)** — a
        small net gain despite ~130 raw template hits across the two "has
        `<name>`" templates, because most real cards in that backlog grant an
        activated ability or a phase-scoped trigger (both deferred above),
        and the all-or-nothing gate means a newly-claimed clause often isn't
        a card's *only* unclaimed one.
      - **Deferred** (beyond the three fail-closed shapes above): Aura ETB
        effects ("when ~ enters, tap enchanted permanent", "create a food
        token"), "return this aura to hand" triggers, and the qualified
        combat-restriction variants already left over from Batch 2.

- [x] **Card-pool Batch 4 (2026-07-19): self-referential-trigger family —
      two foundational primitives.** Rather than one recognition sweep, this
      batch closed two gaps flagged (twice) as deferred in Batches 2/3, since
      Batch 4's own backlog needed both:
      - **RULE 207.2c ability-word stripping**
        (`normalize._strip_ability_words`) — "Landfall"/"Constellation"/
        "Battalion" are italicized labels with no rules meaning of their own
        (unlike a keyword ability, whose label *does* carry meaning); a small,
        deliberately conservative list, stripped per-line right after
        lowercasing. Landfall pumps ("Landfall — Whenever a land you control
        enters, ~ gets +N/+N until end of turn.") now fall out of the
        *already-existing* `_GROUP_SUBJECT_RE`/pump handler entirely — zero
        new parsing code, the label alone was blocking them.
      - **Controller-scoped phase triggers** (RULE 500.7) — "at the
        beginning of your `<step>`"/"at the beginning of each opponent's
        `<step>`" alongside the pre-existing unscoped "each `<step>`"/"the
        `<step>` step" forms, all through one extended
        `segmenter._PHASE_TRIGGER_RE`. Since a `STEP_BEGIN` event carries no
        controller of its own to key off (unlike RULE 603.1's object-subject
        events), the new `AbilitySpec.trigger["phase_relation"]`
        (`"you"`/`"not_you"`) is consumed by a new predicate in
        `effect_binder._trigger_condition` that checks
        `context.state.active_player` against the ability's own source's
        controller — the same shape `not_controllers_turn`/
        `controllers_turn_only` already use elsewhere in the codebase, just
        for this specific "whose turn is it" question.
      - **Self-subject "deals (combat) damage to a player/creature"** (RULE
        120.3) — `segmenter._SELF_DAMAGE_TRIGGER_RE`, a dedicated bypass (like
        `_MAGECRAFT_RE`) emitting `EventType.DAMAGE` + a `{"combat": bool,
        "is_player": bool}` filter — exactly the shape
        `effect_binder._trigger_condition`'s `"filter"` docstring already
        documented for the hand-authored Sword-cycle equipment, just never
        reachable from oracle text before. DAMAGE's subject key is
        `source_id` (`_subject_event_key`), already correctly handled by the
        ordinary `{"subject": "self"}` condition — no new binder plumbing
        needed for the direct (non-granted) case. "`~` deals damage" (no
        "combat") omits the `combat` filter key entirely rather than pinning
        it `False`, so an unqualified damage trigger still matches real
        combat damage instead of wrongly excluding it.
      - **Bonus, closing a Batch-3 deferral**: extended
        `grant_triggered_ability`/`continuous._granted_trigger_condition` to
        DAMAGE events too — `_granted_trigger_condition` gained a
        `trigger_event`/`event_filter` parameter and an event-subject-key
        table (`_GRANTED_EVENT_KEYS`, mirroring `effect_binder.
        _subject_event_key`) instead of always assuming `instance_id`, and
        `grant_triggered_ability`'s `EffectSpec`/factory now threads a
        `filter` param through. Combat Research ("Enchanted creature has
        'whenever ~ deals combat damage to a player, draw a card.'") now
        models fully, where Batch 3 explicitly left it unclaimed.
      - `PARSER_VERSION` bumped "5" → "6". Tests:
        `backend/tests/test_phase_and_damage_triggers.py` (18 tests, parse
        **and** execute — incl. a your-upkeep trigger firing only on the
        controller's own upkeep vs. an opponent's-upkeep trigger firing only
        on an opponent's, a damage-counter trigger not firing for a
        different creature, and the Combat Research quoted-DAMAGE-grant
        firing only for its own host); one existing Batch-3 test
        (`test_quoted_damage_trigger_grant_stays_unclaimed`) flipped to
        `_is_modeled` now that the gap it documented is closed. Full suite
        1561 → 1579 passed, zero regressions.
      - **Coverage: 7,516 → 7,672 / 34,209 (22.0% → 22.4%, +156 cards).**
      - **Deferred**: "sacrifice `<name>` unless you pay `<cost>`" — the
        single biggest remaining upkeep-trigger template (45 cards), now
        blocked *only* by this effect body (a real new primitive needing an
        interactive pay-or-lose-it choice), not by phase-scoping anymore;
        "draw a card at the beginning of the next turn's upkeep" (a
        delayed-trigger phrasing, distinct from a standing phase trigger);
        conditional-transform upkeep triggers (Delver-shaped,
        `BACKLOG.md` #16); group-subject damage triggers ("a creature
        you control deals combat damage to a player").

- [x] **Card-pool Batch 5 (2026-07-19): modal-block cleanup — investigation
      overturned the plan's own premise.** The ranked "choose `<n>` —"
      backlog entry (306 cards) looked like a header-recognition gap, but
      `catalogue/modal.py` already splits and parses every real modal block
      correctly. The real cause: `gate.py`'s `_process_modal_block`/
      `_process_triggered_modal_block` fail-close a modal block as a
      *whole* — when even one "• " mode body doesn't parse, every mode body
      (including ones that parse perfectly fine standalone) gets appended to
      `unclaimed` alongside the header, so the header shows up in the
      template ranking as a proxy for "some mode in this block still has a
      gap", not a template fixable by touching the header at all. Re-running
      `_parse_mode_body` per bullet (rather than trusting the aggregated
      `unclaimed` list) isolated the *actually*-failing bodies, surfacing
      three real, cross-cutting gaps — none specific to modal blocks, so
      each also unlocks ordinary non-modal cards that happened not to show
      up under the "choose" ranking at all:
      - **Bare "proliferate."** (RULE 701.30) — `ProliferateEffect`
        (`game/effects.py`) already existed and was already wired into
        `EffectRegistry`; it simply had no oracle-text `EffectHandler` at
        all. One handler (`_proliferate`, matching bare `proliferate`) fixed
        it, and — since `parse_effect_body`'s connector-splitting already
        composes independently-parsed sentences — this alone flips every
        multi-sentence body whose only other gap was already closed by an
        earlier batch (e.g. "Draw a card. Proliferate."). "proliferate
        twice"/"proliferate X times" stay unclaimed (fail-closed):
        `ProliferateEffect` has no repeat-count parameter to carry that to.
      - **Targeted "target player gains/loses N life."** — `GainLifeEffect`
        gained an opt-in `target_kind` (`targeting.TargetSpec`), mirroring
        `LoseLifeEffect`'s pre-existing one exactly (same "declares no
        `target_spec` unless opted in, so a shared `targets` list on a
        multi-effect ability isn't misread" reasoning). Investigating this
        surfaced a **real latent bug**, not just a missing feature:
        `_lose_life`'s regex already *matched* the "target player loses N
        life" phrasing (`(?:you |target player )?loses?...`), but the
        builder never inspected *which* alternative matched — so a
        genuinely targeted life-loss clause was silently being bound as an
        untargeted "you lose N life" all along. Fixed by naming the
        alternation group `who` (matching `_mill`'s existing convention) and
        threading `target_kind="player"` through when it reads "target
        player" — `_gain_life` built the same way from scratch.
      - **"target creature with power/toughness/keyword quality"**
        (`targeting.TargetSpec.creature_filter`, genuinely new — the
        `TargetSpec` dataclass only had `color`/`max_mana_value` as
        offer-time narrowings before) for `DestroyEffect`/`ExileEffect`'s
        new `creature_filter=` param — "destroy/exile target creature with
        power N or greater/less", "…with toughness N or greater", or a
        closed keyword list (flying/defender/first strike/double
        strike/trample/vigilance/deathtouch/lifelink/menace/haste/
        indestructible/hexproof/reach, checked via the existing
        `combat.has`). Deliberately narrow — a compound filter ("power 4 or
        greater and flying") or a non-creature noun ("target artifact or
        enchantment with...") stays unclaimed rather than guessing.
      - `PARSER_VERSION` bumped "6" → "7". Tests:
        `backend/tests/test_modal_creature_filter_family.py` (17 tests,
        parse **and** execute — incl. a direct `targeting.legal_targets`
        check that `creature_filter` actually narrows the offered target
        pool, and that an untargeted `GainLifeEffect` still falls back to
        the source's controller). Two pre-existing tests updated to match
        the now-correct behavior:
        `test_effect_families_wave3.py::test_lose_life_recognizes_plain_and_selector_forms`
        (the "target player loses 3 life" assertion now expects
        `target_kind: "player"` instead of the old silently-untargeted
        params) and `test_oracle_pipeline.py::test_unhandled_clause_is_unclaimed`
        (dropped "proliferate" from its "still has no handler" example set).
        Full suite 1579 → 1596 passed, zero regressions.
      - **Coverage: 7,672 → 7,774 / 34,209 (22.4% → 22.7%, +102 cards).**
        The "choose `<n>` —" backlog entry itself only dropped 306 → 292 —
        expected, since most of that count was always collateral from
        *other*, still-unclaimed sibling modes (compound filters, "fight",
        "exile a player's graveyard", Un-set joke cards, …), not this
        batch's three fixes.
      - **Deferred**: "proliferate twice"/"…x times" (repeat-count support);
        a compound creature filter; "exile target player's graveyard" (a
        new "whole graveyard" effect, not just recognition); **fight**
        ("target creature you control fights target creature you
        don't control/an opponent controls") — no `FightEffect` exists at
        all yet, a genuinely new primitive worth ~40 cards across its
        templates, a strong Batch 6/7 candidate; "manifest dread"/"open an
        attraction"/monarch-adjacent modal options (new subsystems, already
        tracked as Batch 10).

- [x] **Card-pool Batch 6 (2026-07-19): cost-keyword mechanics — investigation
      again overturned the plan's own premise.** The plan row framed this as
      "some new keyword mechanics" (landcycling/megamorph/escape/multikicker/
      strive/kicker-counter variants), but Escape/Kicker/Multikicker were
      already fully *behaviourally* modeled — real cast machinery in
      `game_engine.py` (`_kicker_cost`/`_escape_cost`, `can_cast`'s
      `kicked`/graveyard-Escape branches), unrelated to this batch. The real
      blockers were two **recognition bugs**, neither touching behavioral
      code at all:
      - **`keywords._resolve` only special-cased the `<type>walk` family**
        (Islandwalk → the generic `landwalk` row). Cycling has the identical
        "Scryfall mints one keyword name per type" shape — Plainscycling/
        Mountaincycling/Forestcycling/Swampcycling/Islandcycling/
        Wizardcycling/Slivercycling/**Basic landcycling** — but wasn't
        generalized the same way. "Basic landcycling" in particular wasn't
        even in the hand-written `_ALIASES` map at all, so `parse_keywords`
        silently skipped it as an unrecognized keyword name (fail-closed
        skip), never reaching cost extraction — not a coverage-gate quirk,
        a real gap in the keyword-spec *builder* itself. Fixed with the same
        suffix generalization `_resolve` already had for `walk`
        (`slug.endswith("cycling")` → the base `cycling` row), covering
        every present and future `<type>cycling` name in one change.
      - **`segmenter.is_keyword_line`** (the coverage gate's "this line is
        just a keyword, don't try to parse it as a clause" check) had two
        compounding bugs:
        1. It only recognized `KEYWORDS`' canonical `_TABLE` display names
           ("Kicker", "Morph", "Cycling"), never the alias spellings a real
           card actually prints ("Multikicker", "Megamorph", "Landcycling",
           "Partner with", …) — `KEYWORDS` only holds the canonical rows;
           `_ALIASES` maps slug→slug, not display→slug, so this raw-text
           scan never saw them. Fixed with a new `keywords.ALIAS_DISPLAYS`
           export (the alias keys' own lowercase spellings) folded into the
           same `_KEYWORD_DISPLAYS`/`_KEYWORD_TOKEN_RE` construction.
        2. It blindly `line.split(",")`ed every line, so any keyword whose
           own parameter contains a comma — Escape's "{cost}, Exile N other
           cards from your graveyard", Ward/Kicker's non-mana fallback costs
           ("Pay 2 life", "Discard a creature card"), Partner with's
           "\<Name\>, \<Epithet\>" — had its own continuation misread as a
           second, unrecognized token, failing the "every token must be a
           keyword" check for the *whole* line. A first attempt (split only
           before a comma that's immediately followed by a *new* recognized
           keyword) proved too permissive: a manufactured regression test,
           `"flying, then draw a card"`, was wrongly accepted, because not
           splitting there let the trailing prose ride along inside
           `_KEYWORD_TOKEN_RE`'s own greedy `.*$`. Replaced with a narrower,
           closed-list design instead: a comma-split token only rejoins its
           predecessor when the predecessor starts one of six known
           compound-parameter keywords (`_COMPOUND_PARAM_START_RE` —
           escape/ward/kicker/multikicker/partner with/friends forever) —
           the regression test now correctly fails.
      - Separately, one real **new capability** (not a recognition fix):
        RULE 702.33b's kicked-conditional flavor of the RULE 614.1
        entry-counters clause — "if ~ was kicked, it enters with N counters
        on it." (Academy Drake/Baloth Gorger/Cragplate Baloth/Grunn-shaped)
        and its Multikicker-scaled sibling "~ enters with N counters on it
        for each time it was kicked." (Apex Hawks-shaped, where the printed
        N is a *per-kick* amount, not the total). Both reuse the existing
        `counters.py`/`RulesEngine._apply_entry_counters` machinery — two
        new regexes plus new `kicked_gate`/`kicked_scale` condition-dict
        keys, resolved against `GameObject.kicker_count` (already stamped
        at cast time by `_cast_current_face` for the pre-existing "if this
        spell was kicked, \<effect\>" additional-effect shape). Since
        `entry_counters_condition` is the single source of truth both the
        coverage gate and the engine consult, this one change is
        simultaneously the recognition fix and the real behavior.
      - `PARSER_VERSION` bumped "7" → "8". Tests:
        `backend/tests/test_batch6_cost_keyword_family.py` (23 tests,
        parse **and** execute) — including the fail-closed regression guard
        above, an end-to-end `GameEngine` cast proving the kicked-gated and
        Multikicker-scaled counters actually land (or don't) on the
        battlefield object, and a `Comet Storm`-shaped card confirming the
        batch didn't accidentally claim the separate, still-unmodeled
        "X damage divided among any number of targets" clause riding on the
        same card. Full suite 1596 → 1622 passed, zero regressions.
      - **Coverage: 7,774 → 7,872 / 34,209 (22.7% → 23.0%, +98 cards).**
      - **Deferred** (fail-closed): the "…and with \<keyword\>" compound
        form of kicked-gated entry counters (conditionally granting a
        keyword too — a different, bigger mechanism than counters alone);
        Kicker `{X}`'s own paid-X variant (Emblazoned Golem, 1 card — its
        "X" is the kicker's own paid amount, a different value than a plain
        cast-for-X's `x_paid` the unconditional shape resolves against, so
        deliberately not conflated); granting cycling *to other cards*
        ("each card in your hand has cycling {2}" — a static-grant shape,
        not a keyword-recognition one); **Strive** — not actually a RULE
        702 keyword ability in this codebase's catalogue at all (confirmed
        absent from `docs/Reference/rules_wiki/`), a per-extra-target cost
        escalation needing its own new grammar, not a `keywords.py` fix;
        true face-down Morph/Megamorph *execution* (casting face-down as a
        2/2, turning face up — a real new permanent-state subsystem,
        `BACKLOG.md`-tracked, unrelated to this batch's
        recognition-only scope); generic Cycling *execution* for an
        unregistered card (the `discard_self` hand-zone activated-ability
        primitive already exists from earlier Channel/Cycling work, but
        binding a bare oracle-recognized "cycling" keyword spec into a real
        activatable ability for *any* card, not just the two hand-authored
        ones, is still unbuilt).

- [x] **(2026-07-16) "Play/cast from the top of your library" permission**
      (Oracle of Mul Daya/Glarb, Calamity's Augur-shaped — the frontend's
      library-zone visualization, `docs/implementation-state/BACKLOG.md`/
      `Done_Frontend.md` "Game engine hookup", asked for the engine
      capability underneath it). RULE 701 has no native "play from the
      top" provision — every real card grants it as its own static
      ability — so this is a new, self-contained engine mechanism rather
      than an extension of an existing family:

      **New marker effect** `TopLibraryPermissionEffect` (`game/
      effects.py`, registered as `"top_library_permission"`): carries
      `look`/`play_lands`/`cast_spells`/`min_mana_value`/`requires_
      attached` params, binds via the ordinary `static` `AbilitySpec`
      dispatch onto its source's `obj.static_effects` — the same list
      `StaticAbility`s live in, but this isn't one (mirrors the existing
      `CantBeCounteredEffect` precedent: `continuous.recompute` only ever
      reads `StaticAbility` instances off that list via an `isinstance`
      filter, so it's inert to the layer system; a dedicated reader
      consumes it instead).

      **New `game/top_library.py`** reads these live off the battlefield
      (`state.permanents_controlled_by(player.id)`, mirroring `game/
      mana_abilities.py`'s "scan on demand" shape rather than a cached
      derived field) — so the permission disappears the instant its
      source leaves the battlefield, or (for a `requires_attached` grant,
      an Equipment/Reconfigure shape) the instant it's unattached, with no
      separate cleanup step. `may_look_at_top_of_library`/`may_play_land_
      from_top_of_library`/`may_cast_spell_from_top_of_library(card)` are
      the three consumer-facing predicates; multiple simultaneous grants
      **OR together** (a spell is castable if *any* active grant's
      `min_mana_value` gate, or lack of one, allows it — never the
      intersection of every grant's own filter).

      **Engine wiring** — all zone-agnostic, reusing existing machinery
      rather than adding a parallel path: `GameEngine.can_play_land`/
      `can_cast`'s zone gates each grew one more disjunct
      (`player.library[-1]` plus the matching permission check, mirroring
      the pre-existing exile/graveyard "castable from X" precedent);
      `play_land` changed its hardcoded `Zone.HAND` removal to
      `player.remove_from_zone(obj, obj.zone)` (zone-agnostic — `obj.zone`
      is always accurate, the same idiom `RulesEngine.
      _remove_from_current_zone` already used for casting, which turned
      out to have been **zone-agnostic for the library already** — its own
      docstring already said "hand, exile, library, graveyard", so casting
      from the library top needed no `RulesEngine` change at all, only the
      `GameEngine`-level legality gates). `legal_actions` grew one more
      zone loop (`player.library[-1]`, mirroring the graveyard loop
      immediately above it) offering `play_land`/`cast_spell` actions —
      which, being ordinary actions keyed by `instance_id`, dispatch
      through the pre-existing zone-agnostic `GameSession._object`/
      `find_object` with no changes there either.

      **Two real cards hand-authored** (`game/ability_catalogue.py`,
      confirmed against the live cache's exact oracle text): Oracle of Mul
      Daya (`look`/`play_lands` only — its "additional land drop" line is
      a separate, still-unmodeled player-level permission, deliberately
      left off rather than guessed at) and Glarb, Calamity's Augur
      (`look`/`play_lands`/`cast_spells` with `min_mana_value=4`, plus its
      `{T}: Surveil 2.` activated ability using Batch 12's new `surveil`
      effect — Deathtouch comes from the RULE 702 keyword catalogue
      automatically, unconditional on registration).

      **Session view**: a new `top_library_visible: {player_id: bool}`
      field (`services/game_session.py`'s `view()`) tells the frontend
      whether to render that player's top card at all — the card's own
      data was already unconditionally on the wire (`Player.to_dict()`'s
      `library` array; this app has no hidden-zone redaction layer at
      all, a pre-existing property of this single-process, no-auth tool),
      so this is purely a "should the UI show it" signal, not new data
      exposure. Whether it's actually playable/castable is conveyed the
      ordinary way, through `legal_actions`.

      **Not modeled**: the temporary/activated-cost-based shape (pay a
      cost to gain the permission for a turn, as opposed to a permanent's
      standing "as long as it's on the battlefield" grant) — no real card
      in the local cache needs it yet (The Reality Chip, the shape the
      user asked about by name, isn't in the local cache to verify its
      exact oracle text against; from general knowledge its "as long as
      attached" permission is actually the *same* continuous shape as
      Oracle of Mul Daya/Glarb, just Equipment-gated — supported already
      via `requires_attached`, once the card is cached). A real N>=2
      "look at the top N and choose" variant (Future Sight-adjacent) is
      also out of scope — every card modeled here only ever exposes the
      single top card. Tests: new `tests/test_top_library.py` (19 tests —
      unit coverage of the merge/OR/`requires_attached`/liveness
      semantics, `GameEngine` integration for `can_play_land`/`play_land`/
      `can_cast`/`cast_spell`/`legal_actions`, both hand-authored cards
      end to end, and the session-view flag).

- [x] **(2026-07-20) Search/tutor & graveyard batch** — three previously
      deferred `BACKLOG.md` items:

      **Whole-graveyard targeted exile** (`ExileTargetGraveyardEffect`,
      `game/effects.py`, registered `"exile_target_graveyard"`):
      "exile target player's graveyard" (Bojuka Bog) — distinct from both
      `_exile_from_graveyard`'s single-card family ("exile target creature
      card from your graveyard") and `ExileAllGraveyardsEffect`'s
      untargeted "exile all graveyards" (Farewell-shaped); this one targets
      one player and empties only that graveyard. Parser recognition
      (`parser/oracle/catalogue/handlers.py`'s `_exile_target_graveyard`)
      claims both real phrasings — Bojuka Bog's "exile target player's
      graveyard" and Tormod's Crypt's "exile all cards from target
      player's graveyard" — as the same effect.

      **Standing graveyard-cast permission** (`GraveyardCastPermissionEffect`,
      `game/effects.py`, registered `"graveyard_cast_permission"`; new
      **`game/graveyard_cast.py`**): the graveyard-zone sibling of
      `top_library_permission` just above — same "scan on demand" shape
      (`active_graveyard_cast_grants`/`graveyard_cast_grant_for`/
      `may_cast_spell_from_graveyard`, multiple grants OR together on the
      loosest filter) — but a genuinely different mechanism from
      Flashback/Escape's closed alt-cost keyword vocabulary
      (`GameEngine._graveyard_cast_keyword`): this is a *permission*
      granted by some other permanent, paid at the cast card's own normal
      mana cost, not an alternative cost printed on the card itself.
      `max_mana_value`/`permanent_only` gate what's castable;
      `once_per_turn` (default True, Lurrus's own "once during each of
      your turns") is tracked per **granting object**
      (`GameObject.graveyard_casts_this_turn`, reset every untap step
      alongside `activated_loyalty_this_turn` — two copies of the granting
      permanent each grant their own use). Engine wiring mirrors
      `top_library`'s exactly: `GameEngine.can_cast`'s zone gate grew a
      `_graveyard_cast_permission` disjunct alongside the existing
      `_castable_from_graveyard` keyword check, `_cast_current_face`
      records which grant was used (captured before the cast moves the
      card off the graveyard, same reason `graveyard_keyword` already was)
      and increments its source's counter after a successful cast, and
      `legal_actions`'s graveyard loop offers the cast when either check
      passes. `effective_cast_cost` needed no change — a standing
      permission carries no keyword, so it already falls through to the
      card's own printed cost. Hand-authored: Lurrus of the Dream-Den
      (`game/ability_catalogue.py`, `max_mana_value=2`) — **not** its
      trailing "if a spell cast this way would be put into a graveyard
      this turn, exile it instead" replacement clause, a separate RULE 616
      gap still open in `BACKLOG.md`.

      **Graveyard-sourced "return this card transformed"**
      (`RulesEngine.return_from_graveyard`'s new `transformed` param;
      new `ReturnFromGraveyardTransformedEffect`, registered
      `"return_from_graveyard_transformed"`): the graveyard-sourced sibling
      of the existing `exile_return_transformed` (Fable of the
      Mirror-Breaker/Ayara-shaped exile-and-blink). `transformed=True`
      flips the object onto its back face (`transform_permanent`) right
      after `_put_searched_card` places it — same RULE 400.7 "new object"
      + RULE 712.8 forced-flip treatment, just sourced from a graveyard
      zone-change instead of an exile. The new effect class is untargeted
      (always `self.source`, a dies trigger's own subject — mirroring
      `ExileReturnTransformedEffect`'s identical shape) and no-ops if the
      source isn't actually sitting in a graveyard when it resolves.
      Parser recognition (`_return_from_graveyard_transformed`) claims
      "return it/~ to the battlefield transformed under its owner's
      control" — the graveyard-sourced sibling of
      `_EXILE_RETURN_TRANSFORMED_RE`'s "exile ~, then return it..." (no
      "exile ~, then" prefix: a dies trigger's card is already in the
      graveyard by the time this resolves).

      `PARSER_VERSION` bumped "18" → "19". Tests: `backend/tests/
      test_graveyard_cast.py` (new, 16 tests — unit coverage mirroring
      `test_top_library.py`'s shape, `GameEngine` integration, the
      once-per-turn reset, and Lurrus end to end) plus new parser/engine
      tests in `test_effect_families_wave3.py` (exile-target-graveyard
      parsing + a real two-player exile, the transformed-return primitive,
      its no-back-face no-op, and a full dies-trigger-to-Hulk end-to-end
      test off real oracle text). Full suite 1817 passed, zero
      regressions. **Coverage: 8,041 → 8,052 / 34,209 (23.5%, +11 cards).**

- [x] **Stickers (RULE 123) declared a permanent non-goal** — a project
      directive, not an engineering gap: this codebase will never model
      Sticker sheets/cards. Rather than leaving them as an ordinary
      `UNMODELED` card whose unclaimed clauses perpetually clutter the
      processing-list backlog (no handler will ever claim them), the gate
      now recognizes and fails closed on them distinctly: `gate.py`'s new
      `_mentions_stickers(raw)` (a plain case-insensitive `"sticker" in
      raw.lower()` substring check — no real card uses that word for
      anything else, so no segmenter/normalize machinery is needed to
      decide) runs as an early exit in `_parse_oracle_uncached`, right
      after `raw` is read and before `normalize()`, returning a new
      `NEVER_SUPPORTED` verdict (alongside `MODELED`/`UNMODELED`) with
      `unclaimed=[]` — so the card contributes zero processing-list noise.
      `ParseResult` gained a matching `.never_supported` property
      (`.modeled` already correctly returns `False` for it, so the binder
      treats it exactly like an ordinary unmodeled card — no behaviour is
      ever bound). Threaded through the engineering-side reporting too,
      kept as a *separate* bucket rather than folded into either
      "modeled" or the backlog: `processing_list.CoverageReport` gained a
      `never_supported` field/count (`coverage_report()`); `services/
      coverage_db.py` gained a matching `NEVER_SUPPORTED = "never_supported"`
      ledger value (the `coverage` column already accepted any string, no
      schema migration); `scripts/coverage_report.py`'s `measure()`/`main()`
      write and print that count distinctly instead of collapsing it into
      "unmodeled" (its CLI summary line now reads "N never-supported
      [Stickers, RULE 123]"). `PARSER_VERSION` bumped "19" → "20". A
      Sticker-mentioning card was already uncovered before this change (it
      just polluted the backlog ranking instead of being excluded from
      it), so this doesn't move the headline coverage fraction. Tests:
      `backend/tests/test_stickers_never_supported.py` (new, 7 tests —
      verdict shape, case-insensitivity, zero unclaimed clauses, backlog
      exclusion, and that an ordinary unrelated UNMODELED/vanilla card is
      unaffected). Full suite 1857 passed, zero regressions.

- [x] **Combat blocking + creature-vs-creature damage core:**
      `GameEngine.declare_blockers`/`can_block` and `_step_combat_damage`
      handle blocked/unblocked attackers, gang blocks (lethal-first
      damage spread), and blockers striking back, with the SBA
      destroying lethal-damaged creatures. Attackers declare a defender
      (player or opponent planeswalker, RULE 508.1a); the solo goldfish
      gains a passive dummy so swings connect. Combat/evasion keywords
      (`game/combat.py`, recognized off Scryfall `keywords` + oracle
      text): flying/reach, menace, defender, haste, vigilance, first
      strike, double strike (two damage steps), deathtouch, trample,
      lifelink, indestructible, and protection-from (colour/creatures/
      everything) — surfaced on the board as badges.

- [x] **RULE 613 layer system, full layer coverage + ordering:**
      `game/continuous.py` re-derives every battlefield permanent's
      characteristics in layer order (2 control, 4 type-changing, 5
      colour, 6 ability-adding, 7a/7b/7c/7d/7e power/toughness), stamping
      derived P/T, added types, granted keywords, and a per-object layer
      *trace*; recomputed on every SBA pass and before the view.
      `StaticAbility` + registry bridges every layer it implements:
      `anthem`/`pt_set`/`grant_keyword`/`type_change`/`cost_reduction`
      plus `color_change` (layer 5), `control_change` (layer 2), `pt_cda`
      (layer 7a), and `pt_switch` (layer 7e) — previously those four were
      only reachable by constructing a `StaticAbility` directly in a test
      fixture, with no whitelisted `AbilitySpec` path. `affects` gained
      `"attached_permanent"`, resolving off the ability source's own
      `attached_to` (RULE 303.4/301.5) — the missing half of Aura/
      Equipment support, and `control_change` + `"attached_permanent"`
      covers Mind-Control-style "you control enchanted creature" Auras
      (seed example: Armadillo Cloak). **Timestamp ordering** within a
      layer (`_in_layer` sorts by `GameObject.timestamp`, stamped on
      battlefield entry). **Layer 1 and 3, and RULE 613.8 dependency
      ordering** round out the system: layer 3 (text-changing, RULE 612)
      is scoped to word-substitution over a new `GameObject.
      effective_oracle_text` derived field (`continuous.py`'s `text`
      sublayer, between layers 2 and 4), consumed today only by `combat.
      protections_of_text` (Artificial Evolution's "protection from red"
      → "protection from blue") — not a full oracle-text re-parse, so
      bound abilities/keywords are unaffected; no real card exercises it
      yet (synthetic direct-`StaticAbility` test coverage, the same
      bootstrap pattern `pt_cda`/`pt_switch` used before real-card
      coverage existed). RULE 613.8 dependency ordering is bounded to
      layer 2 (`_order_control_effects`): a `pt_cda`'s count-selectors
      can only *count* objects, never read another object's power/
      toughness, so 7a-level dependency is genuinely impossible, not just
      unauthored; layer 2's controller-scoped `affects` ("creatures you
      control") is the one real case (the textbook CR 613.8 example — two
      control-changing effects where the second's scope depends on what
      the first stole), so direct-scoped abilities (self/
      attached_permanent) always apply before controller-scoped ones,
      regardless of timestamp; every other sublayer is provably safe on
      pure timestamp order. Tests: `test_continuous.py`,
      `test_effect_binder.py` (`TestStaticEffectRegistryBridges`).

- [x] **Oracle-effect parser — Phase 0/1 front-end (keyword catalogue +
      effect-clause front-end):** the compiler design agreed in
      [09_ORACLE_EFFECT_PARSER.md](../concepts/09_ORACLE_EFFECT_PARSER.md)
      (two-stage: front-end parses `oracle_text` → `AbilitySpec` IR;
      binder maps IR → `GameEffect` via the registry) shipped its first
      two phases. **Keyword catalogue (Phase 1a):**
      `parser/oracle/catalogue/keywords.py` maps the full RULE 702
      vocabulary (194 keywords) to its `AbilitySpec` shape (flag/number/
      cost/number+cost/quality) with a regex that extracts each
      parametric keyword's one parameter; `parse_keywords(card)` anchors
      on Scryfall's `keywords` array and pulls the parameter out of
      oracle text. Flag keywords bind: `specs_for` folds the parsed
      keyword specs in, the binder docks parameterless ones onto
      `GameObject.intrinsic_keywords`, unioned into `game/combat.py`'s
      recognition. **Effect-clause front-end (Phase 1b):** `parser/
      oracle/` gained `normalize.py` (reminder-strip, self-name → `~`,
      digit-word fold, newline-preserving), `catalogue/subgrammars.py`
      (shared TARGET/NUMBER/COUNT matchers — one damage handler covers
      "any target"/"target creature"/…), `catalogue/handlers.py` (the
      effect-family table: damage/draw/discard/gain_life/destroy/
      counter, each full-matching a clause), `segmenter.py` (peels
      trigger wrappers → `EventType`, "you may" → optional, splits
      chained clauses), and `gate.py` (`parse_oracle(card)` → specs + a
      fail-closed `MODELED`/`UNMODELED` coverage verdict + unclaimed-
      clause list). `ability_catalogue.specs_for` falls back to it for
      unregistered cards, adding effect/triggered/activated specs only
      when the card is fully `MODELED` (never half-resolves). Handled
      effect families grew to mill, exile, tap/untap, +1/+1 counters,
      and token creation (`MillEffect`/`ExileEffect`/`TapEffect`/
      `AddCountersEffect`/`CreateTokenEffect` + engine primitives
      `RulesEngine.exile`/`set_tapped`/`add_counters`/`create_token`).
      **Tokens** carry the rules-critical lifecycle: `GameObject.
      is_token` (a token *copy* of a real card is still a token), and a
      new SBA `RulesEngine._remove_stranded_tokens` implements RULE
      704.5d — a token that leaves the battlefield reaches its zone long
      enough to fire its dies/leaves triggers, then ceases to exist
      (RULE 111.7-8); exile and destroy both funnel through it. +1/+1
      counters may target any permanent, not only creatures (RULE
      122.1a). **Activated abilities parse too**: the segmenter peels a
      `<cost>: <effect>` wrapper, feeds the cost to `costs.
      parse_activation_cost` and the effect body to the same handler
      table (loyalty `[+N]:` costs stayed `UNMODELED`, closed later).
      `parser/oracle/processing_list.py` added the coverage metric +
      ranked, template-abstracted processing list (docs/09 "coverage is
      the roadmap"). **Static/anthem clauses** (`catalogue/
      static_handlers.py`): "creatures you control get +N/+N", tribal
      lords ("Other Goblins you control …", singularised), token anthems
      (Intangible Virtue), and compound "get +N/+N and have [flag
      keywords]" became `static` specs (`anthem`/`grant_keyword`);
      `continuous.affected_objects` gained subtype/tokens/color/
      exclude_self selectors (Changeling matches any subtype; colour vs
      `card.color_identity`) plus global scope (Bad Moon/Crusade),
      "all"/"each" markers, and multicolour scopes. **Landwalk binds**:
      the binder docks a landwalk keyword spec onto the `<type>walk`
      slug, flowing through as a layer-6 grant. **Replacement binding**:
      `bind_ability` builds `ReplacementEffect`s from a `replacement`
      spec via a new `ReplacementRegistry` whitelist (`prevent_damage`
      shipped first), attached to `obj.replacement_effects`.
      **Parametric keywords** bind their parameter onto `GameObject.
      parametric_keywords` (annihilator N, kicker cost, ward,
      protection quality). **More effect families**: `pump` ("+N/+N
      until end of turn", also −N/−N and a temporary keyword grant, via
      `GameObject.temp_power/temp_toughness/temp_keywords` folded at
      layers 7d/6 and ended in cleanup, RULE 613.4d/514.2), `-1/-1`
      counters, and `scry` (RULE 701.18). Tests: `test_oracle_pipeline.py`.

- [x] **2026-07-14 — three waves of parser expansion** (cache-wide
      coverage 16.9% → 26.9% fully-`MODELED`, suite 922 → 1027 tests):
      - **Enters-tapped claiming** (RULE 614.1): tap-condition
        recognition moved to pure `parser/oracle/catalogue/lands.py`
        (`tap_clause_condition` full-matches one line; `game/
        ability_catalogue.land_tap_condition` delegates), claimed as
        covered-without-spec, plus two new engine kinds —
        `unless_opponents` (Battlebond lands) and basic-land
        `unless_count` (`test_oracle_lands.py`, `test_land_tap_
        conditions.py`).
      - **Attached-permanent statics**: "equipped/enchanted/fortified …
        gets +N/+N [and has \<kw\>]" / "… has \<kw\>" parse to `anthem`/
        `grant_keyword` with `affects="attached_permanent"` (engine side
        already existed; `test_oracle_statics.py`).
      - **Trigger-condition scoping** (RULE 603.1): the segmenter emits
        `trigger.condition` ({subject: self} or {subject: group, type/
        controller/other}); ENTERS_BATTLEFIELD/DIES/ATTACKS/BLOCKS events
        carry `instance_id`+`object_types`; the binder builds the
        matching predicates — fixed a live over-firing bug where a parsed
        "when ~ enters" fired for *any* entering permanent
        (`test_oracle_triggers.py`).
      - **Counter family**: spell target filters (noncreature/card-type
        list/mana-value on `TargetSpec.spell_filter`), "unless its
        controller pays {…}" via a `counter_unless_pays` `pending_choice`
        (auto-counter when unpayable), and "this spell can't be
        countered" as a `CantBeCounteredEffect` marker `RulesEngine.
        counter_spell` refuses (`test_counter_family.py`).
      - **Modal spells** (RULE 700.2): "choose one —"/"choose one or
        both —" blocks parse into `AbilitySpec.modes`
        (`catalogue/modal.py`); casting offers one `cast_spell` action
        per mode (the MDFC per-face pattern), the chosen mode's effects
        becoming the spell's resolve-time effects (`test_modal_
        spells.py`).
      - **Additional cast costs** (RULE 601.2b/601.2h): "as an additional
        cost …, sacrifice a creature/artifact/land | discard a card |
        pay N/X life" parse onto `AbilitySpec.additional_cost`, gate cast
        legality, and are paid at cast time (survive a counter); reuses
        `costs.parse_activation_cost` (`test_additional_costs.py`).
      - **New one-shot families**: return-to-hand (bounce), graveyard
        recursion (new `graveyard_creature`/`creature_you_control`/
        `land_you_control` target kinds), tutor-to-hand + basic-land
        fetch (onto the existing `search`), `add_mana` (Dark Ritual),
        mass damage ("deals N damage to each creature/player/opponent",
        a closed `selector` on `DealDamageEffect`), and ETB self-attach
        for Equipment (`test_effect_families_wave3.py`).

- [x] **2026-07-16 — four engine mechanisms, chosen over further game-
      engine (M5 multiplayer) work since they gate card-text coverage
      directly**: a "remove a counter from ~" activation cost, a real
      N>=2 multi-target choice, "choose *N* —" modality (N>=2), and a
      generalized library-search/tutor grammar. `tests/`: `test_costs.py`
      (already had cost-parsing coverage), `test_search_effects.py`
      (new), `test_modal_choose_n.py` (new), `test_multi_target.py`
      (new) — 1406 backend tests green.
      - **"Remove a counter from ~" cost** (RULE 701.19/602.1): the
        cost-parsing and payment machinery (`costs.py`'s
        `ActivationCost.remove_counters`/`_REMOVE_COUNTERS_RE`,
        `game_engine.py`'s `_can_pay_activation_cost`/`_pay_activation_
        cost`) already existed and was already tested — the only gap was
        `segmenter.py`'s `_COST_LOOKS_REAL` sniff not recognizing
        "remove … counter" as a real cost, so a line whose *entire* cost
        was this (no mana/{T} alongside it) never reached
        `parse_activation_cost` at all. One new regex alternative fixes
        it; Triskelion's real oracle text now parses fully `MODELED`
        end to end. Scope: the fixed-count shape only (already what
        `_REMOVE_COUNTERS_RE` supported) — variable counts ("remove X
        counters", "remove up to 3", "remove any number") still fail
        closed (`docs/implementation-state/BACKLOG.md`).
      - **N>=2 multi-target** (RULE 115.1a generalized — "destroy two
        target creatures"/"destroy up to two target artifacts and/or
        enchantments"/"deals N damage to each of up to two target X"):
        `game/targeting.py`'s `TargetSpec` gained a `count` field (the
        existing `optional` flag is the 0-vs-`count` lower bound);
        `all_requirements_satisfiable` now checks `len(options) >=
        count` for a mandatory multi-target requirement (RULE 601.2c);
        `DestroyEffect`/`ExileEffect`/`DealDamageEffect` each gained a
        `count` param and now apply to `targets[:count]` instead of
        `targets[0]` — sliced off the *front* of a stack item's shared
        targets list, not the whole list, so an unrelated single-target
        effect sharing that same list (a pre-existing pattern —
        `test_ward_two_simultaneous_wards_each_ask_in_turn`) isn't over-
        consumed. New `catalogue/handlers.py` grammar (`_MULTI_TARGET_
        ROWS`/`_MULTI_TARGET_QUANTIFIER`, deliberately separate from the
        shared singular `TARGET` macro other families use) recognizes
        both the mandatory and "up to N" phrasing. Frontend
        (`gameBoardView.js`): a `count > 1` requirement is expanded into
        `count` synthetic one-per-round requirements sharing the same
        options — reusing the *existing* "pick N from one pool, one at a
        time" modal a "tap N untapped `<type>`s you control" cost choice
        already used (`expandMultiTargetRequirements`); had to split the
        old overloaded `excludePicked` flag into a pure dedup flag plus a
        new `isTapChoice` flag (cost-payment UI/dispatch vs. a real RULE
        115 target choice), since the two cases now share the picker but
        need different labels and a different wire dispatch
        (`tap_choices` vs. `targets`). Verified end to end in a real
        browser (Playwright + Replay/Puzzle mode): Curtains' Call
        ("destroy two target creatures") offered both creatures on
        round 1, correctly excluded the round-1 pick on round 2, and
        both died on resolution. Scope: one targeting effect wanting N
        targets, wired up for `destroy`/`exile`/`damage` only — see
        `docs/implementation-state/BACKLOG.md`'s new entry on
        why several *different* targeting effects sharing one spell
        still don't each get their own targets (a real, pre-existing
        limitation this work surfaced more prominently, not introduced).
      - **"Choose *N* —" modality** (RULE 700.2, N>=2 —
        Kolaghan's/Austere Command-shaped, both as a spell and as a
        triggered ability): `MODAL_HEADER_RE` (`catalogue/modal.py`)
        generalized from a fixed `choose 1` to a captured digit;
        `AbilitySpec.modes` gained a `choose` field (`spec.py`,
        validated `1 <= choose <= len(options)`, defaulting to 1 for
        backward compatibility). For a *spell*, `game_engine.py`'s
        `_modal_cast_actions` offers one cast action per legal
        `itertools.combinations` of `choose` modes (`mode` becomes a
        list of indices instead of a bare int/`"both"`); `_effects_for_
        mode` combines the chosen modes' effects in **printed order**,
        not pick order. For a *triggered* ability, `rules_engine.py`'s
        `trigger_mode` choice became iterative — one mode picked per
        round, already-picked ones excluded from the next offer — the
        exact same "pick up to N one at a time" shape the library
        search's `_search_choice`/`resolve_search_choice` already used,
        so `answer` stays a single scalar string per round and neither
        `game_session.py`'s generic choose/decline dispatch nor the
        frontend needed any change (`gameBoardView.js` already renders
        any `pending.options` array generically). Real Kolaghan's
        Command text parses fully `MODELED`.
      - **"Choose *N* or more —" modality** (RULE 700.2, Farewell-shaped —
        a *variable* N from a minimum up to every mode, the other grammar
        axis "Choose *N* —" left unattempted): `MODAL_HEADER_RE`
        (`catalogue/modal.py`) gained an `or_more` suffix group alongside
        the existing `or_both` one (mutually exclusive — Scryfall never
        prints both on one header); `AbilitySpec.modes` gained an
        `at_least` bool (`spec.py`, rejecting `or_both`+`at_least`
        together), threaded through the binder as `obj.spell_modes_
        at_least`/`TriggeredAbility.modes_at_least`. For a *spell*,
        `game_engine.py`'s `_modal_cast_actions` offers one action per
        combination of *every* size from `choose` to all modes
        (`itertools.combinations` per size, chained) instead of one fixed
        size; `_effects_for_mode`'s validity check becomes `>= choose`
        rather than `== choose`. For a *triggered* ability, the existing
        iterative one-mode-per-round `trigger_mode` choice
        (`rules_engine.py`) needed the one piece of genuinely new logic:
        once the minimum is met it offers a `"done"` option (alongside the
        remaining modes) so the player can stop early instead of being
        forced through every mode; picking "done" combines whatever was
        picked so far, in printed order. Real Farewell's own header/mode
        count parses fully `MODELED` (its actual "exile all `<type>`"
        mode bodies are a separate, still-unclaimed mass-effect shape, not
        this feature's concern). No frontend change — same generic
        `pending.options`/`legal_actions` rendering as the fixed-N case.
      - **Generalized "search your library for X" grammar** (RULE
        701.19): the engine mechanism (`SearchLibraryEffect`/
        `RulesEngine.request_search`) was already fully generic —
        arbitrary criteria, arbitrary destination, arbitrary count,
        proven against 15 popular real tutors by `test_search_popular_
        tutors.py` — the gap was entirely in parser recognition, which
        only covered two narrow phrasings ("search for a card, put in
        hand" / "search for a basic land card, put onto the battlefield
        tapped"). New `catalogue/handlers.py` grammar independently
        combines: a criteria noun phrase (bare "a card", a type word
        or "and/or" list, "basic land" as its own alternative so it
        stays `{"basic": True}` rather than also setting a redundant
        `type`), an optional "reveal `<pronoun>`" clause (consumed,
        not modeled — no separate game-state effect at this engine's
        fidelity), five destination phrasings, five pronoun variants
        (a real phrasing difference across cards — "it"/"that card"/
        "them"/"those cards"/"the card"), and both clause orders
        ("…, then shuffle" and the reordered "…, then shuffle and put
        `<pronoun>` on top"). 13 real popular tutors (Demonic/Diabolic
        Tutor, Vampiric/Mystical/Enlightened/Worldly Tutor, Rampant
        Growth, Farseek, Nature's Lore, Crop Rotation, Entomb, Buried
        Alive, Eladamri's Call) now parse fully `MODELED` — Rampant
        Growth specifically was previously blocked by a pronoun
        mismatch the old narrow regex didn't anticipate ("put **that
        card**" vs. the old handler's "it"/"them"-only). Scope
        (deliberately unattempted, real cards found but left
        unclaimed): "search library **and/or graveyard**" (Doomsday/
        Finale of Devastation — `request_search` only reads
        `player.library`, a real engine gap); a split destination per
        found card (Cultivate); "search for N cards and exile the
        rest" (Doomsday); a mana-value/colour-qualified criterion tied
        to a spell's own X (Green Sun's Zenith/Chord of Calling).
        Friedhof-Recherche ("search your graveyard") isn't a real
        template at all — RULE 701.19 searching only applies to a
        *hidden* zone; graveyard retrieval already ships as a
        target-based `return_from_graveyard`/`exile_from_graveyard`
        family (see this section, above) since a graveyard's contents
        are public.

- [x] **Search/tutor: "library and/or graveyard", split destination, and
      "exile the rest" (2026-07-20)** — closes three of the scope gaps the
      generalized search grammar entry above left open (the fourth, a
      mana-value/colour-qualified criterion tied to a spell's own X, stays
      unattempted). `RulesEngine.request_search`/`_search_choice`/
      `resolve_search_choice`/`_finish_search` gained three new params,
      additive and default-preserving (existing callers untouched):
      `zones` (default `["library"]`; `["library", "graveyard"]` combines
      both, eligibility pooled library-then-graveyard and a chosen card
      removed from whichever zone actually holds it —
      `_search_zone_objects`/`_remove_search_hit`), `destinations` (a
      per-found-card override list, zipped positionally against the picks,
      falling back to the shared `destination` past its end — Cultivate/
      Kodama's Reach's "put one onto the battlefield tapped and the other
      into your hand"), and `exile_rest` (once the search finishes, every
      remaining criteria-matching card still in `zones` is moved to exile
      and the shuffle is suppressed entirely — Doomsday's own text puts the
      chosen cards "on top of your library in any order" with no shuffle
      instruction at all, unlike an ordinary RULE 701.19e search). The
      general (non-`exile_rest`) case shuffles whenever `"library" in
      zones`, a documented simplification that doesn't track which
      specific zone the chosen card(s) actually came from.
      `EventType.LIBRARY_SEARCHED` (Archivist of Oghma's trigger) now only
      fires when `"library"` is among the searched zones, matching its own
      "whenever … searches **their library**" wording. `game/effects.py`'s
      `SearchLibraryEffect`/`GameContext.request_search`/the `"search"`
      `EffectRegistry` factory all forward the three new params unchanged.
      Parser side (`catalogue/handlers.py`), three new handler siblings to
      the existing put-then-shuffle/shuffle-then-put-top pair:
      `_search_zone_put` (the real ~50-card backgrounds/planeswalker-tutor
      family's "search your library and/or graveyard for `<criteria>`,
      [reveal `<pronoun>`,] put `<pronoun>` `<destination>`. If you
      search[ed] your library this way, shuffle." — its criteria grammar
      adds a `name` alternative, `card_query`'s existing but
      previously-unused-by-this-grammar `{"name": …}` key, restricted to a
      name with no internal comma since a comma-bearing subtitle like "a
      card named Angrath, Minotaur Pirate" is indistinguishable from the
      following put-clause's own comma without a name dictionary — left
      unclaimed rather than guessed); `_search_split_destination`
      (Cultivate/Kodama's Reach's "put one `<destA>` and the other
      `<destB>`, then shuffle" — the printed "one" is folded to `1` by
      `normalize`'s spelled-number pass same as any other count word, so
      the regex matches the folded form, not the English word);
      `_search_exile_rest` (Doomsday's "search your library and graveyard
      for `<N>` cards and exile the rest. Put the chosen cards on top of
      your library in any order" — no "then shuffle" tail at all, matching
      the engine's own suppression). Doomsday's own card is *not* fully
      hand-authored/parsed end-to-end here — its remaining "you lose half
      your life, rounded up" clause needs a new dynamic-amount life-loss
      primitive this batch didn't build, so the card stays `UNMODELED`
      overall (fail-closed: never resolving half of what a card says);
      the exile-rest primitive itself is proven directly against
      `RulesEngine`/parser recognition instead. Cultivate and Kodama's
      Reach *do* now parse fully `MODELED` end-to-end (identical oracle
      text, both proven). Tests: `test_search_effects.py` (zone/split/
      exile-rest recognition axes, the comma-bearing-name fail-closed
      boundary, a real Tower Winder library+graveyard end-to-end resolve
      proving a graveyard-only hit works, a real Cultivate split-
      destination end-to-end resolve, a direct `RulesEngine` exile-rest
      proof); `test_search_popular_tutors.py`'s prior "known limitation"
      two-search Cultivate workaround test replaced with a real
      single-search split-destination assertion.

- [x] **"Draw a card at the beginning of the next turn's upkeep" parser
      recognition (2026-07-20)** — closed a narrower gap than it looked:
      the RULE 603.7 delayed-trigger *mechanism*
      (`CreateDelayedTriggerEffect`/`GameState.delayed_triggers`) already
      existed (built for Mana Drain), but the oracle-text parser had **zero**
      recognition of the phrase at all — every card using the mechanism was
      hand-authored. New `catalogue/handlers.py` handler `draw_next_upkeep`
      matches "`[you] draw[s] <count> card(s) at the beginning of the next
      turn's upkeep`" and emits `create_delayed_trigger` with `scope="any"`
      (RULE 603.7a — no "your" qualifier means the very next such step
      regardless of whose turn, unlike Mana Drain's own controller-scoped
      "your next main phase"). Deliberately unclaimed: the pronoun-scoped
      "its controller may draw…" variant (Arcane Denial's own first
      sentence) — a different, indirect-referent grammar shape. ~46 real
      cards match the clause; 17 sampled cards flip fully `MODELED`
      (Carrier Pigeons, Blessed Wine, Burnout, …) — the rest have an
      unrelated unclaimed sibling clause. Real cards proved a genuine,
      **pre-existing bug** along the way: `DrawCardEffect.apply` (and the
      identical `DiscardEffect.apply`) fell back to `context.active_player`
      instead of the shared `_controller_of(self.source, context)` helper
      every other untargeted effect uses (`GainLifeEffect` etc.) — invisible
      as long as a "draw a card"/"discard a card" effect only ever resolved
      during its own controller's turn, exactly the assumption an "any
      scope" delayed trigger crossing into another player's turn breaks.
      Both fixed to use `_controller_of`; ~8 other `context.active_player`
      fallback sites elsewhere in `effects.py` were spot-checked but not
      individually audited — flagged, not fixed, since each needs its own
      verification (`docs/implementation-state/BACKLOG.md` doesn't currently list them
      as they weren't proven broken). Tests:
      `test_draw_next_upkeep_family.py` (13 — recognition, the pronoun
      fail-closed boundary, a full step-loop end-to-end resolve, and a
      regression guard proving the delayed draw credits its controller, not
      whoever is active when it fires).

- [x] **Layer-6 grant of an *activated* ability (2026-07-20)** — Umbral
      Mantle/Squirrel Nest-shaped "`<host>` has '`{cost}`: `<effect>`.'",
      the activated sibling of the already-shipped `grant_triggered_
      ability`/`grant_mana_ability`/`grant_keyword` layer-6 grants. **Twice
      deferred** before this (Batch 3, Batch 7) as needing "a real engine
      primitive" — turned out to be a well-scoped mirror of the existing
      `trigger_event` branch, not a from-scratch one: `GameObject.
      _granted_activated_abilities`/`granted_activated_abilities` (mirrors
      `_granted_triggered_abilities` exactly); a `grant_activated_ability`
      `EffectSpec`/`StaticAbility`; a matching layer-6 branch in
      `continuous.recompute` that builds (and per-relationship caches, keyed
      `(id(ability), obj.instance_id, "activated")` so it can't collide with
      the triggered-ability cache dict it shares) a real `ActivatedAbility`
      via `costs.parse_activation_cost`; `GameEngine.can_activate`/
      `activate_ability`/`legal_actions` all now read `activated_abilities +
      granted_activated_abilities` together (both call sites enumerate the
      identical concatenation, so an offered index still addresses the
      right ability). Parser side: `static_handlers._quoted_ability_grant_
      effects` (previously triggered-only) now also recognizes a plain
      `<cost>: <effect>` inner body and emits `grant_activated_ability`;
      `once_per_turn`/`sorcery_speed_only` markers are stripped the same way
      `effect_binder.bind_ability` does for a top-level activated ability
      (no real card needs either yet). Also added the **non-attached**
      sibling `_QUOTED_GRANT_RE` ("`<scope>` [you control] have
      '`<ability>`'" — Acidic Sliver's "All Slivers have '`{2}`, Sacrifice
      this permanent: …'"), sharing `_scope`/`_scope_params` with
      `_GRANT_RE`/`_ANTHEM_RE`.

      Getting a real card working end-to-end surfaced a **pre-existing
      segmenter bug**: `_ACTIVATED_RE` (the top-level "`<cost>`:
      `<effect>`" check) was quote-blind, so a quoted grant whose *inner*
      ability itself contains a cost-colon ("has '`{3}`, `{Q}`: ...'") was
      silently misparsed as if that inner colon were the *outer* line's own
      cost/effect boundary — invisible until now since no handler had ever
      tried to recognize a quote-containing activated-ability shape.
      Chasing this down surfaced a second, larger latent issue: for ~950
      real cards whose quoted grant is a **mana** ability ("Elves you
      control have '`{T}`: Add `{B}`.'", Tyvar Kell-shaped — a plain
      top-level mana ability is claimed-without-a-spec by `segmenter.py`,
      covered directly by `game/mana_abilities.py` instead of the
      `EffectRegistry` pipeline), the *old* buggy `_ACTIVATED_RE` was
      accidentally swallowing the line as "claimed, no spec" whenever the
      bogus quote-truncated cost prefix happened to contain a `{...}`
      symbol and the remaining "effect" text started with "add" — silently
      dropping the real grant while still marking the clause claimed. Fixing
      the quote-blindness (`_ACTIVATED_RE`'s cost group now excludes `"`)
      correctly flipped these to honestly `UNMODELED` rather than
      silently-wrong-but-`MODELED` — a real full-universe coverage
      *decrease* (8038→8019) even though this batch's own net card count
      only tells the fail-closed-correctness story, not a regression in
      real behaviour. Recognizing the mana-ability shape itself
      (`grant_mana_ability` text recognition) is a distinct, still-open
      follow-up — `docs/implementation-state/BACKLOG.md` — that recovered most of the
      apparent loss (8019→8041, net +3 over the pre-batch baseline once the
      two real handlers above are counted) via the non-attached
      `_QUOTED_GRANT_RE` addition alone. `PARSER_VERSION` → `"18"`
      (16: draw-next-upkeep; 17: the `_ACTIVATED_RE` fix; 18: the
      non-attached quoted-grant family). Tests:
      `test_aura_equipment_grant_family.py` (its "activated ability grant
      stays unclaimed" test flipped to a real coverage proof, plus three new
      end-to-end tests: direct `ActivatedAbility.apply` for Umbral Mantle
      and Squirrel Nest, and a full `GameEngine.legal_actions`/
      `can_activate`/`activate_ability` round trip proving the offered
      index and the resolved ability are the same object).

- [x] **Per-effect target partitioning, `StackItem.target_groups`
      (2026-07-16)** — the "targeting / hexproof / ward" edge-case chapter's
      biggest entry: `docs/implementation-state/BACKLOG.md` had
      documented, since the N>=2 multi-target batch above, that a stack
      item's resolved `targets` list is shared by *every* effect on it —
      2+ *different* targeting effects on one spell/ability (two modes of
      a "choose N —" ability each naming a different target, or an
      ordinary triggered ability with two differently-targeted effects)
      would have the second effect wrongly consume the first's target.
      Fixed properly rather than worked around:
      - `StackItem` gained an optional `target_groups: list[list[Any]]`
        field, index-aligned to the targeting effects *encountered in
        order* among `item.effects` (group 0 = the first effect with a
        `target_spec`, group 1 the second, …); `None` (the default) keeps
        every effect reading the flat `targets` list directly, byte-for-
        byte the pre-existing behaviour. `targets` itself is still always
        the flattened union (derived automatically when a caller supplies
        `target_groups` but no explicit `targets`), so every pre-existing
        flat-`targets` consumer (`check_ward`, Aura attachment in
        `_resolve_permanent_spell`, the stack display) is unaffected.
      - `RulesEngine.resolve_top_of_stack` walks `item.effects` with a
        running group cursor, handing each targeting effect only its own
        slice — *except* when `item.effects` is a single `TriggeredAbility`/
        `ActivatedAbility` wrapper (the ordinary, non-modal shape,
        `effects=[ability]`): the partitioning then has to happen one level
        down, inside the wrapper's own sub-effects list, invisible to the
        outer loop. Both `TriggeredAbility.apply`/`ActivatedAbility.apply`
        gained an optional `target_groups` parameter and now share a new
        `game/effects.py` helper, `_apply_effects_partitioned`, doing the
        identical per-effect dispatch against `self.effects` instead of
        `item.effects`.
      - **Casting/activating**: `RulesEngine.cast_spell`/`GameEngine.
        cast_spell`/`GameEngine.activate_ability` all gained an optional
        `target_groups` parameter, threaded all the way to
        `services/game_session.py`'s `cast_spell`/`activate_ability`
        action handlers (`_resolve_target_groups`, the `_resolve_targets`
        per-target resolver applied to each sub-list) — so a caller
        (engine-level code, a test, or a future frontend) can supply
        grouped targets through the same JSON action payload shape
        `requirements_with_targets` already offers per-requirement, in
        order. No real card needs this for *casting* yet, so nothing
        auto-derives `target_groups` from a plain flat `targets` list —
        that's still a genuine follow-up (`docs/implementation-state/BACKLOG.md`)
        once one does; a modal spell's own `mode=[i, j]` combination
        already combines target_groups correctly too, as long as the
        caller supplies them in the same printed order `_effects_for_mode`
        combines effects in.
      - **Triggered abilities**: this *is* fully automatic. `_trigger_
        target_spec` (singular, "only the first spec is meaningful") became
        `_trigger_target_specs` (every spec, in order). `_place_or_pause_
        trigger` keeps the single-spec path byte-for-byte unchanged; for
        2+ specs, a new `_continue_trigger_multi_target` gathers one
        target per effect, one `pending_choice` at a time — the same
        "accumulate across rounds" shape `_trigger_mode_choice`'s "choose
        N" already used — via a new `trigger_target_multi` choice kind
        (`resolve_trigger_target_multi_choice`, wired into `GameEngine.
        resolve_pending_choice`) kept fully separate from the existing
        `trigger_target` kind/resolver so the well-tested single-spec path
        couldn't regress. RULE 603.5 "you may" is only offered as a
        decline on the *first* spec (already committed to the ability
        after that); a mandatory spec with zero legal options drops the
        whole ability (RULE 603.3c), an *optional* ("up to one") spec with
        none is silently skipped (empty group) instead.
      - New `tests/test_multi_effect_targeting.py` (9 tests): direct
        `target_groups` casting (engine call and the session/API JSON
        payload), the single-spec backward-compat guard, the full
        triggered-ability interactive multi-target flow (offer/decline/
        drop/skip), and a modal-spell two-different-targets combination.
        `test_modal_choose_n.py`/`test_modal_spells.py`'s docstrings that
        previously called this an open gap were updated to point here.
      - Deliberately still out of scope: cross-target *constraints* ("two
        target creatures controlled by *different* players", Run Away
        Together) — a different, unrelated axis (correlating *which*
        legal choices are mutually valid, not just giving each effect its
        own target).
- [x] **Ward cost `{X}` resolution, RULE 702.21b (2026-07-16)**: "Some ward
      abilities include an X in their cost and state what X is equal to.
      This value is determined at the time the ability resolves, not
      locked in as the ability triggers." No real card in the cache needs
      this yet, but the previous behaviour was a silent correctness trap
      waiting for one: an unresolved `{X}` mana pip defaults to amount 0
      (`ManaSymbol`), so a hypothetical "Ward—Pay {X}, where X is the
      number of creatures you control" would have always resolved as
      free, regardless of the board. Fixed properly:
      - `costs.ActivationCost` gained an `x_selector` field; `_parse_text`
        recognizes a ward cost's own "where X is the number of `<phrase>`"
        clause against a small, explicit vocabulary (creatures/lands/
        permanents/artifacts you control, cards in your graveyard) —
        reusing (not duplicating) `game/continuous.py`'s existing
        layer-7a characteristic-defining-P/T count-selector vocabulary,
        now factored into a public `count_selector(state, controller_id,
        selector)` (`_count_selector` becomes a thin per-`StaticAbility`
        wrapper over it). An unrecognized phrase leaves `x_selector` unset
        — RULE 107.3c's safe "X stays 0" default, not guessed.
      - `RulesEngine.resolve_ward_effect` (already the *ward ability's own
        resolution*, correctly late per RULE 702.21b's timing — `check_ward`
        merely triggers it) now resolves `cost.mana`'s `{X}` via
        `count_selector`, scoped to the *warded permanent's controller*
        (RULE 603.3a — who controls the ward ability, not the caster who
        pays it; threaded through via `WardEffect.apply`'s new
        `ability_controller_id` argument, derived from `WardEffect.source`)
        — freshly computed against the *current* board, so a permanent
        gained between the spell being cast and the ward ability resolving
        correctly changes X.
      - New tests in `test_game_engine.py`: selector recognition, an
        unrecognized-phrase fallback, a resolution-time-not-trigger-time
        proof (a second creature enters after the ward ability is placed
        but before it resolves, changing X from 1 to 2), and the
        uncastable-counters-without-a-choice case.

- **Equipment/Aura payoff primitives + the "Wyleth Equip" commander deck**
  (2026-07-17): hand-authored the whole "Wyleth Equip" Boros voltron
  commander deck (`game/ability_catalogue.py`, ~50 cards) and, along the
  way, shipped a batch of generic, reusable engine primitives none of the
  deck's individual cards fully accounted for on their own:
  - **Mass "destroy/exile all X [with a filter]" board wipes** (RULE
    601.2c) — `DestroyEffect`/`ExileEffect` gained a `selector`
    (`all_creatures`/`all_artifacts`/`all_enchantments`/`all_permanents`/
    `all_planeswalkers`) + an optional `filter` dict
    (`min_toughness`/`max_mana_value`/`min_mana_value`), mirroring
    `DealDamageEffect.selector`'s existing untargeted-group shape
    (`effects._mass_selector_objects`). `DestroyEffect` also gained
    `can_be_regenerated=False` (Wrath of God's "They can't be
    regenerated.") — `RulesEngine.destroy` skips the replacement pass
    (and so any regeneration shield) entirely rather than going through
    `apply_replacements`. Wired into modal spells (`AbilitySpec.modes`)
    for Austere Command (choose two of four) and Farewell (choose one or
    more, `at_least`); a combined `each_creature_and_player` damage
    selector for Volcanic Fallout.
  - **A new trigger-subject family**: `{"subject": "attached_permanent"}`/
    `{"subject": "self_or_attached_permanent"}` in `effect_binder.
    _subject_condition` — "whenever equipped/enchanted creature `<verb>`"
    (RULE 303.4/301.5), resolved live off the ability's own source's
    `attached_to` every check (naturally stops firing the instant it's
    unattached). Which event-data key identifies "the acting object" is
    now itself selector-driven (`_SUBJECT_EVENT_KEYS`, default
    `"instance_id"`, `"source_id"` for `DAMAGE`) rather than hardcoded.
  - **"Deals combat damage to a player" as its own trigger family**: a new
    `trigger["filter"]` dict (`effect_binder._trigger_condition`), an
    exact-match AND over the firing event's payload — `EventType.DAMAGE`
    filtered to `{"combat": True, "is_player": True}` covers the whole
    Sword-cycle/Bloodforged Battle-Axe/Rogue's Gloves family; `{"is_player":
    False}` would cover "combat damage to a creature" the same way. This
    needed a real bug fix first: `RulesEngine.deal_damage`'s *broadcast*
    event (after replacements resolve) was rebuilt from scratch with only
    `amount`/`is_player`/`target_id`, silently dropping `combat`/`source_id`/
    `source_controller_id`/`source_colors` that the pre-replacement event
    carried — switched to `resolved.copy_with(amount=final)` so those
    survive onto the event every trigger actually observes.
  - **A `requires_equipped` trigger gate** (Akiri, Fearless Voyager) — "an
    equipped creature you control attacks" scoped to the source's own
    `attached_to` relationships, live-checked the same way.
  - **A `subtype_any`-style gate keyed `spell_subtype_any`** (Sram, Senior
    Edificer) — "whenever you cast an Aura/Equipment/Vehicle spell" needs a
    card *subtype* check a `"group"` condition's `object_types` (main types
    only) can't express; reads the live object's `type_line` instead. Also
    added `"SPELL_CAST": "player_id"` to `_GROUP_CONTROLLER_EVENT_KEYS` (a
    "you control" scope on a cast trigger) and stamped `instance_id`/
    `object_types` onto both `SPELL_CAST` firing sites.
  - **Living Weapon (RULE 702.92) and Renown (RULE 702.112) got real
    behaviour**, not just keyword recognition: `effect_binder.
    _keyword_triggered_abilities` now also synthesizes a Living Weapon's
    ETB germ-token creation + self-attach (`LivingWeaponEffect`, a single
    atomic effect since "attach to the token this same effect just
    created" has no other channel) and Renown's counter-placement + a new
    `EventType.RENOWNED` firing (`RenownEffect`, gated by a new
    `GameObject.renowned` one-time flag) — letting a card's own *separate*
    "when this creature becomes renowned, …" trigger (Relic Seeker) key off
    it independently of Renown's own effect.
  - **A per-count static anthem multiplier**: layer 7d `pt_mod` gained
    optional `power_count`/`toughness_count` params (`continuous.
    _pt_mod_count`) — "+1/+1 for each land you control" (Blackblade
    Reforged) reuses the existing controller-scoped `count_selector`
    vocabulary (plus a new `artifacts_and_or_enchantments_you_control`
    entry for Nettlecyst); "+2/+0 for each Equipment attached to *it*"
    (Bruenor Battlehammer) needed a genuinely different *per-object* count
    (`_equipment_attached_count`, evaluated per affected creature rather
    than once for the whole ability) and a `plus_one_counters_on_self`
    selector reading the source's own counters (Lion Sash).
  - **Layer-6 keyword *removal***: a new `remove_keyword` static type
    (mirrors `grant_keyword`) populating a new `GameObject._removed_keywords`
    set, subtracted last in `combat._obj_keywords`/`display_keywords` —
    Colossus Hammer's "loses flying".
  - **RULE 702.8b Flash now actually gates `GameEngine.can_cast`'s timing
    check** (`sorcery_speed = not (card.is_instant or combat.has(obj,
    "flash"))`) — previously Flash was recognized as a keyword but never
    consulted for casting timing at all, so a Flash permanent could only
    ever be cast at sorcery speed; a real pre-existing gap this batch hit
    directly (Embercleave, The Wandering Emperor).
  - **New target kinds** (`game/targeting.py`): `nonbasic_land`
    (Encroaching Wastes), `attached_equipment_you_control`/
    `equipment_you_control` (Akiri's unattach ability / Nahiri, Heir of the
    Ancients' +1).
  - **New one-shot effects**, each backing one clause shape rather than a
    single card: `ExileGainLifeToControllerEffect` (Swords to Plowshares —
    exile + the *same* target's controller gaining life equal to its power,
    a single atomic effect since `GainLifeEffect` deliberately never reads a
    shared `targets` list); `TargetPlayerDrawLoseLifeEffect` (Sign in Blood)
    and `CounterAndFirstStrikeEffect` (The Wandering Emperor's +1) — both
    exist specifically to avoid the "two targeting effects on one ability"
    double-prompt bug (docs/11 §5) that composing two separate `EffectSpec`s
    sharing one target would hit; `ProliferateEffect` (RULE 701.30, auto-
    applies to every permanent already carrying a counter — no
    proliferation picker exists yet); `UnattachTapIndestructibleEffect`
    (Akiri's second ability); `ExileAllGraveyardsEffect`/
    `ExileGraveyardCardCounterIfPermanentEffect` (Farewell / Lion Sash);
    `ExileGraveyardCreaturesGainLifeEffect` (Crypt Incursion);
    `PeekTopLandBattlefieldTappedEffect` (Explorer's Scope);
    `CreateTokenMayAttachEquipmentEffect` (Nahiri, Heir of the Ancients'
    +1); `UnblockableEffect` (Rogue's Passage, a new `GameObject.
    temp_unblockable` flag `GameEngine.can_block` consults, cleared at
    cleanup like every other `temp_*` field); `DrawCardEffect`/
    `LoseLifeEffect` both gained an opt-in `target_kind` (a real RULE 115
    target, previously only reachable untargeted); a new `"cast_free"`
    search destination (`RulesEngine._put_searched_card`) reusing cascade/
    discover's `cast_without_paying` primitive for Sunforger's "search your
    library … and cast that card without paying its mana cost"; a new
    `unattach_self` activation-cost component (`costs.ActivationCost`,
    `GameEngine._pay_activation_cost` clears `attached_to` and stamps
    `GameObject.last_unattached_from_id` so the ability's own effect can
    still reach "that creature" after the cost already detached it).
  - Tests: `tests/test_wyleth_equip_deck.py` (11 end-to-end cases through a
    real `GameEngine`/`RulesEngine`, one per mechanic family above, using
    real cached cards). Deliberately not exhaustive per-card — see
    `BACKLOG.md` "Equipment / Auras / 'combat damage to a player'
    triggers" for narrower per-card edge cases left open, and the entry
    just below for the 8 real architecture gaps that batch surfaced,
    since closed.

- **The 8 real feature gaps the Wyleth Equip batch surfaced** (2026-07-17,
  `docs/implementation-state/BACKLOG.md`'s former "Feature gaps surfaced by hand-
  authoring the 'Wyleth Equip'..." entry) are now closed:
  - **{X} cost threading**: `StackItem.x` (set at cast/activate time) is
    now substituted into a resolving effect's `"x"`-sentinel `amount`/
    `count` by `RulesEngine._substitute_x`, called from
    `resolve_top_of_stack` right before dispatch (both the flat spell-
    effect case and the wrapped `TriggeredAbility`/`ActivatedAbility` case).
    `EffectSpec`'s `"amount"`/`"count"` params may now be the literal
    string `"x"` — the same idiom `additional_cost`'s `pay_life: "x"`
    already used — validated no differently since `_clamp_params` only
    touches `int` values. Tests: `test_x_cost.py` (Banefire/Stroke of
    Genius-shaped fixtures, direct-stack-resolution unit cases, and the
    full cast pipeline).
  - **Board-count cost reduction**: `continuous.cost_reduction_for`
    (battlefield statics) gained an optional `per: <count_selector>` param
    scaling its `generic` reduction by a board count (Delve/Affinity-
    shaped), reusing the existing `count_selector` vocabulary rather than
    inventing a second one. A *second*, new function,
    `continuous.self_cost_reduction_for(obj, state)`, reads a `layer=
    "cost", affects="self"` static straight off `obj.static_effects` for a
    reduction printed **on the spell card itself** (Delve/Affinity's real
    shape) — since that's never on the battlefield, the existing
    battlefield-only scan can't see it; both `GameEngine._adjust_cost` and
    the `legal_actions` cost preview now sum both sources. Tests added to
    `test_continuous.py` (Treasure Cruise/Dig Through Time-shaped Delve,
    Frogmite/Myr Enforcer-shaped Affinity — no in-deck card needs this yet,
    so it's validated off-deck).
  - **Impulsive-look** ("look at the top N cards, take one matching a
    filter, put the rest into Y" — Grisly Salvage/Commune with the Gods-
    shaped): a new `ImpulsiveLookEffect` + `RulesEngine.
    request_impulsive_look`/`resolve_impulsive_look_choice` (a new
    `pending_choice` kind, `"impulsive_look"`, wired into `GameEngine.
    resolve_pending_choice`), modeled on `CascadeEffect`'s peel/route shape
    but generalized like `SearchLibraryEffect`'s criteria/destination
    params — distinct from both (peels exactly N, not "until a match" or
    "the whole library"). Tests: `test_impulsive_look.py`.
  - **Channel (RULE 702.29) / Cycling (RULE 702.28)**: a hand-zone,
    non-mana "Discard this card: `<effect>`" activated ability — distinct
    from `mana_abilities.py`'s hand-exile mana-ability shortcut since
    Channel/Cycling *do* use the stack. `costs.py` gained a
    `_DISCARD_SELF_RE` (checked before the generic `_DISCARD_RE` so "this
    card" is never misread as "a card") and `ActivationCost.discard_self`;
    `RulesEngine.discard_specific(obj)` discards a specific hand object
    (unlike `discard`'s auto-choice); `GameEngine.can_activate`/
    `_can_pay_activation_cost`/`_pay_activation_cost` all gained a
    hand-zone branch, and `legal_actions` gained a matching discovery loop
    over `player.hand`. Dismantling Wave's own Cycling clause ("destroy all
    artifacts and enchantments") and Renewed Faith's ("draw a card") are
    both real now (`ability_catalogue.py`). Tests: `test_channel_cycling.py`.
  - **Conditional Flash / conditional instant-speed loyalty activation**
    (RULE 702.8b/606.3, The Wandering Emperor-shaped): a new
    `AbilitySpec.conditional_flash` field (a separate whitelist,
    `ALLOWED_CAST_CONDITION_KEYS` in `parser/oracle/spec.py`, from
    `EffectSpec.condition`'s — this one gates cast/activation *legality*,
    not whether a resolving effect applies), bound onto `obj.
    conditional_flash` by `effect_binder.attach_to_object` the same way
    `additional_cost` rides on any spec regardless of which one carries
    the "real" effects. A new `game/condition_query.py` module evaluates
    it live (today just `"entered_this_turn"`, checked against a new
    `GameObject.turn_entered` stamp set by `GameState.
    add_to_battlefield`); `GameEngine.can_cast` and `_can_activate_loyalty`
    both consult it. The Wandering Emperor's "activate loyalty abilities
    any time you could cast an instant" clause is real now. Tests:
    `test_conditional_flash.py`.
  - **Impulsive draw** ("exile, you may play until the end of your next
    turn" — Light Up the Stage-shaped): a new `GameState.
    temp_play_permissions` dict (`instance_id -> turn granted`, since the
    card sits in exile rather than on a battlefield permanent — the
    standing, continuously-re-derived pattern `top_library.py` uses
    doesn't apply), populated by a new `RulesEngine.
    exile_with_play_permission`/`ImpulsiveDrawEffect`; `GameEngine.can_cast`/
    `can_play_land` both gained a branch reading it, and `_step_cleanup`
    sweeps expired entries (kept as long as `turn_granted >= turn_number`,
    so presence alone means "still valid" — no separate window check
    needed at the read sites). Tests: `test_impulsive_draw.py`.
  - **Impulsive draw's dual-player extension** (Ragavan, Nimble Pilferer;
    Mnemonic Betrayal): Light Up the Stage's mechanism assumed the same
    player both owns the exiled zone and gets the play permission — false
    for both these cards, so it grew a second dict, `GameState.
    temp_play_permission_player` (`instance_id -> player_id`, defaulting to
    "anyone" when absent so every pre-existing single-player grant is
    unaffected), consulted by a `player`-taking `GameEngine.
    _has_temp_play_permission` alongside the existing turn check. Ragavan's
    own trigger ("whenever ~ deals combat damage to a player, exile the top
    card of *that player's* library... until end of turn, you may cast that
    card") splits into two triggered abilities sharing one condition: the
    Treasure token has no per-firing variance, so it's an ordinary bound
    `TriggeredAbility`; the damaged-player-dependent exile can't be (a
    bind-on-load ability's one fixed `effects` list can't vary who's
    library is hit), so it rides a new hand-authored-only `AbilitySpec.
    impulsive_draw_on_combat_damage` marker (`{"count": N}`, validated,
    stamped onto the `GameObject` by `effect_binder.attach_to_object` the
    same "scan every spec" idiom as `additional_cost`/`conditional_flash`)
    that a new `RulesEngine._collect_impulsive_draw_triggers` reads fresh
    off a DAMAGE event's own source every firing — building the per-firing
    `ImpulsiveDrawEffect` (now also taking `permission_player`/
    `same_turn_only`) the same "build a fresh ability right when the event
    fires" shape `_collect_inherent_triggers` already uses for the Monarch/
    Initiative combat-damage swap, queued through the ordinary
    `pending_triggers` pipeline (RULE 603.3 ordering) rather than
    `check_rampage`/`check_ward`'s immediate-placement shortcut. Mnemonic
    Betrayal ("Exile all opponents' graveyards. You may cast spells from
    among those cards this turn, and mana of any type can be spent to cast
    them. At the beginning of the next end step, if any of those cards
    remain exiled, return them to their owners' graveyards.") is a
    graveyard-sourced sibling: a new `RulesEngine.
    exile_graveyard_with_cast_permission` (sharing `exile_with_play_
    permission`'s new `_grant_temp_play_permission` helper) exiles a whole
    graveyard at once, plus RULE 605.1a's broadest "any type" mana-wildcard
    grant — `ManaPool.can_pay`/`pay`'s new `wildcard` param ("color" widens
    a colored pip to any of WUBRG, "type" also lets colorless mana pay it),
    tracked per-object in `GameState.mana_wildcard_permission` and read by
    `RulesEngine.cast_spell`/`GameEngine.can_cast`. A new
    `GraveyardImpulsiveCastEffect` drives the exile-all-opponents'-
    graveyards + arms a `DelayedTrigger` (RULE 603.7, "at the beginning of
    the next end step") running a new `ReturnRemainingExiledEffect` that
    sends back whatever's still unexiled. Also closed a real pre-existing
    gap this surfaced: `resolve_top_of_stack` unconditionally routed a
    resolved instant/sorcery to the graveyard, even when one of its own
    effects (a trailing "Exile ~." self-exile, `ExileEffect`'s
    `target_kind=None` self mode) had already moved it elsewhere — it now
    checks `obj.zone != Zone.STACK` first and skips the graveyard route
    when so. `RulesEngine._remove_from_current_zone` also now searches
    every player's zones (not just the acting player's own), since a card
    with this dual-player permission can sit in a *different* player's
    exile than whoever is now casting it (RULE 400.3: a card's zone is
    keyed by its owner). Tests: `test_ragavan_and_mnemonic_betrayal.py`.
  - **Delayed-trigger showcase cards for the frontend's new "planned"
    panel** (Ephemerate's Rebound, Marchesa, the Black Rose's counter-death
    return, Sneak Attack/Meek Attack's cheat-into-play-then-sacrifice — see
    `Done_Frontend.md`'s "Game engine hookup" for the panel itself):
    `CreateDelayedTriggerEffect` gained a real `description` param (it
    previously read `getattr(self, "description", "")`, an attribute
    nothing ever set — always blank; now filled in for Mana Drain/Final
    Fortune too) and `DelayedTrigger` a `to_dict()` (`GameSession.view()`'s
    new `delayed_triggers` key). Ephemerate's Rebound (RULE 702.88b) is a
    new hand-authored-only `AbilitySpec.rebound` marker (the "scan every
    spec" idiom, mirroring `impulsive_draw_on_combat_damage`) plus two
    `GameObject` fields (`has_rebound`, and transient `rebound_pending` set
    by `cast_spell` only when cast *from hand*): `resolve_top_of_stack`
    exiles the spell instead of routing it to the graveyard and arms a
    `DelayedTrigger` for the controller's next upkeep running a new
    `ReboundFreeCastWindowEffect`, which opens a *standing* free-cast
    window (`GameState.free_cast_instance_ids`, a same-turn-only sibling of
    `temp_play_permissions`) rather than a forced yes/no choice at the
    trigger's own resolution — this engine has no synchronous mid-
    resolution chooser for a one-shot optional action, the same fidelity
    `RulesEngine.discard`'s "auto-choose, no chooser in this MVP" already
    sits at elsewhere. Marchesa, the Black Rose's "whenever a creature you
    control with a counter on it dies, return it at the beginning of the
    next end step" is a new `AbilitySpec.counter_death_return` marker (a
    "group"-subject per-firing trigger, mirroring Ragavan's per-firing
    shape but scanning every permanent for the marker instead of reading it
    off the event's own source, since Marchesa isn't the dying object) read
    by a new `RulesEngine._collect_counter_death_return_triggers` off a new
    `counters` snapshot `_move_to_graveyard` now stamps onto every `DIES`
    event (live, before the object leaves the battlefield) — Dethrone
    itself (RULE 702.107, both Marchesa's own keyword and the static
    granting it to every other creature she controls) stays unmodeled, a
    separate keyword-mechanic build tracked in `docs/implementation-state/BACKLOG.md`.
    Sneak Attack/Meek Attack ("{cost}: you may put a creature card from
    your hand onto the battlefield with haste, sacrifice it at the
    beginning of the next end step", the latter capped at total P/T 5) are
    one new `CheatCreatureFromHandEffect` sharing a new `RulesEngine.
    put_hand_creature_onto_battlefield` (auto-picks the first eligible
    creature — no chooser in this MVP, same precedent) plus a new
    `SacrificeObjectEffect` for the delayed tail — both hand-authored via
    `game/ability_catalogue.py`'s ordinary `cost={"text": …}` activated-
    ability shape. This pass also found and fixed two real pre-existing
    bugs while testing Ephemerate end to end against a live backend over
    the real HTTP API (curl — no browser-automation tool available this
    session): `RulesEngine.blink` left a phantom duplicate reference in the
    owner's exile zone list after returning the blinked object to the
    battlefield (`_put_searched_card`'s battlefield branch never removes
    the object from wherever it currently sits — its other callers, e.g.
    tutors, already pop the card off its zone first; `blink` exiles via
    `self.exile(obj)`, which *appends*, then never removed it before
    calling `_put_searched_card`); and `GameEngine.legal_actions`'s exile
    loop only ever checked `_castable_from_exile` (the Adventure/prepared-
    copy shapes), so a temp-play-permission-exiled card — Light Up the
    Stage/Ragavan/Mnemonic Betrayal/Rebound alike — could never actually be
    *offered* as a castable action, despite `can_cast`/`cast_spell` fully
    supporting it; no prior test caught either gap, since every existing
    impulsive-draw test asserted `can_cast` directly rather than going
    through `legal_actions`, the surface a real caller actually uses. Tests:
    `backend/tests/test_delayed_trigger_examples.py` (18 tests, including a
    regression test for each of the two bugs above).
  - **A per-firing dynamic trigger reference** ("that creature"/"the token
    this ability just created"): deliberately **not** new IR — no card in
    this catalogue needs one yet, and inventing a `"triggering_object"`
    target-spec kind without a driving card would be exactly the
    speculative-abstraction anti-pattern this project avoids. Instead,
    `TriggeredAbility`'s docstring now documents the sanctioned answer:
    build a fresh `TriggeredAbility` (or, when even the controller/shape
    varies per firing, a raw `StackItem`) at the call site with the
    per-firing data baked directly into its effects, exactly as
    `RulesEngine.check_rampage`/`check_ward` already do — a named pattern
    to follow rather than re-derive, not a code change.
  - **Phasing (RULE 702.26)**, scoped to what Robe of Stars actually needs
    (a single permanent, no "phase out together" attachment-chain family):
    a new `GameObject.phased_out` flag; `GameState.permanents`/
    `permanents_controlled_by` (already the sanctioned battlefield-reading
    choke point for ~28 existing call sites) now filter it out, so the SBA
    pass, combat attacker/blocker eligibility, activated-ability
    discovery, and `continuous.py`'s `group_selector_objects`/
    `_battlefield_static_abilities` (both switched from raw
    `state.battlefield` to `state.permanents()`) all treat a phased-out
    permanent as though it doesn't exist for free. `targeting.py`'s
    `legal_targets` (15 sites) and a handful of `game_engine.py`/
    `rules_engine.py` raw-`.battlefield` reads that needed it explicitly
    (`_can_attack`, `can_block`, `_lands_controlled_by`,
    `_attachment_legal`, `_sacrifice_candidate`) were migrated too. A new
    `GameEffect`, `PhaseOutEffect` (untargeted, defaulting to its own
    source's `attached_to` host — the same "no RULE 115 target, defaults
    to a computed subject" shape `TransformEffect` already uses — detaches
    any Equipment/Aura on phase-out rather than modeling the full
    "phases out together" family). `GameEngine._step_untap` gained the
    RULE 702.26a phase-in sweep (reading raw `state.battlefield`, the one
    caller that must still see a phased-out object) — no card yet phases
    an already-phased-in permanent out automatically, so that half of
    702.26a is deliberately not modeled. Robe of Stars' Astral Projection
    is real now (`ability_catalogue.py`). Tests: `test_phasing.py`.
  - **Targeting / multi-target / counters batch** (2026-07-20): the
    remaining N=1-only targeting families extended to RULE 115.1a's N>=2,
    plus four smaller, independent counter-family gaps closed alongside it.
    - **N>=2 multi-target for `return_to_hand`/`tap`/`add_counters`/
      `return_from_graveyard`**: the `count`-slicing idiom `DestroyEffect`/
      `ExileEffect`/`DealDamageEffect` already used (`game/effects.py`)
      extended to the other four families (`TapEffect` already had it —
      only its parser grammar was missing). `add_counters` needed a new,
      distinct `EffectSpec` key (`target_count`) since `count`/`amount`
      were already the *counter* amount. Parser grammar mirrors
      `_MULTI_TARGET_ROWS`/`_MULTI_TARGET_QUANTIFIER`
      (`parser/oracle/catalogue/handlers.py`) — `add_counters` is the
      highest-value one (100+ real cards spelling out "put a +1/+1 counter
      on each of up to two target creatures", independent of the
      still-unbuilt "Support N" keyword shorthand); `return_from_graveyard`
      got its own plural graveyard-clause regex
      (`_RETURN_FROM_GRAVEYARD_MULTI_RE`). Confirmed `o is not source` is
      already baked into every `legal_targets` "creature"/"permanent"/"any"
      branch (`game/targeting.py`), so "up to two *other* target creatures"
      needed no new engine work, just an optional "other" in the regex.
      Tests: `test_multi_target_extended.py`.
    - **Compound creature-target filter** ("power 4 or greater and
      flying"): `targeting.TargetSpec.creature_filter`/
      `_creature_matches_filter` already AND every key in the dict — the
      entire gap was the parser only ever emitting one key. Extended
      `_CREATURE_FILTER_SUFFIX`/`_creature_quality_filter` to an optional
      second `" and [with] <clause>"`, no `game/` changes needed. Tests:
      `test_modal_creature_filter_family.py`.
    - **Variable-count "remove a counter" activation cost**: a live query
      against the cached Oracle DB showed the ToDo's four phrasings weren't
      all costs — "remove up to N"/"remove all counters from all
      permanents" are resolution *effects* on every real card found (see
      below), while "remove X counters" (32 real cards: Arcbound
      Javelineer/Chamber Sentry/Marath/the storage-land and Baku cycles)
      and "remove any number of counters" (23 real cards: the Mana Battery
      cycle, more storage lands, Geistflame Reservoir) genuinely are
      costs. `ActivationCost.remove_counters` gained two sentinels
      (`REMOVE_COUNTERS_X`/`REMOVE_COUNTERS_ANY`, mirroring `PAY_LIFE_X`'s
      existing idiom), paid/validated against the same `x` parameter
      `activate_ability` already threads for mana `{X}`; a new
      `_max_x_for_activation_cost` (`game/game_engine.py`) merges the
      mana-`{X}` bound with the counters-available bound so `has_x`/`max_x`
      are offered correctly even when the ability has no `{X}` mana symbol
      at all (Blademane Baku-shaped). Also fixed a latent bug where
      `_REMOVE_COUNTERS_RE`'s count group already structurally matched the
      literal word "x" but silently resolved it to `1`. Deliberately
      doesn't model the bespoke effect text on each of these ~30 unique
      cards ("It deals X damage…"/"Scry X…") — reading an *activated
      ability's* own announced X into a generic effect amount isn't wired
      anywhere yet, a separate, larger feature. Tests:
      `test_remove_counters_cost.py`.
    - **"Remove all counters from target/all permanents"** (Vampire
      Hexmage/Oblivion Stone/Aether Snap/Thief of Blood-shaped): a new
      `RemoveCountersEffect` (`game/effects.py`), untargeted (board-wide)
      or `target_kind="permanent"`, stripping every counter of every kind
      via `context.add_counters` with a negative amount per kind (not a
      raw dict mutation, so a counter-removed trigger still fires
      correctly). Tests: `test_remove_counters_effect.py`. "Remove up to N
      counters" (a genuinely different, chosen-quantity effect) is covered
      separately, below.
    - **"Proliferate twice" / "proliferate N times"**: `ProliferateEffect`
      gained a `times` param (mirroring `ScryEffect.count`'s existing
      shape) and a parser handler for the literal word "twice" or a
      digit-folded "N times" (normalize.py doesn't fold "twice" itself,
      unlike spelled-out numbers). A bare "proliferate x times"
      (Expansion Algorithm's announced-X, Tromell's dynamic count-selector)
      stays unclaimed — a different shape. Tests:
      `test_modal_creature_filter_family.py`.
    - **Kicked-gated entry counters + a granted keyword together** (RULE
      702.33b's "…and with `<keyword>`" compound form): both
      `_KICKED_ENTRY_COUNTERS_RE`/`_KICKED_SCALED_ENTRY_COUNTERS_RE`
      (`parser/oracle/catalogue/counters.py`) gained an optional trailing
      keyword clause off a small closed vocabulary;
      `RulesEngine._apply_entry_counters` grants the keyword onto
      `GameObject.intrinsic_keywords` under the same kicked gate as the
      counters — a one-time additive mutation is exact here (not an
      approximation needing the RULE 613 conditional-static-gate
      machinery), since `kicker_count` never changes after cast, and
      `intrinsic_keywords` is already read as a stable baseline every
      layer-engine pass, the same mechanism a card's own printed flag
      keywords use. Tests: `test_batch6_cost_keyword_family.py`.
    - **"Remove up to N counters from target permanent/creature"** (Glissa
      Sunslayer/Heartless Act/Render Inert-shaped) — a genuinely different,
      interactive chosen-*amount* shape from the "all" shape above.
      `RemoveCountersEffect` gained a `max_count` param that switches
      `apply()` to open a `pending_choice` (`RulesEngine.
      request_remove_counters_choice`) asking how many (0..
      min(max_count, counters present)) instead of resolving synchronously;
      answering it (`resolve_remove_counters_amount_choice`) either
      resolves directly (0 chosen, or only one counter kind present) or
      opens a second, mandatory `pending_choice` asking *which* kind, one
      at a time (`_continue_remove_counters`/
      `resolve_remove_counters_kind_choice`, mirroring `_search_choice`'s
      "re-ask for the next" shape) — modeled on `_offer_enter_choices`/
      `resolve_enter_choice`'s "pause mid-resolution" idiom, since no
      existing chooser combines an amount pick with a kind pick. Price of
      Betrayal's "target artifact, creature, planeswalker, **or opponent**"
      compound target (a player alongside three permanent types) stays
      unclaimed. Tests: `test_remove_counters_choice.py`.
    - **Player-counter primitive** (`RulesEngine.add_player_counters`,
      `Player.add_counters`): the engine's first effect-driven way to add
      poison/energy/experience counters to a *player* — previously only the
      Replay/Puzzle editor could set `Player.poison` directly
      (`services/game_session.py`'s `edit_player` action), and no gameplay
      effect routed through it at all. Mirrors `add_counters` exactly (a
      positive amount goes through `apply_replacements` via the same
      `EventType.COUNTER` event shape, `is_player=True`/`target_id` the
      player's id — mirroring `deal_damage`'s own player/permanent split —
      so a doubling replacement needs no special-casing for "or player").
      Built to land Innkeeper's Talent (below); nothing else creates player
      counters through it yet (Infect and proliferate-on-players are both
      still unmodeled).
    - **Innkeeper's Talent's causer-scoped counter-doubling** ("if **you**
      would put one or more counters on a permanent or player, put twice
      that many… instead") — a different scoping axis from Doubling
      Season's already-shipped "on a permanent **you control**": Doubling
      Season reads the *recipient*'s controller (already handled, no
      `game/` change needed), Innkeeper's Talent reads who's *causing* the
      placement. `add_counters`/`add_player_counters` gained an optional
      `source` param, carried onto the `COUNTER` event as
      `source_controller_id` (mirroring `deal_damage`'s own field of the
      same name); `_double_counters_replacement` gained a
      `your_effects_only` flag checking it against the replacement's own
      source. The "or player" half needed no extra code at all beyond the
      player-counter primitive above — the replacement's `COUNTER`-event
      handling was already recipient-agnostic. Threaded `source=self.source`
      through every real (non-removal) `add_counters` call site
      (`AddCountersEffect`/`RenownEffect`/`ProliferateEffect`/the two
      "gains a +1/+1 counter" one-shots) so the scoping actually has
      something to check. Tests: `test_replacement_clause_recognition.py`.
    - **Mechanized Warfare's compound "a red or artifact source" filter**:
      `additional_damage`'s single `color` param generalized to OR-combined
      `colors`/`types` lists (`color` kept standalone for the existing
      single-colour Torbran shape) — a source qualifies if it matches *any*
      listed colour (`event`'s own `source_colors`) or *any* listed type
      word (currently only `"artifact"`, looked up fresh off the source's
      printed card via the `DAMAGE` event's existing `source_id`, no new
      event field needed). Parser: `_ADDITIONAL_DAMAGE_RE` gained a second
      optional qualifier joined by "or", each a colour word or a type word.
      Tests: `test_replacement_clause_recognition.py`.
    - **Cross-target "controlled by different players/controllers"**
      (Protector of the Wastes/Cloud's Limit Break-shaped — one targeting
      effect's own N>=2 targets, RULE 115.1a further generalized): a new
      `targeting.TargetSpec.distinct_controllers` flag, wired into
      `DestroyEffect`/`ExileEffect`/`ReturnToHandEffect`. Unlike every other
      `TargetSpec` filter (checked per-candidate, independent of what else
      was picked), this constrains the *relationship* between the targets
      chosen for one requirement, so it's enforced at offer/pick time
      across rounds rather than inside the resolving effect: `legal_targets`
      now includes `controller_id` on every "creature"/"permanent"
      descriptor, `requirements_with_targets` surfaces the flag, and
      `gameBoardView.js`'s `expandMultiTargetRequirements` gained a second
      per-round exclusion (`excludeControllers`, alongside the existing
      `excludePicked`) that drops any option sharing a controller with an
      already-picked round. Parser: `_MULTI_TARGET_DISTINCT_CONTROLLERS`, an
      optional trailing clause on `destroy`/`exile`'s existing multi-target
      grammar. Run Away Together's own two-sentence "Choose two target
      creatures controlled by different players. Return those creatures to
      their owners' hands." stays unclaimed — a different, indirect-
      referent grammar shape ("choose target(s) [+ constraint]. Verb those
      [referent]s.") no handler recognizes yet, even though
      `ReturnToHandEffect` itself already accepts `distinct_controllers`.
      Tests: `test_distinct_controllers.py`.
    - **Library-top/impulsive-draw permissions closeout** (PARSER_VERSION
      23): the generic "You may play lands [and cast [noncreature] spells
      [with mana value N or greater]] from the top of your library" static
      (`catalogue/static_handlers.py`'s `_TOP_LIBRARY_PERMISSION_RE`/
      `_TOP_LIBRARY_VERB_PARAMS`) — the oracle-text sibling of the two
      hand-authored `top_library_permission` catalogue entries (Oracle of
      Mul Daya, Glarb, Calamity's Augur), unblocking any card printing this
      exact wording with no further hand-authoring (Future Sight,
      Experimental Frenzy's own permission line — though that card stays
      UNMODELED overall on its separate, still-unclaimed "can't play from
      hand" restriction). `noncreature_only` is a closed vocabulary of one
      (Elsha of the Infinite's own restriction — no other real card needs a
      different one today), not a general subtype filter. Also claims
      "Play with the top card of your library revealed." as a documented
      no-op (`segmenter.py`'s `_PLAY_WITH_TOP_REVEALED_RE`, mirroring the
      pre-existing "look at any time" no-op) — needed for Future Sight/
      Oracle of Mul Daya, which print it right next to the permission line.

      Each of the two previously-cited blocked cards also needed its own
      same-line "If you cast a spell this way, ..." conditional tail
      recognized as part of the *same* clause (Elsha/Bolas's Citadel both
      fold the tail into the permission's own paragraph, not a separate
      line — so the whole two-sentence line had to fullmatch as one static,
      not two): Elsha of the Infinite's "you may cast it as though it had
      flash" (`TopLibraryPermissionEffect.grants_flash`, a new field
      consulted by `game/top_library.py`'s `may_cast_flash_from_top_of_
      library` and folded into `GameEngine.can_cast`'s existing flash union
      alongside `conditional_flash`/temp-flash — simpler than reusing
      `conditional_flash` itself, since the permission and its flash grant
      already live together on the *granting* permanent's
      `TopLibraryPermissionEffect`, not on the cast object); and Bolas's
      Citadel's "pay life equal to its mana value rather than pay its mana
      cost" (`.life_payment`, a genuinely new RULE 118 alternative-cost
      shape — `game/top_library.py`'s `top_library_life_payment_required`,
      `GameEngine._top_library_life_payment`/`can_cast`/
      `_cast_current_face`). Unlike Kicker/Buyback/the RULE 601.2f
      free-cast condition (each an opt-in the caller requests via its own
      parameter), the life payment is mandatory and automatic — casting a
      spell via a `life_payment` grant *always* substitutes life for mana,
      so `can_cast`/`_cast_current_face` detect it themselves (top card of
      the library + an applicable grant) rather than taking a caller flag;
      mechanically it reuses `RulesEngine.cast_without_paying` (the
      cascade/discover/free-cast primitive) for the zone change, then a
      separate `RulesEngine.lose_life` call for the cost. Tests:
      `test_library_top_permission_family.py` (parser),
      `test_top_library.py` (engine).
    - **Replacement-effects batch** (PARSER_VERSION 25): closed most of the
      "Replacement effects / mana" backlog in one pass.
      - `prevent_damage`'s two real cards (Riot Control/Thought Lash) — a
        new one-shot `PreventDamageEffect`/`RulesEngine.
        prevent_damage_to_player`, Regenerate-shaped (a `ReplacementEffect`
        built and attached at *resolve* time, not bind time) but
        player-scoped: it lives on `Player.player_effects` (already
        `_all_replacement_effects`'s second collection source) rather than
        a permanent's `replacement_effects`, since nothing is being
        regenerated. `amount="all"` (Riot Control) prevents every point of
        damage for the rest of the turn and never self-removes; an int
        (Thought Lash's own repeatable activated ability, "the next 1")
        opens a cumulative bank spent across however many `DAMAGE` events
        it takes, self-removing once exhausted. Either shape is swept at
        cleanup regardless of remaining balance (RULE 514.2) by a new
        `damage_prevention_shield`-marker sweep over every player's
        `player_effects` in `GameEngine._step_cleanup`, mirroring the
        pre-existing unused-regeneration-shield sweep. Riot Control's own
        "gain 1 life for each creature your opponents control" needed a
        new `GainLifeEffect.count_selector` param (reusing `continuous.
        count_selector`'s existing "you control"/"opponents control"
        pair vocabulary, adding `creatures_opponents_control`). Thought
        Lash's activated ability needed a new additional-cost shape too:
        `ActivationCost.exile_top_of_library` (`costs.py`), charged via
        `RulesEngine.exile(player.library[-1])` — the card's own
        Cumulative upkeep and "exiles all cards from library" trigger stay
        deliberately unclaimed (Cumulative upkeep isn't modeled at all;
        out of scope). Tests: `test_prevent_damage.py`.
      - RULE 616.1's damage-multiplying family gained oracle-text
        recognition (`catalogue/replacements.py`): Furnace of Rath/Dictate
        of the Twin Gods's unscoped "if a source would deal damage..., it
        deals double that damage instead" and Fiery Emancipation's
        "triple" sibling — `_double_damage_replacement` gained a
        `multiplier` param (default 2, so the two pre-existing
        hand-authored cards are unaffected). Also recognizes Gratuitous
        Violence's own narrower "a creature you control" phrasing (new
        `creature_only` param, checked against a new `source_is_creature`
        field on the `DAMAGE` event) — which also **fixed a latent bug**:
        the pre-existing hand-authored catalogue entry wrongly required
        `combat_only`, a restriction the real printed text has never had
        (Gratuitous Violence doubles *any* damage from your creatures, not
        just combat damage). Tests: `test_replacement_clause_recognition.py`,
        `test_replacement_ordering.py`.
      - Lurrus of the Dream-Den's own trailing "if a spell cast this way
        would be put into a graveyard this turn, exile it instead" —
        `GraveyardCastPermissionEffect.exile_if_would_be_put_into_
        graveyard` (a new opt-in field, `False` for any other card reusing
        the base graveyard-cast permission). `GameEngine.cast_spell`
        stamps `GameObject.cast_via_graveyard_cast_permission_until_turn`
        with the casting turn only when the grant used has this flag,
        reassigned (not just set) on every cast — like `cast_via_
        flashback` — so a later normal recast the same turn correctly
        clears it. `RulesEngine._move_to_graveyard` (the one choke point
        every graveyard-bound move — destroy, sacrifice, SBA "dies" —
        funnels through) redirects to `exile` first, while that turn
        number still matches. Tests: `test_graveyard_cast.py`.
      - Two new `game/mana_abilities.py` RULE 605.3a mana-spend-restriction
        kinds: `chosen_type_spell` (Cavern of Souls/Unclaimed Territory's
        "of the chosen type" — the type itself isn't parsed from text at
        all; `GameEngine.tap_for_mana` resolves it per-instance into an
        ordinary `type_spell` restriction off the tapped land's own RULE
        601.2b `GameObject.chosen_type` ETB choice) and
        `mana_value_or_x_spell` (Helga, Skittish Seer/Troyan, Gutsy
        Explorer's "mana value N or greater or ... with {X} in their mana
        costs", optionally creature-scoped). Fixed a related pre-existing
        gap while wiring Helga's own test: "X mana of any one color, where
        X is `<name>`'s power" (as opposed to the already-supported
        "equal to `<name>`'s power"/"where X is the number of ...") wasn't
        recognized as a variable-amount selector at all — new
        `_WHERE_X_POWER_RE`, reusing the existing `_power_selector` helper.
        Throne of Eldraine's own chosen-*colour* restriction is a
        different, still-unmodeled shape (needs a "monocolored" check plus
        a second, genuinely distinct mana-colour lock on its own second
        ability) — left open. Tests: `test_mana_spend_restrictions.py`.
      - RULE 122 energy's `{E}` cost pips (`ActivationCost.pay_energy`,
        `costs.py`) — previously silently discarded by `_parse_text`'s
        brace loop. Handles both the repeated-pip form ("Pay
        {E}{E}{E}{E}") and the spelled-out-count form ("Pay eight {E}",
        "Pay fifty {E}" — `_PAY_ENERGY_WORD_RE`, extending `_NUMBER_WORDS`
        with the tens words a real energy cost needs). Charged via
        `RulesEngine.add_player_counters(player, -amount, "energy")` —
        `Player.counters["energy"]` is the same generic per-player counter
        dict `rad`/`poison` already use, so "you get {E}" (the production
        side) already worked with no new plumbing; only the *cost* side
        was the gap. Tests: `test_energy_cost.py`, `test_costs.py`.
    - **Replacement-effects / mana closeout** (PARSER_VERSION 26): the rest
      of the former "Replacement effects / mana" ToDo section, in one pass.
      - **More RULE 616.1 replacement families** (`catalogue/replacements.
        py`, all recognized from oracle text now):
        - *Life-gain rewrite* — Angel of Vitality's additive "you gain that
          much life plus N instead" and Boon Reflection/Alhammarret's
          Archive/Rhox Faithmender's multiplicative "twice that much life
          instead" (`gain_life_replacement`, `plus`/`multiplier` params).
          Needed a new `EventType.LIFE_GAIN` pre-event: `RulesEngine.gain_
          life` now routes through `apply_replacements` first (mirroring
          `deal_damage`/`add_counters`), synchronous and unchanged when no
          replacement applies. Self-scoped ("if **you** would gain life")
          off the event's `player_id` vs the effect's controller.
        - *Recipient-scoped +1/+1 counter replacement* — Hardened Scales/
          Conclave Mentor's additive "that many plus one" (creature you
          control), Kami of Whispered Hopes' permanent-scoped variant, and
          Branching Evolution/Corpsejack Menace's "twice that many"
          (`_double_counters_replacement` gained `plus`/`multiplier`/
          `recipient` params; the COUNTER event gained `recipient_
          controller_id`/`recipient_is_creature`). Distinct from Doubling
          Season's own unscoped clause.
        - *"If ~ would die, exile it instead"* — Gloomshrieker (self),
          Corpseweaver Prodigy (an opponent's creatures), and the
          you-control/any variants (`die_to_exile`, subject-scoped). A new
          `EventType.WOULD_DIE` fired by `RulesEngine._move_to_graveyard`
          for a creature actually leaving the battlefield (RULE 700.4),
          redirected to exile side-effect-style like regeneration's shield;
          covers destroy, sacrifice and SBA "dies" (all funnel through that
          one method), and never fires for a noncreature or a non-battlefield
          graveyard move. Tests: `test_replacement_clause_recognition.py`.
      - **Throne of Eldraine** — fully MODELED (was UNMODELED on all three
        of its mechanics). (1) Chosen-colour mana *production*: "Add N mana
        of the chosen color" (`ManaAbility.color_selector="chosen_color"`,
        recoloured per-instance off `GameObject.chosen_color` in
        `mana_abilities_for`/`resolve_options`, dropped while no colour
        chosen). (2) A `monocolored_spell`-of-the-chosen-colour spend
        restriction (`chosen_color_monocolored_spell`, resolved at tap time
        in `GameEngine.tap_for_mana` into a concrete `monocolored_spell`
        restriction off `chosen_color` — the colour sibling of the
        chosen-*type* family). (3) The second ability's colour-locked
        activation cost: "Spend only mana of the chosen color to activate
        this ability" (`ActivationCost.spend_only_chosen_color`, peeled off
        the effect body in `segmenter.py` and enforced in `_can_pay_/_pay_
        activation_cost` by re-expressing the whole mana cost as
        `chosen_color` pips — `GameEngine._chosen_color_locked_cost`).
        Throne's own chosen-*colour* ETB ("choose a color") was already
        modeled. Tests: `test_mana_spend_restrictions.py`.
      - **Energy — the resolve-time optional payment** "you may pay {E}{E}.
        If you do, `<effect>`." (Aether Chaser/Herder/Inspector/Swooper —
        the sibling of the already-shipped "Pay {E}" *activated-ability
        cost*). `pay_energy_then`/`PayEnergyThenEffect` opens an interactive
        yes/no `RulesEngine.request_pay_energy_then` choice at resolution
        (modeled on the shock-land pay-life choice, dispatched through
        `resolve_pending_choice`); if the controller pays, the follow-up
        effects (built lazily via `build_effects`, mirroring
        `InstallTemporaryPlayerTriggerEffect`) resolve. `segmenter._peel_
        optional` is guarded so the "you may" here isn't stripped into a
        redundant whole-ability optional. Only *untargeted* follow-ups are
        modeled (create-token/gain-life/draw); a targeted one (Guide of
        Souls) stays fail-closed. Also added the `get_energy` handler for
        "you get {E}{E}" production (→ the generic `add_player_counters`
        energy primitive), so these creatures parse whole. Tests:
        `test_energy_pay_then.py`.
      - **"Add 1 mana of any color"** as a resolve-time effect was already
        modeled (`_add_mana_any_color` → `add_mana {"colors": ["any"]}`,
        `test_effect_families_wave3.py`) — the stale ToDo bullet was struck.

    - **Triggers / grants closeout** (PARSER_VERSION 27): the whole
      "Triggers / grants" ToDo section, seven items, closed in one batch.
      Coverage 24.5% → **25.2%** (8,395 → 8,633 of 34,209 cards).

      - **Group-subject damage triggers** (RULE 120.3 + RULE 603.1's
        `group` subject). `segmenter._SELF_DAMAGE_TRIGGER_RE` became
        `_DAMAGE_TRIGGER_RE`, gaining an "a/an/another `<type>` [you
        control]" subject alongside the shipped `~` one — Bident of
        Thassa/Deepfathom Skulker/Defiling Daemogoth. Two engine-side
        pieces were genuinely missing, both because a DAMAGE event names
        its *source* rather than stamping the `instance_id`/`controller_id`
        the RULE 603.1 object-subject events carry: `_GROUP_CONTROLLER_
        EVENT_KEYS` gained a ``DAMAGE → source_controller_id`` row, and
        `_build_group_ok`'s hard-coded ``instance_id`` lookup became a
        `_subject_event_key` call (a no-op for every other event, which is
        what makes it a safe generalization rather than a behaviour
        change). Every *qualified* variant ("a **modified**/**renowned**
        creature you control") stays fail-closed on the closed type
        vocabulary. Fixing this also surfaced a small pre-existing gap: the
        group-subject article alternation was ``a|another``, so **every**
        vowel-initial group subject ("an enchantment you control dies",
        Ashiok's Reaper) had been silently failing closed. Tests:
        `test_phase_and_damage_triggers.py`.
      - **"Sacrifice ~ unless you pay `<cost>`."** (RULE 701.17, 45 cards —
        the single biggest remaining upkeep-trigger template: Arcades
        Sabboth, Breeding Pit, Child of Gaea, Chromium, Kuro). This needed
        a real interactive pay-or-lose-it choice, and per this file's own
        "grep for an equivalently-shaped primitive from another card's
        batch" discipline, it got one that already existed: **ward's**
        (RULE 702.21). `RulesEngine._can_pay_ward_cost`/`_pay_ward_cost`
        were never ward-specific — they're "can this player pay an
        arbitrary `ActivationCost` out of their own resources" — so they
        were renamed `_can_pay_player_cost`/`_pay_player_cost` and shared,
        rather than a second parallel copy being written. New:
        `SacrificeUnlessPayEffect`, `RulesEngine.request_sacrifice_unless_
        pay`/`resolve_sacrifice_unless_pay_choice`, and a
        `sacrifice_unless_pay` `pending_choice` kind (the session/board UI
        needed no change — it renders `options` generically). A player who
        *can't* pay isn't asked at all, the same "don't stall a passive
        goldfish opponent on a choice nobody can act on" shortcut ward and
        `counter_unless_pays` take; a "pay" answer is re-checked against
        the live board, since the offer and the answer are separate
        round-trips. The parser claims a deliberately **closed** cost
        vocabulary (mana pips / "pay N life" / "discard a card" /
        "sacrifice a `<type>`") rather than handing free text to
        `parse_activation_cost`, which returns a **free** cost for anything
        it doesn't understand — that would have silently read as "pay
        nothing to keep it". Echo/Cumulative Upkeep's self-referential
        costs, scaled "for each" costs, "discard a card at random" and
        multi-permanent sacrifices all stay unclaimed. Tests:
        `test_sacrifice_unless_pay.py`.
      - **Quoted granted phase/upkeep triggers.** ``STEP_BEGIN`` joined
        `_GRANTABLE_TRIGGER_EVENTS` — the one grantable event with no
        object subject at all, so what makes it *safe* to regrant is
        threading the segmenter's ``phase_relation`` through
        `grant_triggered_ability` to `continuous._granted_trigger_
        condition`, which resolves "your" against the **granted-to**
        permanent's controller rather than the granting source's (that's
        exactly what Clawing Torment/Commander's Authority mean, and why
        `effect_binder._trigger_condition`'s own `phase_relation` branch —
        which closes over the printed source — couldn't be reused). The
        un-scoped "at the beginning of *each* upkeep" form stays
        fail-closed: a regranted copy would have no way to say whose upkeep
        it means. Tests: `test_aura_equipment_grant_family.py`.
      - **Aura lifecycle triggers.** Three pieces, only one of them a
        recognition gap. (a) RULE 700.4 — "the term *dies* means 'is put
        into a graveyard from the battlefield'" — is an exact definitional
        synonym, so `normalize._fold_dies_long_form` rewrites the pre-2011
        long phrasing and *every* existing "dies" grammar covers it for
        free (self/group/attached subject, tribal subjects, the
        quoted-grant recursion). The narrower "is put into **your**
        graveyard from the battlefield" (Angelic Renewal) is deliberately
        not folded. (b) That immediately exposed a real engine bug: RULE
        700.4 isn't creature-scoped, but `_move_to_graveyard` only fired
        `EventType.DIES` ``if was_creature`` — so an Aura/enchantment/land
        dying was invisible to any dies-trigger whatsoever. Widened; every
        consumer that *does* mean creatures already narrows on the event's
        own ``object_types``. (c) `ReturnToHandEffect` gained a self form
        (``target_kind=None``, and — following `TapEffect`'s untargeted
        modes — **no** `TargetSpec` at all, so `_trigger_target_specs`
        doesn't open a RULE 115 choice with nothing to pick). It resolves
        against the source wherever it is, which for Rancor/Launch/Aspect
        of Mongoose is the *graveyard* (RULE 400.7 — the source moved
        before the ability resolved), and for Flickering Ward's "{W}:
        Return this Aura to its owner's hand." the battlefield.
        `handlers._ATTACHED_SUBJECT` also gained "enchanted permanent"/
        "enchanted land" (Flood the Engine's "tap enchanted permanent").
        Tests: `test_aura_lifecycle_family.py`.
      - **Standing granted protection** (RULE 702.16, layer 6). There was
        no continuously-re-derived protection concept at all — only printed
        text plus `temp_protections`, a *resolve-time* "until end of turn"
        grant (Mother of Runes). New `grant_protection_static` →
        `GameObject._granted_protections`, stamped every `continuous.
        recompute` and unioned in by `combat.is_protected_from`, so it
        stops applying on its own when its source leaves (RULE 613.6) with
        no teardown code. Covers the group form (Hungry Lynx's "Cats you
        control have protection from Rats", Righteous War, Absolute Grace/
        Law), the attached form, the self form, and RULE 601.2b's dynamic
        "protection from **the chosen color**" (Voice of All/Order of the
        Stars), re-read off the source's own `chosen_color` every pass.
        Quality *words* are normalized engine-side (`continuous._
        protection_qualities` → `combat.protections_of_text`) because the
        parser front end may not import `game/`. Registered as
        `grant_protection_**static**` on purpose: a one-shot
        `grant_protection` already existed and `EffectRegistry.register`
        silently overwrites a duplicate name. Rebbec's computed "protection
        from each mana value among artifacts you control" stays
        fail-closed. Tests:
        `test_standing_protection_and_type_extension.py`.
      - **Type grants past the battlefield** (RULE 613.4a, layer 4). The
        layer engine only walks battlefield permanents, so Arcane
        Adaptation/Leyline of Transformation's "The same is true for
        creature spells you control and creature cards you own that aren't
        on the battlefield" and Ashes of the Fallen's graveyard form had
        nowhere to land. `continuous._apply_off_battlefield_types` is a
        dedicated pass over the controller's hand/graveyard/library/exile
        plus their spells on the stack, stamping `_added_subtypes` (which
        `has_subtype` already reads, so no caller needed changing). Because
        those objects never see `reset_derived`, the pass tracks what it
        stamped on the state and clears it first — that, not any teardown
        branch, is what makes the grant vanish with its source. The
        battlefield half of the same family shipped alongside as the group
        sibling of `_IS_CHOSEN_TYPE_RE` (Xenograft, Realmwright's
        "Lands you control are …", Lifecraft Engine's tribal narrowing);
        Arcane Adaptation prints both sentences on one line, so one regex
        has to claim both (the segmenter splits on newlines, not
        sentences). Tests: as above.
      - **Quoted mana-ability grants.** "Elves you control have '{T}: Add
        {B}.'" (Tyvar Kell) / "Enchanted land has '{T}: Add 1 mana of any
        color.'" (Abundant Growth, Find the Path) can't go through the
        recursive `segment_line` parse the other quoted grants use: a plain
        top-level mana ability is claimed-**without**-a-spec by the
        segmenter, since mana production is recognized directly off printed
        text by `game/mana_abilities.py` rather than the `EffectRegistry`
        pipeline — so the nested parse comes back with nothing to re-emit.
        `static_handlers._granted_mana_options` recognizes the bare "{T}:
        Add `<mana>`" body itself and emits the existing (previously
        hand-authored-only) `grant_mana_ability` primitive. `{T}`-only:
        any other cost component ("{T}, Sacrifice a creature: …", Animal
        Boneyard) isn't expressible as a bare production list and stays
        unclaimed. Tests: `test_aura_equipment_grant_family.py`.

- [x] **Combat statics — the qualified/conditional restriction family**
      (batch 27, 2026-07-22, `PARSER_VERSION` 29, +225 covered cards:
      8,672 → 8,897 / 34,209 = 26.0%). Closes the whole "Combat statics"
      section that was open in `docs/implementation-state/BACKLOG.md`; what remains
      around it there is three *different* rules (requirements, multi-block
      permissions, pairwise restrictions), not leftovers of this one.

      The plain restrictions ("~ can't attack.") shipped in batch 2 as
      synthetic layer-6 flag keywords, and that was the right shape for
      them — a flag is all they need. Every *qualified* sibling carries a
      parameter a flag can't hold, so the load-bearing decision here was a
      new **`combat_restriction` static** (`game/effects.py`; a
      `continuous._NON_RULE_613_LAYERS` bucket, not a layer — none of this
      changes a characteristic) stamped onto `GameObject.
      combat_restrictions` every recompute and **evaluated at combat time**.
      That last part is the whole point: the two things these depend on —
      who is defending, and who else is attacking — don't exist yet when
      the layer engine runs, so a recompute-time answer would be wrong, not
      merely early. The `kind` whitelist lives in `game/combat.py`'s
      `COMBAT_RESTRICTIONS`, its `filter` vocabulary in
      `matches_object_filter` (which `targeting._creature_matches_filter`
      now delegates to, so the two can't drift), its `condition` vocabulary
      in `GameEngine._COMBAT_CONDITIONS`.

      - **Blocking filters** (RULE 509.1b) — "~ can't be blocked by
        creatures with power 2 or less" / "…except by Walls" / "…except by
        creatures with flying or reach" / "…by creatures with greater
        power" (the one *relative* filter, resolved against the attacker
        per blocker rather than baked in at parse time), plus the two
        counted forms "…by more than one creature" and "…except by two or
        more creatures", which generalize `combat.min_blockers`' existing
        menace floor into a `min_blockers`/`max_blockers` pair
        `declare_blockers` checks over the whole projected block. The
        blocker-side mirror shipped with them ("~ can block only creatures
        with flying", "~ can't block creatures with power 3 or greater" —
        `blocker_may_block`), as did the *inverted* phrasing that reads off
        the other end of the sentence ("Creatures with power less than ~'s
        power can't block it." — Sedge Troll), which is the same
        `cant_be_blocked_by` restriction and so gets a regex rather than a
        second mechanism.
      - **Conditional restrictions** — "~ can't attack/block[ or block]
        unless `<condition>`", over a closed board/turn-state vocabulary
        (defending player controls a land type/permanent type; you control
        N (other) X; more creatures/lands than the other player; cards in
        graveyard/hand; opponent is the monarch/poisoned; a creature died
        under your control this turn). Two things fell out of this: RULE
        508.1a's condition is about the player *actually* being attacked, so
        `_can_attack` gained an optional `defending_player` — `None` asks
        the weaker offer-time question "could this attack somebody" (for
        `legal_actions`), and `declare_attackers` re-checks against the
        assigned defender; and "a creature died this turn" is a *history*
        question no live board can answer, so `GameState.
        creatures_died_this_turn` joined `spells_cast_this_turn` as a
        subscribed per-turn tally (`RulesEngine._track_creature_death`,
        narrowed to creatures off the `DIES` event's own snapshotted
        `object_types`, since RULE 400.7 means the object is already gone by
        the time a subscriber runs). An unrecognised condition kind returns
        **False** — the restriction keeps biting — so a mis-parse fails
        toward "can't attack" rather than silently deleting the restriction.
      - **"…alone"** — both halves. The restriction ("~ can't attack
        alone.", "…attack or block alone") is a property of the *finished*
        attack, so it's enforced where `_enforce_attacks_if_able` already
        is: as the caller tries to leave the declare-attackers step. Since
        `declare_attackers` is additive (the UI declares one creature per
        click), rejecting mid-way would wrongly bite the first creature of a
        legal pair. The **trigger** ("Whenever ~ / a Samurai or Warrior you
        control attacks alone, …") needed a new aggregate `EventType.
        ATTACKS_ALONE`, fired once combat locks in, for exactly the reason
        `PLAYER_ATTACKED` is aggregate: `ATTACKS` fires per creature as it's
        declared, so the first declaration of a two-creature attack would
        always momentarily look alone. It carries `ATTACKS`' payload
        verbatim, so RULE 603.1's self/group/subtype subject scoping works
        unchanged.
      - **"…unless they're mana abilities"** (RULE 605.1a) — an
        `except_mana_abilities` rider on the existing `activation_
        prohibition`. Wiring it exposed the converse bug: `tap_for_mana`
        never consulted `activation_prohibited` at all, so an *unqualified*
        prohibition wasn't stopping mana abilities either — which is
        precisely what Null Rod is for. Both now go through the same check.
      - **"Target creature can't block this turn"** — the family's largest
        half (~100 cards) and, unlike everything above, an ordinary one-shot
        effect rather than a static: `CantBlockEffect` →
        `GameObject.temp_cant_block`, the blocker-side mirror of the
        `temp_unblockable` grant that already existed, cleared at cleanup
        (RULE 514.2). Shipped with the N-target ("up to two target
        creatures") and untargeted mass ("creatures without flying can't
        block this turn") forms.
      - **The resolve-time "…this turn" variant** of the blocking filters
        ("{3}{G}: ~ can't be blocked by creatures with power 2 or less this
        turn") shipped in the same batch rather than being deferred as a
        sibling: `GameObject.temp_combat_restrictions` holds the *same*
        clamped param dicts, and `combat.combat_restrictions` reads the two
        lists together, so no combat-time check has to know which kind of
        grant a restriction came from.

      Tests: `test_qualified_combat_restrictions.py` (new, 25 tests — each
      shape driven through `parse_oracle` **and** exercised against a real
      `GameEngine`), plus the fail-closed half rewritten in
      `test_combat_restriction_family.py`.

- [x] **Combat statics — requirements + multi-block permissions** (batch 28,
      2026-07-22, `PARSER_VERSION` 30, +46 covered cards: 8,897 → 8,943 /
      34,209 = 26.1%). Closes the three RULE 508/509 families batch 27
      deliberately left open, so `BACKLOG.md`'s "Combat statics" entry
      now holds only two narrow parser-only gaps (a board-count-threshold
      filter, a qualified group scope).

      **Combat requirements (RULE 509.1c/d)** — the mirror image of a
      restriction (they force a block rather than forbid one):
      - **"~ must be blocked if able."**/**"All creatures able to block ~ do
        so."** (Lure-shaped) bind as synthetic layer-6 flag keywords
        (`"must_be_blocked"`/`"all_must_block"`) — the same `grant_keyword`
        plumbing `attacks_if_able` already used, so no new static-ability
        shape was needed, only the flag names. Checked by a new
        `GameEngine._enforce_block_requirements`, called exactly where
        `_enforce_attacks_if_able` already is: as the caller tries to leave
        the relevant declare step (here, declare-blockers) — the same "no
        other 'I'm done' signal" reasoning, since `declare_blockers` is
        additive too.
      - **Deliberately no full requirement-satisfaction optimizer.** RULE
        509.1c's real behaviour, when two requirements can't both be
        satisfied by the creatures available, has the defending player
        choose which to break subject to maximizing how many are obeyed.
        Building that solver wasn't worth it: `_enforce_block_requirements`
        instead re-asks `can_block` for each candidate, which *already*
        reflects every restriction and remaining block capacity — so a
        creature already fully committed elsewhere is naturally excused
        from a second requirement, without tracking "why" it's excused.
        This gets the common case (no conflict) exactly right and the
        conflicting case gracefully (whatever the defending player actually
        declared stands), which is what `test_all_must_block_excuses_a_
        blocker_already_committed_elsewhere` pins down.
      - **The resolve-time, *pairwise* siblings** — "target creature blocks
        ~ this turn if able."/"…can't block ~ this turn." — name a
        *specific* attacker (the ability's own source), which a bare flag
        can't carry and which doesn't exist as a fixed value at parse time
        (it varies per game object). `GrantCombatRestrictionEffect` (the
        existing resolve-time `combat_restriction` grant) gained a
        `restrict_to_source` flag: at `apply()` time it stamps
        `{"instance_id": self.source.instance_id}` onto the restriction's
        `filter`. Two new pieces made this reachable: `matches_object_
        filter` gained an `instance_id` key (engine-internal only — never
        emitted by the oracle-text parser itself, only computed at resolve
        time), and a new `must_block_target` restriction kind, read by
        `_enforce_block_requirements`'s second pass (over every permanent,
        not just attackers, since the requirement lives on the *blocker*).
        "…can't block ~ this turn" reuses the *existing* `cant_block_
        filtered` kind with the same `restrict_to_source` trick — zero new
        restriction kinds needed for that half.
      - **"Target creature attacks this turn if able."** needed *no* new
        engine code at all: it's a plain temporary keyword grant onto the
        target (`GameObject.temp_keywords`, the same mechanism "gains flying
        until end of turn" already uses), and `combat.has()` already unions
        `temp_keywords` into the flag-keyword check `_enforce_attacks_if_
        able` reads — so the resolve-time and standing forms of this one
        requirement share one predicate without knowing which granted it.

      **Multi-block permissions (RULE 509.1b)** — "~ can block an additional
      creature each combat."/"~ can block any number of creatures.":
      - `GameEngine.can_block`'s old bare `blocker.blocking is None` check
        (one block per blocker, hard-coded) generalizes to `combat.
        has_block_capacity`, backed by a new `GameObject.additional_
        blocking` list — `blocking` still holds the *first* attacker
        (untouched for the overwhelming majority of blockers), and
        `additional_blocking` holds every one after it. `combat.
        blocking_attacker_ids`/`blocks_used`/`max_blocks_for` read the two
        together; the grants themselves ride the *existing* `combat_
        restriction` static (`"extra_blocks"` + `count`, `"unlimited_
        blocks"`) — a permission rather than a restriction, but neither
        changes a characteristic either, so the same non-RULE-613 bucket
        fits both.
      - **Combat damage** (`GameEngine._deal_combat_damage_step`) needed a
        real change: a blocker's power used to go entirely to the one
        attacker it was blocking. `_split_blocker_damage` now divides it
        evenly (remainder to the earliest-blocked attacker) across every
        attacker named across `blocking`/`additional_blocking` — an
        auto-pick, non-interactive simplification for the "divided as its
        controller chooses" assignment (RULE 510.1c), matching this
        project's existing "auto-pick" convention for choices with no
        interactive UI yet (`_sacrifice_candidate` and friends). Degenerates
        to the pre-existing single-attacker behaviour exactly when there's
        only one, so no regression risk for the ordinary case.
      - `declare_blockers`'s "can't block alone" check and its projected-
        blocker set, and `_combat_has_first_strikers`'s combatant scan, both
        moved from the bare `blocking is not None` test to `combat.
        blocking_attacker_ids(...)` so a multi-blocker is counted correctly
        everywhere, not just at the capacity check.

      Tests: `test_combat_requirements_and_multiblock.py` (new, 13 tests —
      each shape driven through `parse_oracle` **and** exercised against a
      real `GameEngine`, including the damage-split and requirement-conflict
      cases).

- [x] **Combat statics — the last two parser-only gaps** (batch 29,
      2026-07-22, `PARSER_VERSION` 31, +3 covered cards: 8,943 → 8,946 /
      34,209 = 26.2%). Closes the two narrow gaps batch 28 deliberately left
      open, so `BACKLOG.md`'s "Combat statics" entry is fully closed —
      nothing left in that section at all.

      **A count-selector threshold instead of a literal int** — "Creatures
      with power less than the number of Islands you control can't block
      ~." (Kraken of the Straits). Every existing filter key in `combat.
      matches_object_filter` (`min_power`, `max_power`, …) is a literal int
      baked in at parse time; this one is a *board count*, re-evaluated at
      combat time:
      - `matches_object_filter` gained a `power_lt_count_selector` key and,
        for the first time, an optional `state` parameter — needed to walk
        the whole battlefield for the count, unlike every other key (which
        answers from `obj`/`reference` alone). `blocker_allowed` threads it
        through from `GameEngine.can_block`.
      - `continuous.count_selector` gained a `lands_you_control_of_type_
        <x>` entry (the `devotion_to_<colour>`-style prefix-matched family)
        for "the number of Islands you control" specifically.
      - Scoped to the *attacker's* controller (RULE 613.7c: "you" in an
        ability's text always means its own source's controller), read off
        `reference.controller_id` in `matches_object_filter` — `reference`
        is already the attacker at every call site, so no new parameter was
        needed to carry that scoping.
      - Parser: `object_filter`'s new `_POWER_LT_COUNT_RE` maps a basic land
        type word to the selector name; an unrecognised type (or a
        non-land-type count, e.g. "the number of creatures you control")
        still fails closed, since `_BASIC_LAND_PLURALS` is a closed five-
        entry table.

      **A group scope with its own qualifier** — "Each creature you control
      **with power 4 or greater** can't be blocked by more than one
      creature." (Challenger Troll/Flopsie, Bumi's Buddy-shaped; Delney,
      Streetwise Lookout combines this with an independent filtered *tail*
      in the same sentence — "Creatures you control with power 2 or less
      can't be blocked by creatures with power 3 or greater."):
      - `_QUALIFIED_SUBJECT` gained a trailing `(?: with (power|toughness)
        N or (greater|less))?` group, read by `_qualified_affects` into
        `min_power`/`max_power`/`min_toughness`/`max_toughness` — new
        per-object *selector* qualifiers, distinct from the restriction
        tail's own `filter` dict (which describes the *other* creature in
        the interaction, e.g. the blocker).
      - `continuous.group_selector_objects` reads the four new keys to
        narrow `result` by each affected object's own derived power/
        toughness — the same names `combat.matches_object_filter`'s filter
        dict already uses, but a different namespace (selector params vs. a
        nested filter dict), so no collision. Whitelisted through
        `effects.py`'s `_SELECTOR_KEYS` (the params-clamping boundary every
        static-ability spec goes through) — shared infrastructure, so any
        other static-ability family (anthem, `pt_set`, `grant_keyword`, …)
        can use the same qualifier for free if a future card needs it.
      - **A real ordering fix, not just new vocabulary**: a power qualifier
        has to see the *current* recompute pass's derived power, including
        an anthem that fires earlier in the very same pass — but
        `combat_restriction` used to be stamped *before* the layer-7 P/T
        pass (it isn't a RULE 613 layer itself, so its position in
        `continuous.recompute` had never mattered before). Moved the whole
        `combat_restriction` block to run *after* layer 7 instead;
        `test_qualified_group_scope_reads_same_pass_anthem` pins down the
        same-pass visibility this fixes. Purely a within-function
        reordering — no other bucket depends on combat restrictions running
        early, so nothing else changed behaviour.

      One pre-existing test (`test_combat_restriction_family.py`'s
      `test_qualified_variants_outside_the_vocabulary_stay_unclaimed`) had
      cited the Kraken shape as a "stays unclaimed" example; updated to a
      still-genuinely-unmodeled sibling (a *creature*-count threshold,
      which has no selector at all) now that the Islands-count shape ships.

      Tests: `test_combat_restriction_dynamic_thresholds.py` (new, 5 tests
      — the dynamic threshold at two different board counts, its
      RULE-613.7c controller-scoping, the qualified-scope filter alone, the
      same-pass-anthem visibility fix, and the Delney-shaped combination of
      a subject qualifier with an independent filtered tail).

- [x] Two "auto-pick the first candidate" gaps became real player choices
      (2026-07-27), reported directly against play: an activated ability's
      own "Sacrifice a `<type>`" cost, and any discard (looting: "Draw a
      card, then discard a card.", or a directly-targeted forced discard
      like Mind Rot). Neither is a resolution-time effect — both used to be
      paid/applied in one synchronous call with no player prompt at all.
      **Sacrifice-as-cost**: `GameEngine._sacrifice_candidate` gained an
      optional `chosen_id`, threaded as `sacrifice_choice` through
      `_can_pay_activation_cost`/`_pay_activation_cost`/`can_activate`/
      `activate_ability`/`tap_for_mana` (an Ashnod's Altar-shaped mana
      ability's cost pays the same way) — the exact shape `tap_choices`
      already established for "tap N untapped `<type>`s you control"
      (Birchlore Rangers): `None` auto-picks (non-interactive callers, and
      the existence-only check `legal_actions` uses before a choice is
      made), an explicit id is validated against every legal candidate.
      `GameEngine._sacrifice_cost_choice` (mirroring `_tap_cost_choice`)
      offers the pool via `legal_actions`' new `sacrifice_cost` key on both
      the `activate_ability` and `tap_for_mana` action shapes; not offered
      for a `"self"` cost, which is never a choice. `game_session.py`'s
      `_dispatch` round-trips a `sacrifice_choice` instance id the same way
      it already does `tap_choices`. Frontend: `gameBoardView.js` reuses
      the existing one-pick-at-a-time `castTargeting` modal (previously
      only wired to `tap_cost`) with a new `isSacrificeChoice` flag,
      `data-sacrifice-choice-start`. **Looting/discard**: `"discard"` joined
      `RulesEngine.CHOOSE_OBJECT_ACTIONS` (alongside `tap`/`sacrifice`/
      `return_to_hand`/`soulbond_pair`/`library_top`) with `discard_specific`
      as its one-pick action; the new `RulesEngine.discard_choice` opens
      that chooser via the existing `request_choose_objects`, and
      `DiscardEffect.apply` (`game/effects.py`) now calls it — through a new
      `GameContext.discard_choice` — instead of the plain `discard`. RULE
      701.8: the *discarding* player picks, not the effect's controller, so
      a Mind-Rot-shaped "target player discards N" still asks the right
      seat. Forced with no prompt when the hand has at most `count` cards
      left (Windfall's whole-hand discard, still routed through the plain
      `discard` — no choice ever exists there). Cost-payment discard
      (`ActivationCost.discard`, e.g. a Madness-enabling "Discard a card:
      …") deliberately keeps the old non-interactive `RulesEngine.discard`
      — a cost is paid inside one synchronous call, the same reason a
      cast-time "as an additional cost, sacrifice a creature"
      (`_pay_additional_cast_cost`) also stays auto-pick for now (see
      `docs/implementation-state/BACKLOG.md`). Tests: `test_game_engine.py` (3 new
      sacrifice-cost cases: 2+ candidates offered/honoured, auto-pick
      fallback, invalid-choice rejection) and the new
      `test_discard_choice.py` (5 cases: choice opens, answering discards
      the one picked, a 2-card discard asks twice, whole-hand discard needs
      no prompt, the discarding player — not the caster — owns the choice).

- [x] **Fight (RULE 701.14, MEC-1, 2026-07-28)** — the mechanic *and* its
      parser recognition in one batch, which is the standing rule for a
      mechanic ticket: an engine primitive nothing can emit from oracle text
      is half a feature. `game/effects.py`'s `FightEffect` is deliberately
      **one atomic effect, not two `DealDamageEffect`s**, because RULE
      701.14b's cancellation is mutual — if either creature has left the
      battlefield or stopped being a creature by resolution, *neither* deals
      damage — and because 701.14a's two damage events are simultaneous, so
      both powers are snapshotted before either half lands. 701.14d (not
      combat damage) falls out of `deal_damage`'s default; 701.14c (a
      creature fighting itself deals twice its power) falls out of dealing
      both halves to the same object.
      ``fighter_kind`` picks the subject the way `TapEffect`'s modes do —
      a target kind for the two-target printed form (the second requirement
      riding the `GameEffect.extra_target_specs` shape `AttachChosenEffect`
      introduced), ``None`` for "it fights …" where the source itself
      fights, ``"attached_permanent"`` for an Aura host ("when this Aura
      enters, enchanted creature fights …", re-read off `attached_to` at
      resolution). No new targeting kind was needed: the engine's plain
      ``creature`` kind already excludes the ability's own source, which is
      exactly RULE 109.5's "**another** target creature" for a self-fight.
      **Parser** (`catalogue/handlers.py`, four rows) brought two reusable
      pieces. `subgrammars.target_macro(suffix)` is the shared `TARGET`
      alternation with its group names renamed, so one regex can finally
      carry *two* RULE 115 requirements ("target creature you control fights
      target creature you don't control") — previously impossible, since a
      regex can't name a group twice, and the reason every earlier
      two-target card (Brass Squire, Halvar) had to be hand-authored.
      `EffectHandler.self_subject_only` is the first handler row gated on
      *context rather than text*: "it fights …" is the source in a trigger
      body ("When Kogla enters, **it** fights …") and a **previously
      targeted creature** in a spell's chained sentences ("target creature
      you control gets +1/+2 until end of turn. **It** fights …", Epic
      Confrontation) — the same string, two referents. `segmenter.
      parse_effect_body` grew a ``self_subject`` flag that only the
      *unsplit* body of a self-subject trigger sets (once a body chains
      clauses on a connector, an earlier clause may have rebound the
      pronoun, so it stops being trusted), and Epic Confrontation stays
      UNMODELED rather than being modeled as a *sorcery* fighting — which
      would resolve to nothing at all, exactly the half-modeling the
      coverage gate exists to prevent.
      Yield: fight cards MODELED 4 → 23 of 160; cache-wide 9,264 → 9,283
      (27.1%), `PARSER_VERSION` 37. What's left is *whose* creature fights
      (pronoun-chained clauses, cross-target "another", "those creatures
      fight each other") and the same-shaped one-sided "deals damage equal
      to its power" family — filed as MEC-10 and closed by the entry below;
      the Enrage trigger condition found on the way is MEC-11. Tests:
      `test_fight.py` (18: the primitive's five subjects/cancellations,
      lethal-through-SBA, the not-combat-damage event, Prey Upon
      parser→binder→stack end to end, and three guards that the fail-closed
      shapes *stay* unclaimed).
- [x] **Whose creature fights (MEC-10, 2026-07-28)** — the follow-up batch
      that closed the rest of the fight family, and with it [ENG-5]. The
      shape of the problem was never the fight: it was *naming* a creature
      the card doesn't re-describe. Four mechanisms, each general rather
      than fight-specific:
      **1. A pronoun bound to the previous clause** (`GameContext.
      previous_targets`). RULE 608.2 applies an effect list in printed
      order, so `_apply_effects_partitioned` — the one choke point every
      resolution goes through, spell, wrapper ability and RULE 608.2-resumed
      remainder alike — now records what the last *targeting* effect
      actually chose. A later clause names it with the pseudo-subject
      ``previous_target``/``previous_target_2`` (`_IMPLICIT_FIGHT_SUBJECTS`,
      shared with the source and Aura-host subjects MEC-1 introduced).
      That's what makes "target creature you control gets +1/+2 until end of
      turn. **It** fights target creature you don't control." (Epic
      Confrontation) one ordinary pump plus one ordinary fight instead of a
      bespoke fused effect class per verb pair — the trap
      `CounterThenFightlikeDamageEffect` had already fallen into once for
      Archdruid's Charm. A non-targeting clause in between doesn't clear the
      referent: it's the last thing *chosen*, not the last thing that
      happened.
      **2. Per-effect target partitioning for a spell/ability** ([ENG-5]).
      The referent above is only worth anything if the two clauses resolve
      against *different* picks, and until now a spell's effects all read
      the same flat list off the front. `targeting.partition_targets` splits
      a flat, in-printed-order list into one group per requirement (RULE
      115.1 — the order the board's own targeting rounds gather them in),
      and both `GameEngine._cast_current_face` and `activate_ability` derive
      `StackItem.target_groups` from it when the caller didn't supply any.
      It deliberately returns ``None`` — old shared-list behaviour — when
      the length doesn't match, because that is exactly what a **declined
      "up to one"** produces and no server-side rule can tell which slot was
      skipped. So the board sends the partition explicitly (see
      `Done_Frontend.md`), bots do too (`bots.pick_target_groups`), and
      `FightEffect`/`DamageEqualToPowerEffect` still refuse to have a
      pronoun fighter fight *itself* as a last-line guard against a
      hand-posted flat list. `_ability_target_requirements` also had to
      start reading `target_specs` rather than ``target_spec`` — an
      activated ability whose single effect wants two targets (Ulvenwald
      Tracker) had been offering only the first.
      **3. RULE 109.5's cross-requirement "another"** (`TargetSpec.
      distinct_from_others`). "Target creature you control fights
      **another** target creature" excludes the *other requirement's* pick,
      which no per-candidate filter can answer — so, like
      ``distinct_controllers``, it's an offer-time exclusion across rounds
      (board + bots) with a resolve-time backstop in the effect. The
      source-relative reading of the same word needs nothing new: the plain
      ``creature`` kind already excludes the ability's own source, and
      "another … you control" maps to the existing
      `other_creature_you_control`.
      **4. The one-sided fight** (`DamageEqualToPowerEffect`) — "target
      creature you control deals damage equal to its power to target
      creature you don't control" (Rabid Bite/Bite Down) and the "when ~
      dies, **it** deals damage equal to its power to any target" family.
      Same subject vocabulary as a fight on the dealer side,
      `DealDamageEffect`'s untargeted ``selector`` on the recipient side.
      Two deliberate differences from a fight: the damage is one-way, and
      the dealer is **not** required to still be on the battlefield —
      the commonest printed form is a dies trigger, where RULE 608.2h's last
      known information is what its power comes from.
      Parser: `EffectHandler.previous_subject_only` mirrors MEC-1's
      `self_subject_only`, handed out by `parse_effect_body` to a split
      part whose predecessor actually chose a creature
      (`_announces_creature_target`) — the two flags are never both set, so
      a pronoun means the source or the last pick, never either-or; plus a
      `choose_targets` row for the "choose target … and target …" opener
      (`ChooseTargetsEffect`, a real no-op effect so the pair is announced
      at cast time even when the clause consuming it is conditional), the
      "another" variants, the one-sided rows, and a "target creature or
      planeswalker you don't control" `TARGET` row.
      Yield: fight cards MODELED 23 → 39 of 160; cache-wide 9,283 → 9,344
      (27.3%), `PARSER_VERSION` 38. The fight cards still open are blocked
      on *other* clauses (a sibling mode of a modal block, "if it's
      legendary", the Enrage ability word — MEC-11), not on who fights.
      Tests: `test_fight.py` grew to 33.

- **Monstrosity, Adapt and Goad** (2026-07-29, MEC-2 + MEC-3, RULE 701.37 /
  701.46 / 701.15). Three keyword actions that had no primitive *and* no
  recognition; shipped in one batch because each is engine + parser or it
  isn't shipped at all.

  **Why monstrosity and adapt are not one mechanic.** They read alike
  ("put N +1/+1 counters on it") and the backlog ticket treated them as one,
  but their *gates* differ in kind: monstrosity's is a **designation**
  (701.37b — once monstrous, always monstrous until it leaves the
  battlefield), adapt's is the creature's **current counters** (701.46a), so
  adapt can happen again and again as counters come and go. Sharing an
  implementation would have meant one of them carrying a flag it must never
  read. So: `RulesEngine.monstrosity` (atomic for the same reason
  `RenownEffect` is — the 701.37a guard, the counters and the flag are a
  single conditional, and two steps would put counters on a second
  activation) and a separate `RulesEngine.adapt`. Adapt correspondingly gets
  **no** event and no designation, and its cards' "as long as ~ has a +1/+1
  counter on it" statics needed nothing new at all — that is the layer
  engine's existing `min_level` gate with `level_counter="+1/+1"`.

  **What the designation is for.** `GameObject.is_monstrous` exists so two
  other things can read it: `EventType.BECAME_MONSTROUS` (fired only on the
  transition, so a second activation is silent) and the RULE 613.6
  conditional static "as long as ~ is monstrous, it has `<keywords>`" — a new
  `requires_monstrous` gate in `group_selector_objects`, sitting with
  `active_player_only`/`min_level`/`min_count_selector` rather than being a
  layer of its own. Fleecemane Lion's hexproof therefore *appears and
  disappears* with the designation on every recompute instead of being
  granted once at resolution. `monstrosity_x` records 701.37c's "the value
  of X as it became monstrous". Both are cleared by `reset_as_new_object`,
  which is exactly 701.37b's "until it leaves the battlefield".

  **Goad's two requirements land in two different places**, and that is the
  whole design. "Attacks each combat if able" (701.15b) is the *same*
  requirement the `attacks_if_able` flag keyword already imposes, so it
  rides the same `_enforce_attacks_if_able` check rather than a parallel
  one. "Attacks a player other than the goader if able" cannot be judged
  creature-by-creature at declaration time — it is about the finished
  attack — so it is a new `_enforce_goad_requirements` beside
  `_enforce_attack_alone_restrictions`, on the way *out* of the
  declare-attackers step, which is where this engine already puts
  whole-attack requirements. One subtlety cost a debugging round and is
  worth keeping: that check asks `_attack_conditions_ok`, **not**
  `_can_attack`. By the time it runs the creature is declared and (without
  vigilance) tapped, so `_can_attack` would answer "no legal alternative
  existed" for every defender — it would be reading the state the very
  declaration under audit created. Everything `_can_attack` adds beyond the
  per-defender conditions is defender-independent and was already checked
  when `declare_attackers` accepted the creature.

  **Goaded is a set of goaders, not a flag.** RULE 701.15c (several players
  goading = several requirements) and 701.15d (the same player twice = no
  extra requirement) both fall straight out of that, and 701.15a's "until
  the next turn of the controller" becomes a one-line sweep in `begin_turn`
  discarding the incoming active player's own id — the same "until your next
  turn" duration the player-effect and replacement-effect sweeps above it
  use, keyed per-goader on the creature because goaded is a designation and
  not an effect. The **static** half ("Enchanted creature gets +2/+2 and is
  goaded", 8 cards — the most common goad phrasing printed) is deliberately
  a *second* store, `_goaded_by_static`, re-derived every recompute: an
  Aura's designation must vanish with the Aura, which the sticky
  resolve-time set must not. `combat.goaders` unions them, the way
  `combat_restrictions` already unions its standing and until-end-of-turn
  halves. The static binds to a new `goaded` "layer" that isn't a RULE 613
  layer at all — goaded is explicitly neither an ability nor a copiable
  value (701.15b), so it can't be a layer-6 grant; `continuous.recompute`
  stamps it in the same non-613 bucket as the combat restrictions, after the
  P/T pass for the same reason (a power-scoped goad scope must see this
  pass's anthems).

  Parser: `monstrosity <n>|x` and `adapt <n>` effect rows; `goad {TARGET}`
  plus its pronoun form (`previous_subject_only`, "goad that creature",
  7 cards) and mass form (`goad all creatures your opponents control` over a
  new `creatures_opponents_control` **group** selector — the name already
  existed as a `count_selector`, so one idiom now covers both counting and
  acting); `becomes monstrous` as a `_TRIGGER_VERBS` row, which also gets
  "when ~ enters **or** becomes monstrous" (Alpha Deathclaw) free through
  the existing compound-verb path; and three static rows — the "…and is
  goaded" tail on `_ATTACHED_ANTHEM_RE`/`_ATTACHED_GRANT_RE`, the bare
  "enchanted creature is goaded", and `_MONSTROUS_GRANT_RE`.
  `requires_monstrous` had to be added to `_SELECTOR_KEYS` or it would have
  been silently dropped at bind time — the standing trap for a new selector
  param.

  Yield: +28 cards cache-wide with **zero regressions** (9,344 → 9,372,
  27.4%), `PARSER_VERSION` 39 — and Acquired Mutation, the one card MEC-3
  named, which had been sitting UNMODELED on its goad line alone since the
  rad-counter batch (`test_rad_counter_deferred_gaps.py`'s assertion that it
  stays unmodeled was inverted to assert the opposite). Both tickets' card
  estimates were stale in opposite directions: MEC-2 claimed ~63 monstrosity
  cards (the cache has 43), MEC-3 claimed Acquired Mutation was "the one
  blocked real card" (85 cards mention goad). What is left is genuinely
  *not* about these mechanics — a variable target count, a
  power-comparison scope, a token-creation referent, a goaded-filter trigger
  subject, and a compound "as long as" tail — enumerated as MEC-12/MEC-13
  rather than left implied.
  Tests: `test_monstrosity_adapt_goad.py` (26), covering both no-op gates,
  the designation's death on a zone change, the conditional static appearing
  only once monstrous, goad expiry on the goader's turn (and *not* on
  anyone else's), the two-player "may attack its goader" case that makes
  goad inert in 1v1, and the static-vs-sticky distinction.

- **"As long as" and "until": one condition vocabulary and one duration
  system** (2026-07-29, MEC-13 + PAR-11, RULE 613.6 / RULE 611). The user
  asked for MEC-13 and for the generic mechanism underneath it, and the
  second is what this entry is mostly about.

  **The problem.** Conditional statics had arrived one card at a time, and
  each had added its own parameter to `continuous.group_selector_objects`:
  ``active_player_only`` (Nahiri's "during your turn"), ``min_level``/
  ``max_level`` (a Class/Leveler's own counters), ``min_count_selector``
  (Metalcraft), and — shipped hours earlier in the monstrosity batch —
  ``requires_monstrous``. Four `if`s returning `[]`, four entries in
  `effects._SELECTOR_KEYS`, four chances to hit the trap where an
  unwhitelisted selector param is silently dropped. Measuring first showed
  why that pattern had to stop rather than continue: **"as long as" leads
  ~250 clauses in the cache**, across at least five unrelated families (the
  source's own state, an attached permanent's characteristics, a board
  count, whose turn it is, a player's life/hand). The next dozen cards would
  have been the next dozen parameters.

  **`game/static_conditions.py`** is the single evaluation path: a whitelisted
  ``{"kind": …}`` dict, carried by *any* static in its ``active_if`` param and
  evaluated live on every recompute against the ability's own source and
  controller. Live evaluation is the whole trick — "as long as ~ is untapped"
  turns itself off the moment the permanent taps, with no event, no trigger
  and no bookkeeping anywhere. The four legacy gates keep their spelling in
  every shipped spec and are *translated* into this vocabulary
  (`condition_from_legacy_params`) rather than evaluated separately, so there
  is one implementation and no migration of existing cards.

  Two naming decisions worth keeping. The param is ``active_if``, not
  ``condition``: a ``combat_restriction`` static already carries a
  ``condition`` of its own from the *combat-time* vocabulary ("~ can't attack
  unless defending player controls an Island"), and one key holding two
  vocabularies made each fail closed on the other's dicts — caught
  immediately by four `test_qualified_combat_restrictions` failures, which is
  exactly what that suite is for. And this module is deliberately *not*
  `condition_query.py` (a cast/activation-legality gate that must work for a
  card in hand) nor `spec.py`'s ``_ALLOWED_CONDITION_KEYS`` (whether a
  resolving one-shot applies): three different questions, three whitelists,
  per docs/09.

  **The parser side is a pure wrapper.** `_conditional_static_specs` parses
  the gate, hands the *bare* static back to `static_effect_specs`, and stamps
  ``active_if`` on every spec that comes back — so no family needs a
  conditional variant of itself, and both printed orders ("As long as X,
  Y" / "Y as long as X") produce identical specs. Making that work needed the
  first **self-scoped** anthem/grant rows the catalogue had ("~ gets +2/+2",
  "~ has trample"): real cards print that shape almost only *inside* a
  conditional, which is why they'd never been needed. Fail-closed in the
  direction that matters — an unrecognised condition kills the whole clause
  rather than degrading to an ungated static, since a static that should be
  gated but isn't is strictly worse than an unmodeled card.

  **Durations (`game/durations.py`)** are the time-bound half. The existing
  ``temp_power``/``temp_keywords``/``temp_protections`` fields *are* "until
  end of turn" — cleared wholesale at RULE 514.2 cleanup, with nowhere to
  record any other ending — so "until your next turn" (120 occurrences),
  "until end of combat" and RULE 611.2b's "for as long as `<condition>`" were
  structurally unreachable. A RULE 611 continuous effect created by a
  resolving spell now lives on `GameState.floating_statics` as an ordinary
  `StaticAbility` (same layers, same timestamps, same dependency pass; it
  deep-copies with `clone` because it is plain data) and is swept at the
  window its duration names — cleanup, end of combat, the granting player's
  next turn, the next end step. Existing until-EOT effects deliberately stay
  on the `temp_*` path: one phrasing, one implementation, and the parser
  routes only the durations `temp_*` can't express to `GrantUntilEffect`.

  The subtlest piece is that a ``for_as_long_as`` duration must **remove** the
  effect when its condition fails, not skip it — otherwise it is silently an
  ``active_if`` gate, and the two are indistinguishable from outside until a
  card's effect wrongly comes back. A test asserting exactly that (bring the
  named permanent back; the grant must stay gone) caught the first
  implementation, which only filtered. Unknown durations fail closed in the
  *visible* direction — treated as ``rest_of_game`` and never swept, so a
  mis-parse leaves a lingering effect rather than silently deleting a
  legitimate one.

  **MEC-13** then falls out as a small consumer: a combat-permission tail on
  the grant rows ("…has trample **and can attack as though it didn't have
  defender**") plus the new ``attacks_as_though_no_defender`` restriction —
  which is a RULE 508.1a *permission*, not a keyword removal, so the creature
  keeps Defender and only `_can_attack` is affected. 15 real cards print that
  phrase; the ticket had it as one.

  **PAR-11 closed by composition, with no new primitive at all** — the best
  evidence the generalization was the right shape. "Tap target land. It
  doesn't untap during its controller's untap step for as long as ~ remains
  tapped." is the fight batch's `previous_subject` pronoun + batch 8's
  ``no_untap`` static + this batch's condition-bounded duration; all three
  existed, and had simply never met. It needed one handler row and one
  widening: `segmenter._CREATURE_TARGET_KINDS` now also accepts a
  land/artifact/permanent antecedent, since a pronoun pointing at a land is
  no more ambiguous than one pointing at a creature. 8 of 23 lock-down cards
  now model — and with them **`no_untap_optional` became reachable by 6 real
  cards**, which was that ticket's entire premise (the engine, `legal_actions`
  and the frontend toggle had all shipped in batch 8 with no card able to
  reach them).

  Yield: **+125 cards cache-wide with zero regressions** (9,344 → 9,469,
  27.7%), `PARSER_VERSION` 41. Tests:
  `test_static_conditions_and_durations.py` (27) — the condition vocabulary
  unit by unit, conditions through the layer engine (on, off, and on again),
  each duration at its own window, the ``for_as_long_as``-vs-gate
  distinction, the fail-closed directions, MEC-13's card end to end, and the
  composed lock-down family. What's left is whitelist width, not mechanism:
  MEC-14 (conditions about the *attached* permanent, opponent-scoped counts)
  and PAR-11's residue — both closed by the batch below.

- **Goad's four residues and the rest of the "as long as" vocabulary**
  (2026-07-29, MEC-12 + MEC-14, both closed in full). Neither ticket was
  really about its headline mechanic, which is why they were worth taking
  together: goad was only the card pool that made four *unrelated* system
  gaps visible first, and MEC-14 was the widening that turned out to need one
  new idea rather than four new rows.

  **The condition subject (`of`) is the load-bearing part of MEC-14.** The
  ticket read as four separate whitelist entries; the biggest of them
  ("as long as **enchanted permanent** is a creature"/"…is red"/"…is a
  Vehicle", ~52 cards) is not a new *kind* at all but a new *subject*: the
  condition is about the Aura's host, not the Aura (RULE 303.4a), and an Aura
  is never itself a creature, so reading the source made those conditions
  permanently false. `static_conditions.condition_holds` now resolves a
  subject first (`CONDITION_SUBJECTS`: ``source`` — the default and what
  every shipped spec means — ``attached``, ``affected``), which makes *every*
  existing ``source_*`` kind work on an attached host for free rather than
  needing an `attached_*` twin per kind. Three characteristic kinds
  (``is_card_type``/``is_color``/``is_subtype``) read through `continuous`'s
  own matchers, so a *derived* type counts — an animated Vehicle is a
  creature for "as long as enchanted permanent is a creature", which is
  exactly what those cards are for. The remaining three phrasings were the
  ordinary rows the ticket predicted (``drawn_cards_at_least`` off the
  already-existing `GameState.cards_drawn_this_turn`; ``opponent_count``, the
  opponent-scoped sibling of ``control_count``, satisfied by *any one*
  opponent because that is what "an opponent has …" means).

  The parser half needed one thing beyond the rows: `_conditional_static_
  specs` rewrites the inner clause's pronoun to whichever attached-subject
  phrase the gate used ("As long as enchanted permanent is a Vehicle, **it**'s
  a creature…" → "enchanted permanent is a creature…"), so the body parses
  through the ordinary `_ATTACHED_*` rows with no conditional variant — the
  same "the wrapper stays a pure wrapper" discipline the previous batch set.

  ``of="affected"`` closes **PAR-11's residue** in the same pass: "…doesn't
  untap for as long as **it** has a paralyzation counter on it", where "it"
  is the *locked* permanent. Only the floating static holds that referent
  (`StaticAbility.object_ids`), so `durations.is_expired` supplies it and a
  multi-object static yields none — the condition then fails closed, which is
  right, because a group static has no single referent to mean.

  **RULE 702.94b soulbond** finally reaches an engine primitive that had been
  sitting unused: the ``soulbond_pair`` selector shipped with the cEDH cube
  batch and nothing could say "each of those creatures has …" to it. Three
  rows (quoted grant, anthem, bare keyword) and the pool parses. A good
  reminder of why this repo's batch discipline says to grep for an existing
  primitive first — the "missing mechanism" was a phrase.

  **MEC-12(a), a target count read off the board.** The ticket described
  Death Kiss's "goad up to **X** target creatures"; measuring first showed
  that shape is *one* card, while four others print "**for each opponent**,
  goad up to one target creature that player controls" — which is the same
  feature (a `TargetSpec.count_selector` resolved at announce time, RULE
  601.2c) with `distinct_controllers`, already shipped, doing the "that
  player" half. The interesting constraint was the trigger path: it gathers
  exactly one pick per spec, so `targeting.expand_counts` splits a
  multi-target requirement into one round each and `collapse_groups` merges
  them back before resolution, keeping `_apply_effects_partitioned`'s
  one-group-per-`target_specs`-entry contract intact. RULE 115.1a's "stop
  before N" needed its own answer (`"stop"`) rather than overloading the "you
  may" decline — stopping keeps the ability and resolves it against what was
  picked, declining abandons it — and RULE 601.2c's "not the same object
  twice" is enforced within a span. An all-ones `spans` means nothing was
  expanded, so every pre-existing path is byte-for-byte unchanged.

  **MEC-12(b), a dynamic threshold on a group scope.** "Creatures your
  opponents control **with power less than ~'s power** are goaded" can't use
  the literal `min_power`/`max_power` the scope already had, because ~'s own
  power is itself layer-engine output — an anthem on ~ moves the threshold.
  `continuous.dynamic_threshold` reads either the source's derived
  characteristics or `count_selector`'s whole board-count list, since both
  appear in that same printed position.

  **MEC-12(c), naming what the previous clause created.** `GameContext.
  created_objects` is `previous_targets`' sibling and exists for the same
  reason: those tokens were never targeted and did not exist when the ability
  went on the stack, so no `TargetSpec` can name them.
  `LivingWeaponEffect`'s docstring had recorded this gap from the other side
  since it shipped ("there's no vocabulary for whatever the previous effect
  just made") — an atomic effect class per verb pair was the only alternative.
  Scoped per resolution and threaded through a RULE 608.2 suspension the same
  way `previous_targets` is. Reaching it from card text also wanted "**each
  player/opponent** creates" and "creates a **tapped** …" (RULE 110.5a —
  applied as the token enters, not as a later tap), both of which the token
  grammar simply hadn't had. The duration itself is a second designation set
  (`GameObject.goaded_permanently`) rather than a per-entry expiry stamp: the
  only thing these cards change about RULE 701.15a is the duration, so the
  turn-begin sweep just never touches that set and `combat.goaders` unions
  all three.

  **MEC-12(d), a trigger subject filtered on a designation.** "Whenever a
  **goaded** creature attacks/dies" is neither a type, a subtype nor a
  controller, so it is its own key on the group filter. The RULE 400.7
  wrinkle is the familiar one: a DIES event's object is already gone, so
  ``goaded`` and ``in_combat`` are snapshotted onto the event at fire time
  exactly as ``object_types``/``subtypes``/``counters`` already were — and
  ``in_combat`` has to be, since RULE 506.4 removes a permanent from combat
  as it leaves the battlefield, so even a live lookup would answer wrongly.

  **Frontend**: `continuous.active_static_abilities` now carries each
  static's two *bounds* — ``duration`` (RULE 611, empty for a standing one)
  and ``condition`` (RULE 613.6's gate) — plus ``active``, whether that gate
  holds right now, and the board's "Statische Effekte" panel shows them as
  badges. A gated static that is currently off is **dimmed rather than
  hidden**: it is genuinely in play and applies again the moment its
  condition becomes true, which is the whole reason showing the condition is
  worth anything. Without this, an effect that ends at end of combat and one
  that lasts forever were indistinguishable on the board.

  Yield: **+58 cards cache-wide with zero regressions** (9,469 → 9,527,
  27.9%), `PARSER_VERSION` 42, 44 tests in
  `test_goad_residues_and_condition_subjects.py`. Both tickets are closed
  entirely — the goad pool's residue that remains (Rendmaw's "whenever you
  play a card with two or more card types", Baeloth's "choose a Background",
  Life of the Party's copy-token) is ordinary [PAR-12] tail work on clauses
  that have nothing to do with goad.

### ENG-1: re-validate attachments every SBA pass (2026-07-29)

RULE 704.5m/n ("an Aura not attached to a legal object goes to its owner's
graveyard"/"an illegally-attached Equipment or Fortification just becomes
unattached") had only ever been checked at the one moment a host *leaves the
battlefield* (`RulesEngine._detach_attachments_from`). A host that stays on
the battlefield but becomes newly illegal for its attachment — the common
real case is the enchanted/equipped creature *gaining* protection from the
attachment's colour after it's already attached — was never re-checked.

Two pieces:

- **`_attachment_legal` now checks protection** (`combat.is_protected_from
  (target, obj)`, RULE 702.16c/d), which it never had before — only
  matters once something re-checks an *existing* attachment, since the
  initial `attach_to_target`/spell-resolution path already can't select a
  protected target via `targeting.legal_targets`' own protection filter.
- **`RulesEngine._revalidate_attachments`**, a new RULE 704.5m/n check
  slotted into `check_state_based_actions` alongside the 704.5q counter-
  annihilation check: for every attached permanent whose host is still on
  the battlefield (and not phased out — see below), re-run the same
  `_attachment_legal` an initial attach uses. Illegal → an Aura goes to the
  graveyard (704.5m), an Equipment/Fortification/Reconfigure-as-equipment
  just unattaches and stays (704.5n) — one action per pass, matching every
  other SBA check's "act once, then let the caller re-check the whole
  board" cadence.

Reusing `_attachment_legal` verbatim means any future legality rule added
there (a changed "enchant" quality, a control check) is picked up by the
periodic sweep for free — the two checks can't drift apart.

**Phasing interaction (RULE 702.26g):** `PhaseOutAllYouControlEffect`
(Teferi's Protection) phases an Aura/Equipment out *together* with its host
rather than unattaching it (a deliberate exception to the single-permanent
`PhaseOutEffect`, which does unattach) — a phased-out permanent is excluded
from `state.permanents()`, so it's already invisible to the new sweep's own
iteration; the host-lookup also explicitly skips a phased-out host as a
belt-and-suspenders guard for the same-host-different-controller edge no
shipped card reaches yet.

**Fallout, since this was the first thing to ever re-validate an
*already-attached* permanent's legality:** two existing hand-authored/test
paths turned out to rely on `parametric_keywords` being populated for an
attachment that never went through the normal `attach_keyword`/oracle-text
route, and would have had their (legitimate) attachment silently stripped
on the very next SBA pass —

- `RulesEngine.return_dies_as_new_permanent` (Harold and Bob, First
  Numens' "return it to the battlefield, it's an Aura enchanting...")
  builds a synthetic post-death `Card` and deliberately clears
  `parametric_keywords` ("loses all other abilities"), then stamps
  `attached_to` directly — bypassing `attach_to_target`. It now re-runs
  `parse_keywords`/`attach_keyword` against the *new* card's own printed
  text before attaching, which docks the structural "enchant" keyword
  quoted right there in the new oracle text without reviving any of the
  old creature's triggered/activated/static abilities (those stay cleared,
  same as before).
- Two test fixtures (`test_phasing.py`'s Robe of Stars,
  `test_cedh_cube_control_and_zones.py`'s Rancor) set `.attached_to`
  directly on a bare synthetic `Card` with no "Equip {N}"/"Enchant
  creature" oracle text — unrealistic versus the real cards, which always
  print that text — so `_attachment_kind` never recognized them as
  attachable at all. Fixed by giving both fixtures the missing oracle-text
  line, matching the real card.

Tests: `tests/test_attachment_revalidation.py` (new — protection-gained-
after-attach for both an Aura and an Equipment, an Equipment's host
changing control, a same-pass regression guard, and confirming a
host-left-the-battlefield attachment stays `_detach_attachments_from`'s
job rather than double-handled). Full suite green (2,790 tests) including
`--full-cache`.

### ENG-2: `SacrificeEffect` gets a real choice (2026-07-29)

RULE 701.17's "player sacrifices N permanents matching `<type>`" —
Annihilator's "defending player sacrifices two permanents" chief among
them — auto-picked the first matching permanent each time
(`RulesEngine.sacrifice`), even though nothing forces the choice: with more
matching permanents on the board than the count demands, RULE 601.2c
entitles the sacrificing player to pick which ones go.

`RulesEngine.sacrifice` now builds the candidate pool and hands it to
`request_choose_objects(..., action="sacrifice", ...)` — the same RULE
601.2c-style chooser Tevesh Szat's own "you may sacrifice another creature
or planeswalker" already used (`game/effects.py`'s `ChooseObjectsEffect`),
just reached from the *other* direction: `SacrificeEffect`'s plain path
(no `greatest_power`) now funnels through it instead of Tevesh Szat being
the sole consumer. `request_choose_objects` already auto-applies without a
prompt when the pool is no bigger than the count, so the "sacrifice
everything you have" edge case is unchanged — the pending_choice only
appears when there's an actual decision.

**Scope**: `greatest_power` (Professor Onyx's −3 — "a creature with the
greatest power") deliberately keeps its own `max()` auto-pick among the
tied leaders rather than routing through the chooser. It's a genuinely
different shape: the "greatest power" set has to be recomputed after each
removal (a creature sacrificed can change who's now the max), which
`request_choose_objects`'s single up-front pool doesn't model, and no
shipped card sacrifices more than one this way — so extending it there
would be unused generality for a real correctness edge (a tie) that isn't
reachable by any card in the pool today.

**Fallout**: `RulesEngine.sacrifice` opening a `pending_choice` instead of
resolving synchronously meant every caller that previously read the result
of a sacrifice off the very next line had to change. Checked every call
site: `_pay_player_cost`'s own sacrifice-cost-payment path (ward/RULE
701.17's "sacrifice ~ unless you pay") already clears `state.pending_choice`
before calling into it, so a nested choice opening there is architecturally
safe (and is itself a free correctness upgrade — a "Ward—Sacrifice a
creature." cost is no longer an auto-pick either). One test needed updating
— `tests/test_game_engine.py`'s Annihilator test now answers the interactive
choice (two picks from three eligible permanents) rather than asserting the
graveyard state immediately after `resolve_until_stable()`.

Tests: `tests/test_attachment_revalidation.py` unaffected; the updated
Annihilator test in `test_game_engine.py` is the execute-level coverage,
since `SacrificeEffect`'s own class had no dedicated test file. Full suite
green (2,790 tests) including `--full-cache`.

### ENG-3: cost-payment sacrifice/discard get the same choice shape (2026-07-29)

Two auto-picks left over after ENG-2, both *cost* payment rather than an
*effect* resolving — which matters, because cost payment is one synchronous
call inside `cast_spell`/`activate_ability` and can't pause for a
`request_choose_objects` `pending_choice` the way ENG-2's fix could (there's
no "resolving" moment yet; the spell hasn't even gone on the stack). The
existing precedent for exactly this constraint is `tap_choices`/
`sacrifice_choice` — an activated ability's own cost choice, threaded in as
an action parameter the caller already knows the answer to before calling,
rather than opened as a mid-call prompt.

- **A spell's own "as an additional cost to cast this spell, sacrifice/
  discard …" (RULE 601.2b, `GameEngine._pay_additional_cast_cost`)** now
  accepts `sacrifice_choice`/the new `discard_choices`, threaded through
  `can_cast`/`cast_spell`/`_cast_current_face` exactly like an activated
  ability's `sacrifice_choice` already flowed through `can_activate`/
  `activate_ability`. `_sacrifice_candidate` already supported a
  `chosen_id` param (built for the activated-ability path) — this is its
  first cast-cost consumer.
- **A plain "discard N cards" cost component** (`ActivationCost.discard`,
  distinct from Channel/Cycling's `discard_self`, which was never an
  auto-pick to begin with — it names a specific card) gained the
  `_resolve_discard_cost`/`_discard_cost_pool` pair, the `_resolve_
  tap_others` counterpart for discard: `chosen_ids` (instance ids)
  validated against the legal pool, `None` falling back to an auto-pick of
  the back of hand — unchanged from before for every non-interactive
  caller. Wired into **both** places `ActivationCost.discard` is paid: the
  additional-cast-cost path above, and an activated ability's own cost
  (`_can_pay_activation_cost`/`_pay_activation_cost`, alongside its
  existing `tap_choices`/`sacrifice_choice`). `DISCARD_HAND` ("discard your
  hand") stays a plain unconditional `RulesEngine.discard` call in both —
  there's nothing to choose when everything goes.
- Chosen discards are applied one `RulesEngine.discard_specific` call per
  card rather than a single `RulesEngine.discard(count=N)` — the same
  per-card event-firing granularity `request_choose_objects`'s own
  "discard" action already uses (`_apply_chosen_object`). No trigger
  currently reads `EventType.DISCARD`'s `count` field, so this is a
  no-op change in practice, not a behavioural one.
- `_can_pay_additional_cast_cost` keeps excluding the spell itself from its
  own discard pool (RULE 601.2b — it's still in hand at payment time but
  isn't a legal discard candidate for its own cost), now via
  `_resolve_discard_cost`'s own `exclude` param rather than a bespoke
  `len(hand) - (1 if obj in hand else 0)` count.
- `tap_for_mana` deliberately did **not** gain `discard_choices` — it
  already threads `sacrifice_choice` for a "Sacrifice a creature: Add …"
  mana ability (Ashnod's Altar), but no mana ability in the pool has a
  discard cost component, so there's nothing real for it to reach yet.

Tests: `tests/test_cost_payment_choices.py` (new) — an explicit choice
honoured for both the additional-cast-cost sacrifice and discard, an
invalid choice (wrong instance id / wrong count) making `can_cast` refuse,
the spell excluded from its own discard pool, the `None` auto-pick
fallback unchanged, and an activated ability's own discard-cost choice.
Full suite green (2,797 tests) including `--full-cache`.

### ENG-16: shared `_chosen_targets` helper in `effects.py` (2026-07-29)

Pure consolidation, no behavior change — the first phase of a broader
God-class refactor (`game_engine.py`/`rules_engine.py` are next). Seven
`GameEffect` subclasses each independently reimplemented the identical
RULE 115.1a "up to N target(s), off the front of a possibly-shared list"
resolution block before calling their own `context.<verb>(...)`:
`DestroyEffect`, `ExileEffect`, `ReturnToHandEffect`,
`ReturnFromGraveyardEffect` (found along the way — same block, not one of
the originally-named candidates), `TapEffect`, `AddCountersEffect`, and
`DealDamageEffect`'s non-divided branch. Extracted one module-level
`_chosen_targets(targets, count, target=None)` (`effects.py`, just above
`DestroyEffect`) that all seven now call; each class keeps its own name
(the `EffectRegistry` type-string identity), constructor params, and RULE
comments — this only removes the duplicated body, not the classes
themselves. `SacrificeEffect` was checked and doesn't fit: it resolves a
*player*, not a target list, and delegates the count to
`RulesEngine.sacrifice`. Full suite green (2,797 passed, 238 skipped)
verifies no behavior change.

### ENG-18: shared combat-damage-marker trigger scaffold (2026-07-29)

Third consolidation phase of the same God-class refactor
([ENG-16]/[ENG-17]). The backlog ticket estimated five of the nine
`_collect_*_triggers` methods shared an identical scaffold; reading all
nine in full found that was optimistic — only two,
`_collect_impulsive_draw_triggers` (Ragavan) and
`_collect_rad_counter_damage_triggers` (Glowing One/Infesting Radroach),
are genuinely byte-for-byte identical outside their own effect
construction: both guard on "combat damage to a player", read the
event's own `source_id`, look up the marker on that single source, and
resolve the damaged player + controller before building one
`TriggeredAbility`. The other three candidates each scan a different
domain with different filters —
`_collect_attacks_you_rad_counter_triggers` scans every permanent
filtered by `defending_player_id`/`requires_mode`,
`_collect_counter_death_return_triggers` scans every permanent filtered
by controller + a specific counter kind, and
`_collect_mill_return_from_graveyard_triggers` scans every *graveyard*
skipping the milling player's own — forcing one driver over all of them
would have meant threading three more parameters through call sites that
don't share logic, not real deduplication. Extracted only what's
genuinely identical: `_collect_combat_damage_marker_trigger(event,
marker_attr, build_effect, description)` now holds the shared guard/
lookup/ability-construction, with `_collect_impulsive_draw_triggers`/
`_collect_rad_counter_damage_triggers` supplying just their own
`build_effect`/`description` closures. Full suite green (2,797 passed,
238 skipped).

### ENG-19: `_halvar_god_of_battle` duplicate definition removed (2026-07-29)

Found while surveying `ability_catalogue.py` for parametrization potential
during the same God-class refactor: `_halvar_god_of_battle` was defined
twice (an early, incomplete version predating `GameEffect.
extra_target_specs`, documented as only modeling the static double-strike
grant since a two-independent-targets move-attachment trigger wasn't
supported yet; and the real, complete version from the cEDH-cube batch's
wave 6, once `extra_target_specs` shipped — see "cEDH staples cube" §
Wave 6 above). Since `register()` re-keys the same dict entry, the second
`register("Halvar, God of Battle", ...)` call had always won at runtime —
this was dead code, not a live bug, so removing the first definition and
its `register` call is a pure no-op verified by the full suite staying
green and `engine_bench.py inspect "Halvar, God of Battle"` still showing
all three bound abilities (triggered/activated/static).

Also found in the same pass: `BACKLOG.md`'s `ENG-12` ("Brass Squire,
Halvar, Archdruid's Charm... left unregistered") was itself stale —
all three were fully registered by the same wave-6 batch this section
already documents. Deleted rather than re-narrated, since the shipping
narrative already exists above.

### ENG-21: `rules_engine.py` split into per-responsibility mixins (2026-07-29)

The other reorganization half of the God-class refactor ([ENG-20] was
`game_engine.py`; [ENG-16]/[ENG-18]/[ENG-19] were this file's own
consolidation pass, done first). The single 7,849-line `RulesEngine` class
(236 methods) is now composed from nine mixins under a new `game/rules/`
subpackage — `triggers_mixin.py`, `casting_mixin.py`, `draw_discard_mixin.py`,
`damage_death_mixin.py`, `mana_counters_mixin.py`, `copies_mixin.py`,
`search_mixin.py`, `sba_mixin.py`, `misc_mixin.py` — with `rules_engine.py`
itself shrunk to the module docstring/helper functions, `__init__`, the
RULE 616 replacement-effect core (`apply_replacements`/
`_run_replacement_loop`/…, its own central entry point rather than one
responsibility among several), and the `class RulesEngine(TriggerCollectionMixin,
...)` composition (471 lines). Same mixin-not-delegation reasoning and same
mechanical extraction method as [ENG-20] (an `ast`-based script pulling
exact method spans incl. leading comments, header imports bumped one `.`
level per mixin, function-scoped relative imports caught by a second pass);
the one new wrinkle here was 2+ *consecutive* class-level constants
before a single method (`_ANY_COLOR_LABELS` then `_MANA_TYPE_LABELS`
before `add_mana_any_color`) — the first script draft's single
`pending_const` variable silently dropped the first constant when a second
one immediately followed, caught by the resulting `NameError` on import
before any test ran; fixed by accumulating a list instead of one slot.

Investigated both dedup items the `ENG-21` ticket had carried over from
initial scoping, and only one held up. The 237-line `_sba_pass` **did**:
broken into eleven `_sba_check_<name>` helpers (`sba_mixin.py`), one per
RULE 704.5 lettered sub-check (player loss, zero toughness, zero loyalty,
Siege defeat, battle zero-defense, battle protector, Saga completion,
lethal damage, counter annihilation, commander-zone-choice offer — three
checks, `_revalidate_attachments`/`_apply_legend_rule`/
`_remove_stranded_tokens`, were already their own methods before this
batch) called in the same order from a now-short dispatcher, each helper
independently citable by its own RULE number. The 8-times-repeated local
`_finish(resolved)` continuation closure **didn't**: reading all eight
found each has a genuinely different, mechanic-specific body (damage's
records stats and calls `lose_life`; a counters one is a 2-line call to
`_place`; draw's does the actual draw) — what repeats is the closure's
*name and signature* as the `on_resolved` callback `apply_replacements`
already accepts, not duplicated logic. Extracting a wrapper around a
2-line null-guard would trade a small amount of boilerplate for an extra
indirection layer obscuring control flow at each of the eight call sites —
the premature abstraction CLAUDE.md warns against, so left as-is. The
ticket's wording is adjusted accordingly rather than silently shipped as
originally scoped, the same honesty-over-estimate call [ENG-18] made.

Verified with the full suite (2,797 passed, 238 skipped, unchanged) plus
the opt-in `--full-cache` suite (same 4 pre-existing failures as
[ENG-20]'s verification, reproduced independent of this change),
`python -c "import mtg_analyzer.api.app"`, and `engine_bench.py`'s `play`
(Mulldrifter's ETB draw-two, exercising replacement effects and triggers)
and `combat` commands against a real `RulesEngine`.

### ENG-22: `continuous.py`'s `recompute()` split into one function per layer (2026-07-29)

The last God-class-refactor reorganization phase, and the highest-risk one
by design (RULE 613 layer *order* is load-bearing, unlike the mixin splits
in [ENG-20]/[ENG-21] where method order genuinely didn't matter). The
single 424-line `recompute()` is now a ~15-line dispatcher calling seven
top-level functions in the same order the inline blocks always ran in:
`_apply_layer_2_control`, `_apply_layer_3_text`, `_apply_layer_4_type`,
`_apply_layer_5_color`, `_apply_layer_6_ability`, `_apply_layer_7_pt`, and
`_apply_post_layer_combat_restrictions_and_goad` (the RULE 508/509 combat-
restriction and RULE 701.15b goad stamping that runs after the P/T pass,
never itself a RULE 613 layer). Layer 1 (`_apply_copy_layer`) was already
its own function before this batch. Cross-layer data flow turned out to be
almost nonexistent — the whole reason a mechanical extraction was viable
here despite the risk: `animation_pt` (built in layer 4, read by layer 7)
is the *only* value that crosses a layer boundary, so `_apply_layer_4_type`
returns it and `_apply_layer_7_pt` takes it as a parameter; `live_grant_keys`
(layer 6) and `base` (layer 7) are each fully local to their own layer and
needed no threading at all. Extracted via a line-range cut-and-paste script
(exact boundaries taken from the existing `# -- Layer N:` comments, which
already marked every seam) rather than manual retyping, to remove
transcription risk from a function this consequential.

Verified harder than [ENG-20]/[ENG-21], per the ticket's own instruction to
go carefully here: full suite (2,797 passed, 238 skipped, unchanged), the
opt-in `--full-cache` suite (same 4 pre-existing failures, confirmed
unrelated), every `layer`/`continuous`/`static`-named test explicitly
(368 passed), and three live `engine_bench.py inspect` checks exercising a
layer this risky to touch by hand: an anthem (`--with-bear`, "Creatures you
control get +1/+1." boosts only the controller's own Grizzly Bears, 2/2 →
3/3, leaving the opponent's Hill Giant untouched — layers 6/7 interacting
correctly) and Kraken of the Straits (its board-count-threshold combat
restriction still stamps a "Kampf" trace line — the post-layer block
reading layer 7's own output correctly).

### ENG-24: `_keyword_triggered_abilities` table-driven dispatch (2026-07-29)

The last consolidation-style phase of the God-class refactor, scoped down
on inspection like [ENG-18]: the ticket named *two* long if/elif chains in
`effect_binder.py`, but only one turned out to be one.
`_keyword_activated_ability` (Equip/Fortify/Reconfigure) is a single `if
name not in {"equip", "fortify", "reconfigure"}: return None` applicability
gate followed by one shared body — there's no per-keyword branching to
convert, since all three names build the identical `ActivatedAbility`
shape and differ only in their description string. Left untouched.
`_keyword_triggered_abilities` (soulbond/living_weapon/fading/renown/
annihilator/afflict/bushido) genuinely was seven `if name == "...":
return [...]` arms, now seven `_kw_<name>(obj, spec, n) -> list[
TriggeredAbility]` builder functions in a `_KEYWORD_TRIGGERED_BUILDERS:
dict[str, Callable]` table — same registry-over-if/elif pattern
`EffectRegistry` already uses. Each builder owns its own `n`-requirement
check (`if n is None: return []`) since the three shapes differ (fading/
renown accept `n is not None` inline and use it differently — renown
`int()`-casts only the amount, fading doesn't cast at all; annihilator/
afflict/bushido reassign `n = int(n)` once and read the converted value in
both the effect and the description) — preserved exactly per-builder
rather than hoisting a "same for all" conversion that would have been
wrong for two of the seven. Full suite green (2,797 passed, 238 skipped),
`--full-cache` (same 4 pre-existing failures), and every keyword-named
test explicitly (`annihilator`/`afflict`/`bushido`/`soulbond`/`fading`/
`renown`/`living_weapon`, 14 passed).

### ENG-6/ENG-10: copy-of-a-copy (RULE 707.2), ENG-7: a token's own `enter_as_copy` choice, ENG-8: layer 3's second consumer (2026-07-29)

Four small, related gaps in `game/copy_mechanics.py`/`game/continuous.py`/
`game/combat.py`, closed together since ENG-6 and ENG-10 turned out to be
the same root cause described from two angles (`CopyPermanentEffect`'s
consumer view vs. the layer-1 architecture view), and ENG-7/ENG-8 are two
narrow, low-risk completions of machinery this batch was already touching.

**ENG-6/ENG-10 — copy of a copy.** `become_copy` (all three copy
mechanisms — one-shot ETB, Vesuvan-style conditional/continuous, "until end
of turn" — share it) read a copy target's copiable values off
`target._front_card` rather than `target.card`, a simplification whose real
purpose is RULE 712.4a's "always the front face" rule for a transformed
DFC. The bug: `_front_card` is set once at `GameObject.__init__` and never
updated by `become_copy` itself, so once an object *became* a copy, its own
`_front_card` still pointed at its original printed card — RULE 707.2's
"copy effects that apply to an object with already-changed copiable values
are impacted by that previous effect" was silently unmet, and a copy of an
already-copied permanent copied the pristine card underneath instead.
Fixed with one line: `become_copy` now sets `obj._front_card = obj.card`
right after the copy mutation, so a *later* copy of `obj` — by any of the
three mechanisms, via any consumer (`copy_permanent`/`copy_spell`/another
`become_copy`) — reads the current form. `snapshot_face`/`restore_face`
(used by the conditional-copy revert and the until-end-of-turn revert)
snapshot/restore `_front_card` alongside `card`, so reverting a copy also
correctly un-does this bookkeeping rather than leaving it pointed at the
now-reverted intermediate form. New tests in `test_card_structures.py`:
a `copy_permanent` of an already-copied object, a `become_copy` chained
three deep, and a revert-then-recheck of `_front_card`.

**ENG-7 — a token's own `enter_as_copy` choice.** `create_token`'s
`_build` loop built each token and fired `ENTERS_BATTLEFIELD` immediately,
never consulting `enter_as_copy_effects` — unlike `resolve_top_of_stack`'s
`_resolve_permanent_spell`, which pauses on that RULE 614.1c/614.12 choice
*before* a cast permanent joins the battlefield. A token copy of an
enter-as-copy creature (e.g. a token copy of Clever Impersonator, via
`copy_permanent`/RULE 707.2) would just enter as itself, silently skipping
its own replacement. Fixed by rewriting `_build`'s loop as a recursive
`_next(remaining)` continuation: for a battlefield-bound token, if it
carries `enter_as_copy_effects`, `_offer_enter_as_copy` is called with a
continuation that finishes battlefield entry *and* recurses to the next
token in the batch — the same continuation-passing idiom
`_resolve_permanent_spell` already uses, just generalized to resume a
multi-token loop rather than a single object. `_offer_enter_as_copy` still
calls its continuation immediately when there's no legal target (RULE
603.3c-style), so the common case — no card in the pool combines "create N
token copies" with a second legal target at creation time — still
completes the whole batch synchronously, unchanged from before. When a real
choice does open, `create_token` returns `[]` right away (same documented
contract a RULE 616.1 token-doubling choice already uses) and the rest of
the batch resumes from `resolve_enter_as_copy_choice`. `enter_choice_effects`
(RULE 601.2b "as ~ enters, choose a creature type/color") stays an
acknowledged, unexercised gap — no real card in the pool ever puts that
ability on a token. New tests in `test_tokens.py` cover the choice opening,
declining it, the no-legal-target no-pause case, and a 2-token batch where
resolving the first token's choice must still build the second.

**ENG-8 — layer 3's second consumer.** RULE 612's word-substitution over
`GameObject.effective_oracle_text` was read by exactly one function,
`combat.protections_of_text` — every other oracle-text-derived quality read
`obj.card.oracle_text` directly, so a layer-3 "text_change" static ability
only ever flipped a permanent's protection, never anything else scanned the
same way. `combat._landwalk_slugs` (RULE 702.14's `<type>walk` parametric
keyword, recognized by regex over oracle text exactly like protection is)
was the one other real candidate — same treatment, same non-goal of a full
re-parse (bound abilities/keywords still come from the printed text once at
bind time, unaffected either way). One-line fix: `_landwalk_slugs` now
scans `obj.effective_oracle_text` instead of `obj.card.oracle_text`. New
test in `test_continuous.py`: an "Islandwalk" → "Swampwalk" layer-3
substitution (matched as one templated word, per RULE 702.14's official
"Islandwalk" — no space — rather than a bare colour word) flips
`landwalk_subtypes` the same way the existing protection test flips
`is_protected_from`.

Full suite green (2,807 passed, 238 skipped, +8 from this batch).

### ENG-9, ENG-11, ENG-13, ENG-14 (2026-07-29)

Four more closed off `BACKLOG.md`'s ENG section, closing it out entirely for
now (nothing left under "Game engine").

**ENG-9 — RULE 613.8 dependency ordering, re-verified rather than
extended.** The ticket's own condition for doing any work at all was "extend
if a selector ever reads another object's *derived* state" outside layer
2 — so before touching `continuous._order_control_effects`, that condition
was re-checked against everything the engine has grown since it was
written. Two selectors looked like candidates on a first read —
`group_selector_objects`'s `min_power`/`max_power`/`power_lt_selector`/
`power_gt_selector` — but both are consumed exclusively by
`combat_restriction`/`goaded` statics, which `_apply_post_layer_combat_
restrictions_and_goad` stamps strictly *after* the whole layer-7 pass
finishes (the same ordering the "Combat statics" batch fixed for exactly
this reason — see that section above). They're downstream consumers of
finished layer-7 output, not a same-sublayer ordering dependency, so the
ticket's premise still doesn't hold anywhere in the current effect
vocabulary. No code changed; `tests/test_eng_batch_9_11_13_14.py::
test_power_threshold_selector_sees_same_pass_anthem` pins the finding down
as a regression test (an anthem and a goad power-qualifier applying in the
same recompute must still compose correctly) so the next batch that adds a
selector doesn't have to re-derive this proof from scratch — it can just
check whether the new selector breaks that test.

**ENG-11 — a granted trigger now fails closed without an identity key.**
`continuous._granted_trigger_condition` scopes a layer-6 "X have '…'"
grant per-grantee off the firing event's own subject key
(`_GRANTED_EVENT_KEYS`, `instance_id` by default). Previously, an event
carrying *no* matching key wasn't filtered at all — correct for the one
real subject-less case (a `STEP_BEGIN` phase-trigger grant, scoped by
`phase_relation`/whose turn it is instead of identity) but silently wrong
for anything else: a future `trigger_event` whose payload shape never got
added to `_GRANTED_EVENT_KEYS` would fire for *every* object under the
grant, not just the one the event was actually about. Now fails closed —
mirroring `effect_binder._subject_condition`'s existing "missing
`instance_id` → `False`" rule for the ordinary (non-granted) `{"subject":
"self"}` case, which already documented exactly this reasoning ("the
over-firing bug this grammar exists to close"). `STEP_BEGIN` grants are
unaffected (still scoped by `phase_relation`, not identity). The parser
front-end (`static_handlers._quoted_ability_grant_effects`) already only
ever emits a non-`STEP_BEGIN` grant for a `{"subject": "self"}` trigger,
itself only reachable for events `_TRIGGER_VERBS` has matched to a verb
whose event *does* carry an identity key — so this is a safety net against
a future hand-authored `ability_catalogue.py` entry, not a path any
shipped card exercises. Tests: `test_granted_trigger_condition_fails_
closed_on_unregistered_event_shape`, plus regression coverage that an
ordinary keyed grant (Dionus's shape) and a `STEP_BEGIN` grant both still
behave exactly as before.

**ENG-13 — a per-firing dynamic reference generalizes to granted
abilities.** `GameContext.trigger_event` (built for the cEDH-cube batch,
"the mana a permanent just produced… which player cast the spell…") was
already general enough for an *ordinary* printed trigger's own per-firing
"it" pronoun — `ReturnSharedTypePermanentEffect` (Cloudstone Curio) already
read it. What was missing was demonstrating the same field on a *granted*
ability's own resolution, since `_place_trigger`/`StackItem.trigger_event`
never distinguished the two paths in the first place — turned out to need
no engine change at all, just two bespoke effect classes following this
file's standing "build a fresh per-firing shape rather than new IR" rule
(`TriggeredAbility`'s own docstring):

- `ExileTriggerDamagedCreatureEffect` — Kaldra Compleat's granted "Whenever
  this creature deals combat damage to a creature, exile that creature."
  RULE 603.3d's "that creature" is the `DAMAGE` event's own `target_id`, a
  *different* field from the `source_id` `_GRANTED_EVENT_KEYS` already uses
  to scope *which* grantee reacts (the equipped creature that dealt the
  damage). `ability_catalogue._kaldra_compleat` now grants it via the
  ordinary `grant_triggered_ability` machinery, `filter: {"combat": True,
  "is_player": False}` narrowing to combat damage dealt to a creature.
- `AttachTriggeringPermanentEffect` — Sigarda's Aid's "Whenever an
  Equipment you control enters, you may attach it to target creature you
  control." RULE 603.3d's "it" here is a **group**-subject trigger's own
  matched member (the entering Equipment), read off `GameContext.
  trigger_event`'s `instance_id` — not the ability's source (Sigarda's Aid
  itself, unlike plain `AttachEffect`) and not a chosen target (unlike
  `CreateTokenMayAttachEquipmentEffect`'s equipment-onto-a-just-created-
  token shape). Only the destination is a real RULE 115 target; declining
  it declines the whole attach, the same `target_spec.optional=True` idiom
  those two siblings already use rather than a separate `AbilitySpec.
  optional` flag. Registered as a new (partial) `ability_catalogue.
  _sigardas_aid` entry — only this second ability is modeled; the first
  ("cast Aura/Equipment spells as though they had flash") needs a standing,
  card-type-scoped flash permission distinct from the existing one-shot
  `grant_flash_until_eot`, a documented gap unrelated to ENG-13. Coverage:
  +1 card (hand-authored, no parser handler — `PARSER_VERSION` unchanged).

Tests: `test_kaldra_compleat_exiles_the_damaged_creature`, `test_kaldra_
compleat_does_not_exile_on_player_damage` (the `is_player` guard),
`test_sigardas_aid_attaches_the_entering_equipment_to_chosen_target`.

**ENG-14 — Simian Sling's "defending player" now sees through
Reconfigure.** `effects._defending_player_of` (annihilator/afflict's shared
"defending player" resolver, RULE 506.4) read only its own `source`'s
`combat_defender` stamp — correct when the ability's source is itself the
attacker, wrong the moment Reconfigure moves it onto a *different*
attacking creature: Simian Sling's own trigger already fires correctly off
a `self_or_attached_permanent` subject ("this creature or equipped
creature becomes blocked"), but the payoff effect's `_defending_player_of`
call still only ever checked Simian Sling's own (never-attacking, once
reconfigured) `combat_defender`, finding nobody. Now falls back to the
object `source` is `attached_to` before giving up — the same self-or-host
pair the trigger condition already scoped by. Every existing caller
(annihilator, afflict — always the attacking creature itself, never an
attached permanent) sees no behavior change: `attached_to` is unset for
them, so the fallback is a no-op. Test: `test_simian_sling_hits_defending_
player_when_reconfigured_elsewhere` — Simian Sling reconfigured onto a
different creature, that creature attacks and is blocked, the opponent
takes the 1 damage.

Full suite green (2,815 passed, 238 skipped, +8 from this batch — the new
`test_eng_batch_9_11_13_14.py`).

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
- [x] Multiplayer priority primitive (RULE 117.3-4/APNAP, UC4 groundwork):
      `GameEngine.pass_priority` now takes an optional `player` — called
      with one, it only resolves the top of the stack once every living
      player has passed in succession, otherwise hands priority to the
      next player (APNAP, `_advance_priority`); any real action reclaims
      priority (`give_priority`, called from `begin_turn`/`_run_step`/
      `play_land`/`cast_spell`/`activate_ability`). `GameState.
      priority_passed` tracks who has passed and deep-copies for rewind.
      Called with no `player` it keeps the old solo/goldfish auto-resolve,
      so nothing regresses. The session/route wiring to actually *drive*
      this (`GameSessionManager.create_multiplayer`, `POST /api/game/
      multiplayer`) and the opponent-side interactive blocker-declaration
      UI remain — see `docs/implementation-state/BACKLOG.md` "Game Engine (Phase 3)".
      Tests: `test_priority.py`.
- [x] Dethrone (RULE 702.107, 2026-07-21): "Whenever this creature attacks
      the player with the most life or tied for most life, put a +1/+1
      counter on it." Built as `RulesEngine.check_dethrone`, called from
      `GameEngine.declare_attackers` right where `ATTACKS` fires — a
      per-firing procedural check (like `check_rampage`/`check_ward`)
      rather than a bind-on-load `TriggeredAbility`, since `combat.has`
      needs to be read fresh at the moment of attack: Dethrone isn't only
      ever printed on the attacker, it's also grantable to "other
      creatures you control" by a layer-6 static (Marchesa, the Black
      Rose) that never runs the bind-on-load machinery on those other
      creatures. `check_dethrone` resolves the defending *player* off
      `attacker.combat_defender` — for a planeswalker/battle attack this
      is that permanent's controller, not the permanent itself (a real
      ruling: Dethrone cares about the defending player's life regardless
      of what's actually being attacked) — then compares their life
      against `GameState.living_players()`'s max. "dethrone" was also
      added to `combat.COMBAT_KEYWORDS` so `combat.keywords_of`/`combat.
      has` recognize a card's own printed keyword directly, the same as
      any other evasion/combat-math keyword. Marchesa, the Black Rose's
      "Other creatures you control have dethrone." (her other two clauses
      — her own printed Dethrone needing no hand-authoring, and the RULE
      603.7 delayed-return trigger — were already hand-authored,
      `game/ability_catalogue.py`'s `_marchesa_the_black_rose`) is now a
      plain layer-6 `grant_keyword` static (`affects: "other_creatures_
      you_control", keywords: ["dethrone"]`) — the same generic mechanism
      other keyword grants use, needing no Dethrone-specific plumbing on
      the grant side. Tests: `test_dethrone.py`.
- [x] ENG-17: shared `_resolve_pool_cost` helper (2026-07-29) — pure
      consolidation, part of the same God-class refactor as [ENG-16].
      `_resolve_tap_others` and `_resolve_discard_cost` each independently
      implemented the identical RULE 602.1 "choose N from a pool" logic
      (auto-pick the first N when `chosen_ids` is `None`, else validate
      `chosen_ids` names exactly N distinct eligible objects and look them
      up). Extracted one `_resolve_pool_cost(pool, count, chosen_ids)`
      static helper both now call with their own pool
      (`_tap_others_pool`/`_discard_cost_pool`). `_sacrifice_candidate`/
      `_return_to_hand_candidate` were checked and don't fit — they're a
      single-object first-match-or-`chosen_id` shape, not a "choose N"
      pool, and sacrifice additionally has a `"self"` special case with no
      analogue here. Full suite green (2,797 passed, 238 skipped).
- [x] ENG-20: `game_engine.py` split into per-responsibility mixins
      (2026-07-29) — the reorganization half of the God-class refactor
      ([ENG-16]-[ENG-19] were the consolidation half, done first so there
      was less duplicated code to move). The single 4,702-line `GameEngine`
      class (~130 methods) is now composed from eight mixins under a new
      `game/engine/` subpackage — `turn_loop_mixin.py` (incl. `new_game`),
      `combat_mixin.py`, `casting_mixin.py`, `lands_mixin.py`,
      `activation_mixin.py`, `mana_mixin.py`, `legal_actions_mixin.py`,
      `misc_mixin.py` — with `game_engine.py` itself shrunk to `__init__` +
      the `class GameEngine(TurnLoopMixin, CombatMixin, ...)` composition
      (73 lines). Mixins, not delegation to sub-objects, because every
      method reads/writes the same `self.state`/`self.rules` instance
      state and ~100 test files plus `services/game_session.py`/
      `services/replay.py` call methods on `GameEngine` directly by name —
      a mixin split changes zero method names/signatures, so none of those
      callers needed touching. Extracted mechanically via a small one-off
      script using `ast` to get exact method boundaries (incl. leading
      comment blocks) rather than hand-copying ~130 methods; each mixin
      file carries its own copy of the original file's whole import block
      (simplest way to guarantee nothing's missing, at the cost of ~400
      lines of harmless duplication across 8 files) with relative imports
      bumped one `.` level for the new subpackage depth — caught one
      function-scoped `from . import copy_mechanics` the same bump had to
      apply to (`turn_loop_mixin.py`'s `_step_cleanup`), which a plain
      header-only fix would have missed. `_COMBAT_CONDITIONS` (the only
      class-level, non-method attribute) moved into `combat_mixin.py`
      alongside `_combat_condition_met`, its only reader. Also folded in
      `legal_actions`'s five near-identical per-zone cast-offer blocks
      (hand/command/exile/graveyard/library-top) into one
      `_offer_cast(actions, player, obj)` helper on
      `LegalActionsMixin`. Verified with the full suite (2,797 passed, 238
      skipped, unchanged) plus the opt-in `--full-cache` suite (its 4
      failures reproduce identically on unmodified `HEAD`, confirmed by
      stashing and re-running — pre-existing, not caused by this split),
      `python -c "import mtg_analyzer.api.app"`, and `engine_bench.py`'s
      `play`/`combat` commands against a real `GameEngine` (Lightning Bolt
      killing a Hill Giant, a real declare-attackers/blockers/damage
      sequence).
- [x] ENG-23: `GameSession._dispatch` table-driven dispatch (2026-07-29) —
      the last God-class-refactor phase outside the parser tail (`ENG-25`
      remains, lowest priority). The 264-line if/elif chain over
      `action["type"]` (`services/game_session.py`) is now ~15 lines: the
      cross-cutting guards that ran before any per-kind branching (replay
      board-editing passthrough, the mulligan/setup-phase gate, the
      pending-choice gate, the RULE 117.1 priority gate, and the shared
      advance/auto_turn precondition — all of which read `kind` to decide
      whether to short-circuit *multiple* kinds at once, so they aren't
      "dispatch" in the per-kind sense) stayed inline in `_dispatch` in
      their original order; everything that *was* one `if kind == "X":
      ...; return` arm became its own `_dispatch_<kind>` method, looked up
      through a `_ACTION_HANDLERS: dict[str, Callable]` class attribute —
      same registry-over-if/elif pattern `EffectRegistry` already uses,
      built from plain (not-yet-bound) method references at class-body
      time and called as `handler(self, action, active)`. `"choose"`/
      `"decline"` share one handler (`_dispatch_choose`, which already
      branched on the literal action type for its answer value) and
      `"attack"`/`"declare_attackers"` share another
      (`_dispatch_declare_attackers`), matching the original two-kinds-one-
      branch shape. `_dispatch_declare_blockers` gained one line
      (`state = self.engine.state`) since it was the only handler reading
      the enclosing method's local `state` — every other handler already
      only touched `self.engine`/`self._*` helpers. Handler bodies are
      otherwise byte-identical to their original inline arms. Verified
      with the full suite (2,797 passed, 238 skipped, unchanged),
      `--full-cache` (same 4 pre-existing failures as [ENG-20]'s
      verification — a 5th, `test_a_planechase_game_starts_with_a_face_up_
      plane`, failed on one run and passed on immediate rerun and in
      isolation, an existing order-dependent flake rather than anything
      this change touches), and every `game_session`/`multiplayer`/
      `priority`-named test explicitly (195 passed).

## Card-type & structural coverage

- [x] **Battles (RULE 310)** — the whole card type, from zero scaffolding:
      `Card.defense`/`is_battle`/`is_siege`, `GameObject.defense`/
      `protector_id`, attacking, the protector, and the Siege
      defeat/transform cycle. Tests: `test_battles.py` (27).

      **Defense as counters, not a stat.** A battle enters with defense
      counters equal to its printed defense (310.4b) and its *current*
      defense simply is that count (310.4c), so there is no second field to
      drift. Seeded in `GameState.add_to_battlefield` right beside a
      planeswalker's starting loyalty rather than in `RulesEngine.
      _apply_entry_counters` (where the ToDo had predicted it): that method
      reads *oracle text*, and no battle prints an "enters with N defense
      counters" sentence — the printed number is the rule. Seeding at the
      universal entry choke point also means a battle reanimated or dropped
      in by the Replay editor gets its counters, not just a cast one.
      `RulesEngine.deal_damage` grew a `is_battle` branch beside the
      planeswalker one (310.6); it is deliberately *not* gated on combat, so
      a burn spell chips a battle exactly like an attacker does.

      **`Card.defense` forced a cache reseed.** Scryfall carries `defense`
      per-face (top-level only for the single-faced ones), and it had never
      been captured, so every cached battle read back as `defense=None`.
      Adding the field changed the `Card` schema hash, which is what
      `CardDatabase._reconcile_schema` wipes the app cache on — the
      documented cost of a model change. `scripts/import_bulk.py
      --reseed-only` rebuilt all 34,258 rows from the durable `RawCardStore`
      with no network, and because `card_from_scryfall_data` now parses the
      field, that reseed populated it in the same pass. Worth knowing for
      the next `Card` field: a targeted backfill script is never the right
      answer, since the wipe is all-or-nothing anyway.

      **Defeat is noticed by the SBA pass, not at a counter-removal site.**
      RULE 310.11b is a *triggered* ability ("when the last defense counter
      is removed…"), but hooking it into `deal_damage` would miss every
      other route to zero. `check_state_based_actions` instead notices the
      transition and places the trigger directly on the stack (the
      `check_ward`/`check_rampage` precedent for a per-firing ability), with
      a `GameObject.battle_defeat_triggered` latch so the repeated SBA loop
      can't re-fire it. RULE 310.7's graveyard move then sits *after* it and
      skips any battle that is the source of something still on the stack —
      structurally the same check the Saga sacrifice already used, and what
      lets a defeated Siege survive long enough for its own ability to exile
      it instead. `exile_siege_for_transformed_cast` does the exile as a real
      RULE 400.7 zone change, flips the new object onto its back face, and
      reuses `grant_free_cast_window_from_exile` (Rebound's/Beseech the
      Mirror's window) so the transformed card is castable for free through
      the ordinary action loop. Known simplification: that window lasts the
      rest of the turn, whereas 310.11b's is strictly during resolution.

      **The protector is a genuinely new per-object field.** `protector_id`
      is not `controller_id`: it is the "defending player" for attacks
      against the battle (310.8d) and the only player who may block for it
      (310.8c), which is exactly why a Siege can be attacked by its own
      controller (310.8b). Chosen as it enters via `_offer_protector_choice`,
      a new stage in the same pre-entry continuation pipeline as
      enter-as-copy / choose-a-type / Read Ahead; it only *asks* when 2+
      players are eligible, and with exactly one it assigns silently
      (310.8a is mandatory, and an unprotected battle would be swept up by
      310.10). The blocker half needed no new check at all —
      `_attacker_attacks_player` now routes through `_defending_player`,
      which substitutes the protector for a battle, so every existing
      "who is the defending player" consumer (block legality, "can't attack
      unless defending player controls…", Dethrone) got it at once.

      **Attacking** rode the existing generic defender-spec pattern as the
      ToDo predicted: a third `"battle"` kind in `legal_defenders_for` /
      `_defender_spec` / `_resolve_combat_defender`. Damage routing needed
      no branch there, since `deal_damage` decides off the target object's
      own type. Also closed: 310.9 (a battle can't be attached to — the
      equip/reconfigure paths already required a creature, so this only
      needed to stop a broadly-worded Aura) and 310.10 (a battle with no
      valid protector gets a fresh one, or goes to the graveyard if no
      player qualifies — which is what makes a Siege correctly unplayable
      in a solo goldfish, where its controller has no opponents).

      **Frontend**: a defense badge on the board tile mirroring the
      loyalty/Saga badges (`gf-battle-badge`, showing `🛡 N · <protector>`),
      "defense" filtered out of the generic counter badge so it isn't shown
      twice, and a real bug fix in `defenderPayload` — it branched on
      `kind === 'planeswalker'` and would have mis-sent a battle as a
      player, so it now branches on which key the spec carries.

      **Parser**: 0 → 12 of the 39 cached battles MODELED, almost all of it
      from one line — `normalize._SELF_REFERENCE_RE` folding "this
      battle"/"this Siege" to `~`, without which every real battle failed
      the gate on its own ETB clause. (RULE 310's reminder text was already
      being stripped.) Three shared-grammar widenings the battles motivated
      but that aren't battle-specific came with it: RULE 115.4's "any
      **other** target" (onto the existing `any` kind, whose candidate list
      already excludes the source, so the two are genuinely equivalent here);
      "target creature an opponent controls"/"…you don't control" onto the
      existing `creature_you_dont_control` kind, with `_pump_target` widened
      to accept the controller-scoped creature kinds; and the discard handler
      gaining "target opponent"/"each player"/"each opponent" subjects. That
      last one exposed a latent bug: `_discard` never passed a `target_kind`
      through, so "target player discards a card" had been making the
      *source's controller* discard. `PARSER_VERSION` → 34. The remaining 27
      battles are blocked on ordinary effect-body grammar, itemized in
      `docs/implementation-state/BACKLOG.md`.

- [x] Saga chapter abilities (RULE 714.2d) — the counter mechanics
      (lore-counter-on-ETB/draw-step, final-chapter sacrifice) already
      existed; the chapter *effects* now actually resolve. A shared, pure
      roman-numeral grammar (`parser/oracle/catalogue/saga.py`:
      `CHAPTER_LINE_RE`/`parse_chapter_token`/`all_chapter_numbers`) is used
      both by `segmenter.segment_line`'s new chapter-line branch (gated on a
      new `is_saga` flag threaded from `gate.parse_oracle`, so the shape
      can't misfire on a non-Saga card) and by `rules_engine._saga_final_
      chapter` (no longer a separate duplicated regex). A chapter line
      ("i, ii — some effect") becomes an ordinary `triggered` `AbilitySpec`
      (`trigger={"event": "SAGA_CHAPTER", "chapter": [1, 2]}`) whose effect
      body runs through the *existing* one-shot handler table unchanged.
      `GameState.add_to_battlefield` (the initial chapter-I lore counter) and
      `RulesEngine.advance_sagas` (each subsequent one) both fire the new
      `EventType.SAGA_CHAPTER` (carrying `instance_id` + `chapter`, the same
      self-scoping convention `continuous._granted_trigger_condition` already
      uses); `effect_binder.bind_ability` builds the matching `condition`
      closure so a chapter ability fires only for its own Saga at its own
      number(s). Chapters then flow through the ordinary triggered-ability
      pipeline (targets/"you may"/interactive ordering all work for free).
      Needed a **group ("creatures you control") one-shot pump** alongside
      this, since that's the common Saga-chapter-III/anthem-spell shape
      (e.g. History of Benalia) the single-target `pump` handler couldn't
      express: `continuous.affected_objects`'s selector vocabulary
      (creatures/other-creatures/permanents/lands-you-control, subtype/
      colour/tokens/exclude-self filters) was extracted into a pure
      `group_selector_objects(state, controller_id, affects, params, src)`
      helper reused by both the static-anthem path and a new
      `PumpEffect.selector` (function-scoped import to dodge the
      `effects.py`↔`continuous.py` cycle); `handlers.py`'s `_SUBJECT`
      grammar gained a `creatures you control`/`other creatures you control`
      alternative alongside `TARGET`/`~`. Tests: `test_card_structures.py`,
      `test_oracle_pipeline.py`.
- [x] Saga (RULE 714) residual edges, closed in one pass: the lore counter
      was being added off the draw step, not RULE 714.3c's actual timing
      ("as a player's precombat main phase begins") — fixed by moving
      `RulesEngine.advance_sagas` from `GameEngine._step_draw` to a new
      `_step_main1`; the RULE 704.5x/714.4 sacrifice check was keying off
      "is the whole stack empty", so an unrelated spell/ability sitting on
      the stack (an opponent's instant, another permanent's trigger) wrongly
      delayed a finished Saga's sacrifice — narrowed to check specifically
      whether *this Saga's own* chapter trigger (`StackItem.source is obj`
      and `trigger_event.type == SAGA_CHAPTER`) is what's still on the stack;
      and **Read Ahead** (RULE 702.155/714.3b — recognized as a flag keyword
      already, never bound to behaviour) is now real: `RulesEngine.
      _offer_read_ahead` offers a `read_ahead` `pending_choice` ("choose a
      number from 1 to this Saga's final chapter number") in the same
      continuation-passing entry-choice chain as `_offer_enter_as_copy`/
      `_offer_enter_choices`, right before the object joins the battlefield;
      `resolve_read_ahead_choice` stashes the answer for `_resolve_permanent_
      spell`'s `_finish` to pass straight to `GameState.add_to_battlefield`'s
      new `saga_lore_override` param. RULE 702.155a is the subtle part: only
      the chapter matching the chosen count *exactly* fires — every lower
      chapter is **skipped for good, not delayed** — so this replaces the
      ordinary single-counter/chapter-1 entry path outright rather than
      layering extra firings on top of it (an earlier draft of this that
      fired chapters 1..N in sequence was wrong and got corrected before
      shipping). Frontend: a dedicated Saga chapter badge (`gameBoardView.js`
      — "📜 current/final", mirroring the planeswalker loyalty badge and,
      like it, pulled out of the generic counter badge) reading two new
      `GameObject.to_dict` fields (`is_saga`, `saga_final_chapter` — the
      latter via a small `models/game_object.py` helper sharing the pure
      `parser/oracle/catalogue/saga.py` numeral grammar); the `read_ahead`
      choice renders through the fully generic `pending_choice`/
      `simpleChoiceButtonsHtml` machinery, so only a `CHOICE_ICONS` entry was
      needed. Verified end-to-end in a live Replay/Puzzle session (casting a
      real cached Read-Ahead Saga, "Founding the Third Path") — the choice
      modal and the resulting chapter badge both render correctly. Tests:
      `test_card_structures.py`.
- [x] Class (RULE 716) + Leveler (RULE 711) — both print a multi-line
      **block** structure ordinary per-line segmentation can't see across:
      Leveler's `LEVEL n-m`/`LEVEL n+` tiers (mutually exclusive P/T/keyword/
      triggered-ability alternatives to the base printed text) and Class's
      sequential `Level N: <cost>` levels (cumulative — once unlocked,
      always active). New `Card.is_class`/`is_leveler` derived properties and
      `GameObject.level`/`class_level` counter properties (mirroring
      `is_saga`/`lore` exactly); a Class enters at `class_level = 1`
      (`GameState.add_to_battlefield`, RULE 716.2b) firing a new
      `EventType.CLASS_LEVEL` the same way Saga's chapter-1 does.
      `parser/oracle/catalogue/levels.py` (new, pure, mirrors `saga.py`) owns
      the header grammar (`LEVEL_TIER_RE`/`CLASS_LEVEL_RE`/`LEVEL_UP_LINE_RE`)
      and the block splitters `split_leveler_blocks`/`split_class_blocks`;
      `gate.parse_oracle` threads `is_leveler`/`is_class` (mirroring the
      existing `is_saga` flag) and, for either, splits the normalized text
      into a preamble plus blocks, running each body line through the
      *existing* per-line dispatch (`segment_line`/`static_effect_specs`/
      `parse_effect_body` — no changes there) and then tagging the resulting
      spec's params (a static effect) or trigger dict (a triggered ability)
      with the block's level gate. Note "Level Up" is itself a registered
      RULE 702.87 keyword (a COST shape, like Kicker) that the generic
      catalogue already claimed — like Kicker, nothing consumed it into
      actual behaviour, so `LEVEL_UP_LINE_RE` recognizes the line directly
      and synthesizes the real "put a level counter on this, sorcery speed
      only" `activated` spec (reusing the existing generic `add_counters`
      effect with `kind="level"` — no new effect needed there); a Class
      level's own header has no effect body to segment (the effect is
      "become this level"), so it synthesizes a new `class_level` one-shot
      `EffectSpec`/`ClassLevelEffect` (`game/effects.py`) instead — sets
      `class_level` directly (never incremented) and fires `CLASS_LEVEL`
      with the *same* `chapter` trigger key Saga's chapter triggers use, so
      a rare "when this Class becomes level N" trigger needs no new binder
      code.

      The genuinely new engine primitive both mechanics needed — RULE 613.6
      "as long as" conditional statics, which nothing modeled before this
      (the closest precedent, `affects="attached_permanent"`, just
      re-derives its object list fresh every `continuous.recompute` pass
      rather than gating on a condition) — is a `min_level`/`max_level`/
      `level_counter` triple added to `effects._SELECTOR_KEYS` (so it flows
      through every static factory that already spreads `**_selectors(p)`
      with zero further changes to those factories) and consumed as a final
      source-gate in `continuous.group_selector_objects`: it checks the
      ability's own **source** object's counter (correct for both Leveler,
      where `affects="self"`, and Class, where `affects` targets other
      permanents but the *condition* is still about the Class's own
      `class_level`), returning `[]` (inactive) exactly like
      `attached_permanent`'s "empty list while unattached" shape. The same
      gate exists for a *triggered* ability (a Leveler tier's own trigger,
      e.g. Kargan Dragonlord's attack-pump restricted to `LEVEL 2-6`) via
      `effect_binder._trigger_condition`, restructured from "return early
      after the `chapter` check" into composable predicates so `chapter` and
      `min_level`/`max_level` can each apply independently or together.

      Activation legality: RULE 711.4b (Leveler, sorcery speed, no cap) and
      RULE 716.4c (Class, sorcery speed, legal only from the level just
      below) both needed a **sorcery-speed timing gate that isn't tied to a
      planeswalker** — `game/costs.py`'s `ActivationCost` gained
      `sorcery_speed_only`/`class_level` fields (legality preconditions
      riding along with the cost record, not things paid — putting the
      counter on/becoming the level is the ability's *effect*, resolved off
      the stack, not part of paying for it); `GameEngine._can_activate_
      loyalty`'s timing body was split out into a reusable `_sorcery_speed_
      ok(player)` (now shared by loyalty and the new flag) plus a new
      `_can_activate_class_level(source, target_level)`.

      Fixed along the way: **Scryfall's `keywords` array and a card's
      `oracle_text` both cover a Leveler's *whole* printed text, tier or
      not** — Kargan Dragonlord's "Flying, haste" is only printed under
      `LEVEL 7+`, but both `catalogue.keywords.parse_keywords` (the intrinsic-
      keyword bind) and `combat.keywords_of` (the independent combat-facing
      keyword reader) would otherwise treat it as always-on. Both now
      cross-check against `levels.leveler_base_text` (the raw-text prefix
      before the first `LEVEL` line) for a Leveler card, the same "oracle
      text is ground truth" pattern already used for Enchant/Daybound —
      dropping a tier-only keyword from the always-on set, since it's
      re-granted, correctly level-gated, by the block-tagged `grant_keyword`
      spec instead. Tests: `test_card_structures.py` (end-to-end: level-up
      sorcery-speed gating, tier P/T + keyword + triggered-ability gating,
      Class level-ordering + cumulative grants), `test_oracle_pipeline.py`
      (coverage-gate + spec-shape assertions).
- [x] Class (RULE 716) / Leveler (RULE 711) residual edges, closed: **"When
      this Class becomes level N, `<effect>`."** (RULE 716.4c-adjacent —
      Wizard Class/Cleric Class/Warlock Class/…-shaped) was silently
      failing every Class card that used it, since it has its own trigger
      wrapper the generic per-line dispatch never recognized — a new
      `CLASS_BECOMES_LEVEL_RE` (`parser/oracle/catalogue/levels.py`,
      mirroring Saga's `CHAPTER_LINE_RE`) is checked first in
      `gate._process_class_body`, producing an ordinary `triggered` spec
      (`trigger={"event": "CLASS_LEVEL", "chapter": [n]}`) that reuses
      `ClassLevelEffect`'s existing firing and `effect_binder`'s existing
      `chapter` scoping unchanged — genuinely a one-shot (RULE 716.4c: fires
      once, at the exact moment `class_level` becomes `n`), not the
      ordinary "stays active once unlocked" shape every other body line is,
      confirmed by a new test asserting it doesn't re-fire once `class_level`
      later reads higher. Found and fixed the same pass: **"When this Class
      enters, `<effect>`."** (Ranger Class/Fighter Class/Blacksmith's
      Talent/…-shaped) was *also* silently failing — `normalize.py`'s
      self-reference folding deliberately excludes "this Class"/"this Saga"
      (its own docstring notes they have "their own dedicated parsing," which
      for Class turned out not to exist yet), so `segmenter._SELF_SUBJECT_RE`
      never matched it either. Added `"class"` to that regex's type-word
      list (not `"saga"` — real Saga cards never print this phrasing outside
      stripped reminder text, chapter I already covers it). Together these
      two fixes newly recognize the ETB/becomes-level lines on a dozen-plus
      real cached cards, though most still have one *other*, unrelated
      unclaimed line (general trigger/effect coverage — explicitly
      out of scope for this batch) so don't all flip to `MODELED` outright.
      `PARSER_VERSION` bumped to `"33"`.

      The other two named residuals turned out to already be non-issues:
      a Leveler's non-keyword *base* (pre-`LEVEL`) ability line already goes
      through the same unconditional per-line dispatch a Class's preamble
      does (RULE 711.4's "treated normally" — no level gate applied), which
      a new test now locks in explicitly (an anthem printed before the first
      `LEVEL` tier stays active at every level, including well past the
      card's own tiers). CDA-based Leveler P/T (``*/*``) is left
      deliberately unimplemented rather than merely deferred: `game/
      continuous.py`'s layer-7a `pt_cda` pass already exists and could gate
      the same `min_level`/`max_level` way `pt_set` does, but there is no
      real printed Leveler tier anywhere in the ~34k-card Oracle cache to
      derive the CDA's count selector from — wiring it now would mean
      guessing exactly what docs/09's fail-closed discipline forbids.
      Tests: `test_card_structures.py`.
- [x] DFC transform infrastructure (RULE 712.8) + day/night (RULE 731) +
      daybound/nightbound (RULE 702.145) — `GameObject.transform()` only
      ever flipped `card`; nothing in the live engine called it, and nothing
      rebound the new face's catalogue-derived abilities/keywords (the same
      bug `switch_to_face`, modal-DFC casting, already solved). New
      `RulesEngine.transform_permanent(obj)` is the fix, reusing
      `switch_to_face`'s "clear + rebind via `bind_from_catalogue`" pattern;
      `services/game_session.py`'s `edit_transform` puzzle-mode action and
      `services/replay.py`'s deserializer (which bound abilities *before*
      transforming — backwards) both now go through it/its ordering. A new
      `transform` one-shot `GameEffect` (`EffectRegistry`) plus a
      `parser/oracle/catalogue/handlers.py` clause ("transform ~"/"it"/
      "this permanent"/"this creature") makes a loyalty "[0]: Transform ~."
      or "whenever ~ attacks, transform it." fully modeled with no
      hand-authoring, by slotting into the existing trigger/activated/
      loyalty grammar. RULE 731 day/night is new `GameState` fields
      (`day_night`, `spells_cast_this_turn`, `_last_turn_player_id/_spell_
      count`) + `RulesEngine._track_spell_cast` (a second `SPELL_CAST`
      subscriber, covering both paid and free casts from one place) +
      `apply_day_night_turn_check` (RULE 731.2a/2b, called from
      `game_engine._step_untap` — "the second part of the untap step" —
      after `begin_turn` captures the outgoing player's final count) +
      `_check_day_night` (RULE 702.145c/d/f/g's "any time" checked at
      `_sba_pass` cadence, the same simplification already used for the
      Saga-sacrifice check). Daybound/Nightbound recognition itself needed
      one more fix: `parse_keywords` is anchored on Scryfall's `keywords`
      array, but `Card.back_face()` never carries a separate array for the
      back face, so a DFC's *current* face's own `oracle_text` is the only
      reliable signal for which of the (mutually exclusive, opposite-face)
      pair applies — added the same kind of oracle-text cross-check
      `parse_keywords` already does for "Enchant". Tests:
      `test_card_structures.py`, `test_keyword_catalogue.py`.
      Deliberately out of scope: the legacy pre-2021 non-daybound werewolf
      template ("at the beginning of each upkeep, if no spells were cast
      last turn, transform ~") — a different, per-card grammar RULE 731
      superseded; and bespoke conditional transforms (Delver of Secrets'
      "look at the top card… if instant/sorcery, transform") — a genuinely
      new "reveal + conditional" one-shot family, not needed to prove this
      feature works.

- [x] Adventure (RULE 715) and Split/Fuse (RULE 709) cards: both now
      actually castable, not just structurally recognised. The MDFC
      back-face casting machinery (RULE 712.10 above) generalizes almost
      unchanged — `Card.back_face()`'s `back_*` capture, previously gated
      to `_TWO_IMAGE_LAYOUTS`, now also runs for `"split"`/`"adventure"`
      (`scryfall_client._SECOND_FACE_LAYOUTS`); their `card_faces` entries
      just lack their own `image_uris` (shared card image), so
      `has_back_face` stays correctly `False`. `GameEngine._face_card`/
      `can_cast`/`cast_spell`/`_cast_action`/`legal_actions`'s `face`
      parameter is generalized from two literals (`"front"`/`"back"`) to
      three (`"front"`/`"back"`/`"fuse"`), reusing `RulesEngine.
      snapshot_face`/`switch_to_face`/`restore_face` unchanged — a split
      card's other half or an Adventure's instant/sorcery half is just
      another `back_face()`. Adventure's one genuinely new piece (RULE
      715.3d): `GameObject.adventure_snapshot`/`adventure_castable` stash
      the creature's pre-cast face snapshot from cast-time through
      resolution — `RulesEngine.resolve_top_of_stack`'s non-permanent-spell
      branch restores it and calls `self.exile(obj)` instead of the
      graveyard, and `cast_spell`'s zone-removal generalized from a
      hand/command-only hardcode to the existing zone-agnostic
      `_remove_from_current_zone` so casting the creature back out of
      exile needs no dedicated branch. Fuse (RULE 709.4) needed no new
      dual-binding architecture: `Card.fuse_face()` builds a synthetic
      merged `Card` (mirroring `as_copy`'s "whole new instance" shape, not
      a `StackItem` change) with concatenated `mana_cost_string`/
      `oracle_text` — `ManaCost.parse` already sums every `{N}` generic
      token it finds regardless of how many groups they came from, and
      Scryfall's top-level `cmc` is already the two halves' sum, so string
      concatenation alone *is* "pay both costs," reusing the ordinary
      single-card cast/bind pipeline. Each half's own oracle text
      self-refers by its own bare name (e.g. "Burn deals 2 damage…"), which
      the parser's self-reference folding can't match against the fused
      card's combined "A // B" name — `Card._fold_bare_name` pre-folds each
      half's own name to `~` before concatenating, mirroring
      `parser.oracle.normalize._fold_self_name`'s word-boundary rule
      locally rather than importing the parser front-end into the model
      layer. Frontend: the exile zone now passes its `byInstance` action
      map through (previously hardcoded to none), so an exiled,
      `adventure_castable` creature's offered `cast_spell` action actually
      renders a button (with a small "📖 Abenteuer" badge); `faceHint`
      labels a `face: "fuse"` action distinctly from a plain second-face
      offer. Tests: `test_card_structures.py`, `test_scryfall_client.py`.

- [x] "Prepared" (RULE 722, Preparation Cards): a newer mechanic (Scryfall
      `layout: "prepare"`, e.g. "Abigale, Poet Laureate // Heroic Stanza")
      distinct from Adventure/Split despite the shared two-face card frame —
      the inset "prepare spell" second face can *never* be cast from hand
      (RULE 722.3/722.4); it only becomes reachable once some other ability
      makes the permanent "become prepared" on the battlefield, which spawns
      a token copy of *just the prepare spell* in exile, castable for as
      long as the source stays prepared and on the battlefield.
      `scryfall_client._SECOND_FACE_LAYOUTS` now also captures `"prepare"`'s
      second face into `back_*` (same mechanism Adventure/Split use — no
      new capture code). `RulesEngine.create_token` gained a `zone:
      Zone = Zone.BATTLEFIELD` param so it can create a token straight into
      exile, skipping every battlefield-entry side effect (summoning
      sickness, `enters_tapped`, `ENTERS_BATTLEFIELD`) when it's not going
      to the battlefield — a strict superset of its old behavior, every
      existing caller unaffected. New `RulesEngine.make_prepared(obj)` (RULE
      722.3a, a no-op if already prepared or the card has no prepare spell)
      sets `GameObject.prepared` and creates one such exiled token, linked
      back via `GameObject.prepared_source_id` (`instance_id`, the same
      "link to another object" idiom `attached_to` already uses). The
      token-cease-to-exist SBA (RULE 704.5d, `_remove_stranded_tokens`) is
      this codebase's only "a created copy disappears when stranded"
      mechanism — rather than build a parallel one, the prepared copy is
      `is_token=True` with a RULE 722.3c exemption added directly there
      (`_is_prepared_copy`): exempt only for as long as `GameState.
      find_object(prepared_source_id)` is still on the battlefield with
      `prepared` still set, so the copy is reaped automatically, with no
      separate expiry bookkeeping, the instant the source is unprepared or
      leaves play. `cast_spell` clears the source's `prepared` the moment
      the copy is actually cast (RULE 722.3c). The "~ becomes prepared"
      *effect* follows the `transform`/`TransformEffect` precedent exactly:
      `GameContext.make_prepared` passthrough, `BecomePreparedEffect`
      (always self-only — RULE 722.3a has no targeted form), registered as
      `EffectRegistry`'s `"become_prepared"`, plus one oracle-text handler
      in `catalogue/handlers.py` for the "~/it/this permanent/this creature
      becomes prepared" clause (a copy of the `transform` handler's shape).
      Deliberately out of scope: the oracle parser's trigger-*condition*
      table (`segmenter.py`'s `_TRIGGER_EVENTS`, still only enters/dies/
      attacks/blocks) is untouched, so a real Prepared card's own condition
      (e.g. "whenever you cast a creature spell") binds only if it's
      already one of those four — a separate, general parser gap, not
      specific to this mechanic. `GameEngine` reuses the Adventure
      cast-from-exile call-site *shape* (`can_cast`/`legal_actions`) behind
      a new `_castable_from_exile` helper covering both `adventure_castable`
      and a prepared copy's `prepared_source_id` link — no `_face_card`
      change needed, since a prepared copy's own `.card` already *is* the
      full prepare-spell characteristics. Frontend: a `gf-prepared-badge`
      (top-center, so it doesn't collide with the existing attacking/
      Adventure corner badges — a creature can be attacking *and* prepared
      at once) shown when `prepared`; the exiled copy's own cast button
      needs no new frontend work, reusing the exile-zone `byInstance` wiring
      above. Tests: `test_card_structures.py`, `test_scryfall_client.py`.
- [x] Copying objects (RULE 707): **token copies** —
      `RulesEngine.copy_permanent` + the `copy_permanent` effect create a token
      clone of a target permanent's copiable card. **"Becomes a copy of" as
      a layer-1 continuous effect is also done** — see "Become a copy of
      target permanent/creature" in "Rules Engine (Phase 2)" above (Vesuvan
      Shapeshifter).
- [x] Monarch (RULE 725), Initiative (RULE 726), Emblems (RULE 114) —
      Card-pool Batch 10, three previously-deprioritized (roadmap M6)
      greenfield subsystems. Monarch/Initiative are plain player
      designations (`GameState.monarch_id`/`initiative_id`,
      `RulesEngine.become_monarch`/`take_initiative`, `become_monarch`/
      `take_initiative` `EffectSpec`s — untargeted "you become the
      monarch"/"you take the initiative" or a real RULE 115 target). Their
      inherent triggered abilities have *no source* (RULE 725.2/726.2 — not
      attached to any permanent), so the ordinary per-permanent trigger scan
      (`RulesEngine._collect_triggers`) can never find them; a new
      `_collect_inherent_triggers`, called alongside it, builds both fresh
      off live state on every matching event instead: the monarch's own end
      step draws a card, and a creature dealing the monarch (or the
      Initiative holder) combat damage swaps the designation to that
      creature's controller. RULE 726.2's "venture into the dungeon"
      companion trigger is *not* fired — dungeons (RULE 309) aren't modeled
      in this engine at all — so a card whose only clause is "You take the
      initiative." still becomes fully MODELED regardless, on the strength
      of the designation swap and its own combat-damage-steal trigger alone.
      Emblems ("\[Player\] get\[s\] an emblem with '\[ability\]'",
      `create_emblem`/`CreateEmblemEffect`) needed a genuinely new
      "source" concept: an emblem has no permanent for `effect_binder.
      bind_ability` to bind its quoted ability onto at bind-on-load like
      every other ability, so a minimal `Emblem` (`models/emblem.py`) stands
      in — carrying just `controller_id` (for "you control"/`phase_relation`
      trigger scoping) and `timestamp` (RULE 613.7b layer ordering) — with
      `RulesEngine.create_emblem` binding the ability once, at *resolve*
      time, into the new `Player.emblems` list. The quoted ability is
      recursively parsed at *parse* time into a full nested `AbilitySpec`
      (`parser/oracle/catalogue/handlers.py`'s `_emblem_ability_spec`,
      mirroring `static_handlers._quoted_ability_grant_effects`'s
      recursive-`segment_line` idiom) rather than flattened to a
      `grant_triggered_ability`'s bare effects list, since `bind_ability`
      already knows how to build a real `TriggeredAbility`/`StaticAbility`
      from a whole spec and an emblem has no host permanent to flatten onto
      in the first place; subject/selector shapes meaningful only relative
      to a source permanent ("self"/"attached_permanent"/"other creatures
      you control") are rejected at parse time (fail-closed) rather than
      silently binding an ability that could never fire. `game/
      continuous.py`'s static-ability scan and `RulesEngine._collect_
      triggers` both gained a "scan every player's `Player.emblems` too"
      branch alongside their existing battlefield scan (RULE 114.4:
      "abilities of emblems function in the command zone"). Caught along
      the way: `continuous._source_name` read `ability.source.name`
      unconditionally for the static-effect trace log, which crashed the
      instant a real static emblem ability (e.g. "Creatures you control get
      +1/+1.") went through a layer-engine recompute, since `Emblem` (RULE
      114.3: no name of its own) has no `.name` — fixed with a `getattr`
      fallback to `"static"`, the label a sourceless ability already got.
      Deliberately deferred: RULE 725.4/726.4 ("if the monarch/initiative-
      holder leaves the game, the active player inherits it" — no
      multiplayer-elimination flow exercises more than two players yet);
      dungeons/RULE 309 entirely; and an emblem's own *activated* ability
      (permitted in principle by RULE 114.4, but no real emblem in the pool
      prints one, so `create_emblem` only files a bound result's
      `TriggeredAbility`/`StaticAbility`). Tests:
      `backend/tests/test_batch10_monarch_initiative_emblem_family.py` (20,
      parse+execute).
- [x] Rad counters (RULE 728) — the last item on the roadmap M6 "deprioritized
      until a deck needs one" list. Modeled as a fourth entry in `RulesEngine.
      _collect_inherent_triggers` (same file as Monarch/Initiative above): an
      inherent, source-less triggered ability with no permanent to host it,
      built fresh off live state on every `STEP_BEGIN`/`"main1"` event rather
      than found by the ordinary per-permanent scan. Unlike Monarch/
      Initiative it doesn't follow a designation — RULE 728.1 is explicit
      that it's "controlled by the active player" (an explicit RULE 113.8
      exception), so the check is just `state.active_player.counters.
      get("rad", 0) > 0`, no player lookup indirection needed. The counter
      itself needed no new model field: `Player.counters` (`models/
      player.py`) is already a generic slug→count dict built for exactly
      this ("energy", "experience", and now "rad"), so `add_player_counters`
      (the existing engine primitive for poison/energy/experience) and the
      Replay editor's generic `edit_set_player_counter` action already work
      for `kind="rad"` with zero further plumbing. The mill/life-loss/
      counter-removal behaviour is a new `RadiationMillEffect` (`game/
      effects.py`, built inline the same way `BecomeMonarchEffect`/
      `TakeInitiativeEffect` are): mills a number of cards equal to the
      live rad-counter count (read at resolution time, not frozen at
      trigger time, matching the rule's present-tense "have"), diffs the
      graveyard before/after to find how many of the milled cards were
      nonland (`RulesEngine.mill` doesn't itself distinguish land from
      nonland or return what it milled, so this reads `GameObject.is_land`
      off the newly-appended graveyard slice rather than changing `mill`'s
      shared signature), then loses that much life and removes that many
      rad counters — both always ≤ the milled count since it started equal
      to the rad-counter count. RULE 728.1a ("life lost 'from radiation'")
      is honored by threading a `cause` through: `GameContext.lose_life`
      didn't previously expose `RulesEngine.lose_life`'s existing `cause`
      parameter (it hardcoded `cause="effect"`) — now forwards it, so
      `RadiationMillEffect` can call `lose_life(player, n, cause=
      "radiation")` and any future card checking "life lost from radiation"
      can use `effect_binder`'s existing generic trigger-condition `filter`
      key (`{"cause": "radiation"}` on a `LIFE_LOST`-triggered ability) with
      no further engine changes.

      **Follow-up in the same batch**: granting/removing rad counters from
      oracle text, closed against the real ~23-card Fallout-set corpus
      already sitting in the cache (`backend/cache/db/cards.db`, grepped by
      `"rad counter"`) rather than left as a "no card needs it yet" stub.
      New generic parser grammar (`catalogue/handlers.py`, mirroring
      `_gain_life`/`_lose_life`'s who-prefix shape exactly): "\[you/target
      player/defending player\] get\[s\] N/X rad counters" and "each
      player/each opponent gets N/X rad counters" → a new
      `AddPlayerCountersEffect` (`game/effects.py`, the oracle-text-facing
      sibling of `RulesEngine.add_player_counters`, with the same
      `target_kind`/`selector` split as `GainLifeEffect`/`LoseLifeEffect` —
      including `selector="defending_player"`, resolved via the ability's
      *host* permanent when its own source is an Aura/Equipment rather than
      the attacker itself, since only the real attacker gets
      `combat_defender` stamped on it); "target player loses all rad
      counters" (Survivor's Med Kit) → `lose_all_player_counters`/
      `LoseAllPlayerCountersEffect`; "each opponent gets a number of rad
      counters equal to its power" (Feral Ghoul's dies trigger) →
      `dies_grants_rad_counters_equal_power`/
      `DiesGrantsRadCountersEqualPowerEffect`, a bespoke atomic effect
      reading the dying object's own last-known power at apply time
      (RULE 400.7), the same "read the characteristic directly, don't
      compose two effects" shape `ExileGainLifeToControllerEffect` already
      established — Feral Ghoul is the first fully `MODELED` rad-counter
      card. `PARSER_VERSION` bumped to `"21"`.

      "They get N/that many rad counters" off a "deals combat damage to a
      player" self-trigger (Glowing One's flat 4, Infesting Radroach's
      "that many" = the damage just dealt) has no oracle-text grammar at
      all — the *damaged player* (and, for Radroach, the amount) varies per
      firing, which a bind-on-load `TriggeredAbility`'s fixed effects list
      can't carry, and the front-end has no "that many" grammar yet either.
      Same shape as Ragavan's impulsive draw: a new `AbilitySpec.
      rad_counters_on_combat_damage` marker (`{"count": <int>}` or
      `{"count": "damage_amount"}`), read fresh off the `DAMAGE` event's own
      source by a new `RulesEngine._collect_rad_counter_damage_triggers`
      (mirroring `_collect_impulsive_draw_triggers`), building a fresh
      `AddPlayerCountersEffect(player=damaged_player, ...)` per firing.
      Hand-authored only (`game/ability_catalogue.py`, both cards) — the
      oracle-text parser front-end never produces this marker, same
      "hand-author it, no parser grammar needed" precedent as
      `impulsive_draw_on_combat_damage`. Both cards are now coverage
      `AUTHORED`; Infesting Radroach's unrelated "This creature can't
      block." is hand-authored alongside it (a plain `grant_keyword`
      static) so registering the card doesn't regress that clause's
      coverage relative to what the parser could otherwise give it.

      RULE 728.1a's "You gain life rather than lose life from radiation."
      (Strong, the Brutish Thespian) is a new per-player permission static
      — `radiation_life_gain`/`continuous.has_radiation_life_gain`, the
      same "outside the RULE 613 layer engine proper" treatment as
      `no_max_hand_size`/`no_untap_optional` — consulted directly inside
      `RulesEngine.lose_life` (redirecting into `gain_life` when
      `cause="radiation"`) rather than through the ordinary
      `ReplacementEffect`/`apply_replacements` machinery: that machinery
      only ever *rewrites* an event's amount, never redirects it into a
      different engine call, and `lose_life` doesn't route through
      `apply_replacements` at all today (unlike `add_counters`/
      `add_player_counters`/`deal_damage`).

      Net result against the real 23-card corpus: 3 cards fully modeled
      (Feral Ghoul parser-`MODELED`; Glowing One/Infesting Radroach
      hand-`AUTHORED`) and the rad-counter clause itself now parses
      correctly on several more that still land `UNMODELED` overall for an
      *unrelated* reason (Mirelurk Queen/Screeching Scorchbeast/The Master,
      Transcendent/Tato Farmer/Nightkin Ambusher/Vault 12 chapter I/
      Megaton's Fate/Strong/Survivor's Med Kit/Nuclear Fallout — each
      blocked by a genuinely separate gap: a "whenever a player mills a
      card" trigger family that doesn't exist at all yet, a modal sibling
      mode's own unrelated grammar, RULE 400.7 dies-subtype/nontoken group
      scoping, an "as ~ enters, choose one" modal-triggered-ability shape,
      Enrage's "whenever ~ is dealt damage" trigger vocabulary, or a
      quoted-reminder-text-plus-granted-token-ability combo). Left
      genuinely unclaimed (rad-specific, and each niche — 1 card apiece):
      Acquired Mutation's "whenever enchanted/equipped creature attacks"
      trigger-subject recognition from raw text (the `attached_permanent`
      trigger condition exists but is hand-authored-only today, never
      parser-derived); Bloatfly Swarm's replacement-plus-"for each" compound
      clause; Contaminated Drink's "half X, rounded up"; Harold and Bob's
      dies-return-as-a-transformed-Aura-with-a-quoted-grant compound shape;
      Mariposa Military Base's "if you do, ..." conditional and its
      rad-counter-scaled cost reduction; Nuka-Nuke Launcher's delayed
      "until end of next turn, whenever they cast a spell" recurring
      trigger; Struggle for Project Purity's attacker-count-scaled "twice
      that many"; The Ghoul, Gunslinger's subtype+nontoken dies-subject
      filter; The Wise Mothman's compound "enters or attacks" trigger;
      Vault 12 chapter II's sum-across-all-players' rad counters; and
      Vexing Radgull's conditional-then-proliferate branch. All tracked in
      `docs/implementation-state/BACKLOG.md` rather than re-derived from scratch later.
      Tests: `backend/tests/test_rad_counters.py` (18, mixing parser-level
      clause assertions with full engine execute-and-assert coverage).

- [x] Rad counters (RULE 728) — the 11-card deferred-gap backlog above,
      closed in one batch (2026-07-21, PARSER_VERSION 22), per the explicit
      instruction not to leave modest-yield items deferred a further round:
      every remaining named card now has real engine behaviour, not just
      parser recognition. New primitives, each reusable well beyond the one
      card that motivated it:
      - **Trigger-subject grammar** (`parser/oracle/segmenter.py`):
        "enchanted/equipped creature \<verb\>" now parses from raw oracle
        text (`_ATTACHED_SUBJECT_RE` → the pre-existing
        `{"subject": "attached_permanent"}` condition, previously
        hand-authored-only — Acquired Mutation); a tribal "a/another/~ or
        another \[nontoken\] \<subtype\>\[...\] you control \<verb\>" family
        (`_GROUP_SUBTYPE_SUBJECT_RE`/`_SELF_OR_GROUP_SUBTYPE_RE`, a new
        `"self_or_group"` subject alongside plain `"group"` —
        `effect_binder._build_group_ok` shared by both — The Ghoul,
        Gunslinger's "The Ghoul or another nontoken Zombie or Mutant you
        control dies"); checked *after* the pre-existing exact-main-type
        `_GROUP_SUBJECT_RE` so a bare "creature" still matches the more
        specific pattern first (a real regression during development,
        caught by the full suite, not shipped). A target-based intervening-
        if, "if that player is(n't) you, \<rest\>"
        (`_TARGET_IS_CONTROLLER_RE` → `condition={"target_is_controller":
        bool}`, `ConditionalEffect` — Ghoul's own "if that player is you,
        create a Treasure token."). A compound "~ \<verb1\> or \<verb2\>"
        multi-event trigger (`_SELF_MULTI_EVENT_RE`, `trigger["event"]` as
        a `list[str]` — `effect_binder.bind_ability`'s `"triggered"` branch
        now returns a list of `TriggeredAbility`, one per event, when it
        sees a list — The Wise Mothman's "enters or attacks").
      - **Amount/cost grammar**: "half X rad counters, rounded up/down"
        (`_substitute_x`'s new `"half_x_up"`/`"half_x_down"` division-of-X
        sentinels — Contaminated Drink); "draw X cards" (`COUNT_X`/
        `count_or_x_of` widening the `draw` handler past digit/word-only
        counts — the other half of the same card); "create a Treasure/Clue/
        Food token" (`_create_named_token` — Ghoul's self-targeted branch);
        a per-ability, counter-scaled activation-cost reduction
        (`costs.ActivationCost.dynamic_reduction`, `GameEngine.
        _reduced_activation_mana` — distinct from the existing
        static-granted `continuous.activation_cost_reduction_for`, stacks
        with it — Mariposa Military Base's "costs {1} less ... for each rad
        counter you have"); a land's own "you may have this enter tapped,
        for a bonus" choice (`optional_bonus_rad`, `RulesEngine.
        enter_land_tapped`/`_land_tapped_bonus_choice`/
        `resolve_land_tapped_bonus_choice` — the mirror image of a shock
        land's pay-life choice — Mariposa's other clause).
      - **New replacement/compound families** (`game/effects.py`): a
        damage-prevention-plus-counter-conversion replacement
        (`prevent_damage_convert_counters`/
        `_prevent_damage_convert_counters_replacement` — "that many" ties
        both the counters removed and the rad counters granted to the
        damage amount that would have been dealt, known only inside the
        replacement itself — Bloatfly Swarm); a third `enter_replacement`
        "named mode" family alongside creature-type/color
        (`ChooseNamedModeReplacement`/`GameObject.chosen_mode`,
        `RulesEngine._offer_enter_choices`/`resolve_enter_choice`'s
        `"choose_named_mode"` kind — Struggle for Project Purity's "choose
        Brotherhood or Enclave"), gating each subsequent named-bullet
        ability via `effect_binder._trigger_condition`'s new `"named_mode"`
        predicate rather than never binding the "wrong" one; a genuinely
        new aggregate combat event, `EventType.PLAYER_ATTACKED`
        (`GameEngine._fire_player_attacked_events`, fired once per
        attacker/defender pair leaving `declare_attackers`, unlike
        once-per-creature `ATTACKS`) plus its own marker/collector
        (`rad_counters_on_attacked`, `RulesEngine.
        _collect_attacks_you_rad_counter_triggers` — Struggle's Enclave
        mode: "twice that many rad counters"); a *recurring*, bounded-
        duration player-scoped trigger — RULE 603.7's one-shot
        `CreateDelayedTriggerEffect` has no sibling for "until the end of
        X's next turn, \<recurring effect\>" (`InstallTemporaryPlayerTrigger
        Effect`/`GameState.temporary_player_triggers`/`TemporaryPlayerTrigger`'s
        own waiting→active→expired phase state machine driven off
        `EventType.TURN_BEGIN`, `RulesEngine._collect_temporary_player_
        triggers` — Nuka-Nuke Launcher); a wholly new "return dies as a
        different, synthetic permanent type" primitive
        (`ReturnDiesAsNewPermanentEffect`/`RulesEngine.
        return_dies_as_new_permanent` — distinct from RULE 712.8's
        DFC-based "return transformed," which needs a real printed back
        face this card doesn't have; swaps `obj.card` for a synthetic
        `Card` built from quoted text, attached to a real RULE 115 target
        resolved by the trigger's own interactive `trigger_target` choice
        — Harold and Bob, First Numens). "~ loses all other abilities" is
        made literal by clearing every bind-on-load field
        (`triggered_abilities`/`activated_abilities`/`static_effects`/
        `replacement_effects`/`intrinsic_keywords`/`parametric_keywords`) on
        the object, not just skipping a re-bind — an ordinary blink/
        return-transformed object deliberately leaves those alone
        (`GameObject.reset_as_new_object`'s own docstring), but this card's
        printed text is explicit that the *old* card's abilities (vigilance,
        reach) are gone for good, caught and fixed during this batch's own
        test-writing.
      - **Extended existing primitives**: `ProliferateEffect` now also
        proliferates player-level counters (`Player.poison`/`Player.
        counters`), not just permanent counters — Vexing Radgull's
        "otherwise, proliferate" branch (`rad_counters_on_combat_damage`'s
        new `"else": "proliferate"` key, checked against the damaged
        player's *pre-damage* counter count so "don't have any yet" reads
        correctly even on the first hit); `AddCountersEffect` gained a
        `subtypes` filter narrowing its mass `each_creature_you_control`
        selector to an OR-combined tribal check (Vault 12 chapter III:
        "each creature you control that's a Zombie or Mutant"); `continuous.
        count_selector` gained `"total_rad_counters_among_players"`, the
        first cross-player (rather than single-controller-scoped) aggregate
        count (Vault 12 chapter II: "X is the total number of rad counters
        among players," feeding `CreateTokenEffect.count_selector`); fixed a
        real pre-existing bug in `game/mana_abilities.py`'s "any one color"
        parsing — a printed fixed count > 1 was always silently discarded
        down to 1 mana (no card before Harold and Bob's own granted ability
        printed one; also affects the real card Jeweled Lotus, whose own
        test asserted the buggy 1-mana behavior and was corrected
        alongside this fix); and a `self_rad_counters` mana-ability rider
        mirroring the pre-existing `self_damage` one (Harold and Bob's
        granted "{T}: Add three mana of any one color. You get two rad
        counters.").
      - Net result: all 11 previously-deferred cards now have real,
        reusable engine behaviour (not parser-recognition-only) —
        Acquired Mutation, Bloatfly Swarm, Contaminated Drink, Harold and
        Bob First Numens, Mariposa Military Base, Nuka-Nuke Launcher,
        Struggle for Project Purity, The Ghoul Gunslinger, The Wise
        Mothman, Vault 12: The Necropolis (all 3 chapters), and Vexing
        Radgull. Acquired Mutation and The Wise Mothman still land
        `UNMODELED` overall — each has one genuinely separate, out-of-scope
        line ("goaded" status, RULE 701.15-ish; a "whenever one or more
        nonland cards are milled" trigger family, respectively — neither
        modeled by this engine at all) — but their rad-counter clause now
        parses and executes correctly in isolation.
      - Tests: `backend/tests/test_rad_counter_deferred_gaps.py` (37,
        mixing parser-level clause assertions with full engine
        execute-and-assert coverage per card, mirroring
        `test_rad_counters.py`'s own two-layer style).
- [x] Mill-trigger family closeout (2026-07-21) — the "whenever a player/an
      opponent mills a nonland card"/"whenever one or more nonland cards are
      milled" gap the Rad counters batch above surfaced (Glowing One/
      Infesting Radroach/The Wise Mothman's own second abilities). New
      generic primitive: `EventType.MILL_CARD` (`models/events.py`),
      fired by `RulesEngine.mill` once per *nonland* card milled (never for
      a land — no real card needs that side yet), in addition to the
      existing aggregate `MILL` event (unchanged). Wired into
      `effect_binder`'s existing "group" subject controller scoping
      (`_GROUP_CONTROLLER_EVENT_KEYS["MILL_CARD"] = "player_id"`) — the same
      machinery `LIBRARY_SEARCHED`'s "an opponent searches" trigger
      (Archivist of Oghma) already uses, so an ordinary bind-once
      `TriggeredAbility` with `{"subject": "group"}` (any player) or
      `{"subject": "group", "controller": "not_you"}` (an opponent) just
      works off it.
      - Glowing One: a plain such trigger, `EffectSpec("gain_life", {"amount": 1})`.
      - Infesting Radroach: RULE 112.6a — a triggered ability that must keep
        functioning while its own source sits in a *graveyard*, not the
        battlefield, so it can't ride the ordinary per-permanent
        `_collect_triggers` battlefield scan at all. New `AbilitySpec.
        mill_return_from_graveyard` marker (a bare bool, mirroring
        `rebound`'s own single-flag shape — this ability has no card-varying
        parameter) stamped onto the `GameObject` by `attach_to_object`
        (survives the death/zone-change: `GameObject.reset_as_new_object`'s
        own docstring already establishes `triggered_abilities` et al. are
        never wiped by a zone change, only counters/attachment/cast-time
        flags are) and read fresh off *every player's graveyard* by the new
        `RulesEngine._collect_mill_return_from_graveyard_triggers` — the
        same "per-firing marker scan" idiom `_collect_counter_death_return_
        triggers`/`_collect_rad_counter_damage_triggers` already use, just
        over `player.graveyard` instead of `state.permanents()`. New
        `ReturnSelfFromGraveyardEffect` (`game/effects.py`) — the object is
        baked in at construction (no `target_spec`, so no spurious target
        choice opens), re-checks its zone at resolution time before calling
        `RulesEngine.return_from_graveyard`.
      - The Wise Mothman: registering the card (needed for the second
        ability) means `specs_for` no longer falls back to the oracle-text
        parser for it at all, so its already-correctly-parsing first ability
        ("enters or attacks" rad counters) is reproduced by hand too,
        verbatim. The second ability is *simplified*: rather than a
        genuinely dynamic "up to X targets where X varies per firing" (the
        `RulesEngine.check_rampage` shape — a fresh `TriggeredAbility` built
        at the firing call site), it reuses the same per-nonland-card
        `MILL_CARD` event Glowing One/Infesting Radroach use: "put a +1/+1
        counter on up to one target creature" fires once per nonland card
        milled. Across N simultaneous nonland mills this reaches the
        identical set of possible end states as the real card's single "up
        to X targets" choice (N independent "put a counter on some creature,
        or decline" chances) — only trigger *count* differs, matching the
        "for each, optionally act" broadcast simplification already used
        elsewhere in this catalogue (Dismantling Wave-shaped entries) for a
        fixed-count case, just driven by a per-firing count here. Needed
        `AbilitySpec.optional=True` at the ability level (not just the
        effect's own `TargetSpec.optional`) since `RulesEngine.
        _trigger_target_choice`'s decline button is gated on `ability.
        optional` — without it, RULE 115.1a's "up to one" couldn't actually
        be declined when a legal target existed.
      - `Acquired Mutation`'s "goaded" status remains open, now tracked
        under "Game Engine (Phase 3)"'s Multiplayer entry instead of here.
      - Tests: `backend/tests/test_mill_trigger_family.py` (13 — the generic
        `MILL_CARD` primitive plus all three cards, including the
        opponent-only/own-mill-doesn't-trigger and decline paths).
- [x] Double-faced & modal-DFC cards (RULE 712) — the ToDo entry's last two
      open items (2026-07-27):
      - **Delver of Secrets-shaped conditional transform**: "look at the
        top card of your library. If it's a[n] `<type>` card, transform
        ~." New `RevealTopThenTransformEffect` (`game/effects.py`,
        registered as `"reveal_top_then_transform"`), parameterized on a
        `models.card_query` criteria dict rather than hardcoded to
        instant/sorcery, so it's the general primitive for any future card
        sharing this exact template, not a one-off. Delver of Secrets
        itself is hand-authored in `game/ability_catalogue.py` (a plain
        `EventType.STEP_BEGIN`/`"upkeep"` trigger, no `phase_relation` —
        fires on *every* player's upkeep, mirroring Tangle Wire's own
        "each player's upkeep" shape — but the effect reads its own
        *controller's* library via `_controller_of(self.source, ...)`
        regardless of whose upkeep fired it). The card is only looked at,
        never moved. Tests: `backend/tests/test_delver_of_secrets.py`.
      - **MDFC commanders cast from the command zone**: `GameEngine.
        legal_actions`'s command-zone loop only ever offered a commander's
        *front* face — the hand loop three lines above it had a whole
        second `if obj.card.back_face() is not None: ...` branch the
        command-zone loop never got. `can_cast`/`_cast_action`/
        `commander_tax` already threaded `face="back"` through generically
        (zone-agnostic — `commander_tax` only checks `obj in player.
        command`, not which face), so the fix is purely additive: one more
        branch in the command-zone loop calling those same functions with
        `face="back"`. Deliberately **not** mirroring the hand loop's
        `can_play_land(face="back")` branch too: RULE 903.6 only lets a
        commander be *cast* from the command zone, and playing a land
        isn't casting a spell — a land back face stays unreachable from
        there (same as a real paper Commander ruling), reachable only once
        the card is actually in hand. Tests: `test_card_structures.py`
        (`test_mdfc_commander_offers_a_castable_back_face_from_the_
        command_zone`, `test_mdfc_commanders_land_back_face_is_not_
        offered_from_the_command_zone`, `test_casting_an_mdfc_commanders_
        back_face_still_pays_commander_tax`).
      - `GameObject.to_dict()` also gained a `has_back_face` key (read off
        `_front_card`, stable across an actual transform) so the frontend
        can offer a "peek other face" toggle without guessing from a
        name-keyed cache — see `docs/implementation-state/BACKLOG.md`/
        `Done_Frontend.md` for the board-side half of this.
      - Still deliberately unmodeled: the legacy pre-2021 non-daybound
        werewolf template ("if no spells were cast last turn, transform
        ~") — superseded by RULE 731 day/night, a permanent non-goal, not
        a gap.

- [x] **Face-down spells and permanents (RULE 708) — morph, megamorph,
      disguise, manifest, cloak** (2026-07-28, closes the former TYP-1).
      The first *permanent-state* subsystem where a permanent stops
      presenting its own card at all: a face-down object "has no
      characteristics other than those listed by the ability or rules that
      allowed it to be face down" (RULE 708.2a) — a 2/2 creature with no
      text, no name, no subtypes, no mana cost.
      - Modeled as a **face swap**, the same shape a DFC transform already
        used (`RulesEngine.switch_to_face`): `GameObject.turn_face_down`
        stashes the whole face-up bundle (`Card` + every catalogue-derived
        ability list, `_face_up_snapshot`) and swaps `card` for the
        synthetic face-down one (`game/face_down.py`'s `face_down_card`).
        Everything downstream — the layer engine, combat, targeting, the
        board — then reads a plain 2/2 with no abilities and needed *no*
        special case. `turn_face_up` is one assignment back, which is
        exactly RULE 708.8's "it regains its normal characteristics".
      - The synthetic card carries `mana_cost_string="{3}"` (RULE 702.37a's
        flat alternative cost, so the ordinary `effective_cast_cost`
        pipeline prices a face-down cast) but `converted_mana_cost=0` (RULE
        708.2a's "no mana cost" — a face-down permanent's mana value is 0,
        which is what every "mana value N or less" check must see). The one
        deliberate inconsistency in the model, and the reason both fields
        are set explicitly rather than derived.
      - **Casting face down** is a fourth "face" on the existing
        `can_cast`/`cast_spell` face parameter (`face="face_down"`,
        alongside back/fuse), so the whole timing/cost/rollback path is
        shared: a rejected cast restores the card face up in hand exactly
        the way a rejected modal-DFC back-face cast already did. RULE
        708.4's "effects that care about the spell's characteristics see
        only the face-down ones" is honoured by two explicit overrides in
        `can_cast` — the face-up card's own Flash doesn't apply (a
        face-down creature spell is always sorcery-speed), and its "as an
        additional cost" clause doesn't either.
      - **Turning face up** is a genuine RULE 116.2b *special action*:
        `GameEngine.turn_face_up`, offered by `legal_actions` any time its
        controller holds priority with no main-phase/empty-stack gate at
        all (revealing a morph in response to removal is the point of the
        mechanic), and it doesn't use the stack — the permanent has its
        real characteristics back the instant the action returns.
        `face_down.turn_face_up_options` returns a *list* of routes because
        RULE 701.40c/701.58c say a manifested/cloaked card that also has
        morph may use either: its printed morph/disguise cost, or (manifest/
        cloak only, and only for a creature card with a mana cost — RULE
        701.40b) its own mana cost.
      - **Megamorph** (RULE 702.37b) adds its +1/+1 counter only when the
        *megamorph* cost was the one paid, so the counter rides the chosen
        route, not the card. The keyword catalogue folds Megamorph onto the
        `morph` slug (same cost shape, same rules section), so the
        distinction is read back off the printed text
        (`face_down.is_megamorph`) rather than needing a second slug.
      - **Disguise/cloak** (RULE 702.168a/701.58a) differ from morph/manifest
        in exactly one characteristic — ward {2} — which is stamped onto the
        face-down object by `RulesEngine.turn_face_down`, since a face-down
        object's characteristics are what the *rule that made it face down*
        lists and nothing is read off the card underneath.
      - **Manifest/cloak** (RULE 701.40a/701.58a) is `RulesEngine.manifest`,
        one card at a time (701.40e) so an ETB trigger on the first can see
        the second still in the library. "Manifest dread" got its own
        `pending_choice` kind rather than riding `request_choose_objects`:
        that chooser only ever *acts on the picks*, and "the one you didn't
        pick goes to the graveyard" is half of this keyword action.
      - RULE 708.9's "reveal it as it changes zones" lives in
        `GameState.remove_from_battlefield` — the one chokepoint every
        departure goes through — as the bare model transition, never
        `RulesEngine.turn_face_up`: that reveal fires no "turned face up"
        trigger and charges no cost.
      - Parser: `manifest`/`cloak`/`manifest dread` effect handlers, and the
        "when ~ is turned face up" trigger family that had no event to bind
        to before this (see the trigger-vocabulary entry below). Frontend:
        the board's card-back sleeve fallback finally has a state that
        reaches it (`Done_Frontend.md`). Tests:
        `test_face_down_permanents.py` (21 cases).

- [x] **Dungeons (RULE 309) and venturing (RULE 701.49)** (2026-07-28,
      closes the former TYP-2, and with it the RULE 726.2 gap the
      initiative had carried since batch 10).
      - A dungeon is **not** a `GameObject`: `models/dungeon.py`'s
        `Dungeon`/`DungeonRoom` are plain data on `Player.dungeon` (RULE
        309.3's single slot). The reasoning is `models/emblem.py`'s — a
        dungeon has no power/toughness, no controller-vs-owner split and no
        zone changes but the one that removes it from the game, so every
        permanent-shaped path a `GameObject` drags along would be dead
        weight. It *does* carry `controller_id`/`timestamp`, because RULE
        309.4c makes the dungeon card the **source** of its room abilities.
      - The room graph is parsed from the **printed card text**
        (`game/dungeons.py`): a dungeon's whole rules text is
        `"<Room> — <effect>. (Leads to: A, B)"` lines, and that
        parenthetical is not reminder text but the RULE 309.5a arrows — so
        it is read off the *raw* text before `normalize` (which strips
        parentheticals) ever sees it. Only the effect half goes through the
        ordinary effect-body grammar, so an unmodeled room keeps its place
        in the graph and simply has no effect (fail-closed). 20 of the 30
        rooms bind today; the rest are `PAR-13` tail work.
      - The card pool is a **committed catalogue**
        (`services/dungeon_database.py` + `mtg_analyzer/data/dungeons.json`),
        the same three-tier durability argument `TokenDatabase` makes: a
        dungeon is never in a decklist and never fetched by name, and two of
        them aren't even in the app card cache (the bulk importer drops the
        `double_faced_token` layout Undercity is printed under, which keeps
        the parser's coverage denominator honest). Four dungeons ship;
        Baldur's Gate Wilderness is deliberately excluded because its Oracle
        text lists rooms with no "(Leads to: …)" arrows at all, so every room
        would read as bottommost and one venture would complete the dungeon.
      - `RulesEngine.venture_into_the_dungeon` implements RULE 701.49's
        three branches literally: enter a chosen dungeon at its top room
        (701.49a, an interactive `choose_dungeon` choice), follow one of the
        arrows out of the current room (701.49b, a `venture_room` choice when
        there are several), or — from the bottommost room — complete this
        dungeon and start a fresh one (701.49c). RULE 701.49d's "venture into
        [quality]" is a `dungeon` param, and it is ignored once the player is
        already in a dungeon, which is the rule's own wording.
      - Room abilities are collected the **source-less** way the monarch's
        and the initiative's are (`_collect_dungeon_room_triggers`, off a new
        `EventType.DUNGEON_ROOM_ENTERED`): there is no permanent for the
        per-object trigger scan to find, only a card in the command zone.
      - RULE 309.6's completion is **not** a separate SBA scan. Appending a
        `CompleteDungeonEffect` to the bottommost room's own ability puts it
        exactly at the moment 309.6's condition first becomes true ("the
        marker is on the bottommost room and that dungeon isn't the source of
        a room ability still on the stack"), without the SBA pass having to
        answer "is this stack item this dungeon's ability?".
      - **RULE 726.2 is now complete**: all three of the initiative's
        inherent abilities fire — the combat-damage steal (already there),
        the upkeep venture, and "whenever a player takes the initiative,
        that player ventures into Undercity", the last off a new
        `EventType.TOOK_INITIATIVE` that `take_initiative` announces
        *unconditionally*, so RULE 726.5's re-take (same player, no new
        designation) still ventures.
      - Parser: `venture` effect + the "venture into the dungeon"/"venture
        into Undercity" handler (46 cards in the cache print it). Tests:
        `test_dungeons.py` (21 cases).

- [x] **RULE 603.1/500.7 trigger-condition vocabulary** (2026-07-28, closes
      the former TYP-3).
      The parser named exactly four object verbs (enters/dies/attacks/blocks)
      and four steps (upkeep/draw/end/cleanup); everything else fell out of
      the coverage gate no matter how well the engine could already fire it.
      - `segmenter._TRIGGER_VERBS` is now **one table** feeding
        `_TRIGGER_EVENTS`, `_VERB_EVENTS` and the verb alternation all five
        subject regexes share (self, attached-permanent, group, group-subtype,
        self-or-group, and the compound "<verb> or <verb>" form) — so a new
        verb is one edit, not six regexes drifting. Added, each measured
        against the cache: `is turned face up` (91 cards, and the direct
        payoff of the face-down subsystem above), `leaves the battlefield`
        (148), `becomes blocked` (58), `becomes tapped` (52), `mutates` (31).
        Every compound form ("enters or is turned face up", "attacks or
        blocks") came along for free.
      - The admission rule is explicit: a verb earns a row only if the engine
        fires an event carrying an `instance_id` for it. "Becomes untapped"
        is deliberately absent — `EventType.UNTAP` is fired once per untap
        *step*, keyed by player — as are "becomes monstrous"/"specializes",
        which have no engine primitive at all (`MEC` tickets).
      - `_PHASE_STEP_WORDS` gained the two **phase**-named families the
        step-only vocabulary couldn't reach: "at the beginning of combat on
        your turn" (315 cards — the commonest phase trigger after upkeep and
        end step) and the main phases, printed either by ordinal or by
        pre-/postcombat name (52 + 30), plus "each player's <step>" (83+) and
        "each of your <phase>s". A card names a *phase*; `EventType.
        STEP_BEGIN` names that phase's first step, which is why this is a
        mapping rather than a bare alternation.
      - Cache-wide effect: coverage 26.6% → **27.1%** (9,092 → 9,259 of
        34,208), `PARSER_VERSION` 34 → 35. Tests:
        `test_trigger_condition_vocabulary.py` (23 cases).

- [x] **Formats and casual variants (RULE 8/9): Planechase, Archenemy,
      Vanguard** (2026-07-28, closes the former TYP-4 for everything but the
      team variants, now `PLR-14`).
      - `models/game_format.py` replaces "pass `starting_life=40` everywhere"
        with a named record — starting life, starting hand size, singleton,
        and which RULE 9 variants are on. `GameEngine.new_game` takes a
        format name and, given one, sets the numbers *and* builds the variant
        state; given none it behaves exactly as before, which is every
        existing caller. `get_format` never raises: an unknown name falls
        back to Commander, so a stale client or an old saved game can't wedge
        a session on a format string.
      - All three variants share the shape **dungeons** established: cards
        that begin outside the game, live in the command zone and whose
        abilities function from there. The difference is that these are real
        cards with real oracle text, so they are ordinary `GameObject`s in
        `Zone.COMMAND`, bound by `bind_from_catalogue` like any permanent,
        and picked up by the same static/triggered scans that already read
        `Player.emblems` (`variants.command_zone_ability_sources`, one new
        call site each in `continuous.py` and `_collect_triggers`).
      - **Planechase (901)**: one shared planar deck on `GameState`
        (901.5 permits per-player decks too; one shared deck is the common
        table setup and the only one with no "whose plane is this"
        bookkeeping). `planeswalk` fires away-then-to (901.10's own order),
        the planar die is a RULE 901.6 **special action** costing {X} where X
        is that player's roll count this turn (reset in `begin_turn` beside
        the land drop), and its six faces are one chaos, one planeswalk, four
        blank. **Phenomena** (901.17) ride the same `planar` layout and the
        same deck: capped at two per deck (901.15), kept off the opening
        face-up card (901.9), and RULE 901.18's "planeswalk again once its
        ability leaves the stack" is chained straight after the trigger is
        queued, with a depth guard for a hand-built deck the rule's own cap
        wouldn't protect.
      - **Archenemy (904)**: a per-player scheme deck, 40 life for the
        archenemy (904.4), and "set the top card in motion" as a *turn-based
        action* in the precombat main phase (904.7) — filed next to the Saga
        lore counter in `_step_main1`, not in the trigger machinery. An
        ongoing scheme stays face up until abandoned (904.9/904.11); every
        other scheme goes back under its deck immediately after its ability is
        queued rather than after it resolves (904.10) — indistinguishable
        here, since the ability is already on the stack with the card bound as
        its source and reads no zone of its own.
      - **Vanguard (902)**: an avatar per player in the command zone, its
        hand modifier applied *before* the opening hand is drawn (902.3) and
        its life modifier as the game starts (902.4).
      - Card data is a committed catalogue again
        (`services/variant_card_database.py` +
        `mtg_analyzer/data/variant_cards.json`, 416 cards: 207 planes and
        phenomena, 102 schemes, 107 avatars) — `scripts/import_bulk.py`
        deliberately drops those three Scryfall layouts from the app card
        cache so the parser's coverage denominator stays "cards a player can
        cast", which leaves this the only place they can come from.
      - Parser: the four fixed variant trigger conditions ("whenever chaos
        ensues", "when you set this scheme in motion", "when you planeswalk
        to/away from ~", "when you encounter ~"), plus the commonest plane
        template — "when you planeswalk to ~ **and at the beginning of your
        upkeep**" — which emits **two** `AbilitySpec`s rather than one
        list-valued event, because only the upkeep half may carry the step
        filter (a filter is AND-ed onto the event payload, so a shared one
        would fail closed and the planeswalk half would never fire).
      - Explicitly **not** built, and tracked as `PLR-14`: the RULE 809/810/811
        team variants. Those change the turn structure itself (shared life,
        two players taking one turn, a defending *team*) rather than adding a
        card pool beside it. Tests: `test_casual_variants.py` (29 cases).

## Multiplayer (UC4)

`mtg_analyzer/services/lobby.py`, `services/game_session.py`,
`api/multiplayer.py`, `api/multiplayer_ws.py`; tests in
`test_multiplayer_session.py` (21) and `test_api_multiplayer.py` (24).

Shipped 2026-07-22, replacing the long-standing 501 stub. Two players sit
down from a lobby, each with a saved deck, and play a real game against
the same engine goldfish mode uses. The design keeps a hard line between
**people** and **Magic**:

- [x] **`services/lobby.py` — the lobby, deliberately rules-free.** It
      knows `LobbyPlayer` (id, name, presence) and `LobbyGame` (seats,
      status, observers) and imports nothing from `game/`. Presence is the
      three states the UI shows — `online` (connected, elsewhere in the
      app), `available` (in the lobby) and `playing` — and `playing` is
      *derived* from holding a seat rather than settable, so a client can't
      claim it (or, more usefully, can't accidentally show as available
      while it holds a seat). A `Seat`'s `ready` flag is cleared by *any*
      change to the table (a join, a leave, a deck pick, a settings
      change), which is what makes "when all players accept, the game
      starts" safe: you can only ever be carried into the table you
      accepted. A player's identity is a server-assigned id, never the
      free-text Profil name — that name is neither unique nor
      authenticated (this app still has no auth), and the id doubles as
      the `Player.id` inside the `GameState`, so a seat and its player are
      the same thing by construction.

- [x] **Handing off to the engine.** `Lobby.start()` takes an
      already-built `GameSession` id; `api/multiplayer.py` is the only
      module that bridges the two, resolving each seat's saved deck the
      same way `api/game.py` resolves a goldfish deck (shared
      `expand_entries`, same Commander-legality gate — a multiplayer game
      is a real game). An illegal deck blocks the start with a 422 naming
      *whose* it is. `build_multiplayer_engine` is the N-player sibling of
      `build_goldfish_engine`: one seat each, no passive dummy, everyone
      draws an opening hand, seat order is turn order (RULE 103.2's "who
      goes first" is settled by the lobby rather than by a die roll the
      server would have to arbitrate).

- [x] **Per-seat setup.** `GameSession`'s single `_setup_complete` bool
      became `_setup_pending`, a set of seats that still owe a kept hand,
      and `_mulligan_count` became per-player: every seat mulligans for
      itself, in parallel (RULE 103.4 resolves them in turn order, but no
      seat's decision depends on another's, so there is nothing to
      serialize). `MULLIGAN_STYLES` is the table's agreed procedure —
      `london` or `none`; Vancouver is deliberately absent, see
      `docs/implementation-state/BACKLOG.md`.

- [x] **Actions carry an actor.** `apply_action(action, actor_id=...)`;
      solo modes leave it implicit (the active player) and are unchanged.
      The point of threading it is that **the engine already does the
      rules validation against an explicit `player`** — `can_cast`'s RULE
      601.3a active-player timing gate, `declare_blockers`' "the attacking
      player does not declare blockers" — so a non-active seat gets
      exactly the instant-speed-and-blocking subset for free, with no
      second, drifting list of "what may an opponent do" in the session
      layer. Only turn advancement is gated here (RULE 500.1: the active
      player's job), because it isn't an action the engine attributes.

- [x] **Hidden zones are redacted server-side** (RULE 400.2).
      `view(perspective=...)` strips every *other* player's hand out of
      the payload and every player's library (including your own — you
      don't know your own draw order), keeping `hand_count`/
      `library_count` so the board can still draw the right number of
      card backs. A pending choice is delivered only to the player it's
      addressed to; everyone else gets a `waiting_on_choice` marker, since
      a choice's options can name cards in a hidden zone. `observer_view()`
      is the same machinery with a perspective that matches nobody, plus
      an empty `legal_actions`. This is redaction, not hiding: an
      opponent's hand never leaves the process.

- [x] **`RulesEngine.concede` (RULE 104.3a)** — legal at any time from any
      seat, so it is *not* routed through the timing gates. The RULE 800.4a
      cleanup (their objects leave with them) is deliberately **deferred**:
      conceding is in practice a sorcery-speed act, and pulling a board out
      from under the other players mid-turn is disorienting, so the id is
      parked on `GameState.pending_leave_ids` and swept by
      `GameEngine.begin_turn` when the next player's turn starts
      (`remove_player_from_game`). With one living player left the game is
      over anyway and the final board simply stands for the review.
      `GameState.next_active_index` now also skips a player who has lost,
      so a conceded seat is passed over in turn order.

- [x] **Interactive blocker declaration (RULE 509.1a).**
      `GameEngine.legal_actions` finally *offers* `declare_blockers` — one
      entry per creature the defending player could block with, carrying
      the attackers `can_block` says it may be assigned to (evasion,
      protection and the whole RULE 508/509 restriction family included).
      A creature already blocking is left out, since the action is
      additive. The UI collects a complete block and submits it as one
      action, which is what lets RULE 702.111b menace and its "…except by
      N or more creatures" siblings — validated across the whole
      assignment — actually be satisfied.

- [x] **The RULE 117 priority loop is real.** Opt-in per session
      (`GameSession.interactive_priority`, on only for `MULTIPLAYER`;
      the engine flag it sets is `GameEngine.interactive_priority`), so
      every solo path keeps auto-draining the stack exactly as before —
      2,300+ existing tests passed through this change untouched, which is
      the point of making it a flag rather than a rewrite.

      `GameEngine.pass_priority(player)` had owned the APNAP round since
      it was built (record the pass, hand priority to the next living
      player, resolve the top of the stack once everyone has passed in
      succession, RULE 117.3b's reset after anything resolves) — it had
      simply never been *driven*. Three things were missing and are now
      there: `_run_step` only puts triggers on the stack instead of
      draining it when the flag is on; a step that gives nobody priority
      (untap/cleanup, RULE 117.3a) now clears the holder rather than
      leaving it pointing at whoever had it last, so "can anybody act?" is
      answerable from the state; and `GameSession._pass_priority` supplies
      RULE 117.4's *other* branch — all passed on an **empty** stack ends
      the step — which the engine can't, because it doesn't drive the turn
      (`_advance_to_priority_window` runs through the no-priority steps).

      Consequences worth knowing: there is **no "advance the turn" action
      in a shared game** — `advance_step`/`auto_turn`/`advance_to_decision`
      are all refused, and the board's primary button is "Passen". Only the
      priority holder may act, and that's enforced in `_dispatch`, not just
      filtered out of `legal_actions`: the filter is a hint to the UI, and
      a client could always post an action it was never offered. The one
      exemption is RULE 509.1a declare-blockers, a turn-based action the
      *defending* player takes while the attacker still holds priority.
      Keeping the last opening hand now also runs the game into its first
      priority window, since with 117.4 driving the turn nobody can pass
      before somebody holds priority in the first place.

- [x] **A seat is reclaimed by player name.** `services/lobby.py`'s
      identity moved from the server-issued id to `normalize_name(name)`
      (case- and whitespace-insensitive), because the name is the only
      handle that survives a page reload — so reconnecting with the same
      Profil name walks straight back into the same seat, mid-game, which
      is what makes a refresh survivable at all. The id stays as the
      opaque handle every REST call takes (and as the `Player.id` inside
      the `GameState`); it just isn't what recognizes a returning client.
      The trade is deliberate and documented in the module: two people who
      pick the same name *are* the same player here, and the second to
      connect takes the seat over rather than being refused — because the
      overwhelmingly common cause of "that name is already connected" is a
      dead socket the server hasn't noticed, and refusing would lock
      someone out of their own game.

- [x] **Disconnects hold the seat instead of forfeiting it.**
      `Lobby.disconnect` marks a player absent and starts a grace period
      (`config.MULTIPLAYER_DISCONNECT_GRACE_SECONDS`,
      `MTG_MULTIPLAYER_DISCONNECT_GRACE`, default 90s) rather than
      dropping them; a player with no seat is still removed at once, since
      there's nothing to hold and a ghost in the player list is worse than
      no entry. Meanwhile the table must not freeze on somebody who isn't
      there, so `api/multiplayer_ws.pass_for_absent_players` passes
      priority for them — the one action that is always legal and can
      never gain the absent player anything. Letting the grace lapse
      concedes for them (RULE 104.3a), because a seat nobody is coming
      back to can't be waited on forever.

- [x] **An idle priority holder is disconnected** after
      `config.MULTIPLAYER_IDLE_TIMEOUT_SECONDS`
      (`MTG_MULTIPLAYER_IDLE_TIMEOUT`, default 120s; 0 disables). This is
      not about policing slow play — only the player the game is actually
      *waiting on* is ever checked — it's that a browser tab which went
      away without a clean close still holds priority, and the game would
      otherwise wait on it forever. `POST …/action` calls `Lobby.touch`,
      so acting is what proves a client is still there. Both timers are
      swept once a second by `sweep_once`, run from the app's lifespan
      (`api/app.py`) — the only background task in the app.

- [x] **`/ws/lobby` (`api/multiplayer_ws.py`)** — one socket per client,
      held for the session. It *is* the presence signal (losing it removes
      the player; there is no auth or cookie to expire), it broadcasts a
      fresh lobby snapshot on any change, and after a move it pushes each
      participant **their own** view rather than one shared payload — that
      asymmetry is the hidden-information rule, so it can't be flattened
      into a broadcast. An abandoned table (nobody who belongs to it still
      connected) is dropped rather than left in everyone's list. The
      socket also carries presence *both ways*: `player_disconnected` /
      `player_reconnected` tell everyone when somebody drops or returns,
      and a `disconnected` frame tells a client being dropped **why**
      (`idle`, `replaced`, `timeout`) before the close, so the UI can say
      what happened instead of just flickering. Connecting always pushes
      the client's own game straight away, which is the resync a reload or
      a reconnect needs — the board is rebuilt from server state rather
      than from whatever the client was holding.

- [x] **`GameState.round_number` (2026-07-27)** — a display-only companion
      to `turn_number`. RULE 500.1 counts every player's turn separately,
      which is correct and is what the whole engine reads; it is *not* what
      a player means by "we're on turn 4", which is the fourth time it has
      come back around to them. `GameEngine._advance_round_number` bumps it
      when the turn reaches whoever took turn 1 (`starting_player_id`),
      moving that reference point if they leave the game (RULE 800.4a) so
      the counter can't get stranded. A board assembled rather than played
      (Replay/Puzzle, the `edit_set_turn` action) derives it instead, via
      `GameState.sync_round_number`. Nothing in the rules engine reads it.
- [x] **Leaving a *finished* table closes it (2026-07-27).** `Lobby.leave`
      kept the seat of anyone who walked away from a non-SETUP game, which
      is right for a RUNNING one (the position is still the table's, and
      they may come back) and wrong once the game is over: there is nothing
      to come back to, and a played-out table sat in every player's lobby
      list until the last participant's socket died. FINISHED now leaves
      the same way SETUP does, dropping the table with the last human out.

- [x] **Equip/Fortify/Reconfigure restricted to what you control
      (2026-07-27).** RULE 702.6a ("target creature *you control*"),
      702.67a ("target land *you control*") and 702.151a ("another target
      creature *you control*") were all unenforced — `game/targeting.py`'s
      `legal_targets` dispatch for these three (keyed off `_attachment_kind`
      in the ``kind == "permanent"`` branch `game/effect_binder.py`'s
      `_keyword_activated_ability` always sets, since it doesn't know the
      real target restriction) offered *any* creature/land at all,
      including an opponent's, and `game/rules_engine.py`'s
      `_attachment_legal` didn't re-check control at resolution time either
      (RULE 301.5b: control matters at both points). Both now compare
      `target.controller_id` against the activating player (offer time) /
      the Equipment's own controller — the only one who may activate it,
      RULE 301.5d (resolution time). Equip's old `target.card.is_artifact`
      fallback (letting it target a non-creature artifact — flatly wrong
      per RULE 301.5's very first sentence) is gone with it. Regression
      tests in `test_game_engine.py` seat an opponent's creature/land as
      bait at both checkpoints.
- [x] **`GameSession.take_back` — a per-seat undo budget (UC4 Setup,
      2026-07-27).** Table-configured (`LobbyGame.takebacks_per_player`,
      host-only via `set_options`, clamped to `MAX_TAKEBACKS_PER_PLAYER`),
      not a RULE concept — a friendly-game convenience distinct from
      `rewind` (a solo-practice, disabled-in-multiplayer, undo-by-count
      tool). Unlike an ordinary action, it isn't gated by RULE 117
      priority at all (the same exemption `concede` gets — a misclick
      doesn't wait for a convenient moment), and unlike `rewind` it
      targets *a specific player's own* last move rather than a raw count:
      `_history` entries now carry the acting player's id (`_snapshot`'s
      new `actor_id` param, threaded from `apply_action`'s `actor` and
      from `concede` — so a player can even take back their own
      accidental concession), and `take_back` walks backward for the
      caller's most recent entry, discarding it and everything after. That
      "everything after" is deliberate, not a gap: `_history` is one
      shared timeline, so an opponent's move made *after* the point being
      undone cannot survive undoing it — a take-back is "put the game back
      to right before my mistake," and whatever happened next didn't
      happen in a timeline where the mistake didn't. Slicing both
      `_history` and `move_log` by a **tail-relative** depth (not an
      absolute front-based index) is what keeps this correct once
      `_history` starts dropping its oldest entries past `MAX_HISTORY` —
      `move_log` never trims, so the two lists can differ in length, and
      only their *tails* are guaranteed to stay aligned.

- **Tables of two to four (PLR-2, 2026-07-28).** `services/lobby.py`'s
  `MAX_SEATS` went from 2 to 4 (plus an explicit `MIN_SEATS = 2`), which
  is the whole backend change — and that is the point worth recording:
  the engine had been written for N players since the multiplayer batch
  (`build_multiplayer_engine` builds one `Player` per seat,
  `GameState.next_active_index` rotates through however many there are,
  `GameEngine.legal_defenders_for` already offers *every* living opponent
  as a defender, `can_block` already resolves "is this attacker attacking
  me", `GameSession._redact_hidden_zones` already redacts per seat rather
  than "the other one", and the RULE 800.4a deferred-leave sweep is a
  list comprehension over `living_players()`). What the 2 was protecting
  was the *board layout*, not the rules. Two clamps were tightened on the
  way: `Lobby.create` and `set_options` now floor at `MIN_SEATS` as well
  as capping at `MAX_SEATS` (`num_players=0` used to be able to leave a
  one-seat table permanently "full"), and `set_options` still can't shrink
  a table below the seats already taken, so resizing never evicts anyone.

  Four is a cap on the *UI*, not on the rules — the pod size Commander is
  played at, and where three opponent boards stacked above your own stops
  being readable. The frontend half is a seat-count picker in Setup and a
  per-opponent fold-away on the board (`Done_Frontend.md`).

  Tests: `test_multiplayer_pods.py` (22) covers the lobby seat machinery
  (opening/filling/resizing/refusing a fifth player) and the rules
  consequences that only exist with 3+ seats — turn order rotating through
  four seats, a priority round visiting all of them in APNAP order, every
  opponent offered as a defender, *only the attacked* player being offered
  (and allowed) blocks, damage landing on just the chosen opponent, a
  concession leaving a game the survivors keep playing and the turn order
  skipping the conceded seat, and per-seat redaction with three opponents.
  `test_api_multiplayer.py::TestPodSizedTables` (6) covers the same over
  HTTP: opening a table for 3 or 4, starting it, growing it, the cap, and
  a fifth player being refused.

- **Nobody skips the first draw at a pod (RULE 103.8c, 2026-07-28).** A
  real bug the pod work exposed. `GameEngine._step_draw` skipped turn 1's
  draw whenever `len(players) > 1`, citing "RULE 103.7a" — but that rule
  (103.8a in the current CR) is explicitly a **two-player** rule, and
  103.8c says the opposite for everything else: *"In all other multiplayer
  games, no player skips the draw step of their first turn."* At a table of
  three or four the starting seat was therefore quietly a card down all
  game. The gate is now `== 2`, which also keeps the goldfish behaviour
  intact — a solo game is modeling a two-player game, and its dummy is the
  second seat that makes the rule apply (its setup screen's "on the
  draw" option is what clears `skip_first_draw`).
  Tests: `test_multiplayer_pods.py::TestFirstDrawStep` — all four seats on
  eight cards in their own first main phase, and the two-seat game still
  having the starting player on seven.

- **Random seating and random starting player (RULE 103.1/103.2,
  2026-07-28).** Seat order *is* turn order, and it had exactly one
  possible value: join order, so the host always started. Two independent
  host-set table options now sit next to the mulligan style
  (`LobbyGame.randomize_seating` / `random_starting_player`), applied once
  by `LobbyGame.seating_order()` when `api/multiplayer.py`'s `start_game`
  builds the seat list — after which the resulting order simply *is* what
  everyone sees in the board's turn-order strip.

  The two are separate on purpose and compose in that order: seating is
  *whose left you sit on*, so `random_starting_player` **rotates** the ring
  rather than shuffling it — picking a different starting point must not
  disturb who sits next to whom. `seating_order` is a pure function of the
  seats plus an injectable `rng` rather than something that mutates
  `self.seats`, so a test can pin the roll; the lobby stays rules-free by
  only *recording* the choice.
  Tests: `test_multiplayer_pods.py::TestSeatingAndStartingPlayer` (7 —
  join order by default, a shuffle being a permutation and actually
  varying, a random start only ever producing rotations, both together,
  host-only, and the flags reaching the wire) plus an API round-trip in
  `test_api_multiplayer.py` for the camelCase aliases, which is where a new
  option silently goes nowhere.

- **Vancouver mulligan + interactive scry (PLR-1, 2026-07-28).** Vancouver
  had been deliberately absent from `MULLIGAN_STYLES` for one reason —
  `RulesEngine.scry` was a stub that fired `EventType.SCRY` and kept every
  looked-at card on top, so the mulligan's defining feature would have
  been a choice with no effect. So the scry was built first.

  `RulesEngine.scry` now opens a real `scry` `pending_choice` running in
  two phases (later generalized with surveil onto `_look_top_choice`/
  `_resolve_look_top_choice`/`_finish_look_top`, see below): a
  repeated **bottom** question ("which of these goes under the library?",
  top card first, declining to move on), then — only when 2+ cards are
  still headed for the top, since one card has only one order — a repeated
  **order** question ("which goes topmost?"). Both phases offer a decline,
  and the two mean different things: declining the bottoming keeps what's
  left on top *and moves to ordering it*, while declining the ordering
  finishes with the cards in the order they already were. That second
  decline is what keeps the overwhelmingly common "fine as it is" a single
  click while still allowing RULE 701.18's full "in any order". The whole
  decision is carried as instance ids in the choice dict (`remaining`/
  `bottom`/`top`), not as objects or a closure, so it survives the
  `GameState.clone()` that undo takes. `SCRY` still fires up front, at the
  moment the player looks, so "whenever you scry" triggers see it exactly
  where the stub fired it. Dispatch is one more `kind` branch in
  `GameEngine.resolve_pending_choice`.

  On top of that, ``vancouver`` joins `MULLIGAN_STYLES`: `_mulligan` draws
  `hand_size_after_mulligans` (one fewer per mulligan taken, floored at 0)
  instead of a full seven, `bottom_count_for` returns 0 (Vancouver pays in
  the draw, not in bottoming — London is what swapped those), and the
  scry-1 happens **after the whole table has kept**, in turn order, which
  is both the historical rule and the only timing a single shared
  `pending_choice` allows. That queue is `GameSession._pending_scries`,
  started by the last `keep_hand` (`_start_vancouver_scries`) and walked
  one answer at a time by `_after_choice`. The RULE 117 consequence needed
  a matching wait: `_keep_hand` used to run `_advance_to_priority_window`
  the moment the last seat kept, which would now step the game around an
  open scry, so it defers behind `_priority_window_pending` and
  `_after_choice` opens the window once the last scry is answered.
  `_dispatch`'s setup gate gained an exemption for `choose`/`decline`
  while a choice is pending, so a decision raised during setup is
  answerable at all. `view()["setup"]` gained `next_hand_size` for the UI.

  Tests: `test_scry_vancouver_mulligan.py` (21) — the scry's two phases,
  both declines, degenerate libraries, the event still firing, an
  unoffered answer being refused; then the mulligan drawing one fewer,
  never bottoming, scrying only when a mulligan was taken, London being
  untouched, and at a table: the queue running in turn order, only the
  seats that mulliganed being in it, the first priority window waiting for
  the last answer, and the scrying seat being the only one offered it
  (RULE 400.2 — the others get the "waiting on Ann" marker).

- **Interactive surveil + the "whenever you scry/surveil" trigger family
  (PLR-1b, 2026-07-28, PARSER_VERSION 36).** Three pieces, and the first is
  the one that shaped the other two.

  **Scry and surveil are one keyword action with one parameter changed.**
  Look at the top N cards, send any number of them *somewhere*, put the
  rest back on top in any order — scry's "somewhere" (RULE 701.18) is the
  bottom of the same library, surveil's (RULE 701.31) is the graveyard.
  Nothing else about them differs, including the shape of the decision, so
  rather than copying scry's ~100 lines they were refactored onto one
  implementation (`_look_at_top`/`_look_top_choice`/
  `_resolve_look_top_choice`/`_finish_look_top`) driven by a two-entry
  `_LOOK_TOP_KINDS` table holding each keyword's event and its German
  prompts. They keep *separate* `pending_choice` kinds (so the UI can label
  and icon them apart, and `resolve_pending_choice` dispatches by kind) and
  separate public resolvers; only the internals are shared. The choice
  dict's `bottom` key became `away` in the process. Surveil is deliberately
  **not** routed through `mill`: RULE 701.31b and 701.13 are distinct
  keyword actions, so nothing watching for milling sees a surveil — there's
  a test asserting exactly that.

  **A player-subject trigger condition, the first in this grammar.**
  "Whenever you scry" / "whenever you surveil" / "whenever you scry or
  surveil" are RULE 603.1 conditions whose subject is a *player*, not an
  object — so `segmenter._TRIGGER_VERBS` can't express them at all: that
  table's entire scoping discipline (a verb earns a row only if the engine
  fires an event carrying an `instance_id` for it) is about matching the
  acting permanent, and these events carry a `player_id` instead. They got
  their own table, `_PLAYER_TRIGGER_CONDITIONS`, emitting
  `{"subject": "you"}` — which `effect_binder._subject_condition` turns
  into "the event's player key equals this source's controller", reading
  `_GROUP_CONTROLLER_EVENT_KEYS` (gaining `SCRY`/`SURVEIL` → `player_id`)
  for *which* key. That scoping is the whole point and is tested from both
  sides: Dimir Spybug grows a counter when its controller surveils and
  **not** when an opponent does. Unlike `_VARIANT_TRIGGER_CONDITIONS`
  (whose plane abilities are only ever collected for the face-up plane, so
  they need no scoping at all), this one genuinely has to discriminate.
  The compound "scry or surveil" (Matoya, Archon Elder) becomes one
  `AbilitySpec` per event with its own freshly-bound effects, the same
  shape `_SELF_MULTI_EVENT_RE` and the compound plane template use.

  The patterns are anchored end-to-end on purpose: "whenever you surveil
  **for the first time each turn**" (Whispering Snitch) must *fail* to
  match, since the engine can't express a once-per-turn limiter and an
  unanchored pattern would silently bind an over-firing trigger.

  **Yield, stated honestly: 5 of the 25 cards** carrying one of these
  triggers are now MODELED (Arwen Undómiel, Dimir Spybug, Disinformation
  Campaign, Flamespeaker Adept, Matoya, Archon Elder) — coverage 9,259 →
  **9,264 / 34,208 (27.1%)**. The trigger family itself is complete; the
  other 20 are blocked on ordinary effect-*body* grammar ("where X is the
  number of cards looked at while scrying this way", "you may pay {2}",
  Mirko's unrelated end-step ability). The one blocker worth naming is the
  once-per-turn limiter above, which turns out to gate **182 cards**
  cache-wide and is now [PAR-14] rather than an implicit near-miss.

  Tests: `test_scry_surveil_vancouver.py` (36, renamed from
  `test_scry_vancouver_mulligan.py` as it grew the surveil half) — surveil's
  own choice kind and prompt, cards reaching the graveyard rather than the
  bottom, both declines, reordering the kept pile, the `SURVEIL` event
  firing, surveil not being a mill; then the parser recognizing all three
  phrasings, the compound splitting into two specs with unshared effects,
  the once-per-turn qualifier failing closed, and the binder firing for the
  controller but not for an opponent.

- **Two non-deterministic-suite fixes (2026-07-28),** found by running the
  full suite repeatedly while measuring the batch above rather than by any
  test failing once. Both were pre-existing; the suite went from failing
  about one run in five to six clean runs in a row.

  **`variants.build_planar_deck` could return a short deck.** It sampled
  exactly ``size`` cards, then dropped every phenomenon past RULE 901.15's
  `MAX_PHENOMENA` — with nothing to replace them, so ~6% of decks came back
  with 9 (or 8, or 7) cards instead of 10, which is what made
  `test_a_planechase_game_starts_with_a_face_up_plane` fail intermittently.
  It now *deals* off a shuffle of the whole pool, skipping a phenomenon once
  the cap is reached, so the deck is always full size. Worth noting why it
  isn't the obvious one-line fix ("take exactly `MAX_PHENOMENA` phenomena,
  fill the rest with planes"): that would have made every planar deck hold
  exactly two phenomena, where both the old code and the real thing have a
  *random* number up to the cap. Dealing preserves that (measured over 500
  builds: 0/1/2 phenomena in roughly a 28/45/27 split, always 10 cards,
  always a plane on top per RULE 901.9).

  **A registration race in the `/ws/game/{id}` broadcast test.**
  `TestClient.websocket_connect` returns once the *handshake* is accepted,
  one step before `GameConnectionManager.connect` adds the socket to the
  broadcast room (it registers after `await websocket.accept()`). A second
  client that connected and immediately expected a broadcast could therefore
  miss it and block until the 20s pytest-timeout. Fixed in the test — it now
  round-trips one message of the second client's *own* first, which can only
  be answered by the receive loop, i.e. after registration. Deliberately not
  fixed by registering before `accept()`: another connection's broadcast
  could then hit a socket mid-handshake, and Starlette raises on a send
  before accept. The window is only reachable by a client that connects and
  expects a broadcast in the same instant, which no real client does.

### Banner colours (2026-07-28)

A seat's `banner_color` (`services/lobby.py`) — the colours the shared
board paints that player's title bar in, set in Setup. Purely cosmetic, so
the interesting decisions are all about *where* it lives:

- **In the lobby, not in the game.** It's a property of the person at the
  table rather than of the `GameState`, and it has to be visible to
  everyone in Setup, i.e. before there is a game at all. It rides the
  lobby snapshot that already reaches every client, so no view, session or
  engine field was touched — `gameBoardView.js` reads it through the same
  `seatStatus` hook multiplayer already uses for "this player dropped".
- **Normalized, not validated** (`normalize_banner_color`, next to
  `normalize_name` for the same reason): any subset of `wubrg` in any
  order collapses to the WUBRG-ordered key, and anything unrecognizable to
  `"c"`, the grey colourless banner. `None` stays `None` — "not chosen" is
  distinct from "colourless". A cosmetic typo isn't worth a 400.
- **It does not clear acceptance**, the only table setting that doesn't
  (`set_banner_color` deliberately skips `_unready`): it changes how a
  banner looks and nothing about the game anyone accepted, so re-asking
  the table to accept would be noise.
- **The default is the deck's colour identity** — `api/multiplayer.py`'s
  `_default_banner_from_deck`, run when a seat picks a deck and has no
  banner yet. In the API layer because the lobby is rules-free and has no
  idea what colours a deck has; at all because "pick your deck, then also
  pick your colours" is a step nobody wants to take twice. An explicit
  pick is never overwritten by a later deck change, and an identity that
  hasn't been computed yet (`None`, unlike an empty list, which is a
  genuinely colourless deck) leaves the seat unpainted.

`Lobby.set_deck`'s seat-permission logic ("your own seat, or a bot's if
you're the host") was extracted to `_seat_to_configure` and shared, rather
than copied into `set_banner_color`.

- [x] **ENG-15 · Subset attacker selection — closed, no new work needed.**
      `BACKLOG.md` still described the pre-multiplayer state ("swings with
      every able creature, one control"), but `GameEngine.declare_attackers`
      has been additive since the combat-restriction family shipped (RULE
      508.1a's "…alone" needed to reject the *finished* attack, not the
      first creature declared into it — see "Combat statics" above), and the
      multiplayer batch's `legal_defenders_for` (this section, "every
      opponent is offered as a defender") already lets each call assign its
      own defender. Nothing was blocking a per-creature UI on the backend
      side; the ticket had simply never been re-checked against the engine
      after that work landed. Verified with two separate `declare_attackers`
      calls in a 3-player pod, each with a different attacker/defender pair
      — both stay attacking with their own `combat_defender` afterward.
      Paired frontend ticket: VIS-3 (`Done_Frontend.md`).

## Bot AI (UC5)

`mtg_analyzer/services/bots.py`, plus bot seats in `services/lobby.py` and
the routes in `api/multiplayer.py`; tests in `test_bots.py` (22) and
`test_api_multiplayer.py::TestBots` (12).

Shipped 2026-07-27. A bot is a **player at a multiplayer table**, not a
mode: the host seats one from the Setup tab, picks a deck for it, and the
game that starts is an ordinary `GameSession`. Two are built on the base
class — a **Goldfisch** (plays lands, otherwise passes) and a **greedy**
bot (plays everything the moment it can, attacks with everything, blocks
with everything, takes the first legal target).

- [x] **The bot plays through the client surface, and only that.** A bot
      reads `GameSession.view(perspective=<its own id>)` — the same
      RULE 400.2-redacted payload a browser gets, so an opponent's hand and
      every library are simply not in the data it sees — and may only
      submit entries from its own `legal_actions`, through
      `apply_action(action, actor_id=...)`. That is the whole design: the
      engine's existing per-player validation is what makes a bot legal,
      so a bot cannot cheat without the same bug letting a human client
      cheat, and every bot game is an end-to-end test of the redaction.
      Reading `engine.state` directly would have been far easier and is
      deliberately not done anywhere in `bots.py`.
- [x] **`Bot` (the base class) is policy hooks over a fixed skeleton.**
      `decide(view, actions)` fixes the *order* a seat must handle things
      in — answer a `pending_choice` first, then the setup/mulligan
      question, then RULE 509.1a declare-blockers (a turn-based action the
      defending player takes while the *attacker* holds priority, so it is
      checked before the priority gate), and only then, if this bot holds
      priority, `play()`. Subclasses override the policy, never the order:
      `setup()`, `answer_choice()`, `blocks()`, `play()`, `rank_targets()`.
      `pick_targets()` fills a `{TARGET}`-style requirement from the
      offer's own candidate list (respecting `count`, RULE 115.1a's "up
      to", and `distinct_controllers`) and returns None when a mandatory
      requirement can't be met, so the bot skips that offer instead of
      posting something illegal.
- [x] **Bots are driven externally, not by a loop of their own.**
      `run_bots(session, bots)` applies one action at a time, re-reading
      the view between each, and is called from three places: after any
      human action (`api/multiplayer.py`'s `_after_move`), right after
      `lobby.start()` (so a bot keeps its opening hand before the humans
      are shown the mulligan screen — nobody is going to click "Behalten"
      for it), and once a second from the watchdog sweeper
      (`api/multiplayer_ws.sweep_once`), which is what drives a table with
      no human at it at all. Running *before* the broadcast is deliberate:
      a human's move and every bot response it provokes reach the clients
      as one push, so no board ever shows half a bot turn.
      `MAX_BOT_ACTIONS` (200) is a yield point rather than an error budget
      — a bot-vs-bot table simply resumes on the next call.
- [x] **A bad offer can't wedge the table.** If an action a bot chose
      raises `GameActionError`, the bot records that offer's signature in
      `_failed` (so it won't re-pick it) and passes priority, which is
      always legal. This is what keeps an unmodeled corner of a card from
      turning into a hung game rather than a skipped play.
- [x] **`GreedyBot` — "stupid and greedy", by specification.** Attack with
      everything first; then, in its own main phase with an empty stack,
      play a land, tap for mana (picking whichever colour it holds least
      of), then cast/activate, cheapest first with `{X}` spells last (and
      never `{X}`=0, which is a real offer and always a waste). Blocks by
      spreading its untapped creatures across the attackers. Targets are
      ranked "the opponent's things first", which is wrong about as often
      as it's right and is exactly the level of thought asked for.
- [x] **Bot seats in the lobby (`services/lobby.py`).** A bot gets an
      ordinary `LobbyPlayer` and `Seat` (`Seat.bot_kind` is the only new
      field, opaque to the lobby — `api/multiplayer.py` validates it
      against `BOT_TYPES`), so the rules engine never learns that bots
      exist. Three consequences are handled explicitly: a bot seat with a
      deck counts as **ready** (it has no client to accept), a bot is kept
      out of `players()`/`idle_players()` (it isn't a person, and has no
      socket to sweep), and a table whose last *human* leaves is dropped
      along with its bots (`has_human_seat`) rather than left playing
      itself forever. The host acts for a bot throughout:
      `set_deck(..., seat_id=...)`, `add_bot`, `remove_bot`.
- [x] **`GameEngine._cast_action` now carries `mana_value`.** A client
      offered several casts had no way to order them by cost without
      re-deriving it; the bot needs exactly that to cast cheapest-first.
      Added alongside the existing `has_x`/`max_x`.

## cEDH staples cube

- [x] **Batch 25 (2026-07-22): all 43 cards of the cEDH cube pool.** The
      whole "cEDH staples cube" section moved here from
      `docs/implementation-state/BACKLOG.md`; that file now keeps only the narrow
      simplifications each shipped card documents in its own
      `game/ability_catalogue.py` entry. Every card is registered, binds,
      and is playable; 91 new tests across six files
      (`test_cedh_cube_state_tracking.py`, `_mana_primitives.py`,
      `_control_and_zones.py`, `_loops_and_naming.py`,
      `_keyword_mechanics.py`, `_bespoke_tail.py`).

      Organized as six waves, each around the primitive its cards actually
      needed rather than card-by-card:

      **Wave 1 — state the engine never recorded.** These cards weren't
      blocked on an effect but on a *fact* that couldn't be re-derived
      after the event:
      - `GameObject.mana_spent_to_cast` + the `SPELL_CAST` event's
        ``mana_spent`` key (RULE 202.1/601.2h) — deliberately **not** the
        pre-existing ``free`` flag: a spell cast for an alternative cost of
        {0}, or reduced to {0}, spends no mana while still being a paid
        cast, and that is most of why Lavinia, Azorius Renegade and
        Boromir, Warden of the Tower are played. "Counter that spell" is
        the RULE 603.3d ``reflexive`` trigger shape, whose docstring had
        named these two cards as its motivating example since it was built.
      - `continuous.cast_prohibited`'s new ``cast_prohibition`` static
        (RULE 601.3a) — the *conditional* sibling of ``cast_limit``'s flat
        per-turn count, with its ``max_mana_value_selector`` evaluated for
        the **casting** player rather than the static's controller
        ("*that player*'s lands"), which is exactly why it can't be a layer
        value. Lavinia's other half.
      - `GameState.combat_damage_to_players_this_turn`, the
        ``player_dealt_combat_damage_by_source`` target kind, and the
        player-scoped `PlayerCastRestrictionEffect` — Hope of Ghirapur,
        whose target is a *history* question no live board state can answer
        and whose lock has no permanent behind it (it sacrificed itself).
        Introduced the ``until_next_turn_of`` duration key
        `GameEngine.begin_turn` sweeps, reused by three later cards.
      - `continuous.count_selector` gained ``devotion_to_<colour>`` (RULE
        202.2f, hybrid pips counting for both colours),
        ``legendary_creatures_you_control`` and
        ``cards_named_source_in_all_graveyards`` — Thassa's Oracle (whose
        RULE 104.2a win routes through the same `player_wins` choke point
        Jace, Wielder of Mysteries uses), Eiganjo, Seat of the Empire (via
        `ActivationCost.dynamic_reduction`'s new ``count_selector``), and
        Rite of Flame (via `AddManaEffect.amount_selector`).
      - `GameObject.sacrificed_cost_mana_value` +
        `SearchLibraryEffect.mana_value_from`/``extra_counters`` —
        Eldritch Evolution/Neoform. `StackItem.x` only ever threads an
        *announced* {X}, so an additional cost's sacrificed permanent
        needed its own channel.
      - Giver of Runes' "another" restriction closed with a new
        ``other_creature_you_control`` target kind — which also **fixed a
        latent inversion**: `creature_you_control` had been excluding the
        source, so Mother of Runes couldn't protect herself and a Karoo
        land couldn't bounce itself (both legal, occasionally-correct
        plays). Only a kind that actually says "another" excludes it now.

      **Wave 2 — mana.** The headline is the **triggered mana ability**
      (RULE 605.1b/605.4, `TriggeredAbility.mana_ability`): an ability that
      triggers off a mana ability and produces only mana never uses the
      stack — it resolves on the spot, so its mana is spendable within the
      payment that triggered it. Queueing it would deliver the mana one
      full stack resolution too late, which is the entire reason Wild
      Growth and Kinnan, Bonder Prodigy are played.
      - `GameContext.trigger_event` (RULE 603.1) exposes the firing event
        for exactly one resolution window, threaded onto
        `StackItem.trigger_event` through every pause/resume path. Lets an
        effect depend on *which* firing without every `apply()` growing an
        event parameter; the `TriggeredAbility` docstring's "bake per-firing
        data into freshly-built effects" pattern stays the answer whenever
        the ability's *shape* varies, this covers the commoner case where
        only a value does. Used by six cards across waves 2–4.
      - `MirrorProducedManaEffect` (Kinnan — narrower than `AddManaEffect`'s
        ``"ANY"``: only what that permanent *did* produce) and
        `TapMatchingLandsEffect` (Mana Web — deliberately reading what a
        land *could* produce, RULE 605.1a, so a dual tapped for {U} still
        locks down every land making its other colour).
      - `pay_cost_then` (RULE 118.3) — the general form of the shipped,
        energy-only `PayEnergyThenEffect`, on the same
        `_can_pay_player_cost`/`_pay_player_cost` machinery ward and
        "sacrifice ~ unless you pay" already share, with an "if you don't"
        branch and an event-named payer. Mana Vault's upkeep untap; reused
        by Wandering Archaic and both Pacts. Mana Vault also brought a
        ``source_state`` intervening-if (RULE 603.4 about the ability's own
        source, alongside the event- and turn-scoped flavours) and a
        ``controller`` damage selector.

      **Wave 3 — control & zones.**
      - `ExchangeControlEffect` (RULE 701.10) — a genuine two-way swap,
        which neither shipped shape could express: the layer-2
        ``control_change`` static reassigns one permanent while its source
        lasts, and `GainControlUntilEndOfTurnEffect` is a one-way,
        duration-bounded grab. Modeled as a one-shot `controller_id` swap
        precisely so Gilded Drake dying afterwards doesn't hand the creature
        back. Also fixed a RULE 115.1a bug on the way: an "up to one target"
        trigger with **no** legal target was being dropped, when choosing
        zero targets is itself legal — which is what makes Gilded Drake
        sacrifice itself on an empty board.
      - `PhaseOutAllYouControlEffect`/`PlayerShieldEffect` — mass phasing
        (RULE 702.26b, with host and attachment phasing *together* per RULE
        702.26e, unlike the single-permanent `PhaseOutEffect` which
        unattaches), plus "your life total can't change" (RULE 119.6, a
        prohibition checked at the `gain_life`/`lose_life` choke points, not
        a replacement) and player-side protection from everything (RULE
        702.16e). Teferi's Protection.
      - `RulesEngine.move_spell_off_stack` (RULE 400.1) — pulling a
        `StackItem` into hand or exile, which no existing bounce could do
        (they all move battlefield permanents). Practically a counter that
        sends the card somewhere other than the graveyard, which is why
        Narset's Reversal and Possibility Storm both beat "can't be
        countered".
      - `ReturnSharedTypePermanentEffect` (Cloudstone Curio — the legal set
        depends on the *entering* permanent) and
        `PutFromHandOntoBattlefieldEffect` (Tooth and Nail — every other
        "put onto the battlefield" moves from a library or graveyard;
        reuses `request_search` against a new ``"hand"`` zone, which
        correctly neither shuffles nor fires `LIBRARY_SEARCHED`).
      - Reiterate needed **nothing new** — Buyback and `CopySpellEffect`
        were both already built (the latter's docstring even named the
        card); it was simply never registered, so the fail-closed gate left
        it unmodeled.

      **Wave 4 — naming a card, and the three loop shapes.** Four
      separately-listed blockers, all closed:
      - `RulesEngine.request_name_card` — the only choice in the engine
        whose answer space isn't enumerable from game state. Offers the
        names the player can see as *suggestions* while accepting an
        arbitrary string, substituted into a ``"named_card"`` criteria
        sentinel (the naming counterpart of `_substitute_x`). The string is
        only ever compared against card names, never interpreted, so docs/09's
        security boundary is intact.
      - `RulesEngine.dig_until` — the cascade/discover dig with the
        predicate and both destinations made parameters, plus a ``not_name``
        key on `models.card_query`. Demonic Consultation (naming a card
        that *isn't* there exiles the library, which is the actual cEDH
        line into Thassa's Oracle).
      - `MillUntilCreatureEffect` — the first **repeat-until-a-predicate**
        loop; every other repetition primitive had its count fixed before
        it started. Bounded on both sides by construction (X caps it, an
        empty library ends it early), which is what makes having the
        primitive safe. Helm of Obedience.
      - `request_look_top_pay_life_loop` — the first **open-ended** loop,
        bounded by its own life payment rather than a safety cap (RULE
        118.4), driven by a self-re-opening `pending_choice`. Lim-Dûl's
        Vault.
      - `ScrambleSpellEffect` — Possibility Storm and Tibalt's Trickery,
        which differ only in how the spell is answered and what the dig
        looks for. One atomic effect because every clause is about the same
        spell and **its** controller (never the caster). Possibility Storm
        also drove the `SPELL_CAST` event's new ``from_hand`` key.

      **Wave 5 — RULE 702 keywords that had recognition but no behaviour.**
      - **Fading (RULE 702.32)**, both halves on the keyword rather than on
        Tangle Wire, so every Fading/Vanishing card gets them: entry
        counters read off the *parsed keyword* (not the reminder sentence,
        which needn't be printed), and the upkeep "remove one or sacrifice"
        synthesized alongside annihilator/afflict/bushido. Note "if you
        can't" means no counter left, which is why Fading N lasts N+1
        upkeeps.
      - **Soulbond (RULE 702.94)** — real pairing state
        (`GameObject.paired_with`, on both objects) rather than a
        continuous effect, because RULE 702.94c breaks it on *events*;
        swept as an SBA so no removal site has to tear it down. The grant is
        an ordinary layer-6 static over a new ``soulbond_pair`` selector
        that resolves to nothing while unpaired. Deadeye Navigator.
      - **Mutate (RULE 702.140)** — an alternative cast cost that merges
        onto its target instead of entering the battlefield. The **host**
        stays the surviving `GameObject` per RULE 702.140c, so counters,
        damage, Auras and summoning sickness carry over and no ETB trigger
        fires; "all abilities from under it" banks both the oracle text and
        the keyword list, re-derived through the ordinary bind path. New
        `EventType.MUTATES`. Lore Drakkis.
      - **Bargain** — a genuinely payable optional additional cost plus an
        ``"if bargained"`` `EffectSpec.condition`, the exact shape Kicker's
        ``"kicked"`` gate already had. Beseech the Mirror.
      - A **granted** Escape (RULE 702.138 from a permanent rather than
        printed on the card) — `continuous.granted_escape_for`, consulted
        by `_graveyard_cast_keyword`/`_escape_cost`, which is why the rest
        of the escape machinery needed no change. Underworld Breach.
      - The **Pacts** needed nothing new beyond wave 2's `pay_cost_then`:
        `CreateDelayedTriggerEffect` had named them in its docstring since
        it was built. Corpse Dance's long-deferred "exile it at the
        beginning of the next end step" also closed, kept inside the
        returning effect because only it knows which object "it" is.

      **Wave 6 — the bespoke tail.** The shared primitive is **two
      independently-chosen targets of different kinds in one clause**
      (`GameEffect.extra_target_specs`): the gathering paths
      (`_trigger_target_specs`, `spell_target_specs`) now read
      `target_specs` (plural), and `_apply_effects_partitioned` hands such
      an effect all of its groups flattened. That one change closed the
      whole "two independent targeting effects on one ability" entry —
      Brass Squire, Halvar God of Battle, and Archdruid's Charm's second
      mode (which *must* be atomic: the damage reads the target's power
      after the +1/+1 counter lands).
      - New target kinds: ``creature_you_dont_control``,
        ``artifact_or_enchantment``,
        ``attached_aura_or_equipment_you_control``.
      - `DestroyEachWithManaValueEffect` (Dauntless Dismantler — a mass
        destroy whose *filter* is the announced X; its "artifacts your
        opponents control enter tapped" half was already shipped).
      - `SacrificeEffect` gained ``each_opponent`` and ``greatest_power``
        (the one place the engine's arbitrary auto-pick would be actively
        *wrong*) and a registry entry — it had only ever been reachable
        from the annihilator keyword. Professor Onyx.
      - `GainControlOfAllCommandersEffect` (RULE 903.3, Tevesh Szat) and
        `MultiplyDamageFromTargetEffect` (Jeska — RULE 616.1 scoped to one
        source / combat only / your opponents and duration-bounded, reusing
        the replacement machinery rather than a new one), plus RULE
        606.5c's ``[-X]`` loyalty cost (`ActivationCost.loyalty_is_x`).
      - Dress Down and Pemmin's Aura needed no new engine work at all —
        the board-wide ability strip and the Aura pump/untap effects were
        already shipped; Pemmin's inline "A or B" is split into two
        activated abilities, which is faithful (choosing which to activate
        *is* the printed choice).

### Batch 26 (2026-07-22) — closing the documented residue

Batch 25 left nine narrow simplifications behind, each recorded in its
card's `game/ability_catalogue.py` entry and mirrored in
`docs/implementation-state/BACKLOG.md`. All nine are now closed. Six of them needed a
genuinely new mechanism; the rest fell out of those.

- [x] **RULE 608.2 suspended resolutions** — the prerequisite nothing else
      could be built on. `GameState.pending_choice` holds exactly one
      decision, so a resolution with 2+ interactive effects used to let the
      second silently overwrite the first player's prompt.
      `game/effects.py`'s `_apply_effects_partitioned` now parks the
      remainder of the list on `GameState.deferred_effects` whenever an
      effect opens a choice, and `RulesEngine.resume_deferred_effects`
      (driven from `GameEngine.resolve_until_stable`) picks it back up
      afterwards — innermost first, before anything else on the stack, since
      those effects still belong to the same resolving object. The same
      change unified the two per-effect target-partitioning loops
      (`_apply_stack_item`'s and the nested wrapper's) onto one code path.
      A latent correctness bug, not just an enabler: it was reachable by any
      multi-clause ability whose clauses both prompt.
- [x] **Entwine (RULE 702.42a)** — a real priced modal upgrade rather than
      the free RULE 700.2e ``or_both`` flag Tooth and Nail was borrowing.
      The ``entwine`` key on a modes block (`AbilitySpec.modes`, bound onto
      `GameObject.spell_modes_entwine`) makes `_modal_cast_actions` offer a
      *second, separately-priced* "choose all" action that locks when its
      cost isn't affordable, and `_cast_current_face` refuses
      ``mode="both"`` on an ordinary "choose one" block unless that cost is
      actually being paid. Getting the both-modes line for free had made
      Tooth and Nail strictly better than printed. The same pass threaded
      `buyback`/`mutate`/`bargained`/`entwine` through
      `services/game_session.py`, which had never forwarded them — so the
      Buyback toggle `legal_actions` already advertised was unusable.
- [x] **Conditional search destinations (RULE 701.19c)** —
      `SearchLibraryEffect.destination_if`, a list of
      ``{"criteria", "destination"}`` rules checked per *found card*, first
      match winning. Unlike the shipped positional ``destinations`` (fixed
      when the search opens), this can only be resolved once the player says
      what they found: Archdruid's Charm's "onto the battlefield tapped **if
      it's a land card**. Otherwise, put it into your hand."
- [x] **Face-down exile + a conditional cast window (RULE 701.20a)** —
      Beseech the Mirror's round trip is real now. A search destination of
      ``"exile_face_down"`` sets `GameObject.face_down_in_exile` (rendered
      as a card back by `gameBoardView.js`'s `resolveImageUrl`, the first
      genuinely reachable use of the sleeve fallback), and
      `CastExiledFaceDownEffect` hands out Rebound's own exile free-cast
      window (`RulesEngine.grant_free_cast_window_from_exile`, renamed from
      the Rebound-specific name) so the card is cast through the ordinary
      action loop with full targeting. The "put it into your hand if it
      wasn't cast this way" half is a `DelayedTrigger` at the next end step —
      or immediate when the card was never eligible. Note the two halves
      have *different* conditions, which is why this isn't a
      `ConditionalEffect` around a single cast: only the cast is gated on
      ``bargained``.
- [x] **The Ring tempts you (RULE 701.51)** — a whole designation
      subsystem, built the way Monarch and Initiative were.
      `Player.ring_level` (0–4) *is* the emblem: unlike a RULE 114 emblem
      there's no quoted card text to parse, the four abilities are fixed by
      the rules and all read live state, so nothing is created in the
      command zone. `Player.ring_bearer_id` is RULE 701.52a's designation,
      re-chosen on every temptation (an interactive ``ring_bearer``
      `pending_choice` with 2+ creatures, forced with one, none with zero)
      and swept by the SBA pass when its creature stops qualifying.
      Ability 1 splits across `continuous._apply_ring_bearer_static`
      (layer 4 legendary — the first `GameObject._granted_legendary`, and
      the reason `is_legendary` is no longer a straight card read) and
      `GameEngine.can_block` (the greater-power blocking restriction);
      abilities 2–4 are built fresh per firing by
      `RulesEngine._collect_ring_triggers`, source-less like the monarch's,
      so each follows the *current* Ring-bearer rather than whoever was
      bearer when the level was gained. Boromir, Warden of the Tower's
      sacrifice ability now tempts for real.
- [x] **A general interactive object chooser** — `RulesEngine.
      request_choose_objects`, which replaced the "auto-pick the first
      candidate" convention across seven cards at once. Every effect that
      names *what kind* of object to act on but leaves *which one* to a
      player routes through it: Cloudstone Curio's bounce, Tangle Wire's
      tap, Deadeye Navigator's Soulbond partner, Tevesh Szat's and
      Professor Onyx's sacrifices, Thassa's Oracle's "put **up to one** of
      them on top", Lim-Dûl's Vault's final ordering. Offered one object at
      a time like a library search (same UI shape, same undo granularity),
      with the whole decision — candidates, action, picks so far, "if you
      do" follow-ups — held as plain data on `pending_choice` so it survives
      the `clone()` undo snapshots take. That data-not-closure constraint is
      what `then_specs`/`then_specs_if_commander` exist for: Tevesh Szat's
      "**if you do**, draw two cards" and RULE 903's "if a commander was
      sacrificed this way" can only be decided *after* the pick, and are
      carried as serialized `EffectSpec` dicts through
      `_apply_effect_specs`. A forced choice with no room to decide (N or
      fewer candidates, not optional) still applies without prompting.
      Kinnan's produced-type pick reuses the existing
      `add_mana_any_color` choice instead, narrowed to what that permanent
      actually produced — safe to open mid-mana-ability (RULE 605.4) only
      because `tap_for_mana` is a discrete player action, not a payment step.
      Professor Onyx's −8 needed one more thing: seven rounds × N opponents
      of "discard, or lose 3 life?" can't be a Python loop when only one
      choice may be pending, so both branches of each `pay_cost_then` carry
      a bookmarked continuation spec that opens the next round.
- [x] **The optional free cast is offered, not taken** — Tibalt's Trickery
      and Possibility Storm both print "they **may** cast that card", which
      was being force-cast. `dig_until`'s new ``"cast_free_window"``
      destination grants the same exile window Rebound and Beseech use, and
      arms `ReturnUncastExiledEffect` (the generalized "…if it wasn't cast
      this way" tail) to bottom the card at the next end step otherwise.
      Tibalt's "choose 1, 2, or 3 at random" stays random — that's the card,
      not a shortcut.
- [x] **Mutate under the pile (RULE 702.140b)** and its real target line.
      `mutate_onto(..., under=True)` keeps the *host's* characteristics and
      merges the mutating card's abilities instead; which direction applies
      is chosen as the spell is cast (`GameObject.mutate_under`, RULE
      702.140a), and only which card supplies the printed face differs. The
      host is now validated against a genuine ``non_human_creature_you_own``
      target kind — *ownership*, not control (RULE 108.3), and Humans really
      excluded — checked by `can_cast`/`_cast_current_face` directly, since
      a mutate creature spell carries no targeting *effect* for the ordinary
      RULE 115 machinery to read. Fixed a latent bug on the way: the merge
      used to rewrite the shared printed `Card` in place.
- [x] **RULE 305.7 land-type ability removal** — setting a land's subtype to
      a basic land type strips its rules text and abilities, so a
      Blood-Moon'd Underground Sea makes only {R} and a Blood-Moon'd
      Wasteland can't be activated at all. Implemented by having the layer-4
      subtype overwrite also set `_loses_all_abilities`, and by teaching
      `mana_abilities_for` to honour that flag — which it never did, so
      Humility and Dress Down had the same hole. The replacement basic
      type's intrinsic mana ability survives precisely because that function
      reads the *granted* list separately from the printed one.
- [x] **The compact inline "A or B" activated ability (RULE 700.2)** —
      `segmenter._inline_pt_modal_bodies` rebuilds "gets +1/-1 **or** -1/+1
      until end of turn" as two complete clauses and emits one activated
      ability each, so Pemmin's Aura parses without hand-authoring. Only
      tried once the ordinary parse has already failed, and only on two full
      P/T clauses — every *other* " or " in an effect body ("target artifact
      or enchantment", "Add {W} or {U}") joins two nouns, not two effects.
      `Segment.extra_specs` is the small plumbing that lets one printed line
      yield two abilities.

Two pre-existing bugs surfaced and were fixed on the way, beyond the ones
noted above: `LoseLifeEffect` gained a ``player_id`` form (a specific
player named by id is the only form a serialized spec can carry), and
`RulesEngine._matches_permanent_type` learned ``creature_or_planeswalker``.
Coverage moved 25.3% → **25.4% (8,672 / 34,209)**, PARSER_VERSION 28.


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
- [x] `Deck.is_cube` flag (2026-07-17) — marks a saved decklist as a card
      pool (e.g. a curated "cEDH staples" reference list with hundreds of
      cards, no fixed size) rather than a real, legal Commander deck.
      `parser/deckliste_parser.py`'s `_validate_commander_deck`/
      `parse_deck_sections` and `services/deck_validation.py`'s
      `apply_legality`/`validate_deck_sections` all gained an `is_cube`
      param that skips their checks entirely (structural: 100-card total,
      singleton, commander count; semantic: ban list, color identity,
      Partner) rather than reporting a cube's inherent "violations" as
      errors — mirrored client-side in `parser.js`. Same
      preserved-on-omission save semantics as `author`/`sleeve_id`
      (`api/saved_decks.py`'s `save_deck`, `api/schemas.py`'s
      `SaveDeckRequest.is_cube: Optional[bool]`). Tests:
      `test_deckliste_parser.py::TestCubeSkipsStructuralValidation`,
      `test_api_decks.py::test_is_cube_skips_structural_and_legality_checks`,
      `test_api_saved_decks.py` (save/preserve/validation-skip cases).

## Import — follow-up from the frontend

- [x] Server-side Archidekt import proxy (`GET
      /api/import/archidekt/{deckId}`) — Moxfield (`docs/implementation-state/BACKLOG.md`
      "Import — follow-up from the frontend") was tried client- and
      server-side and reverted both times (genuinely Cloudflare-blocked);
      Archidekt's API has no such protection — confirmed live, a plain
      unauthenticated `GET https://archidekt.com/api/decks/{id}/
      ?format=json` returns real deck JSON straight from nginx/Google
      infra. `services/archidekt_client.py`'s `ArchidektClient` (mirrors
      `ScryfallIntegration`'s shape, DI'd via
      `api/dependencies.py.get_archidekt_client`) fetches that endpoint
      and converts `cards: [{quantity, categories: [...], card:
      {oracleCard: {name}, displayName}}]` into decklist text: a card
      goes to `commanderText` if its `categories` includes "Commander",
      to `sideboardText` if "Sideboard", else `mainboardText`; a category
      the deck itself flags `includedInDeck: false` (e.g. a Maybeboard)
      is dropped entirely rather than landing in any section. `deck_id`
      accepts a bare numeric id or a full pasted deck URL
      (`extract_deck_id`); a non-digit id is rejected as 400 before any
      request is made, since Archidekt's own routing 404s in a
      misleading way (a "client routes" error page) for anything
      non-numeric. Route is `{deck_id:path}`, not the default
      single-segment converter, for the same reason as the reverted
      Moxfield route (a URL-shaped id survives `encodeURIComponent` as
      `%2F`, decoded back to a literal `/` by Starlette before routing).
      `api/import_external.py` registers the router; response shape
      (`{name, commanderText, mainboardText, sideboardText}`) matches
      what `POST /api/decks` / `/api/decks/save` expect. Frontend:
      `Done_Frontend.md` "Import". Tests: `test_archidekt_client.py`.

## MEC-4, MEC-6, MEC-7, MEC-8, MEC-9 batch (2026-07-29)

Five independent, narrowly-scoped engine gaps closed together —
`tests/test_mec_batch_4_6_7_8_9.py`.

- [x] **MEC-6 · Embercleave's own cost reduction.** The self-scoped "cost
      {N} less to cast for each `<board count>`" primitive
      (`continuous.self_cost_reduction_for`/`_cost_static_amount`'s `per`
      param, `effects.py`'s `cost_reduction` factory with
      `affects="self"`) already existed for Delve/Affinity's shape but had
      never actually been exercised by any shipped card. Closed by adding
      the one missing `count_selector` entry, `attacking_creatures_you_
      control` (plus its unscoped sibling `attacking_creatures`, live off
      `GameObject.attacking`, RULE 508.1) — Embercleave's hand-authored
      catalogue entry now uses it instead of the previous "always costs
      its full {3}{R}{W}" documented gap. A parser handler
      (`static_handlers._SELF_COST_REDUCTION_ATTACKING_RE`) recognizes
      the oracle-text template directly, which also newly models Ancient
      Stone Idol's bare "for each attacking creature" (no "you control")
      variant for free.
- [x] **MEC-7 · Timely Ward's conditional flash.** `"targets_a_commander"`
      joined `ALLOWED_CAST_CONDITION_KEYS`; unlike `"entered_this_turn"`
      (checked purely off the object/state), this one depends on a choice
      the caster hasn't made yet at the point `GameEngine.can_cast` first
      needs an answer — RULE 601.2c (choose targets) comes *after* the
      timing-permission check RULE 601.3a gates, not before. Resolved by
      threading an optional `targets` param through `can_cast`/
      `effective_cast_cost`: omitted (every offer-time preview caller),
      `condition_query.conditional_flash_holds` answers optimistically
      (legal to *offer* the flash-speed cast whenever a commander exists
      anywhere in play or a command zone); supplied (the real cast,
      `_cast_current_face` already has the chosen `targets` in hand),
      it's checked and enforced for real. Timely Ward's hand-authored
      catalogue entry now carries `conditional_flash={"targets_a_
      commander": True}` instead of the previous documented gap. The
      segmenter recognizes the oracle-text template too
      (`_CONDITIONAL_FLASH_IF_TARGETS_COMMANDER_RE`), though only on the
      instant/sorcery `allow_spell_effect` path — an Aura like Timely Ward
      itself still needs the hand-authored entry, since `gate.py` never
      offers a permanent's own lines that route (RULE 601.2f/702.8b
      condition lines have so far only ever appeared on instants in
      practice, Timely Ward being the one exception).
- [x] **MEC-4 · Strive.** Genuinely not a RULE 702 keyword — no CR entry
      defines it, unlike every other parametric keyword in `keywords.py`'s
      table — so `AbilitySpec.strive_cost` rides as its own field the same
      "own oracle-text line, standalone from the spell's actual effect"
      way `conditional_flash`/`free_cast_condition` do, rather than going
      through the RULE-702-numbered keyword catalogue.
      `effect_binder.attach_to_object` parses it into a real `ManaCost` on
      `obj.strive_cost`; `GameEngine.effective_cast_cost` gained the same
      `targets` param MEC-7 added and adds one full copy of the cost per
      target *beyond the first* — a full `ManaCost.add()`, not just a
      generic delta, since real Strive costs are usually colored ("costs
      {2}{U} more", not just "{1} more" — only 1 of the 20 real cards is
      generic-only). Unlike MEC-6/7, this one lands with **zero** cards
      reaching full `MODELED`: every real Strive card pairs its own line
      with "any number of target creatures `<effect>`", a separate,
      unmodeled targeting family (`PAR-15`, filed while scoping this
      ticket) — Strive's own clause parses cleanly
      (`segmenter._STRIVE_LINE_RE`) and the cost math is tested directly
      against the engine primitive, but no real card clears the whole
      card's fail-closed gate yet.
- [x] **MEC-8 · An emblem's own activated ability.** RULE 114.4 permits
      one; `RulesEngine.create_emblem`'s bind step used to route only
      `TriggeredAbility`/`StaticAbility`, silently dropping an
      `ActivatedAbility` returned by `bind_ability` (and, spotted in the
      same `if`/`elif` chain, a compound multi-event trigger's *list* of
      `TriggeredAbility` too — both fixed together). `models/emblem.py`
      gained `activated_abilities`/`granted_activated_abilities` (the
      latter always empty — nothing grants an emblem an ability — kept
      only so the `source.activated_abilities + source.granted_activated_
      abilities` idiom every activation call site already uses needs no
      special-casing), an `instance_id` sharing `GameObject`'s own
      counter, and a `name` ("Emblem") for the error-message/UI-label
      formatting those call sites already do. `can_activate` gained an
      `Emblem`-shaped branch alongside its permanent-membership check;
      `legal_actions` offers a controlled emblem's activatable abilities
      the same way it offers a permanent's; `GameState.find_object`
      searches `player.emblems` after every zone, so the wire round-trip
      (`instance_id` → dispatch → `activate_ability`) works unchanged.
      The parser's own emblem-quote handler
      (`catalogue/handlers.py`'s `_emblem_ability_spec`) previously hard-
      rejected any `ability_kind == "activated"` nested spec outright
      (`else: return None`) — widened with the same fail-closed
      self-referential guard ("sacrifice this"/"equipped creature…" would
      be meaningless with no host permanent) the triggered/static
      branches already apply. No real cached card prints an emblem with
      its own activated ability, so this is engine-primitive-level
      coverage, proven end-to-end with a synthetic "{1}: Draw a card."
      emblem rather than a real card.
- [x] **MEC-9 · Designation inheritance (RULE 725.4/726.4).**
      `RulesEngine.remove_player_from_game` (the RULE 800.4a leave-the-
      game cleanup `GameEngine.begin_turn` runs once per turn for each
      `GameState.pending_leave_ids` entry) now passes a departing
      Monarch/Initiative-holder's designation to the active player before
      clearing the rest of their board. By the time this runs,
      `active_player_index` has already rotated for the turn about to
      begin (`GameState.next_active_index` skips `has_lost` players,
      which `RulesEngine.concede` sets immediately rather than deferring
      — only the RULE 800.4a battlefield/zone cleanup is deferred), so
      `self.state.active_player` is already guaranteed live and never the
      departing player itself; the rule text's "active player is also
      leaving"/"no active player" fallback (→ clear the designation) is
      honoured rather than assumed unreachable, but never actually
      exercised by this engine's turn order. RULE 726.4 says the active
      player *takes* the initiative — routed through the existing
      `RulesEngine.take_initiative` (which fires `TOOK_INITIATIVE`,
      RULE 726.2's third inherent "ventures into Undercity" trigger)
      rather than a bare field assignment, so the succession itself is
      real Comprehensive-Rules behaviour, not just a state patch; RULE
      725.4's monarch succession has no such inherent trigger, so
      `become_monarch` (a bare field set, as it already was) is enough.
      The "as long as you're the monarch"/"…have the initiative"
      conditional-static family this surfaced (56 of 64 cached "monarch"
      cards UNMODELED, mostly on exactly this shape) is a separate,
      sizeable gap — filed as `MEC-12` rather than folded into this
      ticket, since RULE 613.6's existing `active_if`/`static_conditions.py`
      machinery just needs a new condition *kind*, nothing about
      succession.

## MEC-12 · Monarch/Initiative-conditioned statics, + Ascend/city's blessing (2026-07-30)

- [x] **MEC-12.** `game/static_conditions.py`'s RULE 613.6 whitelist gains
      `is_monarch`/`has_initiative` — plain reads of `GameState.monarch_id`/
      `initiative_id` against the static's own controller, the exact shape
      `your_turn` already had (no `of` subject: "you" always means the
      static's controller). `parser/oracle/catalogue/static_handlers.py`'s
      `_STATIC_CONDITION_RES` gains the matching phrases ("you're the
      monarch"/"you have the initiative"), which is the *entire* fix —
      both printed orders ("as long as `<cond>`, …" / "… as long as
      `<cond>`.") already ride the existing `_conditional_static_specs`
      wrapper with no new engine mechanism, exactly as the ticket
      predicted. Net cached-card yield was smaller than the ticket's
      56-card estimate once measured for real (`scripts/coverage_report.py`,
      not just `grep`-ing for "monarch"): most of the 56 UNMODELED cards
      turned out to be blocked on a second, unrelated gap surfaced along
      the way — `game/parser/oracle/catalogue/static_handlers.py`'s
      `_scope`/`_NONCREATURE_TYPES` deliberately refuses "artifact
      creatures"/"permanents"/etc. as a group scope (a pre-existing,
      already-documented limitation, `CLAUDE.md`'s "Notable gaps": *"non-
      creature group scopes for the anthem/grant families"*), so
      "as long as you're the monarch, permanents you control have
      hexproof"-shaped cards still don't clear the whole-card gate even
      with the condition itself now recognized. The condition machinery
      is nonetheless real, tested directly (`static_conditions.
      condition_holds`, both printed orders via `static_effect_specs`),
      and immediately useful to every self- or already-supported-scope
      static in the family.

- [x] **Ascend / "the city's blessing" (RULE 702.131), built in the same
      batch.** Previously recognized only as a bare `keyword` spec
      (`parser/oracle/catalogue/keywords.py`'s FLAG-shape "Ascend" row)
      with **no engine behaviour bound to it at all** — a silent no-op
      exactly like `create_emblem`'s dropped `ActivatedAbility` was
      before MEC-8, and the natural companion to file the new condition
      vocabulary's third designation kind alongside (`has_city_blessing`)
      rather than leave it dangling. Unlike Monarch/Initiative
      (`GameState.monarch_id`/`initiative_id`, a single shared holder,
      RULE 725/726), the city's blessing is a plain idempotent per-player
      flag (`Player.has_city_blessing`) — RULE 702.131c: "any number of
      players may have the city's blessing at the same time" — that,
      once granted, is never cleared (702.131d: "for the rest of the
      game"). `RulesEngine.get_city_blessing` is the one idempotent
      setter both of Ascend's two printed forms share (702.131a/b give it
      two different bodies, not two different mechanics):
      - **On a permanent** (702.131b, "any time you control ten or more
        permanents…") there's no event to hang a trigger off — it's a
        live board check, so it's swept at SBA cadence exactly like the
        day/night and Ring-bearer checks already are
        (`RulesEngine._sba_check_ascend`, reading the keyword straight
        off `combat.has(obj, "ascend")` — no extra binding needed beyond
        what `attach_keyword` already does for every flag keyword; the
        selector doing the counting is the pre-existing
        `continuous.count_selector`'s `permanents_you_control`).
      - **On an instant/sorcery** (702.131a) is a one-shot resolution
        effect instead (`GetCityBlessingEffect`, registered as
        `"get_city_blessing"`), wired in `effect_binder.
        attach_to_object`'s existing keyword-handling branch: when the
        keyword's name is `"ascend"` and the bound object's card is an
        instant/sorcery, the effect is appended to `spell_effects`
        alongside whatever `attach_keyword` already did for the flag
        itself — the same object, two different consequences depending
        on what kind of card it is, since a permanent's `spell_effects`
        list is simply never read.
      Real-card yield from `has_city_blessing` alone (measured via
      `scripts/coverage_report.py`, PARSER_VERSION 44):
      **coverage 9,529 → 9,536 / 34,208** (monarch +1, city's blessing
      +6) — smaller than the 33-UNMODELED-card population the mechanic
      touches, for the same reason as MEC-12 above: most of those cards'
      *other* clauses (compound "if you have the city's blessing, …
      instead" amount overrides — the already-documented "kicked …
      instead" override-conditional gap; "activate only if you have the
      city's blessing" — a still-unmodeled activation-legality gate,
      a different family from RULE 613.6 statics entirely; non-creature
      group scopes, same pre-existing limitation as above) are the real
      remaining blockers, not Ascend or the condition itself. The
      self-scoped case works end-to-end without any further gap — Dusk
      Charger ("This creature gets +2/+2 as long as you have the city's
      blessing.") parses fully `MODELED` and its anthem live-regates on
      `Player.has_city_blessing` through the ordinary layer-engine
      recompute, tested directly rather than assumed.

## MEC-11 · "Whenever ~ is dealt damage" (Enrage) (2026-07-30)

- [x] RULE 603.1's *recipient* side of a damage trigger — the mirror image
      of `segmenter._DAMAGE_TRIGGER_RE`'s existing "deals damage" family,
      which only ever recognized a permanent *dealing* damage. Three
      pieces, none Enrage-specific despite the ticket's name:
      `normalize._ABILITY_WORD_RE` gained "enrage" (RULE 207.2c — no rules
      meaning, but the label blocks the line on its own until stripped);
      `segmenter._DAMAGE_RECIPIENT_TRIGGER_RE` recognizes "whenever ~/a
      `<type>` [you control]/enchanted-or-equipped `<type>` is dealt
      [combat] damage, …", the same self/attached/group subject grammar
      `_DAMAGE_TRIGGER_RE` already had, just the other direction, marking
      its condition `{"recipient": True}`; `effect_binder.
      _subject_event_key`/`_build_group_ok` read that marker to switch
      from the `DAMAGE` event's `source_id`/`source_controller_id` (who
      dealt it) to `target_id`/`target_controller_id` (who took it) — the
      latter a new field `RulesEngine.deal_damage` now stamps, the direct
      recipient-side sibling of `source_controller_id`. Since this is
      general RULE 603.1 recognition rather than a template gated on the
      "Enrage —" label, far more cards benefited than the ~25 that print
      it (Boros Reckoner/Brash Taunter/Fungusaur/Stuffy Doll/Spitemare-
      shaped self triggers, Rite of Passage's "a creature you control").

- [x] **A real correctness bug surfaced and fixed on the way, not shipped
      broken.** The existing "put a +1/+1 counter on it" handler's bare
      "it" pronoun had always meant the ability's own source — true of
      every prior card, since every existing family combining an implicit
      "it" with a counter/pump effect was self-subject. The new
      *group*-subject recipient trigger broke that assumption for the
      first time (Rite of Passage: "a creature you control is dealt
      damage, put a +1/+1 counter on **it**" — "it" is the *damaged*
      creature, not Rite of Passage itself, an Enchantment). Silently
      landing the counter on the wrong object would have been a
      wrong-but-`MODELED` card — strictly worse than `UNMODELED` by this
      repo's own standing rule. Fixed two ways together: `AddCountersEffect`
      gained `trigger_subject_key` (resolves its target from `GameContext.
      trigger_event` instead of defaulting to `self.source`, the same
      event-key convention `_subject_event_key` uses for the trigger's own
      condition, so the two always agree on which object "it" is); the
      segmenter's group/attached-subject branch rewrites a bare
      `add_counters` this way and, for every *other* effect shape,
      default-denies (fails the clause closed) unless it already carries a
      real RULE 115 `target_kind` or a mass `selector` — neither of which is
      ambiguous about what "it" means. No cached card needs anything past
      `add_counters` here yet, so nothing beyond it was guessed at.

- [x] **The Enrage stragglers, hand-authored (user instruction: "do not
      defer, author all missing cards that use enrage").** Eleven real
      cards remained `UNMODELED` after the trigger fix alone (each blocked
      on its own effect body, not the trigger), closing the entire ~25-card
      Enrage population in `game/ability_catalogue.py` (one further
      "enrage" hit, Borborygmos Enraged, doesn't actually have the
      ability — a name-only false positive, correctly left alone). Several
      needed a small, reusable primitive rather than being purely bespoke:
      - `AddCountersEffect`/`DealDamageEffect` widened selector vocabulary
        — `each_other_creature_you_control` (Bellowing Aegisaur, RULE
        109.5's "another" exclusion) and `each_creature_and_planeswalker`
        (Stalwart Speartail's attacks-trigger mass damage — the union
        excludes a double-hit on a creature that's also a planeswalker by
        construction, not by luck).
      - `targeting.py`'s new `opponent`/`opponent_or_planeswalker` target
        kinds (Frilled Deathspitter/Sun-Crowned Hunters/Indoraptor) — no
        plain "an opponent" player-side target kind existed at all before
        this (only the graveyard-scoped `opponent_graveyard_*` family did).
      - `DamageEqualToCountersEffect` (Red Hulk) — `damage_equal_to_power`'s
        counter-count sibling, reading `GameObject.plus_one_counters`
        instead of power; Red Hulk's own "when you do" (RULE 603.10, a
        genuine second reflexive trigger this engine has no primitive for)
        is folded into one triggered ability's effect list instead — RULE
        608.2a resolves it in printed order and nothing has a window to
        intervene between the two halves anyway in an automated engine, so
        the simplification has no observable effect.
      - `AddManaEffect.amount_from_trigger_event` (Raphael, Ninja
        Destroyer) — reads "that much" off the firing `DAMAGE` event's
        `amount` via `GameContext.trigger_event`, `MirrorProducedManaEffect`'s
        "read this firing's own payload" idiom applied to a plain numeric
        amount instead of a produced-colour set; its own "you don't lose
        this mana as steps and phases end" persistence isn't modeled
        (`ManaPool` has no survives-a-step mechanism yet) — documented, not
        silent.
      - Trapjaw Tyrant reuses the existing `ExileEffect(remember=True)` +
        `ReturnLinkedExileEffect` O-Ring-shaped pair (`Leonin Relic-
        Warder`'s pattern) for "exile … until ~ leaves the battlefield" —
        the modern one-sentence templating is the same linked duration as
        Leonin's older two-sentence phrasing, just terser, so no new
        primitive was needed at all, just recognizing the shape.
      - Polyraptor reuses `copy_permanent`'s existing `target_kind=None`
        self-copy mode; Silverclad Ferocidons reuses `sacrifice`'s existing
        `selector="each_opponent"`.
      Three further, explicitly documented simplifications where a full
      implementation would have needed a disproportionate new subsystem for
      a single card: Indoraptor's "at random" becomes an ordinary target
      choice and its "unless they sacrifice a creature" escape clause isn't
      modeled (an opponent-side interactive "unless", a different shape
      from the existing controller-side `sacrifice_unless_pay`/
      `request_pay_cost_then` family); Vrondiss's created token drops its
      own "sacrifice it after it deals damage" downside (no quoted-ability-
      grant support for a token being created in the same breath yet) and
      its separate dice-roll clause is skipped outright (no dice-rolling
      subsystem exists); Stalwart Speartail's Enrage clause itself (as
      opposed to its already-shipped attacks-trigger half) is left
      unauthored — RULE 121's *perpetual* effect shape reaching into hand
      and library and outliving its own source, genuinely unsupported,
      and approximating it as an always-on static would have been a
      meaningfully more powerful card, not a faithful simplification.
      Coverage moved **9,536 → 9,567 / 34,208** (PARSER_VERSION 45,
      `scripts/coverage_report.py`).

## Mana-Potenzial (offen/genutzt) + Auto-Tap (2026-07-30)

A new, self-contained module (`game/mana_potential.py`) computes per-player
"open" vs. "used" mana potential and drives a real, executable auto-tap —
none of it pre-existing (a repo-wide grep for "mana potential"/"auto-tap"
before starting turned up nothing at all). Two distinct algorithms behind
one module, deliberately kept apart rather than sharing one code path:

- **`open_potential_summary`** — a per-colour (WUBRGC) display aggregate:
  six independent greedy maximizations (one per colour), each starting
  from an **empty** virtual pool. Deliberately not a simultaneous joint
  allocation across all six colours — the empty-pool seed is what keeps
  `open + used` (the latter a new `GameState.mana_produced_this_turn`
  counter, reset for *every* player — not just the active one, since a
  non-active player can tap at instant speed under `interactive_priority`
  — incremented at `tap_for_mana`/`activate_hand_mana_ability`'s existing
  `record_stat` call sites) equal to the turn's total accessed capacity;
  seeding from the real pool instead would double-count mana a source
  already produced. Prefers a net-mana-positive "pay one mana, get more
  back" converter (Selvala, Heart of the Wilds' own `{G}` cost is the one
  real card this engine models today; filter lands are a separate,
  pre-existing oracle-parser gap) over a plain zero-cost producer whenever
  doing so helps the colour being maximized.
- **`find_tap_plan`/`is_castable_via_potential`** — "can I pay *this* cost
  right now, using anything at my disposal" — seeded from the player's
  **real, current** pool (floating mana is genuinely spendable), DFS over
  untapped sources with a bounded fixed-point retry (a plain producer has
  to fire before a converter needing its output becomes payable) and a
  node-count cap so a pathological board can't blow the pytest per-test
  timeout. **Never spends a sacrifice- or hand-exile-cost source** (a
  Treasure, Elvish/Simian Spirit Guide) — `_auto_tappable_candidates`
  filters those out entirely, since consuming a resource to make mana is a
  decision a player should make deliberately via their own explicit
  `tap_for_mana`/`activate_hand_mana_ability` click, never spent for them
  silently. `open_potential_summary`'s display keeps the unrestricted
  candidate set — the two questions ("what's the true ceiling" vs. "what
  may I silently spend") are answered separately on purpose.

`GameEngine.auto_tap_for` (`game/engine/mana_mixin.py`) executes a found
plan for real, entirely through the existing `tap_for_mana`/
`activate_hand_mana_ability` calls — no new mutation logic. Reachable two
ways: a standing `auto_tap_for` action (`services/game_session.py`, dispatched
through the same generic actor/priority gate every other action already
goes through, so it needs zero Multiplayer-specific code), and — per a
mid-session scope refinement — **automatically**, silently, right before an
otherwise-legal `cast_spell`/`activate_ability` would fail purely for lack
of pool mana. That required a new `assume_mana_available` parameter on
`can_cast`/`can_activate`/`_can_pay_activation_cost` (skips only the
mana-pool check, every other legality requirement — timing, targets,
additional costs — still enforced): `_auto_tap_for_cast_if_needed`/
`_auto_tap_for_activation_if_needed` probe with it first to confirm mana is
*the only* thing blocking the play before touching a single source, so an
illegal play (wrong timing, no target) never triggers a silent tap. The
same `assume_mana_available` probe also widens every `legal_actions()`
cast/activate offer site (`_castable_now_or_via_potential`/
`_activatable_now_or_via_potential`) to include a card that's legal except
for mana and payable via potential — otherwise the automatic hook could
never fire in practice, since the UI never posts an action it wasn't
offered. `_offer_cast`'s face-down (morph/manifest) offer is deliberately
left real-pool-only (RULE 702.37a's flat {3} cost isn't expressed through
`effective_cast_cost`'s ordinary `face` handling) — a narrow, documented
gap, not an oversight.

Frontend (`gameBoardView.js`): a new "Mana-Potenzial" readout (open/used
per colour) next to the mana pool, and a `castable-highlight` border class
on a hand card the server flags `castable` (`services/game_session.py`'s
`_annotate_castable`, computed only for the viewing player's own seat —
RULE 400.2 covers a hand-derived number like a Spirit Guide's contribution
just as much as the hand array itself). No separate "Auto-Tap" button was
kept — once casting/activating auto-taps on its own, a dedicated button
would only ever fire in the same cases the real "✨ Zaubern"/"⚡
Aktivieren" button already covers, so it was dead weight (worse, it would
have been a latent footgun: `castable` alone doesn't imply the play is
otherwise legal, so a manual auto-tap trigger gated on it alone could waste
real mana on an illegal play — the automatic hook's own `assume_mana_
available` legality probe avoids exactly that). The pre-existing WUBRGC
emoji glyph map was consolidated while here — three independent,
inconsistent copies existed across `gameBoardView.js`/`cardTile.js` (the
new readout would have needed a fourth); `cardTile.js`'s `MANA_SYMBOL_
EMOJI` is now exported and reused everywhere.

Tests: `backend/tests/test_mana_potential.py` (the simulator itself,
including an `open + used == baseline` invariant check and a shared-
sacrifice-fodder contention case), `backend/tests/test_auto_tap_action.py`
(the executable action, the automatic cast/activate hook, the sacrifice/
hand-exile exclusion, the broadened `legal_actions` offers, rollback on
failure), plus `test_multiplayer_session.py` additions for the priority
gate and RULE 400.2 redaction of the new `mana_potential` view block.

## PAR-1 – PAR-5 batch (2026-08-03)

Five independent parser tickets, closed together (28.0% → 28.1%, 9,567 →
9,608 / 34,208, PARSER_VERSION 45 → 46). Order below is easiest-first, not
ticket-number order, since PAR-5's fix uncovered an unrelated bug PAR-3
later collided with again.

- [x] **PAR-5 · Hexproof-from-`<quality>`.** `keywords.py`'s `Hexproof` row
      moved from `FLAG` to `QUALITY` (mirroring `Protection`'s shape and
      hand-written extractor regex exactly), so "Hexproof from black"
      (Knight of Grace) keeps its colour instead of collapsing to blanket
      hexproof. The engine still treats hexproof as an unscoped boolean
      (`combat.has_hexproof`) — recorded for future use, matching how
      several other params already outrun the engine's own consumption of
      them — so this is enrichment, not a coverage change on its own.
      **Two bugs found and fixed on the way, not shipped broken:**
      `_SPECIAL_REGEX`'s protection/hexproof extractor stopped at a
      trailing `.,;)`/" and ", but a printed reminder-text parenthetical
      right after the quality ("Protection from black **(This creature
      can't be...**") starts with a bare space, so the regex failed outright
      on any keyword-line card whose reminder text immediately follows —
      added a `\s\(` alternative to the stop-lookahead, fixing this for
      *both* Protection and the new Hexproof row. And `_token_keywords`/
      `_flag_keywords` (the "create a token with `<keywords>`"/"`<X>` you
      control have `<keywords>`" grant families) both hard-require
      `KeywordShape.FLAG`, which silently broke every card granting *bare*
      hexproof ("gets +2/+2 and gains hexproof until end of turn",
      Blossoming Defense-shaped — 45 real cards) the moment Hexproof
      stopped being a FLAG shape; both now special-case `slug == "hexproof"`
      as an honorary FLAG for granting purposes (a real quality-suffixed
      grant like "hexproof from black" never reaches that branch at all,
      since `keyword_slug` only resolves the bare "hexproof"/"hexproof
      from" spellings, so it still fails closed correctly).
      Tests: `test_keyword_catalogue.py`.

- [x] **PAR-4 · "As ~ enters, choose a basic land type."** A third
      `enter_choice_effects` sibling alongside creature-type/colour
      (`ChooseBasicLandTypeReplacement`, `game/effects.py`) — stamps the
      very same `GameObject.chosen_type` field the creature-type family
      uses (a land type is just another subtype string to the "is the
      chosen type in addition to its other types" grant clause, which
      doesn't care which family produced it), so no `continuous.py` change
      was needed at all. New pieces: `static_handlers.
      _CHOOSE_BASIC_LAND_TYPE_ON_ENTER_RE`, the fixed five-option list
      (`casting_mixin._BASIC_LAND_TYPE_OPTIONS` — RULE 305.6, always all
      five, unlike creature-type's open board-scan), a `choose_basic_
      land_type` `pending_choice` kind wired through `_offer_enter_choices`/
      `resolve_enter_choice`/`effect_binder`'s `enter_choice_effects`
      routing/`GameEngine._dispatch` (the last of these was the one actual
      *engine-loop* gap — the other three families already branched
      generically enough to need only a new `elif`). Realmwright is fully
      modeled on this alone.
      **A second, unrelated bug found via A-Thran Portal, fixed
      alongside:** it stayed `UNMODELED` even after the enter-choice fix,
      because its own "Thran Portal is the chosen type…" self-reference
      names the card's *un-prefixed* base name — Scryfall's MTG Arena
      "Alchemy" rebalance convention prefixes the printed name with `A-`,
      but the oracle text itself keeps self-referring by the original,
      un-prefixed spelling. `normalize._fold_self_name` now also folds an
      `A-`-stripped sibling of every name form it already tries, which
      fixed 16 more Alchemy cards beyond A-Thran Portal itself (A-Circuit
      Mender, A-Find the Path, …) for free — a pre-existing, general gap
      this ticket happened to trip over, not something A-Thran-specific.
      Tests: `test_batch7_chosen_type_color_family.py`, two new
      `normalize` tests in `test_oracle_pipeline.py`.

- [x] **PAR-3 · Non-creature group scopes.** `static_handlers._scope`
      stays creature-only for `_ANTHEM_RE` (a bare "+N/+N" on a
      non-creature permanent is never printed on a real card — the
      ticket's own instruction), but the keyword-grant/quoted-grant
      families (`_GRANT_RE`/`_QUOTED_GRANT_RE`) now fall back to a new
      sibling, `_permanent_type_scope`/`_permanent_scope_params`, for a
      *bare* card-type word ("Artifacts you control have hexproof." —
      Leonin Abunas; "Other enchantments have '…'." — Aura Flux) — parser-
      side only, exactly as scoped: every selector it produces
      (`artifacts_you_control`/`permanents_you_control`/`lands_you_
      control`/`all_permanents`/`all_lands`, plus the pre-existing generic
      `card_type` filter for the two words with no dedicated selector,
      enchantment/planeswalker) already existed in `game/continuous.py`.
      Deliberately narrow: a compound "artifacts **and** enchantments you
      control" (Fountain Watch) stays unclaimed rather than guessed, since
      no selector ORs two card types yet.
      **A real bug caught before shipping, not after:** the first cut of
      `_permanent_scope_params` only special-cased the *global* "other"
      case (`exclude_self`), missing that the "you control" case has no
      dedicated "other_enchantments_you_control" selector either — Sterling
      Grove's "**Other** enchantments **you control** have shroud." would
      have granted itself shroud too. Fixed by applying `exclude_self`
      whenever "other" is present, independent of "you control" vs global.
      **A second, separate `_scope` widening rides along:** "Artifact
      creatures you control get +1/+1" (Chief of the Foundry, 5 SOLO real
      cards + several more blocked on other clauses) was *also* broken
      before this batch, for an unrelated reason — `_scope`'s "`<word>`
      creatures" branch treated "Artifact" as a guessed creature *subtype*,
      which `_has_subtype` would never match (it's a card type, not a
      subtype printed after the type line's em dash), so the anthem
      silently boosted nothing. `_Scope` gained a `card_type` field for
      exactly this shape (still creature-scoped — `affects` stays
      `creatures_you_control`/`all_creatures` — just filtered further by
      the generic `card_type` param, the same one the bare-scope fallback
      above uses).
      **A third bug found by spot-checking newly-covered cards for
      correctness, not just coverage (the skill's own stated discipline):**
      Greater Auramancy's second clause, "**Enchanted** creatures you
      control have shroud.", hit the exact same `_scope` guessed-subtype
      trap ("Enchanted" is a characteristic, not a subtype) — invisible
      before this batch since the card never reached `MODELED` at all, but
      would have shipped silently-wrong (shroud granted to nothing) the
      moment the first clause started parsing. `enchanted`/`equipped`
      added to `_NONCREATURE_TYPES` so this shape fails closed instead;
      the real fix (a dedicated "creatures you control that are enchanted/
      equipped" selector, narrower than the existing combined
      `enchanted_or_equipped_creatures_you_control`) is real, separate,
      un-ticketed work, affecting 23 real cards — flagged here rather than
      silently dropped.
      Tests: `test_oracle_pipeline.py`.

- [x] **PAR-2 · Compound target-kind unions.** A new `targeting.
      ALLOWED_TARGET_KINDS` member, `artifact_creature_planeswalker_or_
      opponent` (Price of Betrayal's "target artifact, creature,
      planeswalker, or opponent" — three permanent types unioned with a
      player, wider than `any`, which RULE 115.9c excludes bare artifacts
      from), plus its `_TARGET_ROWS` row and `legal_targets` branch,
      following the existing `artifact_or_enchantment`/`opponent_or_
      planeswalker` two-kind-union idiom. `handlers._REMOVE_COUNTERS_
      CHOICE_RE` was rewritten to embed the shared `TARGET` macro instead
      of its old hand-rolled `permanent|creature` alternation, so the new
      kind (and any future TARGET row) reaches it for free.
      **The real work was engine-side, not parser-side, despite the
      ticket's framing:** `RemoveCountersEffect`'s interactive "how many/
      which kind" choice chain (`request_remove_counters_choice`/
      `_continue_remove_counters`/`resolve_remove_counters_kind_choice`,
      `game/rules/mana_counters_mixin.py`) was hard-typed to a
      `GameObject`'s own `counters` dict — targeting a player (RULE 122.5
      lets "remove counters" name a player's poison/energy/experience,
      not just a permanent's +1/+1s) would have opened a choice that then
      crashed or silently removed nothing, exactly the "resolves to
      nothing" failure mode this repo's conventions call out as worse than
      staying `UNMODELED`. Fixed generically rather than special-cased to
      Price of Betrayal: a new `_counter_totals(target)` helper reads
      either a `GameObject.counters` dict or (for a `Player`) that dict
      folded together with the separate `Player.poison` attribute (RULE
      122's poison isn't stored in the generic counters dict), and
      `_remove_target_counters` dispatches removal through the
      already-existing `add_player_counters` for a `Player` instead of the
      permanent-only `add_counters`. No new removal primitive was needed —
      `add_player_counters` already handled negative (removal) amounts
      correctly for a different card family; only the `remove_counters`
      chain hadn't been taught to call it.
      Tests: `test_remove_counters_choice.py`.

- [x] **PAR-1 · Cross-target indirect referents.** Run Away Together's
      two-sentence "Choose two target creatures controlled by different
      players. Return those creatures to their owners' hands." — a
      genuinely different shape from the single-sentence "destroy/exile N
      target X controlled by different players" `_MULTI_TARGET_DISTINCT_
      CONTROLLERS` already claims (`handlers.destroy_multi_target`/
      `exile_multi_target`): here the *choosing* and the *acting* are two
      separate clauses, joined only by the pronoun "those creatures".
      Reused the existing "announce, then read back" machinery
      (`ChooseTargetsEffect`/`GameContext.previous_targets`, built for
      Ancient Animus's fight pair) rather than inventing a parallel one:
      `ChooseTargetsEffect` gained `count`/`distinct_controllers`/
      `optional`, producing one *quantified* `TargetSpec` of a single kind
      (count=2) instead of two independently-kinded single picks, when
      given exactly one `kinds` entry; `ReturnToHandEffect` gained
      `previous_subject=True` (the same flag name/shape `GrantUntilEffect`
      already uses for its own "Tap target land. It doesn't untap…"
      pronoun), which reads the *whole* announced group off `previous_
      targets` instead of opening a fresh RULE 115 choice — `Return
      ToHandEffect`'s docstring had literally been carrying a "this param
      exists so the engine primitive is complete… no parser front-end
      recognizes this yet" note since it was written, exactly describing
      this gap. Parser side: `_choose_targets_group` (a `previous_subject_
      only`-*unlocking* row reusing `_multi_target_params`, the same
      quantifier/distinct-controllers grammar `destroy_multi_target`
      already has) and `_return_previous_group` (a `previous_subject_
      only`-*gated* row for "return those creatures/them to their owners'
      hands"), wired through the segmenter's existing `_announces_
      creature_target` gate with no changes to it — `choose_targets`'s
      `kinds` list already included plain `"creature"`, already in
      `_CREATURE_TARGET_KINDS`.
      Tests: `test_fight.py` (alongside the pre-existing Ancient Animus
      pair-fight tests, since both are the same `previous_targets` pronoun
      family).

Coverage re-measured with `scripts/coverage_report.py`: **28.1% — 9,608 /
34,208 — PARSER_VERSION 46** (synced across `CLAUDE.md`,
`PARSER_LONG_TAIL.md`, `implementationStatusView.js`).

## PAR-6, PAR-8, PAR-9, PAR-10 batch (2026-08-03)

Four tickets closed (28.1% → 28.2%, 9,608 → 9,654 / 34,208, PARSER_VERSION
46 → 47); PAR-7 investigated and re-scoped rather than closed (stays open,
BACKLOG.md). Two of the four uncovered real functional gaps beyond their
own parser recognition — a card can be `MODELED` and still be unplayable if
nothing ever offers the ability `legal_actions`-side, which coverage alone
never catches (see `PARSER_LONG_TAIL.md`'s new lesson on this).

- [x] **PAR-6 · RULE 702.16n/p's "This effect doesn't remove this Aura."
      tail.** `_PROTECTION_SELF_EXEMPT_TAIL`, an optional trailing group on
      `_ATTACHED_PROTECTION_RE`/`_ATTACHED_ANTHEM_PROTECTION_RE`, sets
      `exempt_own_attachment` on the `grant_protection_static` spec. Engine
      side (the real reason this was gated on other work first): a new
      per-*source* `GameObject._protection_self_exempt` flag, stamped by
      `continuous.py`'s layer-6 pass and read by `_attachment_legal` (shared
      by initial attach and `_revalidate_attachments`) — without it, Black
      Ward and eleven siblings would genuinely detach themselves the very
      next SBA pass, since each grants its own host protection from a
      colour the Aura itself is. Closed 11 cards outright (Benevolent
      Blessing, Black/Blue/Green/Pentarch/Red/White Ward, Cho-Manno's
      Blessing, Flickering Ward, Spectra Ward, Tattoo Ward) plus two side
      fixes found on the way: "protection from each color" (Spectra Ward)
      folds to the existing "all colors" quality instead of tripping the
      generic `" each "` computed-quality guard, and a new
      `protection_from_chosen_type` dynamic (Riders of Gavony's "protection
      from creatures of the chosen type"), the creature-type sibling of the
      already-shipped `protection_from_chosen_color`. The latter surfaced a
      **pre-existing, unrelated correctness bug**: Empty-Shrine Kannushi's
      "protection from the colors of permanents you control" was being
      silently stored as a literal (nonsense) quality string that could
      never match anything — confirmed present before this session even
      started (`git show HEAD:…`) — now correctly rejected (the same
      `" of "` guard that also keeps Pledge of Loyalty's identical
      computed-quality shape fail-closed, not half-modeled).
      Tests: `test_standing_protection_and_type_extension.py`.
- [x] **PAR-8 · Granting Cycling to other cards.** "Each `[<filter>]` card
      in your hand has cycling `<cost>`." (Jo Grant/Rhet-Tomb Mystic/
      Tectonic Reformation) — a layer-6 ability grant whose *targets* are
      hand cards, a zone no existing `affects` selector reaches (RULE 613
      selectors are all battlefield-scoped). Parser:
      `_HAND_CYCLING_GRANT_RE`/`grant_cycling_to_hand`, `card_type` an
      optional printed type or "historic" (CR glossary: legendary, an
      artifact, or a Saga). Engine: a dedicated `continuous.
      _apply_hand_cycling_grants` pass (mirroring `_apply_off_battlefield_
      types`'s "track what was stamped, clear it, re-derive" shape) plus its
      own `GameState._hand_cycling_ability_cache` — kept separate from the
      ordinary layer-6 `_granted_ability_cache` rather than sharing it,
      since that dict's own end-of-pass pruning loop only recognizes its
      own key shapes and would silently evict any other shape sharing the
      dict. Found and fixed on the way: `legal_actions_mixin.py`'s hand-zone
      Cycling loop only ever scanned `source.activated_abilities`, never
      `granted_activated_abilities` — so a granted hand-zone ability was
      correctly *bound* but never actually *offered* to the player, a real
      pre-existing gap this ticket's own feature was the first thing to
      exercise. Closed Rhet-Tomb Mystic/Tectonic Reformation (Jo Grant stays
      UNMODELED — its own "whenever you cycle a card" trigger and "Doctor's
      companion" line are separate, unrelated gaps).
      Tests: `test_channel_cycling.py`.
- [x] **PAR-9 · Generic Cycling execution for unregistered cards.** A bare,
      unregistered "Cycling `<cost>`" keyword line was already claimed for
      the coverage gate (`[keyword] []`) but bound to nothing — Barkhide
      Mauler and seven siblings were reported `MODELED` while genuinely
      uncyclable. `effect_binder._cycling_activated_ability` (called from
      the existing `_keyword_activated_ability` hook, alongside Equip/
      Fortify/Reconfigure) binds a real `{cost}, Discard this card: Draw a
      card.` `ActivatedAbility`, guarded two ways: the card's own *raw*
      Scryfall `keywords` list must carry no other "…cycling" entry
      (`keywords.keyword_slug` aliases every `<type>cycling` spelling onto
      the same "cycling" slug, and the shared cost-extraction regex has no
      word boundary — it matches "Landcycling {1}" as a substring just as
      happily as a real "Cycling {1}" line, so the spec alone can't
      distinguish them); and a card already carrying a `discard_self`-cost
      ability (Dismantling Wave/Renewed Faith's own hand-authored one,
      bound earlier in the same pass) is left alone rather than given a
      second, competing "just draw a card" ability for the same cost.
      Tests: `test_channel_cycling.py`.
- [x] **PAR-10 · Jin-Gitaxias-style compound activation condition,** plus a
      much larger discovery made while sizing it. Two independent halves:
      - **The compound condition itself.** "Activate only as a sorcery and
        only if `<condition>`."/"Activate only if `<condition>`." (Cabal
        Inquisitor/Dread Wanderer/Hall of Oracles/Potioner's Trove/Jin-
        Gitaxias // The Great Synthesis) — a new `ACTIVATION_CONDITION_
        MARKER`, stripped and folded into a new `ActivationCost.
        activation_condition` field the same way `SORCERY_SPEED_MARKER`
        already folds into `sorcery_speed_only`, checked live by
        `GameEngine.can_activate` via `game/static_conditions.
        condition_holds` — the *same* RULE 613.6 whitelist a permanent's own
        "as long as `<condition>`" static already uses, so a condition
        recognized for one reads identically for both. Deliberately a
        **small, independent** condition-phrase table in `handlers.py`
        (`_ACTIVATION_CONDITION_RES`), not an import of `static_handlers.
        static_condition` — that module already imports `handlers.py`
        (`SORCERY_SPEED_MARKER`), so the reverse import would cycle. Covers
        only the phrasings real cards actually pair with an activation
        condition today (hand/graveyard counts, an opponent's graveyard
        count, "cast an instant or sorcery spell this turn"); a full-cache
        scan turned up **~150 other** "Activate only if …" phrasings
        (`you control a Plains`, `this creature is attacking`, `a creature
        died this turn`, …) — real, standing PAR-12 tail work, correctly
        left fail-closed rather than guessed at.
        New condition kind: `cast_instant_or_sorcery_this_turn`
        (`GameState.cast_instant_or_sorcery_this_turn`, set by
        `RulesEngine._track_spell_cast` off the same `SPELL_CAST` event
        `spells_cast_this_turn` already tallies) — reset for *every*
        player each `begin_turn`, unlike `spells_cast_this_turn`'s
        active-player-only reset, since a non-active player's own static
        condition (Leapfrog's granted flying, Haunting Figment's evasion)
        must read correctly too. The existing "as long as" conditional-
        static family picks this up for free via one new
        `_STATIC_CONDITION_RES` row — Haunting Figment/Leapfrog/
        Piston-Fist Cyclops all became `MODELED` with no dedicated parser
        work of their own.
      - **The discovery: "Return this card from your graveyard to the
        battlefield[, tapped]."** Found while confirming Dread Wanderer's
        SOLO-blocker status — its *other* clause was this, entirely
        unrecognized. A full-cache scan found **69+ cards**, by far the
        batch's biggest win — Reassembling Skeleton, Cauldron Familiar,
        Bloodsoaked Champion, Drownyard Temple, Scrapheap Scrounger, and
        dozens more. `game/effects.py`'s
        `ReturnSelfFromGraveyardToBattlefieldEffect` mirrors the existing
        `ReturnFromGraveyardTransformedEffect` exactly (untargeted, always
        `self.source`, a no-op if it's left the graveyard by resolution
        time) minus the forced flip, reusing `RulesEngine.
        return_from_graveyard`'s pre-existing `"battlefield_tapped"`
        destination for the tapped variant — no new zone-change primitive
        needed. Named to avoid colliding with the *pre-existing*
        `ReturnSelfFromGraveyardEffect` (RULE 112.6a mill-return-to-hand,
        a per-firing `obj` rather than always `self.source`) — an earlier
        draft reused that name and silently shadowed it in the same module,
        breaking the mill-trigger family's own tests until caught.
        This shape exposed a **second** real "MODELED but unplayable" gap,
        the same one PAR-8 found: `can_activate` had no branch at all for
        an ability sourced from the *graveyard* zone (only the battlefield,
        an Emblem, or `discard_self`'s hand-zone carve-out) — a new
        `ActivationCost.graveyard_zone` flag (stamped by `effect_binder.
        bind_ability` whenever the built effects include a
        `ReturnSelfFromGraveyardToBattlefieldEffect`, the same "the effect
        and the zone always travel together" inference `discard_self`
        already relies on for Cycling) closes it in both `can_activate` and
        `legal_actions`' new graveyard-scanning loop.
      Tests: `test_par10_activation_conditions.py` (new file),
      `test_batch9_conditional_transform_family.py` (one pre-existing
      fail-closed regression guard flipped to its new, correct MODELED
      assertion now that the compound condition it guarded against is
      genuinely supported).

Coverage re-measured with `scripts/coverage_report.py`: **28.2% — 9,654 /
34,208 — PARSER_VERSION 47** (synced across `CLAUDE.md`,
`PARSER_LONG_TAIL.md`, `implementationStatusView.js`). PAR-7 stays open in
BACKLOG.md with its real scope (two disproportionate new primitives for one
card); a new PAR-16 tracks the "…to your hand" sibling of PAR-10's
graveyard-reanimation discovery (20 cache cards, likely near-free by
reusing the pre-existing `ReturnSelfFromGraveyardEffect`).

## PAR-7 batch (2026-08-03)

Closed the ticket the same session's PAR-6..10 batch had left open after
sizing it as disproportionate — Emblazoned Golem, the cache's one card with
a Kicker cost that is itself variable ("Kicker {X}"). Both primitives the
earlier scoping note called out were built, each general rather than
Emblazoned-Golem-specific:

- **Kicker's own announced `{X}`** (RULE 702.33b). `GameEngine.can_cast`/
  `effective_cast_cost`/`cast_spell`/`_cast_current_face` all gained a
  `kicker_x` parameter, a wholly separate announced value from the spell's
  own `x` (the two are independent RULE 601.2b announcements — no card
  needs both today, but they're no longer implicitly conflated the way the
  old `max_affordable_kicker` docstring flagged as fragile).
  `max_affordable_kicker_x` mirrors `max_affordable_x`'s "scan down from the
  pool total" shape, scoped to `kicked=1`. `GameObject.kicker_x_paid`
  records what was actually paid, the same "set once at cast time, read at
  resolution" treatment `kicker_count` already gets — a different field
  from both `kicker_count` (times Kicker was paid) and the ordinary
  `x_paid` the ordinary "enters with X counters" shape reads, kept
  distinct rather than conflated per the original PAR-6..10 scoping note's
  own warning. `legal_actions`' `_cast_action` surfaces `kicker_has_x`/
  `kicker_max_x`, the same shape `has_x`/`max_x` already uses for the
  spell's own X; `services/game_session.py`'s `_dispatch_cast_spell` and
  `frontend/src/js/gameBoardView.js` (`kickerXFieldHtml`/`readKickerX`, a
  third number input alongside the existing X/Kicker-count fields, wired
  into both the immediate-cast and the target-picking cast paths) round-trip
  it end to end — this is playable from the actual Goldfisch/Replay board,
  not just from Python.
- **The "spend only colored mana on X. No more than one mana of each color
  may be spent this way." payment restriction** (RULE 605.3a-shaped, but
  capping *which* colours rather than *what the mana is spent on* — no
  existing spend restriction did this). Built as two new general
  `models.mana_pool.ManaPool` methods rather than a new `ManaCost` symbol
  kind: `can_pay_distinct_colors(n)`/`pay_distinct_colors(n)` (at least `n`
  of the five colours each having >=1 unrestricted mana — colourless and
  raw mana *count* never qualify, only colour *diversity* does), plus a
  `clone()` used only for the read-only legality check. The two-step
  payment this requires — pay the printed/fixed portion of the cost first,
  *then* check/pay Kicker's distinct-colour X against whatever the pool has
  left — matters for correctness, not just style: checking both
  requirements independently against the same starting pool would let a
  card with exactly enough colored mana for one requirement wrongly satisfy
  both (a case a dedicated regression test,
  `test_can_cast_kicked_refuses_when_printed_cost_and_kicker_x_would_share_mana`,
  pins down). `effective_cast_cost` zeroes Kicker's `{X}` symbol out of the
  merged `ManaCost` entirely when this restriction applies (`with_x(0)`,
  read via the new `ability_catalogue.kicker_x_mana_restriction`/
  `GameEngine._kicker_x_distinct_colors`) so it's never double-counted
  against the ordinary solver, and `cast_spell` pays the distinct-colour
  portion as a separate step right after `RulesEngine.cast_spell` pays the
  rest — ordering that happens to be optimal for this card for free, since
  `ManaPool._spend_generic`'s colourless-first order preserves colour
  diversity for whatever needs it next.
- **The counters payoff**: "If this creature was kicked, it enters with X
  +1/+1 counters on it." — X being Kicker's own paid amount, not a fixed
  count or the spell's own `x_paid` — was the original PAR-6..10 batch's
  own deliberate fail-closed gap (`counters.py`'s `_FIXED_AMOUNT`
  explicitly excluded "x" with a comment naming exactly this ambiguity).
  Resolved by widening the kicked-gate regex's amount group to also accept
  "x" (`_KICKED_GATE_AMOUNT`, kept separate from the Multikicker-scaled
  regex's own `_FIXED_AMOUNT`, since no card scales a per-kick amount by an
  announced X) and tagging the result with a new `kicked_x_scale` flag,
  read by `_apply_entry_counters` off `kicker_x_paid` instead of a literal
  count.
- **The restriction clause's own recognition**: a new
  `parser/oracle/catalogue/kicker_mana.py`, mirroring `counters.py`'s
  "recognized directly, engine reads via `ability_catalogue`, no spec"
  split — the restriction is cast-time payment logic the binder has no
  spec shape for, the same reason entry-counters/tapped-entry bypass specs.
  Claimed in `gate.py` the same "if `<recognizer>`(line) is not None:
  return" way as those two.

Emblazoned Golem is now fully `MODELED` with zero unclaimed clauses.
Coverage: **28.2% — 9,655 / 34,208 — PARSER_VERSION 48** (synced across
`CLAUDE.md`, `PARSER_LONG_TAIL.md`; `implementationStatusView.js`'s rounded
percentage was already correct at 28.2% and needed no edit). Tests:
`test_par7_kicker_x.py` (new file — parser recognition, the `ManaPool`
primitives in isolation, `can_cast`/`max_affordable_kicker_x`/
`legal_actions` offer fields, and two full cast→resolve engine tests
confirming both the mana actually spent and the counters that land);
`test_batch6_cost_keyword_family.py`'s pre-existing
`test_kicked_gated_x_amount_stays_unclaimed` fail-closed regression guard
flipped to `test_kicked_gated_x_amount_is_recognized` now that the shape it
guarded against is genuinely supported (the same "un-stale a superseded
fail-closed test" pattern the PAR-6..10 batch hit with Jin-Gitaxias).

While re-verifying the ticket's "Emblazoned Golem is the only card with a
variable Kicker cost" claim (a fresh full-cache scan, not just trusting the
earlier note), three more turned up — Kangee, Aerie Keeper/Thieving
Skydiver/Verdeloth the Ancient — each using a *triggered* "When ~ enters, if
it was kicked, `<effect scaled by X>`." shape rather than the RULE 614.1
entry-counters one this batch closed. Chasing that down further surfaced a
much bigger, unrelated sibling family — a triggered ability's own "if it was
kicked, `<effect>`." gate has no parser support at all (65 SOLO blockers, 79
total) — tracked as **PAR-17** rather than folded into this session, since
it's a genuinely separate segmenter feature, not a natural extension of
either primitive this batch built.

## PAR-16, PAR-17, PAR-14, PAR-15 batch (2026-08-03)

Closed the PAR-17 discovery from the batch above, plus two independently
sized tickets (PAR-14, PAR-15), in one session — user instruction: resolve
all four, no deferring. Coverage: **28.2% → 28.4% (9,655 → 9,731 / 34,208),
PARSER_VERSION 48 → 49**, full suite 3,060 passed (was 3,005), zero
regressions across the whole batch.

**PAR-16 · "Return this card from your graveyard to your hand."** The
hand-destination sibling of PAR-10's "…to the battlefield[, tapped]."
(`ReturnSelfFromGraveyardToBattlefieldEffect`). Re-verifying the ticket's
own "20 cache cards" estimate with a fresh `python scripts/parser_probe.py
blocked` run found **70 SOLO blockers** instead — the estimate had been the
ledger's *stale-blocker* ranking, not a live re-count. Two shapes, both
real:

- A new `ReturnSelfFromGraveyardToHandEffect` (self-only, untargeted, a
  no-op unless still in the graveyard — the same shape as its battlefield
  sibling, just no `tapped` param) plus one merged regex
  (`_RETURN_SELF_FROM_GRAVEYARD_RE`, a named ``hand``/``tapped``
  alternation) instead of a near-duplicate second handler.
- **The triggered half needed a genuinely new engine primitive**, not just
  a spec: Aurora Eidolon/Chandra's Phoenix/Blood Speaker-shaped cards say
  "Whenever `<event>`, [you may] return this card from your graveyard to
  your hand." — a triggered ability that must keep firing while its own
  source sits in the *graveyard* (RULE 113.6a). `_collect_triggers` only
  ever scanned `state.permanents()`; the only precedent was
  `_collect_mill_return_from_graveyard_triggers`, a bespoke per-firing
  marker built solely for RULE 112.6a mill-return and not reusable here.
  Generalized instead of duplicated: `TriggeredAbility.
  functions_from_graveyard` (inferred by `effect_binder.bind_ability`
  straight off the effect list — the same "effect and permission always
  travel together" inference `ActivationCost.graveyard_zone` already uses
  for the activated half) plus a new `RulesEngine.
  _collect_graveyard_function_triggers` scan, run alongside the older
  mill-only one rather than replacing it. The ordinary `check_trigger`/
  subject-condition machinery needed no changes at all — a graveyard
  card's `controller_id` already defaults to `owner_id` and never diverges
  without a control-change effect, which can't reach a graveyard card.
  Tests confirm both a "you may" decline and the "an opponent's Demon
  entering doesn't trigger your own graveyard card" `controller="you"`
  scoping.

**PAR-17 · A triggered ability's own "if it was kicked, `<effect>`."
gate**, generalized per this session's explicit instruction to also cover
Bargain and Multikicker while at it:

- `_KICKED_CONDITION_RE` widened from "if this spell was kicked" (spell-
  only) to `if (this spell|it) was (kicked(?: twice)?|bargained)` — "it"
  reaches a triggered ability's own body (Heartstabber Mosquito/Josu Vess,
  Lich Knight-shaped); "twice" is RULE 702.34a Multikicker's own count
  threshold, a new `kicked_at_least` condition key (`ConditionalEffect.
  _condition_holds`); "bargained" reaches a `ConditionalEffect` condition
  key (`{"bargained": True}`) that the engine has supported since the
  cEDH-cube batch but that **no oracle-text recognizer had ever reached**
  — Beseech the Mirror was hand-authored, and nothing else used the words.
- An "X" inside a kicked-wrapper's own rest clause is rewritten to a new
  `"kicker_x"` sentinel (distinct from the ordinary `"x"`, since it must
  read PAR-7's `GameObject.kicker_x_paid` rather than the spell's own
  `x_paid`) — resolved by a new branch in `RulesEngine._substitute_x`.
  **A real bug caught by the execute-level test, not the parse-level
  ones**: `_substitute_x` iterates a `TriggeredAbility`'s own `effects`
  list, but a kicked-wrapped effect is a `ConditionalEffect`, which has no
  `amount`/`count` attribute of its own — only its `.inner` does. Without
  unwrapping through `.inner`, "if it was kicked, draw x cards" left
  `DrawCardEffect.count` as the literal string `"kicker_x"` forever,
  crashing at `range(count)` the moment it resolved. Fixed by walking the
  `.inner` chain before checking the magnitude attrs. Verified against a
  synthetic card rather than a real one — both real cache examples
  (Kangee, Aerie Keeper/Verdeloth the Ancient) are blocked on a *different*,
  pre-existing gap instead (`_add_counters`/`_create_token` neither accept
  an "X" amount nor, for Kangee, a named "feather" counter type) — the
  mechanism is real and tested, just not yet reachable from either real
  card.
- Sizing this ticket (re-verifying "Emblazoned Golem is the only card with
  a variable Kicker cost" from the prior PAR-7 batch) surfaced **PAR-17
  itself** as a discovery, and sizing *that* surfaced one more: a fresh
  `blocked "if it was kicked"` scan went 65 → 50 unclaimed after this
  batch's fix, confirming the wrapper itself now works — the remaining 50
  are ordinary unrelated effect-body gaps (search, discard, return-with-a-
  qualifier), correctly left for PAR-12 tail work rather than chased here.

**PAR-14 · RULE 603.2's once-per-turn trigger limiter**, in both printed
spellings. The ticket's own "needs a genuine new mechanism" framing was
**wrong** — `TriggeredAbility.once_per_turn`/`_last_triggered_turn`
already existed, built for Dionus, Elvish Archdruid's *granted* ability,
but no oracle-text path had ever set it for an ordinary printed card. Pure
parser wiring once found:

- A trailing-sentence marker (`TRIGGER_ONCE_PER_TURN_MARKER`, "This
  ability triggers only once each turn.") stripped out of the parsed
  effect body, mirroring `ONCE_PER_TURN_MARKER`'s existing shape for
  *activated* abilities exactly, just for a triggered one.
- An inline condition suffix ("…for the first time each turn") stripped
  once, at the single `cond_text = trig.group("cond")` choke point in
  `segmenter.segment_line`, *before* any subject-family dispatch (self/
  group/player/variant) — since real cards print this suffix across every
  one of those families ("~ attacks for the first time each turn", "you
  gain life for the first time each turn", "1 or more counters are put on
  ~ for the first time each turn"), catching it in one shared place means
  every family gets `AbilitySpec.trigger["limit"]` for free rather than
  needing its own copy.
- Both fold into the same `trigger["limit"]` flag, read once by
  `effect_binder.bind_ability`'s triggered branch as
  `TriggeredAbility(once_per_turn=...)`. A pre-existing fail-closed
  regression guard (`test_scry_surveil_vancouver.py`'s own "for the first
  time each turn" test) flipped from asserting `UNMODELED` to asserting
  the new `MODELED`+`limit` behavior — the same "un-stale a superseded
  regression guard" pattern this repo hits almost every batch.

**PAR-15 · RULE 115.1a's "any number of target `<X>`" targeting.** The
ticket's own count (64 cards) undercounted badly — a fresh
`engine_bench.py cards` scan found 167 UNMODELED cards mentioning the
phrase, across a dozen-plus distinct clause families. Shipped the core
mechanism plus the ticket's own named biggest cluster, left the rest as a
narrowed PAR-15 residue (see `BACKLOG.md`) rather than chase every
cluster in one sitting:

- `catalogue.handlers._MULTI_TARGET_QUANTIFIER` (the shared quantifier
  embedded in **nine** existing handler regexes — destroy/exile/tap-untap/
  return-to-hand/"can't block"/damage-to-each-of/"choose"-for-search/
  graveyard-return) gained a third alternative, "any number of ", capped
  at `_ANY_NUMBER_TARGET_CAP` (10) with `optional=True` always implied.
  The cap is a fixed constant, not a live `legal_targets` count, matching
  the one pre-existing hand-authored precedent (`ability_catalogue.
  _fire_covenant`'s own "any number of target creatures" already used
  `count=10` with the same reasoning: "a real board never has X-1's worth
  of relevant creatures beyond that") — safe because the existing
  round-by-round target-gathering machinery (`RulesEngine.
  _continue_trigger_multi_target`) already stops early, either when the
  player explicitly says "stop" or when it runs out of legal candidates,
  regardless of how high the nominal cap is. One shared-grammar edit,
  nine families gained it at once — including "any number of target
  creatures can't block this turn," one of the ticket's own named
  examples, for free.
- **The named biggest cluster** — RULE 601.2d's "`~` deals N/X damage
  divided as you choose among any number of target(s)/target creatures."
  — needed a genuinely new recognizer, `_DIVIDED_DAMAGE_RE`/
  `_divided_damage`, but *not* a new engine primitive:
  `DealDamageEffect(divided=True)` (RULE 601.2d) already existed from the
  cEDH-cube batch, reachable only through two hand-authored cards
  (Shatterskull Smashing, Fire Covenant) with zero oracle-text path in.
  Real cards newly covered end to end: Bogardan Hellkite, Rolling Thunder,
  Boulderfall, Magma Opus, Pyrotechnics, Spreading Flames, Violent
  Eruption, Volley of Boulders, Blinding Flare (a Strive card — see
  below), Consign to Dust, Kiora's Dismissal.
- **Every one of Strive's 20 real cards was blocked on this family**,
  confirming the original ticket's own note: MEC-4 (Strive) shipped with
  *zero* fully-`MODELED` cards, since every Strive card pairs its now-
  modeled `strive_cost` with an "any number of target creatures" effect
  body. Blinding Flare is now the first Strive card to reach `MODELED`.
- Left open, written up as a narrowed PAR-15 in `BACKLOG.md`: a `divided`
  mode for `PreventDamageEffect` (the same shape as `DealDamageEffect`'s,
  2 cards), two new graveyard-recursion destinations ("…on top of your
  library"/"…shuffle into your library", 6 cards combined), and the
  distribute-counters/mass-pump clusters (untouched). None of these need
  a new *targeting* primitive — `_ANY_NUMBER_TARGET_CAP`/`optional=True`
  already generalizes — only new or widened effect-body recognizers.

Tests: `test_par16_graveyard_to_hand.py` (10), `test_par17_kicked_trigger_
gate.py` (20), `test_par14_trigger_once_per_turn.py` (9),
`test_par15_any_number_of_targets.py` (16) — all new files, parse+execute
style throughout (each ticket's engine-level behavior, not just its
coverage verdict, is asserted).

## PAR-15 residue + PAR-13 batch (2026-08-04)

PARSER_VERSION 49 → 50, coverage 28.51% → 28.6% (9,754 → 9,778 / 34,208).
Closed PAR-15's own re-scoped residue ticket in full, and PAR-13 (dungeon
room/plane/scheme effect bodies) substantially — 8 of its 9 unmodeled
dungeon rooms, with the Planechase/Archenemy half re-confirmed as PAR-12's
own tail rather than a distinct gap (13/309 plane/scheme cards measured
modeled, unchanged in kind from before this batch).

**PAR-15 residue** — the four small clusters left after the 2026-08-03
batch, none needing a new *targeting* primitive (`_ANY_NUMBER_TARGET_CAP`/
`optional=True` already generalized that):

- **RULE 615's targeted/divided prevention** ("prevent the next N damage
  that would be dealt this turn to any number of targets, divided as you
  choose" — Embolden/Remedy/Angel of Salvation, 5 cards incl. Pollen
  Remedy's own kicked override). `PreventDamageEffect` gained a
  `target_kind`/`divided`/`amount_if_kicked` mode alongside its existing
  untargeted "prevent all/N damage to you" shape, and a new engine
  primitive, `RulesEngine.prevent_damage_to_target` (the any-target sibling
  of the existing player-only `prevent_damage_to_player`, sharing its
  cumulative-bank shield semantics and cleanup sweep — extended to also
  sweep a permanent's own `replacement_effects`, not just a player's).
  `amount_if_kicked` is a narrow override param on this one effect class
  (not a generic kicked-override mechanism — RULE 702.33b's *additive*
  "if kicked, `<effect>`" shape already exists via `ConditionalEffect`;
  this is the rarer override shape a couple of cards use instead). Sex
  Appeal (an Unhinged silver-border joke card whose "override" condition
  is literally about people in the room) stays UNMODELED — not a real gap.
- **Two new `ReturnFromGraveyardEffect` destinations** — "put any number
  of target creature cards from your graveyard on top of your library."
  (Bone Harvest/Footbottom Feast/Forever Young/Gravepurge) used the
  already-supported `destination="library_top"`; "shuffle any number of
  target `<cards>` from your graveyard into your library." (Piper's
  Melody/Renewing Touch/Perpetual Timepiece/The Bath Song) is modeled as
  "put on the bottom, then shuffle" (`shuffle_after`), since the position
  `library_bottom` gives it is immediately randomized away by the shuffle.
- **`AddCountersEffect.divided`** — "distribute N +1/+1 counters among any
  number of target creatures[ you control]" (Blessings of Nature/Jugan,
  the Rising Star/Verdurous Gearhulk) — the same evenly-split-pool shape
  `DealDamageEffect.divided` already established, now shared.
- **`PumpEffect.target_count`** (a genuinely new N>=2 mode for a class
  that was single-target-only) + **`TapEffect.previous_subject`**
  (mirroring `ReturnToHandEffect`'s existing pronoun) — "any number of
  target creatures each get +N/+N [and gain `<keyword>`] until end of
  turn. Untap those creatures." (Aerial Formation/Ajani's Presence/Cruel
  Feeding/Desperate Stand/Rouse the Mob/Colossal Heroics — 6 of 7 named
  cards; Setessan Tactics' own trailing "gain a granted activated ability"
  clause is a materially different, harder shape and stays UNMODELED).

**PAR-13** — the RULE 309 dungeon engine and all four room graphs
(`game/dungeons.py`) were already complete; `room_effect_specs` runs a
room's printed effect through the *same* `segmenter.parse_effect_body` a
card's own text uses, so a room with no matching handler simply resolves
with no effect (fail-closed) rather than breaking the graph. Was 21/30
rooms bound (re-measured; the ticket's own "20 of 30" was stale), now
29/30, via six pieces:

- **`grant_until`'s new P/T-delta route** (`_pump_until`, riding the
  already-general `anthem` layer-7c static) and **its "can't
  attack/block until `<duration>`" sibling** (`_cant_attack_or_block_until`,
  the resolve-time-grant cousin of the permanent-static `combat_
  restriction` family's synthetic `grant_keyword` flags) — Fungi Cavern
  ("-4/-0 until your next turn")/Twisted Caverns ("can't attack until your
  next turn"). Also widened `_GROUP`/`_GROUP_SELECTORS` with two new
  phrasings ("creatures your opponents control"/"creatures you don't
  control", both `continuous`'s existing `creatures_opponents_control`
  selector) — which is what also picked up real non-dungeon cards
  (A-Binding Geist, Hag of Inner Weakness, Mouth of the Storm).
- **A whole-clause compound-cost handler** (one `discard` + three
  independent `choose_objects` sacrifices, each its own type) for
  Oubliette's "Discard a card and sacrifice a creature, an artifact, and a
  land." — deliberately a dedicated row rather than relying on the generic
  `" and "` connector split (`segmenter._CONNECTORS`), which would also
  have split the sacrifice's own internal "a creature, an artifact, **and**
  a land" list. No new engine primitive; `ChooseObjectsEffect` already
  resolves with no prompt when there's nothing to choose between and as a
  no-op when a type has no legal candidate.
- **A legendary named token** for Cradle of the Death God's "Create The
  Atropal, a legendary 4/4 black God Horror creature token with
  deathtouch." — `CreateTokenEffect`/`synthesize_token_card` gained a
  `legendary` param setting `Card.is_legendary` directly (this builder
  constructs a `Card` from parts, not through the scryfall-data reader
  that normally derives it from the type line), with "Legendary" folded
  into the synthesized type line right after "Token" so `Card.is_token`'s
  own "starts with Token" contract still holds. A parallel plain
  `legendary` flag was added to the ordinary inline-stats `create_token`
  regex too (no real non-dungeon card needs it yet, but the primitive is
  now there for one that does).
- **`ImpulsiveDrawEffect`'s first oracle-text route** — the effect existed
  hand-authored-only (Light Up the Stage) since PAR-8/9-era work; this
  batch's `_exile_top_play` is the first parser handler to reach it, for
  Runestone Caverns' "Exile the top two cards of your library. You may
  play them." (bare, no duration — defaults to the effect's own "until the
  end of your next turn") — also closing Bonehoard Dracosaur/Painter's
  Studio's own "this turn"/"until the end of your next turn" variants.
- **A new one-shot effect, `DrawRevealCastOneFreeEffect`, plus a new
  `RulesEngine.request_choose_objects` action, `"cast_free"`** (every
  existing action was a battlefield pick; this is the first hand-zone one,
  cast through the ordinary `RulesEngine.cast_without_paying` free-cast
  path) — for Mad Wizard's Lair's "Draw three cards and reveal them. You
  may cast one of them without paying its mana cost." (reveal itself
  carries no mechanical weight to model, RULE 701.28).
- **A new mass-interactive primitive, `RulesEngine.
  request_each_player_pay_or`** (RULE 101.4's APNAP "unless", chained as a
  sequence of the existing single-player `request_pay_cost_then` choices —
  `resolve_pay_cost_then_choice` now advances to the next queued player
  when `_pending_each_player_pay_or` is set, a no-op for every ordinary
  single-player caller) for "Each player loses N life unless they `<pay
  cost>`." — Veils of Fear ("…discard a card")/Sandfall Cell ("…sacrifice
  a creature, artifact, or land of their choice"). Sandfall Cell's own
  cost also needed a new compound `ActivationCost.sacrifice` value,
  `creature_artifact_or_land` (checked ahead of the plain single-word
  `_SACRIFICE_RE`, in the two `_matches_permanent_type`/cost-payment
  modules that actually consult it), since "a creature, artifact, or land"
  is an OR of three types the existing single-word grammar can't express.

**Throne of the Dead Three** ("Reveal the top ten cards of your library.
Put a creature card from among them onto the battlefield with three +1/+1
counters on it. It gains hexproof until your next turn. Then shuffle.")
stays UNMODELED — confirmed zero non-dungeon cache siblings for this exact
"reveal top N, choose one, place with counters, shuffle the rest back"
shape, so building it would be genuinely new engine work paying for
exactly one room. Documented as a residual gap (`test_dungeons.py`'s own
fail-closed test now points at it instead of the now-modeled Twisted
Caverns) rather than forced, matching how the battle-pool worked example
in `PARSER_LONG_TAIL.md` treats its own one-card bespoke-tail entries.

Tests: `test_par15_residue.py` (26), `test_par13_dungeons_and_variants.py`
(30) — both new files, parse+execute+end-to-end throughout (including a
two-player sequencing test for `request_each_player_pay_or` and a
dungeon-room-by-room coverage assertion pinned at 29/30).

## MEC-13 · Mana-Potenzial auto-tap's three gaps (2026-08-04)

All three of the ticket's own items turned out real, but not quite where
its own wording placed them — each was verified empirically (running the
real engine, not just reading the code) before being fixed, and one item
led to a genuine bug the ticket hadn't described at all.

**(1) X-spell/Kicker auto-tap.** The ticket read as if `auto_tap_for`
itself couldn't handle a chosen X/Kicker value. It already could —
`_auto_tap_for_cast_if_needed` had threaded a real `x`/`kicked` through to
`effective_cast_cost` since the feature shipped (2026-07-30). The actual
gap was one level up: `max_affordable_x`/`max_affordable_kicker`/
`max_affordable_kicker_x` (which `legal_actions` uses to populate
`max_x`/`max_kicker`/`kicker_max_x`, driving the frontend's X/Kicker input
widgets) bounded their search by `player.mana_pool.total()` alone — a
player with four untapped Mountains and an empty pool was never even
*offered* X=3 for a `{X}{R}` spell, though casting with x=3 once chosen
would already have auto-tapped correctly. Fixed by bounding the search
with a new `mana_potential.max_potential_total` (every untapped source's
best single-tap production, summed, colour-blind — a safe ceiling since
X/Kicker's own `{X}` are always generic costs, RULE 107.3c) and checking
each candidate value via `is_castable_via_potential` instead of the real
pool alone. `_kicker_x_distinct_colors`'s "spend only colored mana on X,
no more than one of each colour" restriction (Emblazoned Golem-shaped,
PAR-7) has no mana-potential equivalent — auto-tapping doesn't know to
diversify colours for it — so a card carrying it keeps the original
real-pool-only search in `max_affordable_kicker_x` rather than risk
answering "yes" for an X only reachable by spending two of the same
colour.

While verifying this, a **second, real execution-time bug** surfaced that
the ticket never mentioned: `_cast_current_face` calls `_auto_tap_for_
cast_if_needed` with every other real cast parameter but had never
threaded `kicker_x` through at all — so a Kicker spell with its own
variable `{X}` (PAR-7) always auto-tapped for `kicker_x=0` regardless of
what was actually announced, silently under-tapping and then failing the
real, correctly-costed `can_cast` right after. Fixed by adding `kicker_x`
to `_auto_tap_for_cast_if_needed`'s signature and threading it through to
`can_cast`/`effective_cast_cost`, zeroed under `_kicker_x_distinct_colors`
exactly as `effective_cast_cost` itself already zeroes it (that portion is
paid separately, via `ManaPool.pay_distinct_colors`, never through
auto-tap). `GameEngine.auto_tap_for`'s own public signature also gained
optional `x`/`kicked`/`kicker_x` (threaded into `services/game_session.py`'s
`_dispatch_auto_tap_for` from the action dict) for the manual "top up mana"
button, which previously always tapped for the base cost only.

**(2) The face-down (morph/disguise) cast offer.** The ticket's own
docstring claim — "RULE 702.37a's flat {3} cost isn't expressed through
`effective_cast_cost`'s ordinary `face` handling" — was checked against
the live code and found **false**: `game/face_down.py`'s `face_down_card`
already carries the flat {3} as an ordinary `mana_cost_string`, and
`effective_cast_cost(face="face_down")` already resolves it correctly via
`_face_card`, with no swap needed first. The real gap was narrower:
`legal_actions()`'s face-down offer used a bare `can_cast(face=
"face_down")` (real pool only) instead of `_castable_now_or_via_potential`,
so the offer itself never appeared unless mana was already floating.
Fixing just that uncovered a **second, deeper bug**: `cast_spell`'s own
`face_down` branch ran its legality gate (`can_cast`) *before* any
auto-tap attempt at all — unlike the ordinary front-face path, where
`_cast_current_face` auto-taps first — so even after the offer correctly
appeared, clicking it would still fail whenever the {3} was payable only
by tapping untapped lands. Fixed by making `_auto_tap_for_cast_if_needed`
`face`-aware (threaded into its own `can_cast`/`effective_cast_cost`
calls) and calling it from the `face_down` branch before the gate — using
`face="face_down"` deliberately preserves `can_cast`'s own face_down-
specific timing gate and its "no additional cost — a face-down spell has
no text" override, both of which a naive "swap first, then call the
ordinary post-swap path" fix would have silently dropped.

**(3) "Multicolor lands and artifacts are counted multiple times."**
Investigated empirically against `find_tap_plan`/`_Commitment` — the
actual auto-tap decision path — with three real shapes: a dual land (one
`ManaAbility`, multiple `options`), a land granted an *additional* basic
land type (RULE 305.6, two separate `ManaAbility` entries on one object —
a printed one plus a derived one), and a "{T}: Add one mana of any
colour" artifact. All three correctly refused a 2-pip cost from a single
copy: `_Commitment.tapped` blocks a second ability on an already-tapped
object regardless of how many distinct `ManaAbility` entries `mana_
abilities_for` returns for it. No bug found in the described shape. The
one place a multicolour source genuinely gets counted more than once is
`open_potential_summary`'s six *independent* per-colour maximizations (a
dual land can appear in both its W-run and its U-run) — already
documented as a deliberate, display-only approximation in `mana_
potential.py`'s own module docstring, and never consumed by auto-tap.

Investigating this *did* turn up a real, different bug in the same
neighbourhood: `_choose_option`'s colour preference was a **static** set
computed once from the cost (`_needed_colors`), never updated as the
search actually filled pips — so two *different* untapped dual lands
(each "{T}: Add {U} or {B}.") searching for a `{U}{B}` cost would both
greedily pick the first colour that matched, producing `{U}{U}` and never
finding the obviously-available plan. Fixed with a new `mana_potential.
_still_short_colors(cost, pool)`, recomputed fresh before every tap
attempt in `find_tap_plan`'s round loop, steering each flexible source
toward whatever the pool is still short on rather than repeating an
already-satisfied colour.

Tests: `test_mec13_auto_tap_gaps.py` (15) — parse+execute+end-to-end
throughout, including the three empirical "does this actually
double-count" checks for item (3) and a positive control proving two
*different* dual lands genuinely can cover a two-colour cost together.

## PLR-3 · Face-down-in-exile redaction (2026-08-04)

`_redact_hidden_zones` (`services/game_session.py`) already stripped whole
*zones* per RULE 400.2 — an opponent's hand and library never left the
server — but a card exiled face down (RULE 701.20a, `GameObject.
face_down_in_exile`, Beseech the Mirror-shaped) is a *zone* nobody's hand
is (exile is otherwise public), so the gap was different in kind: the
object itself should stay visible (something is sitting there face down),
only its identity shouldn't. `GameObject.to_dict()`'s own comment even
said so explicitly — "the name/type stay in the payload: this app's
goldfish/Replay views are all shown to the card's own owner" — true for
solo modes, never checked against a multiplayer *opponent's* view.

Fixed with a new `_redact_face_down_exile`, called from `_redact_hidden_
zones` (so both its call sites — `GameSession.view(perspective=...)` and
`observer_view`'s explicit `perspective=None` fixup — cover it for free):
for every player who isn't the requested `perspective`, any `face_down_
in_exile` object in their exile zone has a fixed set of identity/
characteristic fields (`card_id`, `name`, `type_line`, every `is_*` type
flag, `power`/`toughness`/`loyalty`/`defense`, …) reset to an "unknown
card" placeholder — `instance_id`/`zone`/`face_down_in_exile` itself stay
real, so the board still renders a card-back tile in the right place.
`face_down` (RULE 708.2, morph/disguise/manifest/cloak) needed no
equivalent list: that shape's `self.card` is already swapped to the
synthetic blank 2/2 (`game/face_down.py`), so `to_dict()` never had a real
identity to leak in the first place — the redaction gap was specific to
the one face-down shape that keeps its real card underneath. Solo modes
(`GameSession.view()`'s own default `perspective=None`) never call
`_redact_hidden_zones` at all, so a goldfish/Replay board is completely
unaffected — confirmed with a dedicated test, not just inferred from the
call graph.

Tests: `test_plr3_face_down_exile_redaction.py` (5) — owner keeps the real
card, an opponent and an observer both see nothing, a solo view is
unredacted, and an ordinary (non-face-down) exiled card is unaffected —
built by injecting a `face_down_in_exile` `GameObject` directly into a
real two-seat `GameSession` rather than driving the full Beseech the
Mirror cast (already covered end-to-end at the engine level by
`test_cedh_cube_completion.py`), keeping this file's own scope to the
session-view redaction the ticket was actually about.

## PLR-6 · In-progress UI selection survives a reconnect (2026-08-04)

"A targeting modal or half-assembled block is rebuilt from the pushed
view, which carries only committed state" was literal: a mid-cast
targeting sequence or a block being assembled (RULE 115/509.1a) lives
entirely in the frontend's local `gameBoardView.js` state until the one
final action is sent — the server never saw any of it, so it had nothing
to rebuild from on a genuine reconnect (a new tab, walking back into the
same seat by name). Fixed on the backend by giving `GameSession` a small
place to hold it: `_ui_drafts: dict[player_id, dict]` (opaque,
unvalidated JSON, size-capped at ~20 KB) plus `set_ui_draft`, surfaced in
`view()` as `ui_draft` (only the caller's own — no RULE 400.2 concern,
just no reason to leak someone else's) and a new, deliberately quiet
`POST /api/game/{id}/ui-draft` (generic on session id, like
`replay-export` — works for goldfish/Replay/Multiplayer alike). "Quiet"
matters: it does *not* go through `api/multiplayer.py`'s
`_after_move`/broadcast path, or autosaving your own in-progress pick as
it's built would spam a fresh view at the whole table on every click —
exactly the bug being fixed. A draft is dropped as a side effect of that
same player's own next real action succeeding (`apply_action`/`concede`
pop it) — no separate "clear" endpoint needed for the common case.

Investigating this also found the more common way the bug actually bites
in Multiplayer: `applyView` in `gameBoardView.js` was unconditionally
wiping the local draft on *every* pushed view, including one that
changed nothing about the committed position — e.g. another player's
socket merely reconnecting (`api/multiplayer_ws.py`'s `subscribe_game`
handler broadcasts a fresh view to the *whole* table on every resubscribe,
not just the requester). One player's wifi blip was silently nuking
everyone else's in-progress block/targeting. Frontend half in the
sibling Done_Frontend.md entry.

Verified live against a running server (not just pytest): a plain `GET`
never grows `move_log` (the exact invariant the frontend's guard relies
on to tell "a reconnect refresh" from "a real move happened"), a saved
draft round-trips through `view()` untouched by that GET, and a real
action both grows `move_log` and clears the draft.

## Replay/Puzzle mode: 3-4 player pods (2026-08-04)

`services/replay.py`'s `blank_replay` was capped at 2 players ("solo
puzzle, or with an opponent") even though the turn engine has been
N-player throughout and Multiplayer already seats up to 4
(`services/lobby.py`'s `MAX_SEATS`). Raised the cap to match — `blank_
replay(num_players)` now clamps to `[1, 4]` and names blank seats `["Du",
"Gegner 1", "Gegner 2", "Gegner 3"]` for 3-4 (unchanged `["Du", "Gegner"]`
for the existing 1-2 case). No `api/schemas.py` change needed — `num_
players` was never bounded there, only inside `blank_replay` itself. The
play-mode board needed no engine or session changes at all: it's the same
`gameBoardView.js`/`GameSession` Multiplayer already runs at 3-4 seats.
Frontend half (the puzzle editor's own pod-grid layout) in Done_Frontend.md.

## PLR-5 · A `ping` counts as liveness too (2026-08-04)

The idle watchdog (`api/multiplayer_ws.sweep_once`) only ever reset a
player's `last_action_at` from a real game action
(`api/multiplayer.py`'s `apply_action` → `Lobby.touch`) — a player who
was genuinely still at the table but just thinking a move over past
`MTG_MULTIPLAYER_IDLE_TIMEOUT` (default 120s) got disconnected and
immediately auto-reconnected (the seat is held by name, RULE-free), a
visible flicker for no real absence. `/ws/lobby` already had a `ping` →
`pong` message pair (round-trip keepalive), it just didn't touch
liveness; `_handle`'s `ping` branch now calls `lobby.touch(player_id)`
before replying, exactly the same call `apply_action` already made.
Frontend half (the periodic ping sender) in Done_Frontend.md. Test:
`test_api_multiplayer.py::TestWatchdog::test_a_ping_also_resets_the_idle_timer`
(a real `/ws/lobby` connection, not a call into `_handle` directly).

## PLR-11 · Leyline's opening-hand permission (2026-08-04)

RULE 103.6a: "If this card is in your opening hand, you may begin the
game with it on the battlefield." (the Leyline cycle, 18 real cache
cards using the exact shape) is a **pregame setup permission**, not a
static or resolve-time effect — there's no permanent yet to bind an
`EffectRegistry` ability onto; the card is still sitting in a player's
hand. Same split `game/ability_catalogue.py` already uses for RULE
614.1 tapped-entry/entry-counters: `parser/oracle/catalogue/
opening_hand.py` is the single source of truth for recognising the
clause (`_OPENING_HAND_BATTLEFIELD_RE`, matching "this card"/a folded
self-name `~`, and "it"/"him"/"her"/"them" — Quicksilver, Brash Blur's
own name folds to `~` and uses "him"), claimed-without-a-spec by
`gate._process_line` (so the rest of a Leyline's real text — an anthem,
a granted keyword, whatever — still parses normally on its own lines),
and read directly off the card by `game/ability_catalogue.
opening_hand_battlefield_permission`. Deliberately narrow: Gemstone
Caverns' "…and you're not the starting player…with a luck counter on
it. If you do, exile a card from your hand." and Buried Ogre's
graveyard-destination variant are genuinely different, conditional/
costed shapes and stay unclaimed rather than silently dropping the
condition/cost. PARSER_VERSION 50→51; +6 cards flipped UNMODELED→
MODELED (the rest of the ~18 were already blocked on an unrelated
line) — 28.6% = 9,784/34,208.

The engine half mirrors the *existing* Vancouver-scry queue almost
exactly, since both are "every seat gets one interactive pregame
decision, one at a time, because `GameState` holds exactly one
`pending_choice`": `GameSession._start_opening_hand_choices`/
`_open_next_opening_hand_choice` walk a `(player_id, instance_id)`
queue built the moment the whole table has kept (before Vancouver's
scry — RULE 103.6 precedes it), each entry resolved by a new
`opening_hand_battlefield` `pending_choice` kind (`GameEngine.
resolve_pending_choice` → `RulesEngine.offer_opening_hand_battlefield_
choice`/`resolve_opening_hand_battlefield_choice`). Accepting moves the
card hand → battlefield the same way a search-to-battlefield hit does
(`search_mixin._put_searched_card`'s "battlefield" branch): untapped,
`summoning_sick = True`, `state.add_to_battlefield` +
`EventType.ENTERS_BATTLEFIELD` so an ETB trigger (none of the 18 real
cards have one, but the primitive doesn't assume that) and the layer
engine both see it on the very next `resolve_until_stable()` pass —
which is also what turns "You have hexproof."-style static clauses on
the instant the choice resolves, with zero special-casing needed.
Deliberately does *not* call `_offer_enter_choices` (RULE 601.2b's
"enter as a copy"/"choose a type" family) — a search-to-battlefield hit
doesn't either; no cache card needs both at once, and adding it would
be scope no ticket asked for. Frontend needed one line (a `❔` →
`🌅` icon-map entry in `CHOICE_ICONS`, `gameBoardView.js`) — the
2-option "battlefield"/"decline" choice already renders through the
existing generic `simpleChoiceButtonsHtml` fallback every other binary
`pending_choice` kind uses.

Tests: `test_oracle_opening_hand.py` (11, clause recognition +
coverage-gate integration) and a new `TestOpeningHandBattlefieldPermission`
class in `test_game_session.py` (6 — offered after keep, accept moves it,
decline leaves it, a hand with none opens nothing, two qualifying cards
walk one at a time, a Gemstone-Caverns-shaped near-miss stays unclaimed).

## PLR-11 follow-up · Gemstone Caverns / Buried Ogre's pregame-setup shapes (2026-08-04)

The two shapes PLR-11 deliberately left unclaimed rather than silently
drop their extra condition/counter/cost: Gemstone Caverns' RULE 103.6a
battlefield permission gated on "and you're not the starting player",
entering with a luck counter, and a trailing mandatory "if you do, exile
a card from your hand."; and Buried Ogre's RULE 103.6 permission for a
*graveyard* destination instead of the battlefield (RULE 103.6a has no
sub-letter for a non-battlefield destination — Buried Ogre falls under
103.6's general "some cards allow a player to take actions with them from
their opening hand" umbrella instead), with its own mandatory "if you do,
you lose N life." Both real cache cards now MODELED; PARSER_VERSION 51→52,
28.6% = 9,786/34,208.

`parser/oracle/catalogue/opening_hand.py` gained a `PregameSetupPermission`
dataclass (`destination`, `condition`, `counter_type`/`counter_count`,
`cost_kind`/`cost_amount`) and `pregame_setup_permission(card)`, the
general card-level entry point covering all three shapes side by side with
the original narrowly-scoped `opening_hand_battlefield_permission`
(kept as-is — still what the coverage gate uses to claim the plain-shape
line specifically, and it correctly still doesn't claim either new shape,
same as before). Two new line regexes join the original: Gemstone
Caverns' and Buried Ogre's own printed text both name themselves directly
("...with Gemstone Caverns on the battlefield...") rather than using a
pronoun the way the Leyline cycle's "if this card is in your opening
hand, you may begin the game with **it**..." does — folded to `~` by
`normalize`, so both new regexes accept `~` alongside the original's
`it`/`him`/`her`/`them`. `game/ability_catalogue.py` got the matching
`pregame_setup_permission(card)` delegate; `gate.py` claims both new
lines without emitting a spec, same split as the plain shape.

Engine side, `services/game_session.py`'s `_start_opening_hand_choices`
now reads `pregame_setup_permission` instead of the plain boolean, and
checks a permission's own `condition` ("not_starting_player") against
`GameState.starting_player_id` before ever queuing the card — an unmet
condition means the choice was never offered at all, not offered-and-
expected-to-decline, matching the printed "and you're not the starting
player" gate exactly. `starting_player_id` is normally still unset this
early (turn 1 hasn't begun — `turn_loop_mixin` is what first stamps it),
so this falls back to `state.players[state.active_player_index]`, which
already equals the starting player at this point in both
`build_goldfish_engine`/`build_multiplayer_engine` (seat order is turn
order, PLR-11's own convention).

`offer_opening_hand_battlefield_choice`/`resolve_opening_hand_battlefield_
choice` (`game/rules/misc_mixin.py`) generalized in place rather than
growing siblings: the offered `pending_choice`'s accept option id is now
the permission's own `destination` ("battlefield" or "graveyard") instead
of a hardcoded "battlefield" string, so a plain Leyline's wire shape is
completely unchanged (still `{"id": "battlefield", ...}`) while a Buried
Ogre gets `{"id": "graveyard", ...}` for free — the frontend's
`simpleChoiceButtonsHtml` fallback (`gameBoardView.js`) already renders
any option id generically, so no frontend change was needed at all, not
even a new `CHOICE_ICONS` entry. Accepting applies the permission's own
`counter_type`/`counter_count` (Gemstone Caverns' luck counter) the same
direct-`GameObject.add_counters` way `_apply_entry_counters` applies RULE
614.1 entry counters — deliberately *not* routed through `RulesEngine.
add_counters`'s replacement-doubling (Doubling Season etc.), matching
that existing convention rather than introducing a one-off inconsistency
— then the mandatory "if you do" tail: `lose_life` is a direct
`RulesEngine.lose_life` call (no interactivity — the amount is fixed,
there's nothing to choose), `exile_hand_card` opens a real interactive
choice, since *which* hand card gets exiled is the player's own pick
(RULE 601.2c). That reused `RulesEngine.request_choose_objects` rather
than inventing a new `pending_choice` kind: `CHOOSE_OBJECT_ACTIONS`
gained an `"exile"` entry (`_apply_chosen_object` → `self.exile(obj)`),
general enough for any future "exile a card from your hand" cost/effect
to reuse, not just this one. A graveyard destination fires no zone-change
event of its own (unlike the battlefield branch's `ENTERS_BATTLEFIELD`) —
it isn't a discard, a death, or a mill, no existing `EventType` describes
"began the game here", and nothing can be on the battlefield yet with a
trigger that would care.

Tests: `test_oracle_opening_hand.py` gained the two new line regexes'
recognition tests, `pregame_setup_permission`'s three shapes, and both
real cards' MODELED coverage (23 total, up from 11); a new
`TestPregameSetupPermission` class in `test_game_session.py` (6 — Buried
Ogre's graveyard+life-loss accept/decline in a solo goldfish game since
its permission is unconditional; a 2-seat multiplayer game for Gemstone
Caverns' condition — offered to the non-starting seat, withheld from the
starting one, counter+exile-choice on accept, decline leaves it
untouched).

## VIS-5 · A move/priority feed — `move_actors` (2026-08-04)

The board already had `move_log` (labels only — "cast_spell: Lightning
Bolt", "pass_priority", …), but nothing said *who* made each entry, so a
shared-board feed of "Bob hat X gespielt" (the frontend half, Done_
Frontend.md) had nothing to build from. `GameSession.view()` gained a
parallel `move_actors` list rather than a new tracking structure:
`_history` already carries an `actor_id` per entry (`_snapshot`), and
`_history`/`move_log` are always appended/trimmed together at every one
of their four call sites (`apply_action`, `concede`, `rewind`,
`take_back`) — only `_history`'s *head* is ever dropped early (past
`MAX_HISTORY`), so the two stay aligned from the *tail*, which is all a
"most recent move" feed ever needs. `_move_actors()` zips `move_log[-n:]`
against `_history[-n:]`, padding the untracked prefix (older than
`MAX_HISTORY`, or `_apply_advance_to_decision`'s own actor-less
"advance_step" steps) with `None`. No new bookkeeping at any append/trim
site — reading the existing invariant was the whole fix. Tests: a new
`TestMoveFeed` class in `test_multiplayer_session.py` (3 — parallel
length + correct actor, stays aligned after a `take_back`, a concede is
attributed to the conceding player).

## PLR-13 · A format switch reaches the API (2026-08-04)

`GameEngine.new_game` already understood `game_format`/`archenemy_id`
(`models/game_format.py`, `GameEngine._setup_variants`), but neither
`api/game.py` nor `api/multiplayer.py` ever passed one through — Planechase,
Archenemy and Vanguard were engine-complete and reachable only from Python.
Closed the goldfish and multiplayer halves; the two still-open pieces (a
per-seat Vanguard avatar picker, and card *text* for the RULE 9 pool) stay
open as the narrowed `PLR-13`/`PAR-13` in `BACKLOG.md`.

`build_goldfish_engine`/`build_multiplayer_engine`
(`services/game_session.py`) hadn't gone through `new_game` at all — they
build a `GameState`/`GameEngine` directly (bind-on-load via
`bind_from_catalogue`, which `new_game` skips, since it's a test/bot
builder) — so both gained their own `game_format` handling instead:
`get_format(game_format)` overrides the bare `starting_life`/`starting_hand`
arguments, then `engine._setup_variants(fmt, archenemy_id)` runs *before*
the opening hand is drawn (a Vanguard avatar's `hand_size_modifier` has to
be settled first — the same ordering constraint `new_game` already had).
`build_multiplayer_engine` also takes `archenemy_id`; the goldfish builder
doesn't expose one, since the human is the only candidate a solo game has
(`_setup_variants`'s own `archenemy_id=None` fallback already lands on
`state.players[0]`). Neither builder's no-format call site changed
behaviour — `fmt is None` skips every new branch.

`GET /api/game/formats` (`models/game_format.FORMATS`, as
`{name, label, starting_life, starting_hand, singleton, variants}`) backs
the picker on both the Goldfisch start screen and the Multiplayer Setup
table options — one endpoint, since a format is the same choice either way.
`StartGoldfishRequest.gameFormat` threads straight to
`GameSessionManager.create_goldfish`. Multiplayer needed a genuine table
setting instead: `LobbyGame.game_format`/`archenemy_id` (`services/
lobby.py`), set through the existing host-only `POST .../options` route
(`MultiplayerOptionsRequest.gameFormat`/`archenemyId`) — the lobby stores
`game_format` as an opaque string (its own module docstring insists on
staying rules-free, the same treatment `mulligan_style` already got);
`api/multiplayer.py`'s `set_options` is what validates it against
`FORMATS` and 400s on an unknown name, since a table setting can be
rejected before the game exists, unlike a stale saved one `get_format`
has to fall back safely from. `start_game` resolves `archenemy_id`'s
`None` ("not chosen") to the host explicitly, rather than relying on
`_setup_variants`'s own `state.players[0]` default — the lobby's seat
list (join order) and the engine's `seating_order()` (which
`randomize_seating` may have reshuffled) aren't the same list, so "the
host" has to be named by id, not by position.

Also added, alongside the format picker, the **favorite decks** and
**multiplayer default settings** the Profil tab picked up in the same
pass (frontend-driven, but both needed a small backend of their own):
`services/player_assets.py` gained a third per-player table
(`favorite_decks`, same `player_name`-keyed shape as sleeves/token
images — decks aren't owned in this app, one shared `DeckDatabase`, so a
"favorite" flag can't live on `Deck` itself without two players'
favorites colliding) with `GET/POST /api/players/{name}/favorite-decks`
and `DELETE .../favorite-decks/{deck_id}`; goldfishView.js's and
multiplayerView.js's deck pickers now list favorites first (`Array.
prototype.sort`'s stability keeps everything else in server order). The
multiplayer defaults themselves (format, mulligan style, takebacks,
RULE 103.1/103.2 randomization) are purely client-side (settings.js
cookies, same convention as auto-pass) — `multiplayerView.js`'s
`createGame()` applies them via one `setMultiplayerOptions` call right
after `POST /api/multiplayer/games`, the same host-only route the table
option rows already use, so nothing new had to be taught to validate them.

Tests: `TestGameFormatThreading` (`test_game_session.py`, 4 — goldfish/
multiplayer each with and without a format, life/planar-deck/scheme-deck/
archenemy-life assertions); `TestGameFormatOptions`
(`test_api_multiplayer.py`, 5 — unknown format 400s, round-trips through
`/options`, host-only, and two full `/start` runs asserting the *finished*
session's `state.format`/`state.archenemy_id` — one with an explicit
Archenemy pick, one defaulting to the host); `TestGameFormats` +
`TestStartGoldfish.test_game_format_reaches_the_session`
(`test_api_game.py`, 2); `TestPlayerAssetStoreFavoriteDecks` +
`TestFavoriteDecksApi` (new `test_player_assets.py`, 8 — the first test
file for `services/player_assets.py`, sleeves/token-images had none
either).

## ANA-4 · Dynamic (simulated) deck analysis (2026-08-04)

New `services/dynamic_analysis.py`: run N solo goldfish matches headlessly
against a `services/bots.py` `Bot`, aggregate turn-by-turn stats as
mean ± population stddev (`statistics.mean`/`pstdev`), as a background job
(`DynamicAnalysisJobs`) polled through a new `api/dynamic_analysis.py`
router (`POST`/`GET /api/analysis/dynamic[/{id}]`).

**`Bot` × goldfish is a new combination, and the obvious approach doesn't
work.** `Bot` has only ever driven a multiplayer seat, where
`GameSession.interactive_priority` is on and RULE 117 priority genuinely
passes around the table. A goldfish session runs with that flag *off*
(`_run_step` auto-drains the stack), and `bots.py`'s own "nothing to do"
fallback — `{"type": "pass_priority"}`, exactly what `_one_bot_action`
sends — is a dead end there: `GameEngine.pass_priority()` called with no
player only ever resolves the top of an *already non-empty* stack; on an
empty stack (the common case — nothing on it, nothing to do) it's a no-op,
so reusing `run_bots`/`_one_bot_action` unmodified spins forever on turn 1,
confirmed empirically (a `GoldfishBot` looping 300 straight
`pass_priority`s, `turn_number` never leaving 1) before writing anything
else. The fix: `run_one_match`'s own drive loop falls back to
`{"type": "advance_to_decision"}` instead — the goldfish UI's own "Nächste
Entscheidung" button (`GameSession._apply_advance_to_decision`), which
fast-forwards through steps until the active player has a real decision
(a main phase always qualifies, `_step_has_interaction`) — the primitive
that actually moves a solo game forward between real choices. With that
swap, a `GoldfishBot` reaches turn 9 in ~60 actions and a `GreedyBot`
correctly attacks/casts/plays its commander; `test_dynamic_analysis.py`'s
`test_stops_at_max_turns_without_hanging` pins the regression down.

**Metrics not already tracked anywhere** are computed by the harness
itself rather than by touching `GameState.stats` (which every *real* game
would then pay for) — safe here because a solo simulation has no RULE
400.2 concern, so `run_one_match` reads `engine.state` directly:

- **Lands drawn per turn** — `record_stat("draw", amount=N)` only counts
  total cards, not by type. Derived per turn as `total lands in the
  shuffled library at match start − lands still in the library`, sampled
  once per turn (the first time that turn reaches `main2` — guaranteed to
  happen every turn per `_step_has_interaction`, and late enough that the
  turn's land drop has already happened).
- **Mana potential per turn** — `game/mana_potential.py`'s
  `max_potential_total(engine, player)` (the safe upper-bound total, not
  `open_potential_summary`'s six *independent* per-colour maximizations —
  summing those would double-count a single source's mana across multiple
  colours), sampled at the same `main2` checkpoint.
- **Card advantage per turn** — no existing definition (the concept
  normally compares two players' resources; a goldfish has none). Defined
  as cumulative cards drawn so far minus `max(0, turn − 1)` — RULE 103.7a's
  "the starting player skips their first draw" baseline, so a perfectly
  ordinary game with no draw effects reads as a constant 0 rather than a
  constant −1 (caught by first writing the naive `turn` baseline, seeing
  every all-basics smoke-test deck sit at exactly −1 every turn, and
  fixing the baseline rather than shrugging it off as "just how the metric
  works" — `test_a_normal_game_reads_zero_card_advantage` pins it down).
- **Library searches (tutors) resolved** / **turn a commander entered the
  battlefield** — `state.subscribe` (already-public event-bus hook) against
  one match's own event stream: `EventType.LIBRARY_SEARCHED` (fires for
  *every* library search, so this is a superset of "tutors" in the strict
  sense — also counts fetch lands, documented as such rather than silently
  narrowed) and the first `EventType.ENTERS_BATTLEFIELD` whose
  `state.find_object(instance_id)` has `is_commander=True`, keyed by name
  (a deck with 2+ commanders — Partner — gets one turn-tracked per name).
- **Mana produced per turn** is the one metric already tracked
  (`GameSession.analysis()`'s `mana_per_turn`) — read back rather than
  re-derived.

**Infinite-mana guard, added on request after the first cut shipped.** A
`GreedyBot` against a deck with a genuine infinite-mana combo (an untap
effect feeding a mana ability, say) would otherwise tap forever without the
turn ever ending — eating the whole per-match `action_budget` for nothing,
and reporting a `mana_produced` figure for that turn that dwarfs every
other match's, dragging that turn's mean far past what the deck actually
does. `run_one_match` checks `GameState.mana_produced_this_turn["p1"]`
after every action (it already resets every `begin_turn`, so the sum is
genuinely "this turn's" production, never a running total that would
eventually cross the threshold in any long-but-finite game) and aborts the
match the moment it crosses `INFINITE_MANA_THRESHOLD` (1000 — generous
enough that no real, non-looping turn should ever cross it). The turn the
loop was caught on has its whole snapshot dropped (its own
`mana_produced` reading *is* the runaway number, nothing to salvage);
every earlier turn's data, sampled before the loop started, stays in the
aggregate untouched. Counted separately
(`DynamicAnalysisResult.matches_aborted_infinite_mana` /
`MatchResult.aborted_infinite_mana`) rather than silently folded into a
lower `matches_run`, so a deck with a real combo shows up as "flagged",
not as a normal-looking result with a few quietly-missing turns — the
frontend surfaces the count as a warning (`Done_Frontend.md`). Verified
against the real detection path (not a synthetic hook) by lowering the
threshold and letting an ordinary land deck's `GreedyBot` legitimately
cross it in a few turns (`test_infinite_mana_guard_aborts_the_match`).

**Aggregation & the background job.** `run_dynamic_analysis` loops
`run_one_match` `num_matches` times (a fresh `random.shuffle`d library copy
per match, same convention `api/game.py`/`api/multiplayer.py` already use),
catching a single match's exception rather than losing the whole batch
(mirrors `run_bots`'s "one bad action shouldn't wedge the table"). Bounds
(`MAX_NUM_MATCHES=200`, `MAX_MAX_TURNS=30`) are enforced both here and in
the request schema, since a direct caller (a test) can bypass the schema.
`DynamicAnalysisJobs` is a small in-memory, FIFO-capped (20) registry —
no existing async-job pattern exists anywhere in this codebase to plug
into (checked: only the `GameSessionManager`/`Lobby` process-wide
singletons). Each job reports progress via a plain
`on_progress(completed, total)` callback the API layer's `GET` polls.
**Known cost, not a bug:** `apply_action` snapshots a
full `GameState.clone()` (deep copy) per action for undo/rewind support
that a one-shot simulation never uses — a realistic request (20 matches ×
10 turns, the schema's defaults) takes roughly 20-30s wall-clock, scaling
with `numMatches × maxTurns`; acceptable given the ticket's own "runs in
the background" framing and the frontend's progress bar
(`Done_Frontend.md`), but worth knowing before requesting the 200×30
ceiling.

**Bounded worker pool (2026-08-04 follow-up).** Each job originally got its
own bare `threading.Thread` — simple, but a burst of concurrent requests
(or a user mashing "Simulation starten") could spin up an unbounded number
of OS threads, all CPU-bound and fighting the GIL (and the rest of the
process, including ordinary request handling) at once with no cap.
`DynamicAnalysisJobs` now owns one `_JobWorkerPool` — a fixed set of daemon
worker threads (`config.DYNAMIC_ANALYSIS_WORKERS`, default 4, env
`MTG_DYNAMIC_ANALYSIS_WORKERS`) pulling job callables off a `queue.Queue`.
A job that arrives with every worker busy sits as a new `"queued"` status
(`DynamicAnalysisJob.status`: `"queued" | "running" | "done" | "error"`,
where it used to start straight at `"running"`) until a worker frees up —
matches-per-second for whichever jobs *are* running stays the same however
many requests pile up, they just take their turn instead of all degrading
together. Since the GIL serializes this module's pure-Python simulation
work regardless of thread count, the pool isn't about running any single
job faster — sizing it up only helps once real hardware parallelism (a
future multi-process/async rewrite) exists to use it, so the modest default
matches this app's single-process, local-dev scale rather than trying to
predict that. The frontend (`dynamicAnalysisPanel.js`, `Done_Frontend.md`)
polls through the new state exactly like `"running"` (same disabled form,
same "still going" treatment) with its own "Wartet auf freien Worker …"
label so a queued job doesn't read as stuck.

`api/dynamic_analysis.py`'s `POST /api/analysis/dynamic` resolves the deck
through the exact same pipeline `api/game.py`'s `start_goldfish` does
(`parse_deck_sections` → `LazyCardLoader.load_cards` → `apply_legality` →
`expand_entries`, reusing `api/game.py`'s own `expand_entries` rather than
duplicating it) and rejects an illegal deck or unknown `botKind` before a
job is ever started, so nothing gets simulated that couldn't also be
played as a real goldfish game.

Tests: `test_dynamic_analysis.py` — `TestRunOneMatch` (4: a `GoldfishBot`
plays a land every turn, a `GreedyBot` casts its commander, the max-turns
regression guard above, the infinite-mana guard), `TestRunDynamicAnalysis`
(4: mean/stddev shape, the zero-baseline card-advantage check, an unknown
bot kind raises, request
clamping — the clamp test lowers `MAX_NUM_MATCHES`/`MAX_MAX_TURNS` via
`monkeypatch` rather than actually running 200×30 matches, which is
genuinely slow per the cost note above), `TestDynamicAnalysisJobs` (5:
background completion, unknown job id, a single-worker pool proving a
second job stays `"queued"` while the first is `"running"`, the default
and an explicit worker count both landing on `_JobWorkerPool.num_workers`),
`TestDynamicAnalysisApi` (4: full
start-and-poll round trip, illegal deck rejected before a job starts,
unknown bot kind rejected, unknown job id 404s). Also verified live in a
real browser (Playwright) against a real 41-saved-deck library and the
full ~34k-card cache — see `Done_Frontend.md`'s "Simulation" sub-tab entry
for the frontend half and that end-to-end check.

### ANA-4 follow-up · a survivorship-bias fix + a mana-maximizer bot (2026-08-04)

Found while eyeballing the "Dynamische Analyse" chart for a real deck: the
per-turn "lands drawn"/"mana potential"/"mana produced" means sometimes
*dropped* from one turn to the next, even though each individual match's
own numbers only ever go up. Root cause was survivorship bias, not a math
bug — `run_one_match` builds its dummy "Goldfisch" opponent at the same
life as the real player (`build_goldfish_engine`'s `starting_life`,
40 by default), and a `GreedyBot` attacking every turn kills a real
40-life dummy within a handful of turns for any reasonably aggressive
deck, ending that match's data collection right there. Averaged across
many matches, the matches still contributing to a *later* turn's mean are
disproportionately the ones that developed *slower* (a faster deck
finishes and drops out sooner) — dragging every per-turn metric down turn
over turn. Reproduced empirically before the fix: an aggressive 60-card
synthetic deck (38 lands / 22 big creatures), 40 `GreedyBot` matches,
turn 6 had `n=8` (down from `n=40` at turn 1) and the "lands drawn" mean
fell from turn 6 to turn 7.

Fixed by decoupling the dummy's life from the real player's:
`build_goldfish_engine` gained an optional `dummy_starting_life` param
(defaults to `starting_life`, so every other caller — the real Goldfisch
UI, multiplayer — is unaffected); `dynamic_analysis.py`'s `run_one_match`
passes a new named constant, `DUMMY_ANALYSIS_LIFE = 100_000`, high enough
that no real deck deals lethal within `MAX_MAX_TURNS` (30) without
tripping the pre-existing `INFINITE_MANA_THRESHOLD`/action-budget guards
first. This harness reports mana/land development, not who wins, so the
dummy's life was never meaningful data to begin with — after the fix,
every match runs the full `max_turns` and every turn's sample size stays
at `matches_run`.

Separately, the same investigation surfaced that "mana potential"
(`game/mana_potential.py`'s `max_potential_total`, a battlefield-only
figure) and "mana produced" (whatever a bot actually tapped) both
naturally trail "lands drawn" (hand + battlefield + graveyard, cumulative)
— expected, not a bug: RULE 305.2's one-land-per-turn drop means a player
who draws lands faster than they can play them accumulates a gap between
"lands seen" and "lands in play" by design. But neither existing bot made
that gap easy to *read past*: `GoldfishBot` never taps for mana at all,
and `GreedyBot` only taps for whatever it's about to cast, so "mana
produced" was bottlenecked by bot policy, not the board's real capacity.
New `ManaMaximizerBot` (`services/bots.py`) closes that gap directly: it
plays a land every turn and taps every remaining land/artifact mana
source dry, but never casts anything or attacks — a diagnostic bot, not a
real opponent, that makes "mana produced" read as the board's true
per-turn ceiling, directly comparable to "mana potential". Registered in
the shared `BOT_TYPES` registry, so it's automatically offered everywhere
a bot kind is picked from (`GET /api/multiplayer/bots`, both the dynamic-
analysis panel's and the multiplayer lobby's bot pickers) with no frontend
changes needed.

Tests: `test_dynamic_analysis.py` gained
`test_aggressive_deck_does_not_end_the_match_early` (single match reaches
`max_turns` against an aggressive deck), `test_mana_maximizer_bot_taps_out_
without_casting`, and the direct regression test,
`test_aggressive_deck_does_not_lose_later_turn_samples` (asserts every
turn's sample size stays at `matches_run` and the "lands drawn" mean never
decreases turn-over-turn — reproduces the pre-fix bug at a smaller,
pytest-timeout-friendly scale if `DUMMY_ANALYSIS_LIFE` regresses).
`test_bots.py` gained `TestManaMaximizerBot` (plays lands, taps every one
for mana, never casts an affordable spell, never attacks/blocks) and both
bot-catalogue tests (`test_bots.py`, `test_api_multiplayer.py`) now expect
three registered kinds.

## PLR-7, PLR-8 · A `GreedyBot` that weighs lines + attacks a real opponent (2026-08-04)

`services/bots.py`, `game/targeting.py`, `game/effects.py`,
`game/effect_binder.py`, `game/engine/legal_actions_mixin.py`,
`game/engine/activation_mixin.py`, `game/rules/casting_mixin.py`; tests in
`test_bots.py` (31, up from 23) and `test_targeting.py` (20, up from 14).

Closes both open bot-AI tickets at once, since PLR-8 was always "share
PLR-7's fix" — `rank_targets`/`play` were the intended override points and
nothing used them.

- [x] **The main-phase loop is now explicit, not incidental.**
      `GreedyBot._develop_board` (called from `play()` for both `main1` and
      `main2`) tries a land, then `_cast_or_activate`, falling back to a
      manual `tap_for_mana` only once neither offered anything — see below
      for why that order flipped. `run_bots`/`_one_bot_action` already
      re-read `legal_actions` fresh after every single action, so an extra
      land drop a static ability just granted, or a mana ability a cast
      just unlocked, simply shows back up as a fresh offer on the next
      call; no separate "re-check" step was needed. Once nothing is left
      to develop, the turn structure itself moves to combat, which is why
      "attack once there are no more options" needed no code of its own —
      `attack` is never offered outside `declare_attackers` in the first
      place.
- [x] **Casting now leans on mana-potential auto-tap instead of manually
      pre-tapping.** A `cast_spell`/`activate_ability` offer is *only* ever
      made once real pool or potential (`_castable_now_or_via_potential`)
      can pay for it, and applying it auto-taps the exact sources needed
      (`game/mana_potential.py`, "Mana-Potenzial", shipped 2026-07-30). The
      bot's old behaviour — tap every source before ever trying to cast —
      predates that feature and could only strand the wrong colour, the
      same mistake a human clicking lands one at a time makes. `_develop_board`
      now tries casting/activating *first*; manual `tap_for_mana` is a
      last resort with nothing better to do (kept, not deleted — a
      land-only deck with nothing to cast still exercises it, and
      `test_infinite_mana_guard_aborts_the_match`'s "let a real `GreedyBot`
      legitimately cross the threshold" relies on exactly that fallback).
- [x] **Equip/Fortify/Reconfigure sort last among activated abilities.**
      `ActivatedAbility` gained an `attach_kind` field (set by
      `effect_binder._keyword_activated_ability`, surfaced on the
      `activate_ability` action by `legal_actions_mixin._activate_action`)
      so `_cast_or_activate` can push an equip offer behind every other
      ability without guessing from its description text — mana is better
      spent developing the board first, and whatever's left can still
      equip.
- [x] **Lands prefer entering untapped.** `RulesEngine.predict_land_tapped`
      is a read-only preview of `enter_land_tapped`'s RULE 614.1 outcome —
      every deterministic check/fast/slow/Battlebond shape, read off the
      board exactly as playing the land would, with the two genuine
      payment-choice kinds (a shock land, Mariposa Military Base's mirror)
      reading `None` rather than guessing. `legal_actions_mixin._land_action`
      threads it onto every `play_land` offer as `enters_tapped`;
      `GreedyBot._pick_land` sorts `False` (known untapped) ahead of `None`
      ahead of `True`.
- [x] **Targeting is now polarity-aware, not just "opponent first".**
      The old blanket "prefer the opponent's stuff" rule is actively wrong
      for a beneficial effect (a pump/protection spell reaching for an
      opponent's creature is self-sabotage, not merely unambitious).
      `GameEffect.target_polarity()` (`game/effects.py`, default `None`) is
      a best-effort, non-rules classification — `"harmful"` for
      damage/destroy/exile/discard/mill/counter-spell/goad/steal-control/
      tap-down/lose-life-family effects, `"beneficial"` for gain-life/
      regenerate/grant-protection, and sign-aware for the two effects whose
      polarity depends on their own params (`PumpEffect`'s `power`/
      `toughness`, `AddCountersEffect`'s `kind`, `TapEffect`'s `untap`
      flag). `targeting.spell_target_specs`/`ability_target_specs` stamp
      it onto each `TargetSpec.polarity` from the owning effect, including
      a synthesized Aura "enchant" requirement (no `EffectSpec` of its own
      to ask) via `_aura_enchant_polarity`, which reads the Aura's own
      bound layer-7 P/T static on `attached_permanent` — a curse with no
      P/T clause (Pacifism-shaped) stays `None`, which is exactly right
      since the old "prefer an opponent's permanent" default already
      handles it correctly. `requirements_with_targets`/
      `_ability_target_requirements` thread `polarity` onto the wire
      requirement dict; `Bot.rank_targets` gained a `polarity` parameter
      (default `None`, ignored by the base no-op), and `GreedyBot.
      rank_targets` reverses its own "opponent's things first" order for
      `"beneficial"`, keeping it for `"harmful"` and the unclassified
      default. Deliberately not exhaustive — an effect this doesn't cover
      (a bounce, a counter-removal of unknown sign, …) stays `None`, never
      guessed.
- [x] **A pod of 3+ picks an actual opponent, not whoever's listed first.**
      `GreedyBot._attack` used to take the first *player*-kind defender in
      whatever order `legal_defenders_for` happened to return them — legal
      in a two-player game (there's only one), but not a decision once the
      lobby seats up to four. `_weakest_defender` breaks the tie by life
      total, already present in the view (`Player.to_dict`'s `"life"`) —
      no new server-side plumbing needed. Falls back to the first offered
      defender if life totals aren't in the view at all (a caller handing
      `play` a minimal state) or every candidate is tied.

Notable gap this batch didn't close: `RemoveCountersEffect`'s polarity is
genuinely ambiguous by class alone (stripping an opponent's +1/+1 counters
is good, stripping your own -1/-1 counters is also good) and was left
unclassified rather than guessed — see `GameEffect.target_polarity`'s
docstring for the "don't guess" rule this follows.

## PAR-12 · Saved-deck-priority batch (2026-08-04)

Coverage 28.6%→28.9% (9,786→9,893/34,208), PARSER_VERSION 52→53. Unlike prior
batches (ranked purely by cache-wide template count), this one's target list
came from cross-referencing every saved deck in this install's `decks.db`
against the parser gate — 1,969 of 3,039 unique saved-deck card names were
`UNMODELED`, then ranked by which unclaimed clause templates were SOLO
blockers on that set (`parser_probe.py blocked`, restricted to the
saved-deck names). Five clusters closed, +107 cards, 0 regressions
(`parser_probe.py diff`):

- **Untargeted mass "destroy/exile all X [with a filter]" board wipes**
  (RULE 601.2c — Damnation/Day of Judgment/Supreme Verdict/Armageddon/
  Tranquility-shaped). The engine primitive already existed — `game/
  ability_catalogue.py` hand-authors this exact shape per card (Wrath of
  God) via `EffectSpec("destroy", {"selector": "all_creatures", ...})` — but
  no parser handler recognized the general English phrasing at all.
  `catalogue/handlers.py` gained three rows: `destroy_all` (bare "destroy
  all creatures[, with mana value/toughness filter]"), `destroy_all_no_regen`
  (the "…they can't be regenerated." compound, tried first since
  `parse_effect_body` tries the whole unsplit body before falling back to
  its connector-split — this is a real two-sentence body, not two
  independent clauses, so the "no regen" tail needed its own whole-match
  regex rather than composing with the bare row), and `exile_all` (Farewell-
  shaped). Only the two numeric filter kinds `game/effects.py`'s
  `_mass_selector_objects` actually implements (`max_mana_value`/
  `min_mana_value`/`min_toughness`) are recognized — "power N or greater"
  has no mass-form engine support, left unclaimed rather than silently
  dropped. Widened `_MASS_DESTROY_SELECTORS` with `"all_lands"` (Jokulhaups-
  shaped "destroy all lands"), the one selector real cards needed that
  didn't exist yet.
- **"[<Type> [and <type>]] spells you cast cost {N} less/more to cast."**
  (RULE 601.2f — Baral, Chief of Compliance/Archmage of Runes/Bureau
  Headmaster-shaped). Same story: the `cost_reduction` static's
  `spell_type` filter and `affects="your_spells"` default already existed
  (built for the *unscoped* "<type> spells cost {N} more" Thalia-shaped tax,
  `_SPELL_COST_TAX_RE`) — a stale comment on that row even claimed the
  "you cast" self-scoped sibling was "already covered by the hand-authored
  cost_reduction shape," which was simply wrong (grepped the whole
  catalogue — nothing recognized it, hand-authored or parsed). New
  `_SPELL_COST_TAX_YOU_CAST_RE` in `static_handlers.py`, riding the RULE
  613.6 conditional-static wrapper for free (so "As long as ~ is tapped,
  creature spells you cast cost {2} less to cast." — Centaur Omenreader —
  needed no extra work). The two-type compound ("instant and sorcery
  spells you cast…") passes both words through as a list;
  `continuous._spell_type_matches` widened to OR a list. Colour-scoped
  (Medallion cycle) and creature-subtype-scoped (Banneret cycle, "Equipment
  spells…") variants stay deliberately unclaimed — `_spell_type_matches`
  only ever reads a card's main-type flags, no colour/subtype filter exists
  for the mass form. **Found and fixed a latent bug on the way**:
  `continuous._CARD_TYPE_ATTRS` (the map `_has_card_type` reads) had no
  entries for `"instant"`/`"sorcery"`/`"battle"` at all — every existing
  caller had only ever needed the five permanent-type words (a battlefield
  permanent is never an instant/sorcery), so a spell-type check naming one
  of these three silently always returned `False`. Baral's cost reduction
  was the first consumer to actually need it; without the fix the whole
  family would have parsed but never reduced anything for the single most
  common case.
- **"Whenever you cast a/an <type> spell, <effect>."** (RULE 603.1 — a
  genuinely new trigger-condition family, not a widening: `parser_probe.py
  blocked` found 607 SOLO-blocked cache-wide cards on this exact shape, by
  far the largest single template found all batch). The underlying
  machinery already existed — `EventType.SPELL_CAST` fires with
  `object_types` stamped, and `effect_binder`'s `spell_card_types` predicate
  was already built (for the hand-authored Wandering Archaic) — only the
  oracle-text recognition was missing. New `segmenter._CAST_SPELL_TRIGGER_RE`,
  a dedicated whole-line bypass (mirroring `_MAGECRAFT_RE`/
  `_DAMAGE_TRIGGER_RE`'s existing pattern, since it needs to attach a
  `spell_card_types` filter the generic `_TRIGGER_RE`/`_trigger_condition`
  dispatch's simple event-name table can't carry) emitting
  `{"subject": "you"}` — deliberately narrow to that subject; "an opponent
  casts"/"a player casts" is a different subject grammar
  `effect_binder._subject_condition` doesn't support yet, left unclaimed.
  Creature subtypes ("wizard spell") correctly fail closed — `type_words`
  only ever carries main types.
- **"Whenever ~ or another creature dies, <effect>."** (Blood Artist/
  Falkenrath Noble — only 2 cache-wide cards, but both are iconic
  aristocrats staples appearing in multiple saved decks). The union
  `"self_or_group"` subject already existed for a *subtype*-scoped variant
  (`_SELF_OR_GROUP_SUBTYPE_RE`, The Ghoul, Gunslinger-shaped, mandatory "you
  control"); Blood Artist's condition is the plain main-type sibling with no
  subtype and no controller restriction (the whole point of an aristocrats
  payoff is firing off *any* creature dying). New
  `_SELF_OR_GROUP_SUBJECT_RE`, tried before the subtype regex for the same
  reason `_GROUP_SUBJECT_RE` precedes `_GROUP_SUBTYPE_SUBJECT_RE` — a bare
  main-type word would otherwise also match the subtype grammar's
  permissive `[a-z]+`. `effect_binder._build_group_ok` already treats
  `"group"`/`"self_or_group"` identically regardless of whether the
  condition carries `"type"` or `"subtypes"`, so no binder change was
  needed.
- **"Choose a Background"** (RULE 702.124, Commander Legends: Battle for
  Baldur's Gate — Baeloth Barrityl/Ganax/Jaheira/Vhal/Wilson). The same
  RULE 702.124 keyword family as `Partner`, and just as inert in-game — it
  only matters at deckbuilding time (pairing a commander with a Background
  enchantment, RULE 903.7g), which is `services/commander_legality.py`'s
  job (still unimplemented — BACKLOG.md's DB-3, unaffected by this).
  Registered as a bare FLAG keyword in `catalogue/keywords.py` purely so a
  card whose only other lines are ordinary effects reaches `MODELED`
  instead of parking on this one no-op line forever.

Deliberately not chased this batch despite being found along the way:
"Whenever you gain life, <effect>." (Ajani's Pridemate/Archangel of
Thune-shaped, ~59 cache-wide SOLO blockers per `parser_probe.py blocked`) —
`EventType.LIFE_GAIN` already exists (built for the life-gain replacement
family), so this is next-up, ordinary long-tail work, not a re-deferral (no
prior batch had looked at this template before).

Tests: `tests/test_saved_deck_priority_batch_2026_08_04.py` (24 tests, both
parse and execute per family, including the two adversarial "stays
unclaimed" cases — colour/subtype-scoped cost reduction, a creature-subtype
in a cast-spell trigger, and a "power" filter on a mass destroy). Full
backend suite green (3,299 passed; the one `test_game_ws.py` failure in a
full run is the known pre-existing intermittent `DrawCardsEffect`/
`GameObject` flake, unrelated — passes in isolation).

## PAR-12 · Second saved-deck-priority batch (2026-08-05)

Coverage 28.9%→29.4% (9,893→10,068/34,208), PARSER_VERSION 53→54. Continuing
the prior batch's ranking (the highest-yield templates left after it, both
cache-wide and against the saved-deck UNMODELED set). Five more clusters,
+282 cards cumulative with v53 (this batch alone: life-gain +29, the
artifact/enchantment/land target compound +48, commander-creatures-you-own
+2, the attack-pump family +52, prevent-damage single-target +60-ish — see
`parser_probe.py diff` for the authoritative per-run split), 0 regressions:

- **"Whenever you gain life, `<effect>`."** (RULE 119.3 — Ajani's Pridemate/
  Archangel of Thune-shaped). `EventType.LIFE_GAINED` already existed as the
  post-replacement trigger source (`LIFE_GAIN` is the earlier, *replaceable*
  pre-event a "you gain that much life plus N instead" effect rewrites —
  distinct events, not a naming accident). Only the oracle-text recognition
  was missing: one row in `segmenter._PLAYER_TRIGGER_CONDITIONS` (the same
  bare event-name table "whenever you scry/surveil" already uses) plus the
  matching `effect_binder._GROUP_CONTROLLER_EVENT_KEYS["LIFE_GAINED"] =
  "player_id"` entry.
- **A general N-way "target artifact, enchantment[, or land]" `TARGET`
  row** (RULE 115 — Acidic Slime/Aftershock-shaped). `subgrammars.
  _TARGET_ROWS` already had a dedicated 2-way "target artifact or
  enchantment" row mapping to the broad `"permanent"` kind (the same
  accepted precision loss `targeting.legal_targets`'s `"permanent"` branch
  already has — it offers every permanent regardless of printed type, not
  just the named subset). Added one general regex covering any 2+
  combination of `artifact`/`creature`/`enchantment`/`land`/`planeswalker`,
  same `"permanent"` kind, rather than enumerating every real-card
  permutation by hand.
- **"Commander creatures you own have `"<ability>"`"** (cEDH support cards
  — Clan Crafter/Street Urchin-shaped for the subset the existing quoted-
  ability recursion can parse; 26 of the 28 real cards use a group-subject
  or conditional-phase inner trigger `_quoted_ability_grant_effects`
  deliberately doesn't support yet, so this cluster's honest yield is
  small — 2 cards — not the full template count, exactly the
  `PARSER_LONG_TAIL.md` "every batch-plan estimate is an overcount" lesson
  in action). New `continuous.group_selector_objects` selector
  `"commander_creatures_you_own"` — **ownership** (`GameObject.owner_id`),
  not control, the one selector in this whole family that isn't
  `_you_control`-scoped, since RULE 108.3 ownership is what a "commander
  creatures you own" grant actually means (a stolen commander stays its
  owner's for this purpose). Plus a dedicated fixed-phrase
  `static_handlers` recognizer ahead of the general `_QUOTED_GRANT_RE`,
  since "commander" is a designation (`GameObject.is_commander`), not a
  card type or creature subtype `_scope` has any vocabulary for. **Found
  and fixed a latent crash on the way**: `_quoted_ability_grant_effects`
  read `trigger["event"]` and checked `event not in
  _GRANTABLE_TRIGGER_EVENTS` — but a compound self-trigger inner ability
  ("enters or leaves the battlefield") stamps a *list* there
  (`segmenter._SELF_MULTI_EVENT_RE`), and a list is unhashable, so the `in`
  check raised `TypeError` instead of failing closed. This batch's new
  dispatch was the first caller to reach that particular inner-text shape,
  but the bug was already live on the pre-existing `_QUOTED_GRANT_RE`/
  `_ATTACHED_QUOTED_GRANT_RE`/`_SOULBOND_QUOTED_GRANT_RE` paths too — any
  real card quoting a compound-event trigger would have crashed
  `coverage_report.py` (and real deck loading) outright. Fixed with an
  `isinstance(event, list)` guard before the membership test.
- **"Whenever ~ attacks, it gets +N/+N [and gains `<keyword>`] until end of
  turn."** (Borderland Marauder/Charging Paladin/Kiln Walker-shaped — a
  genuinely common pre-modern vanilla-creature template, dozens of real
  cards). The untargeted self-pump row already existed for the `~`-pronoun
  form ("~ gets +N/+N …", an activated ability's own body); this shape's
  body instead refers to the source as "it" (the trigger's own subject),
  which no existing row's `_SUBJECT` alternation covered. New
  `catalogue.handlers` row, `self_subject_only`-gated (only offered from a
  genuinely self-subject trigger, never a bare unbound pronoun elsewhere).
  The "for each `<count>`" scaling variant (Akroan Hoplite's actual
  printed text, "…where x is the number of attacking creatures you
  control") stays unclaimed — `PumpEffect` has no count-scaled amount
  parameter yet, unlike `cost_reduction`'s `per`; a real future primitive,
  not attempted this batch.
- **"Prevent the next N damage that would be dealt to any target this
  turn."** (RULE 615 — Alabaster Wall/Amulet of Kroog/Aven Redeemer-shaped,
  almost always a `{cost}:` activated ability on a defensive
  artifact/creature). `PreventDamageEffect`'s `target_kind` branch already
  supported exactly one real RULE 115 target with no `divided` flag (built
  for PAR-15's plural "…to any number of targets, divided as you choose"
  sibling) — only the singular oracle-text phrasing was unrecognized. New
  `catalogue.handlers` row; note the different word order from the
  existing divided-form regex ("dealt **to any target** this turn" vs.
  "dealt this turn **to any number of targets**"), which is what keeps the
  two rows from colliding without an explicit precedence comment.

Tests: `tests/test_batch_2026_08_05_attack_pump_grant_prevent.py` (19 tests
— parse, execute, and full-card end-to-end per family, including the two
adversarial cases for the commander-creatures grant: a group-subject inner
trigger correctly stays unclaimed, and the compound-event crash regression
is pinned down directly). Full backend suite green (3,319 passed, 0
failures — the previously-flaky `test_game_ws.py` test also passed this
run).

## PAR-12 · Named counter kinds (2026-08-05)

Coverage 29.4%→29.5% (10,068→10,081/34,208), PARSER_VERSION 54→55. Closes
the "put a spore counter on `<name>`" template (Deathspore Thallid/Elvish
Farmer/Feral Thallid-shaped) — `AddCountersEffect.kind` was already a free
string (`RulesEngine.add_counters` works on any permanent, any named
counter, RULE 122.1a), so no engine change was needed; only the parser's
"put a counter on X" recognition was hard-restricted to the literal
`+1/+1`/`-1/-1` pattern. New `catalogue.handlers._add_named_counter` +
`_NAMED_COUNTER_KINDS` whitelist (currently just `"spore"` — extend as a
real card needs the next one, same discipline
`_CREATURE_FILTER_KEYWORD_WORDS` uses), kept as a wholly separate handler
row rather than widening the P/T row's own `ckind` group, since that row's
builder maps *any* non-`-`-prefixed match to `"+1/+1"` — sharing the group
would have silently mis-typed "spore" as a P/T counter instead of leaving
it unclaimed.

**Caught and fixed a self-inflicted regression before it shipped**: the
edit that split `_add_counters`'s tail out for the new sibling function
initially dropped `params.update(_optional_param(m))` from the *original*
P/T handler, breaking "put a +1/+1 counter on up to one target creature"
(RULE 115.1a). `parser_probe.py diff` didn't catch it — it only tracks
MODELED/UNMODELED status, not whether the emitted params are still
correct, exactly the "coverage counts claims, not correctness" lesson
`PARSER_LONG_TAIL.md` already documents — but the full backend suite did
(`test_optional_targets.py`), which is why that suite is a required, not
optional, step of closing a batch.

Tests: `tests/test_named_counter_family.py` (4 tests — parse, an
adversarial "target fungus" subtype-target case that correctly stays
unclaimed, a full-card check, and an execute test through a real upkeep
trigger). Full backend suite green (3,323 passed, 0 failures).

## PAR-12 · Deck-first audit batch: Investigate + the "Hobbits" precon's own set (2026-08-05)

Coverage 29.5%→29.6% (10,081→10,140/34,208), PARSER_VERSION 55→56. First
batch under the new deck-first methodology (`PARSER_LONG_TAIL.md`'s
basic-vs-set-specific split, written this same session): audit a saved
deck's actual card list, prioritize its commander's own originating set's
signature mechanic ahead of generic cache-wide ranking. +354 cards
cumulative with v55, 0 regressions.

- **Investigate** (RULE 701.19a) — the case study that motivated the
  basic-vs-set-specific split in the first place: it *originated* in
  Shadows over Innistrad but is reused across many later sets (Kaldheim,
  Murders at Karlov Manor, …), so it belongs on the **basic** track despite
  looking set-flavored at a glance — check reuse breadth, not origin,
  before filing something as set-specific. `"Clue"` was already in
  `_NAMED_TOKEN_WORDS` (the token itself needed no work), so this is a pure
  `create_token` alias (`catalogue.handlers._investigate`) — bare
  "Investigate.", "Investigate twice.", and "Investigate `<n>` times." (a
  dynamic "investigate X times" stays unclaimed — `COUNT` only ever
  resolves a literal int). 87+ cards, by far the widest single template
  found this session.
- **The "Hobbits" saved deck's own set, Tales of Middle-earth** — audited
  card-by-card (45 of 89 cards were UNMODELED, including the deck's own
  commander): "The Ring tempts you" (RULE 701.51a) as a resolve-time effect
  was a pure alias — `RulesEngine.the_ring_tempts_you` and `EffectSpec`
  type `"the_ring_tempts_you"` already existed (built for one hand-authored
  card), only the general "the ring tempts you" oracle-text recognition
  was missing (`catalogue.handlers._ring_tempts_you`) — 36+ cards. But
  **"whenever the Ring tempts you, `<effect>`" needed a genuinely new
  engine primitive**: `RulesEngine.the_ring_tempts_you` fired no event at
  all, so no card with this template could ever have been modeled
  regardless of parser work — new `EventType.RING_TEMPTED`
  (`effect_binder._GROUP_CONTROLLER_EVENT_KEYS["RING_TEMPTED"] =
  "player_id"`, `segmenter._PLAYER_TRIGGER_CONDITIONS`), fired once the
  Ring-bearer choice is *settled* — immediately for the 0/1-candidate
  paths inside `the_ring_tempts_you` itself, but deferred to
  `resolve_ring_bearer_choice` for the interactive 2+-candidate path — so
  a trigger reading "if you chose a creature other than ~" (Aragorn,
  Company Leader/Faramir, Field Commander) always sees the final bearer,
  not a stale one. Also widened `_NAMED_COUNTER_KINDS` with `"burden"`
  (The One Ring's own counter type).
- **Explicitly not chased this batch** (documented in
  `PARSER_LONG_TAIL.md`'s set-specific-mechanics table rather than silently
  dropped): Duskmourn's **Specialize** (50 SOLO cache-wide, needs a real
  "exiled card becomes a copy" effect, not yet built) and **starting
  intensity** (0 SOLO alone, needs its co-blocker identified first);
  **Learn**'s Lesson-sideboard-zone infrastructure (bare "Learn." parses as
  a 7-card cluster, but a full Lessons deck needs RULE 701.50a's "look at
  your sideboard" zone, which doesn't exist); and Frodo, Adventurous
  Hobbit // Frodo, Sauron's Bane — this saved deck's own commander — whose
  full ability needs three new small primitives together (a
  `life_gained_this_turn` per-turn tracker with no existing analogue, a
  "chose a creature other than `<name>` as Ring-bearer" condition, and a
  `ring_level`-threshold condition) for what's ultimately a 2-card cluster
  (this DFC's own two faces) — a hand-authoring candidate once the
  turn-tracker exists for other reasons, not attempted here since "no
  half-implementations" cuts against half-modeling a deck's own commander.

Tests: `tests/test_investigate_family.py` (6 tests) +
`tests/test_ring_tempts_you_family.py` (8 tests, including the interactive
2+-candidate Ring-bearer path and a direct check that the trigger does
*not* fire before the bearer choice resolves). Full backend suite green
(3,337 passed, 0 failures).

## PAR-12 · Closing the "Hobbits" deck's own commander (2026-08-05)

Coverage 29.6%→29.7% (10,140→10,151/34,208), PARSER_VERSION 56→57. Follows
directly from the previous batch's audit: Frodo, Adventurous Hobbit's full
ability — "Whenever ~ attacks, if you gained 3 or more life this turn, the
Ring tempts you. Then if ~ is your Ring-bearer and the Ring has tempted you
two or more times this game, draw a card." — needed three small resolve-time
condition primitives that didn't exist, all landing in `effects.
ConditionalEffect`:

- **`GameState.life_gained_this_turn`** — a new per-turn tracker (RULE
  119.3), mirroring `cards_drawn_this_turn`'s "reset only the incoming
  active player" convention (every card reading it is a "whenever ~
  attacks" trigger, and a creature only ever attacks on its own
  controller's turn). Incremented in `RulesEngine.gain_life`'s post-
  replacement `_finish` closure, alongside the existing `LIFE_GAINED` fire.
- **`"is_ring_bearer"`** (RULE 701.52a) and **`"ring_tempted_at_least"`**
  (RULE 701.51b, a `Player.ring_level` threshold) — new `EffectSpec.
  condition` keys, whitelisted in `parser/oracle/spec.py`'s
  `_ALLOWED_CONDITION_KEYS` (missing this step doesn't silently drop the
  param the way an unregistered *selector* key would — `AbilitySpec.
  validate()` raises immediately at bind time instead, which is how this
  batch's own first test run caught it).
- **`ConditionalEffect._condition_holds` generalized** from an if/elif
  chain (exactly one condition key was ever set on any card so far) to an
  AND-fold over every key present in the dict — Frodo's own second clause
  is the first card needing two conditions to hold *together*
  ("is_ring_bearer" AND "ring_tempted_at_least"). Backward compatible:
  every pre-existing condition dict still carries exactly one key, so
  existing cards see identical behaviour.
- **A real correctness bug caught before shipping, not just a coverage
  regression**: the first cut of the new `_LIFE_GAINED_THIS_TURN_CONDITION_
  RE` wrapper greedily captured Frodo's *entire* remaining text as its
  `rest`, so parsing it recursively and then tagging *every* resulting
  `EffectSpec` with the life-gained condition silently overwrote the
  second sentence's own, unrelated "if ~ is your Ring-bearer and tempted
  twice" gate — a card that would have *parsed* as `MODELED` but drawn a
  card on the wrong trigger. `parser_probe.py diff` (coverage-only) didn't
  catch this; a real execute test asserting the draw only happens once
  both conditions hold did (`test_second_clause_needs_both_ring_bearer_
  and_tempted_twice`). Fixed by giving the wrapper regex an explicit
  `trailing` group for a second, independently-gated "`.` Then if …"
  sentence, split off and parsed on its own rather than folded into the
  first condition — exactly `PARSER_LONG_TAIL.md`'s "write the adversarial
  test before trusting a general fix" lesson, just on a condition-wrapper
  instead of a plain regex.
- Also closed on the way: **"if you chose a creature other than ~ as your
  Ring-bearer, `<effect>`"** (the `is_ring_bearer=False` mirror) — Aragorn,
  Company Leader/Faramir, Field Commander/Galadriel of Lothlórien/Gandalf,
  Friend of the Shire all use this exact phrasing after "whenever the Ring
  tempts you," each still blocked on one unrelated second clause of their
  own (a static ability or a different trigger), so none of the four
  reached `MODELED` this batch despite the shared clause now parsing.

**Not attempted**: Frodo, Sauron's Bane (the same physical card's
transformed back face) — a bespoke "an activated ability conditionally
changes this permanent's own type and P/T" shape (RULE 205) with no cache
sibling; genuinely singleton, left as documented hand-authoring territory
in `PARSER_LONG_TAIL.md` rather than forced into this batch's shared
grammar.

Tests: `tests/test_frodo_compound_conditions.py` (4 tests — full-card
check, the per-turn reset, and both execute paths: the first clause only
firing when life was actually gained, the second only drawing once *both*
Ring-bearer status and temptation count hold). Full backend suite green
(3,341 passed, 0 failures).

## "Hobbits" / "Wyleth Equip" saved decks: make every card playable (2026-08-05)

User-directed batch: define "playable" as *every* card in two specific
saved Commander decks having its full ability set bound to real behaviour
(not just parsing), and close every gap. Started from 51 unmodeled cards
across the two decks (Hobbits 42, Wyleth Equip 9); ended at 1 (Frodo,
Sauron's Bane — see below). Coverage 29.7%→29.9% (10,151→10,237/34,208),
PARSER_VERSION 57→58 — the rest of the ~50 cards closed were hand-authored
in `ability_catalogue.py`, which this ledger doesn't count.

**Generalizable primitives, in build order:**

- **"Reveal land" cycle** (RULE 614.1's optional sibling to the
  deterministic check-land `unless_types` kind) — `catalogue.lands`'s new
  `reveal_types` kind, resolved via a genuine interactive `land_tapped_
  reveal` `pending_choice` (the controller can hold a matching card and
  still decline, unlike a board-state check) — `RulesEngine.
  enter_land_tapped`/`_land_tapped_reveal_choice`. 8 SOLO cache-wide
  (Fortified Village, the "Snarl" cycle, …).
- **"Whenever you gain life, `<effect>`" dynamic-amount family** — "that
  much"/"that many", reading `LIFE_GAINED`'s own `amount` off
  `GameContext.trigger_event`: `LoseLifeEffect`/`AddCountersEffect`/
  `PumpEffect.amount_from_trigger_event`, the same idiom `AddManaEffect`
  already had for Raphael, Ninja Destroyer. Surfaced and fixed a real
  latent mis-model risk on the way: the new `add_counters_from_trigger_
  amount` handler's bare-pronoun branch would have silently misread "it"
  as the source under a *group*-subject trigger (Necropolis Regent-shaped
  — "it" there means whichever creature dealt the damage) — gated with
  `EffectHandler.self_subject_only`, and `segmenter`'s player-event branch
  now correctly passes `self_subject=True` (a player-subject trigger
  introduces no group, so a bare pronoun is unambiguous). 12 SOLO
  cache-wide (Ageless Entity, Sanguine Bond, Auxiliary Boosters via the
  `create`+`attach` family below, …).
- **`LIFE_GAINED` as a second player-subject *grantable* trigger event**
  alongside `STEP_BEGIN` (`continuous._PLAYER_SUBJECT_GRANTED_EVENTS`) —
  "equipped/enchanted creature has 'whenever you gain life, …'" resolves
  "you" against the *granted-to* permanent's controller, same rule
  `STEP_BEGIN`'s `phase_relation` already followed for phase triggers.
  Closes Field-Tested Frying Pan/Light of Promise/Sunbond.
- **`AttachEffect`'s `target_kind="created"`** and the matching
  **`_create_token_and_attach`/`_create_named_then_create_token_and_attach`**
  handlers — "create a token and attach ~ to it" (Living Weapon-adjacent,
  printed as ordinary text rather than the keyword), reading
  `GameContext.created_objects`. Closes Auxiliary Boosters/Field-Tested
  Frying Pan's own first sentence.
- **"Whenever you sacrifice a Food/Clue/Treasure, `<effect>`"** —
  `EventType.SACRIFICE` gained a `subtypes` payload (it only had
  `object_types`, main types, before — mirroring `DIES`'s existing split)
  and a new `sacrifice_type` trigger-condition predicate
  (`effect_binder._trigger_condition`). 4 SOLO cache-wide (Experimental
  Confectioner, Nuka-Cola Vending Machine, Trail of Crumbs, Unlucky
  Cabbage Merchant), narrows 3 more.
- **"If you don't control a Food/Clue/Treasure, `<effect>`"** — a new
  `ConditionalEffect` key, `controls_none_of_type`, the same "wrap the
  rest, tag the condition" idiom `life_gained_this_turn_at_least`/
  `is_ring_bearer` already use. Closes Butterbur, Bree Innkeeper.
- **Mass-destroy `min_power`/`max_power` filter** — the power-threshold
  sibling of the pre-existing mana-value/toughness mass-destroy filters
  (`_mass_selector_objects`). 6 SOLO cache-wide, including Elspeth, Sun's
  Champion.
- **`without_card_type` creature-filter qualifier** (`combat.
  matches_object_filter`) — "target **nonartifact** creature", the negated
  sibling of the existing `card_type` key. Hand-authored for Go for the
  Throat rather than wired into the parser this batch (4 more SOLO
  cache-wide if it is — Grisly Spectacle, Magus of the Abyss, The Abyss —
  left for a future PAR pass).

**A real coverage-badge bug, found via the `game-engine` skill's
`primitives` search** (unrelated to any of the above): `ability_catalogue.
is_registered` didn't share `specs_for`'s own DFC/MDFC/split "//"
front-face fallback, so a card registered under its front face alone
(Halvar, God of Battle — registered two cEDH-cube batches ago) reported
UNMODELED when looked up by its full combined name (Halvar, God of Battle
// Sword of the Realms) despite `specs_for` binding it perfectly correctly
in every real game. Fixed by giving `is_registered` the same fallback.
Worth checking any other coverage-measurement code path that calls
`is_registered` directly instead of going through `specs_for`.

**Hand-authored** (`ability_catalogue.py`, ~30 cards) — each with its own
documented simplification where a primitive didn't exist and building one
wasn't worth it for a single card (dynamic entry-counter multiplier
`AddCountersEffect.x_multiplier`; `ConditionalEffect`'s
`source_x_paid_at_least`/`creatures_died_this_turn_at_least`;
`LoseLifeEffect.amount_from_life_gained_this_turn`/
`amount_from_burden_counters_on_self`; `DrawCardEffect`'s
`burden_counters_on_self` count selector; `costs.ActivationCost.
sacrifice_count`, the `tap_others`-shaped sibling for "Sacrifice N
`<type>`s:"; `continuous.activation_cost_reduction_for`'s subtype-scoped
branch, "activated abilities of Foods you control cost `{1}` less"; two
new `ReplacementRegistry` entries, `create_one_of_each_named_token`/
`additional_named_token`, both guarded against the reentrant CREATE_TOKENS
event their own side-effect token creation fires; and the
`legendary_creatures_you_control`/`nonlegendary_creatures_you_control`/
`attacking_creatures` `affects` selectors). Full list and each card's own
simplification note: see the "Hobbits"/"Wyleth Equip" entries in
`ability_catalogue.py` directly (grep for the "saved-deck-priority batch"
section comments).

**Not attempted**: Frodo, Sauron's Bane — a genuine two-stage type/base-P/T/
ability state machine (RULE 205.1/613, "becomes a copy-independent creature
with a new type line" gated on the permanent's *own current* subtype,
closer to a Class's level-up than any one-shot effect this engine has).
Left genuinely unregistered (not registered with empty/vanilla specs)
so the coverage badge keeps meaning what it says.

Tests: `test_land_tap_conditions.py` (+6), `test_lifegain_dynamic_amount_
family.py` (13, new file), `test_sacrifice_type_trigger_family.py` (3, new
file), `test_controls_none_of_type_condition.py` (3, new file),
`test_saved_deck_priority_batch_2026_08_04.py` (1 updated — the mass-
destroy power filter went from documented-unclaimed to parsed). Full
backend suite green throughout (3,370 passed).

## Frodo, Sauron's Bane: closing the "Hobbits" deck's last unmodeled card (2026-08-05)

The two prior batches above both left this card **not attempted**, reading
its two activated abilities — "{W/B}{W/B}: If Frodo is a Citizen, it
becomes a Halfling Scout with base power and toughness 2/3 and lifelink."
/ "{B}{B}{B}: If Frodo is a Scout, it becomes a Halfling Rogue with
'…'" — as "a genuine two-stage type/base-P/T/ability state machine…
closer to a Class's level-up than any one-shot effect this engine has."
Re-examined from scratch: every piece it actually needs already existed,
generically, from unrelated cards — this closed with **one small, reusable
addition** rather than a new state machine.

- **The transformation itself is nothing but composition**, hand-authored
  in `ability_catalogue.py`: a plain custom-kind counter (`frodo_stage` —
  `AddCountersEffect.kind` is free text, no whitelist ties it to "level" or
  "class_level") bumped by each ability's own effect, gating two `static`
  specs via `active_if: {"kind": "source_counters", "counter":
  "frodo_stage", "min": N}` — **deliberately `min`-only, no `max`**, so
  both stages stay active once unlocked instead of being mutually
  exclusive bands (a Leveler's tiers). That's what lets the Rogue stage
  never restate a P/T: RULE 613.7 timestamp layering keeps the still-active
  Scout static's own `type_change` (its `power`/`toughness` params feed
  `continuous._apply_layer_4_type`'s `animation_pt`, the same "becomes an
  X/Y creature" shape an animate effect uses) underneath the Rogue static's
  later `set_subtypes` override — the engine reproduces the card's own
  omission for free, rather than needing to know to copy it forward.
- **`ActivationCost.activation_condition` settable directly from a
  hand-authored `cost` dict** (`game/costs.py`'s `parse_activation_cost`,
  one `elif`-shaped addition) — "if Frodo is a Citizen/Scout" gates each
  ability's own legality through the exact PAR-10 `source_counters` check a
  static's `active_if` already uses, previously reachable only via the
  oracle parser's `ACTIVATION_CONDITION_MARKER` strip-and-fold path
  (`effect_binder.bind_ability`), which a spec built directly in Python has
  no marker to strip in the first place.
- **The Rogue-stage granted trigger's own if/else** — "that player loses
  the game if the Ring has tempted you four or more times this game.
  Otherwise, the Ring tempts you." — was the one real gap:
  `ConditionalEffect` only ever gated a single existing effect (no
  "otherwise" branch), and `grant_triggered_ability`'s `grant_effects` list
  was built through a bare `EffectRegistry.create` with no way to condition
  an entry at all — a printed ability's own clause could be conditional
  (`EffectSpec.condition`), but a *granted* one's never could. Closed
  generally: `continuous._build_grant_effect` now wraps a `grant_effects`
  entry in `ConditionalEffect` when it carries an optional `condition` key,
  and `ConditionalEffect` gained `ring_tempted_at_most`, the upper-bound
  mirror of the already-shipped `ring_tempted_at_least` (Frodo, Adventurous
  Hobbit's own front-face batch) — two independently-gated conditionals
  with complementary bounds standing in for one if/else, without a
  dedicated "otherwise" field. "That player" (not "you") is
  `LoseGameTriggerDamagedPlayerEffect`, the player-flavoured mirror of the
  existing `ExileTriggerDamagedCreatureEffect`'s "that creature" pronoun,
  reading the granted ability's own firing `DAMAGE` event.

Coverage 29.9%→29.9% (10,237→10,238/34,208, +1 AUTHORED card) — the
"Hobbits" saved deck (see the "make every card playable" batch above) is
now fully modeled, closing that batch's one remaining gap.

Tests: `test_frodo_saurons_bane.py` (new file, 6 tests — starting state,
each activation's own legality gate including "can't skip/repeat", the
Scout-stage type/P-T/lifelink transformation, the Rogue-stage transform
that keeps 2/3 without restating it, and both branches of the granted
trigger's if/else). Full backend suite green (3,376 passed).

## "Keywords Showcase" and "Eliferate" saved decks: make every card playable (2026-08-05)

User-directed batch, same "playable" definition as the "Hobbits"/"Wyleth
Equip" batch above: every card in both saved decks bound to real behaviour,
not just parsing. Started at 18 unmodeled cards for "Keywords Showcase" (9)
and "Eliferate" (~40, after Infect/normalize work below already closed a
few incidentally); ended with **"Keywords Showcase" fully modeled (18/18)**
and **"Eliferate" at 64/91** — the remaining 27 are genuinely bespoke
(planeswalker loyalty-ability bodies, Roaming Throne's trigger-doubling,
Channel abilities, three different "as ~ enters, choose a creature type"
*payoff* shapes each needing its own dynamic-chosen-type read, Mirrormind
Crown's "instead of creating tokens, create copies" replacement) and were
deliberately left rather than half-modeled. Coverage 29.9%→30.6%
(10,238→10,479/34,208), PARSER_VERSION 58→59, +239 cards, 0 regressions
(`parser_probe.py diff` after every change). Full pytest suite green
throughout (ended at 3,452 passed).

Worked as a genuine engine-first pass, not a per-card patch list: almost
every fix below started as "what does *this* card need" and ended up
closing a whole family, because the missing piece was a load-bearing
primitive gap, not a regex gap. In build order:

- **RULE 702.90/91 Infect/Wither** — recognized as keywords (`combat.
  COMBAT_KEYWORDS`/`_ORACLE_PATTERNS`) but with **zero behaviour**: no
  code anywhere converted damage to poison/-1-1 counters. `combat.
  has_infect`/`has_wither` + `RulesEngine.deal_damage`'s `_finish` closure
  now branches before the ordinary life-loss/damage-marked paths — infect
  routes a player hit through `add_player_counters(..., "poison", ...)`
  (itself already replacement-aware, so a poison-doubling effect composes
  for free) and a creature hit through `add_counters(..., "-1/-1", ...)`
  instead of `damage_marked`; wither is the creature-only half (players
  still just lose life). Closes Glistener Elf-shaped cards outright, and
  is what makes Triumph of the Hordes' *granted* infect actually do
  something once the normalize fix below lets it parse.
- **A `normalize` fold: "Until end of turn, `<body>`." → the far more
  common trailing "`<body>` until end of turn."** — every existing
  duration handler already expects the trailing form; the leading one
  (Triumph of the Hordes-shaped) was simply invisible to all of them.
  Deliberately conservative (single-sentence lines only — a leading
  duration wrapping a quoted granted ability with its own internal period
  is left unclaimed rather than mis-split). 124-card upper bound, +4
  measured this batch (most of the 124 need a second, unrelated fix too).
- **RULE 702.33b's *override* kicked-conditional** — "deals N damage... if
  kicked, deals M damage *instead*" is a different shape from the additive
  "if kicked, `<effect>`." RULE 702.33b already covered:
  `DealDamageEffect.amount_if_kicked`/`CopyPermanentEffect.
  count_if_kicked`, mirroring the pre-existing (but undocumented as a
  precedent until now) `PreventDamageEffect.amount_if_kicked`. Both
  implemented as a **property**, not a field set at construction, since
  `RulesEngine._substitute_x`'s generic `"x"`-sentinel substitution (an
  X-kicker spell) has to keep composing with the override — closes Burst
  Lightning/Roil Eruption/Shivan Fire/Rite of Replication outright, ~27
  more on the wider "if kicked, ... instead" family left for a future pass
  (each needs its own effect-specific `_if_kicked` param).
- **RULE 707/706.2's bare `create a token that's a copy of target X`** had
  no oracle-text recognizer at all (`CopyPermanentEffect` existed,
  Ephemerate-adjacent cards had always been hand-authored) — narrow by
  design (only a bare `{TARGET}` phrase, no "except it's/has/isn't…"
  modification clause, since that clause's shapes are too varied to fold
  into one grammar safely). Closes Cackling Counterpart/Rite of
  Replication; ~40 more SOLO cache-wide have a "except …" tail this batch
  didn't attempt.
- **RULE 615's Fog-shaped unscoped prevention** — "prevent all combat
  damage that would be dealt this turn," no chosen recipient at all,
  unlike the pre-existing `PreventDamageEffect`'s two per-recipient
  shields. New `PreventAllCombatDamageEffect`/`RulesEngine.
  prevent_all_combat_damage_this_turn`, the shield living on the caster's
  `player_effects` purely as storage (the `condition` itself checks
  nothing about whose damage it is). One of the most repeated templates in
  the cache: +36 cards this batch alone.
- **RULE 119/701.8's hand-disruption "reveal hand, choose a card, that
  player discards it"** (Duress/Thoughtseize/Coercion-shaped) — the
  *chooser* is the caster, not the hand's owner, which is exactly
  `RulesEngine.request_choose_objects`'s existing shape (Tevesh Szat's
  sacrifice, Cloudstone Curio's bounce), just never sourced from a hand
  before; its pre-existing `action="discard"` already resolves against the
  *object's own owner* regardless of who picked it, so no engine change
  was needed there, only `RevealHandChooseDiscardEffect` wiring a hand
  scan through it. Five real filter phrasings recognized (bare/nonland/
  noncreature+nonland/creature-or-planeswalker/artifact-or-creature).
  63-card family, +16 measured this batch (the rest need a filter word or
  trailing "you lose N life" this batch's table doesn't cover).
- **`RulesEngine.blink` gained a `controller` param** — Restoration
  Angel's "return that card to the battlefield under **your** control" is
  not the same as plain blink's "under its **owner's** control"
  (`BlinkEffect.under_your_control`). Surfaced **a real latent bug on the
  way**: `targeting.legal_targets`'s `creature_you_control`/
  `other_creature_you_control`/`land_you_control` branch never consulted
  `TargetSpec.creature_filter` at all — any card needing a filtered
  "target creature you control" (not just this one) was silently offering
  every creature regardless of the filter. Also added `without_subtype`
  to `combat.matches_object_filter` (Restoration Angel's "non-Angel") and
  a dedicated blink-family oracle recognizer (`_BLINK_NON_SUBTYPE_RE`).
- **`RulesEngine.regenerate` gained a `creature_filter` param** the same
  way — "regenerate **another target Elf**" (Ezuri, Renegade Leader/Mad
  Auntie/Baron Sengir). "another" needed no special exclusion logic: the
  plain `"creature"` target kind's own `legal_targets` branch already
  excludes the ability's own source unconditionally, which is also why a
  pre-existing test asserting this shape "stays unclaimed" needed
  updating, not just a new passing test.
- **Two more negative/compound target-filter keys on `combat.
  matches_object_filter`**: `without_color` (Doom Blade's "nonblack" — the
  single most repeated removal template in the cache, ~47 SOLO, this batch
  closed the color+`can_be_regenerated`-tail forms) and `"attacking"`
  (Gnarlroot Trapper's "target attacking Elf you control", composing with
  the pre-existing `subtype` key).
- **Targeted `draws a card`** — "target player draws a card" had **no**
  handler at all; `_draw`'s regex only ever matched the untargeted "you
  draw"/bare "draw" forms, so a targeted draw was silently unclaimed
  (never silently *mis-bound* — the coverage gate is fail-closed — but
  still a real, fixable gap). Widened `_draw` with the same `who`-prefix
  treatment `_discard` already had (`DrawCardEffect.target_kind`/
  `.selector` already existed as engine primitives). Closes Kenrith, the
  Returned King/Oona's Grace, 16-card family.
- **RULE 701.28's "defending player reveals the top card... if it's a
  land card, puts it into their hand"** (Goblin Guide) — a new, narrow
  `RevealTopConditionalToHandEffect` (reveal itself has no separate game
  state; the real behaviour is the conditional move). Single-card yield
  this batch, but the primitive is general over any of the four printed
  card-type words.
- **RULE 702.28c's Cycling trigger, from nothing** — "When you cycle this
  card, `<effect>`." had no event to watch: the pre-existing generic
  Cycling keyword binding (`effect_binder._cycling_activated_ability`)
  built a plain "discard this card: draw a card" `ActivatedAbility` with
  no signal at all that a *Cycling* discard (as opposed to a Channel-cost
  one, which shares `ActivationCost.discard_self`) had happened. New
  `EventType.CYCLED` + `ActivationCost.is_cycling` (set only by the
  generic Cycling binder) fired from `GameEngine._pay_activation_cost`;
  found via a **graveyard-scoped trigger scan**
  (`RulesEngine._collect_cycled_triggers`) mirroring the pre-existing
  dies-from-graveyard one, since the ordinary `_collect_triggers` loop is
  battlefield-only and the cycled source is already in the graveyard by
  the time the event fires. Its own **{X} preservation**
  (`GameObject.cycling_x_paid`, a `"cycling_x"` `_substitute_x` sentinel
  mirroring Kicker's pre-existing `kicker_x_paid`/`"kicker_x"`) closes
  Shark Typhoon's own X/X cycling bonus specifically. Ranked template:
  37-card family, +1 measured directly (Shark Typhoon; the other 36 each
  need their own effect body parsed, this batch only built the trigger
  itself).
- **A card-type-*excluding* spell-cast trigger** — "whenever you cast a
  **non**creature spell" had no recognizer; only the *inclusive* form
  ("…a creature spell") existed (`effect_binder`'s pre-existing
  `spell_card_types` OR-predicate). New `spell_exclude_card_types`
  predicate + `_CAST_SPELL_TRIGGER_NEG_RE`, tried *before* the positive
  row (its own generic word-list regex would otherwise swallow "non..."
  as a bogus type list and return unclaimed without ever trying the
  negation). Ranked template: 92-card family, +1 measured directly
  (Shark Typhoon's other trigger; most of the rest need their own trigger
  body parsed too).
- **The same trigger's creature-*subtype* sibling** — "whenever you cast
  an **Elf** spell" (Lys Alana Huntmaster/Leaf-Crowned Visionary). The
  engine predicate (`effect_binder`'s `spell_subtype_any`, a live
  type-line substring check off the event's `instance_id`) already
  existed, built for "Aura, Equipment, or Vehicle spell" — just never
  reachable from a bare single-subtype-word clause. Deliberately a
  **curated whitelist** of ~30 real creature types
  (`_CAST_SPELL_SUBTYPE_WORDS`), not "any word": the substring check would
  otherwise silently misfire on adjectives that happen to appear in some
  type line ("legendary") or silently never fire on ones that don't
  ("historic"/"kicked"/"multicolored"/"party") — both wrong, and neither
  caught by the coverage gate. Ranked template: 181-card upper bound
  (color-word triggers dominate the rest, not attempted); +2 measured
  directly. Surfaced a **second, pre-existing bug on the way**: neither
  the positive nor negative cast-spell-trigger row ever called
  `_peel_optional` on its body, so "…you may `<effect>`" bodies (a very
  common continuation) had silently failed to parse since those rows were
  first built.
- **RULE 118.3's `pay_cost_then`, first oracle-text recognizer** — "You
  may pay `<cost>`. If you do, draw a card." `PayCostThenEffect` already
  existed (Mana Vault/Wandering Archaic, hand-authored); nothing emitted
  it from oracle text. The load-bearing subtlety: this is **not** the
  generic "you may `<effect>`" `AbilitySpec.optional` shape — the trigger
  itself is mandatory, only the embedded cost is optional, so peeling
  "you may" and setting the ability-level flag would double-gate the same
  choice. `_peel_optional` already had exactly this guard for the
  energy-only `pay_energy_then` case (`_PAY_ENERGY_THEN_PEEL_GUARD_RE`);
  widened from `{E}`-only to any single mana symbol rather than adding a
  second, parallel guard. 21-card "draw a card" tail alone (the general
  "if you do, `<any effect>`" shape wasn't attempted); closes Leaf-Crowned
  Visionary combined with the subtype trigger above.
- **Three dynamic-magnitude token/pump shapes**, each reading a live
  quantity instead of a fixed int: `CreateTokenEffect.
  count_from_trigger_event` ("create **that many** tokens" — Lathril,
  Blade of the Elves' own combat-damage payoff, 38-card family, +1
  measured); `PumpEffect.amount_from_count_selector` ("+X/+X, where X is
  the number of creatures you control" — Craterhoof Behemoth, one shared
  magnitude for the whole selector group, computed via the pre-existing
  `continuous.count_selector`); `PumpEffect.
  per_recipient_controller_counter` ("-1/-1 for each poison counter **its
  controller** has" — Phyresis Outbreak, the one shape where each
  recipient in a group scales *independently* by its own controller's
  count, not one shared number). All three mirror the pre-existing
  `amount_from_trigger_event`/`pt_from_trigger_event` idiom rather than
  inventing a new one.
- **Selector/filter reach widenings**, each closing 2+ cards on their own:
  `creatures_you_control_of_type_<X>` reached `continuous.
  group_selector_objects` (it only ever existed on `count_selector`, a
  different function) so a one-shot `PumpEffect.selector` can target "Elf
  creatures you control", not just count them (Elvish Warmaster/Ezuri,
  Renegade Leader); `permanents_you_control` reached the same function for
  Heroic Intervention's "permanents you control gain hexproof and
  indestructible"; `other_creatures_you_control` reached `TapEffect.
  selector` for Copperhorn Scout's "untap each other creature you
  control" — which surfaced a **third latent bug**: that selector branch
  never passed `src=self.source` to `group_selector_objects`, so "other"
  had always been silently inert for any selector that needed it.
- **`create_token` gained two dynamic-*count* oracle recognizers**
  sharing one selector vocabulary with the pump widenings above: "for
  each `<subtype>` you control" (Elvish Promenade) and "X ..., where X is
  the number of `<subtype/attacking>` ..." (Galadhrim Ambush's own token
  half — its second sentence, a source-filtered Fog variant, was not
  attempted).

**Not attempted, and why** (left genuinely unmodeled rather than
half-modeled): Boseiju, Who Endures/Takenuma, Abandoned Mire's Channel
abilities (a `discard_self`-costed activated ability whose own effect
needs a `search_for_land_and_battlefield` shape this repo hasn't built);
Vraska, Betrayal's Sting/Golgari Queen (planeswalker loyalty-ability
bodies — "target creature becomes a Treasure artifact... and loses all
other card types and abilities" is a genuine become-effect this engine's
`EnterAsCopyReplacement`/`become_copy` family doesn't cover); Roaming
Throne ("if a triggered ability... triggers, it triggers an additional
time" — a trigger-doubling replacement with no existing analogue);
Realmwalker/Vanquisher's Banner/Selfless Safewright (three different
"...of the chosen type" *payoffs* — RULE 601.2b's "as ~ enters, choose a
creature type" is itself modeled, but reading that dynamic choice back
into a cast-trigger filter, a library-permission filter, and a grant
filter are three separate reads none of which exist yet); Mirrormind
Crown ("the first time you would create 1+ tokens, instead create that
many copies of equipped creature" — a genuine replacement effect on the
token-creation event itself); and Glissa Sunslayer/Glissa, Herald of
Predation (each a "choose 1 —" modal trigger whose individual mode bodies
are themselves further blocked on unrelated primitives — Incubate,
transforming all tokens of a kind, etc.).

Tests (all new files unless noted): `test_infect_wither` cases folded into
`test_game_engine.py`; `test_kicked_conditional.py` (+6, existing file);
`test_modal_creature_filter_family.py` (+11, existing file — also fixed
the `creature_you_control` `creature_filter` latent bug's regression
coverage); `test_prevent_damage.py` (+7, existing file);
`test_hand_disruption_family.py` (8); `test_new_object_identity.py` (+2,
existing file); `test_oracle_pipeline.py`/`test_regenerate.py` (+2/+1,
existing files); `test_poison_counter_family.py` (8);
`test_dynamic_token_count_family.py` (5);
`test_group_pump_count_selector_family.py` (4); `test_channel_cycling.py`
(+18, existing file); `test_spell_subtype_trigger_family.py` (7);
`test_attacking_subtype_and_tap_selector_family.py` (5). Full backend
suite green throughout every step (ended at 3,452 passed, 238 skipped).

## "Eliferate" (finish) and "Imodane" saved decks: make every card playable (2026-08-06)

User-directed follow-up to the batch above ("Keine Zurückstellungen" — no
deferrals): close out Eliferate's remaining 27 unmodeled cards, then bring
"Imodane" (a from-scratch Boros/Jeskai-adjacent burn-commander deck, 69
unique cards, previously untouched) to full coverage too. **Both decks
end fully playable: Eliferate 91/91, Imodane 69/69** (`parse_oracle(...).
modeled or ability_catalogue.is_registered(...)` per card, re-verified
against the live saved decks after the batch). Full pytest suite green
throughout (ended at 3,452 passed, 238 skipped).

**Two durable, pre-existing engine bugs found and fixed along the way** —
not scoped to either deck, and were silently blocking *any* card that
would ever have triggered off them: `RulesEngine.add_counters`/
`add_player_counters` (`game/rules/mana_counters_mixin.py`) and
`create_token` (`game/rules/misc_mixin.py`) each computed their event
through `apply_replacements(event, on_resolved=_finish)` but the
`_finish` closure applied the effect and never called `self.state.
fire_event(resolved)` — so COUNTER and CREATE_TOKENS events were never
broadcast to `_collect_triggers` at all. No card in this engine's history
could ever have triggered off "a counter is placed on something" or "a
token is created" until this fix. Both verified via before/after tests
(Flourishing Defenses/High Perfect Morcant for counters, Mirrormind Crown
for tokens) and the full suite stayed green.

Closing Eliferate's last 27 needed one new primitive per genuinely novel
shape, most reused since (see Imodane below):

- **RULE 603.3d trigger doubling** (Roaming Throne, "if a triggered
  ability of a permanent you control triggers, it triggers an additional
  time") — `continuous.trigger_doubler_bonus` plus a `TriggerDoublerEffect`
  marker, wired into `_collect_triggers`'s per-object loop as an extra
  `trigger_doubler_bonus(...)` added to the base copy count. No prior
  analogue existed for "this fires again" as opposed to "this fires
  bigger".
- **RULE 601.2b resolve-time interactive choices** — a new category
  distinct from the existing enter-battlefield `_offer_enter_choices`
  pipeline: "choose a creature type, then grant it something" (Selfless
  Safewright) and "choose a player" (Stuffy Doll, reused for Imodane's
  own remaining singles below), both `RulesEngine.request_choose_X`/
  `resolve_choose_X_choice` pairs dispatched by `kind` string in
  `turn_loop_mixin.resolve_pending_choice`.
- Vraska, Betrayal's Sting/Golgari Queen's loyalty bodies, Mirrormind
  Crown's "create copies instead of tokens" replacement, and Glissa
  Sunslayer/Glissa, Herald of Predation's modal triggers all shipped as
  hand-authored entries reusing existing primitives (`EnterAsCopyReplacement`-
  adjacent copy effects, `request_choose_objects`, the modal `"choose one
  —"` machinery) rather than needing new engine mechanisms — the
  `Done_Backend.md` entry above had flagged them as blocked on primitives
  that, on closer inspection, either already existed or decomposed into
  a documented simplification instead (see each factory's own docstring
  in `game/ability_catalogue.py` for the exact trade made per card).
- Boseiju, Who Endures/Takenuma, Abandoned Mire's Channel abilities
  shipped as their own real `discard_self`-costed activated abilities.

"Imodane" then went from 0/69 to 69/69 across several batches (damage-
modifier family, exile-and-play-window family, mana/cost/counters family,
planeswalker/emblem/equipment family, Sieges + Magda + Birgi, and a final
10-card "remaining singles" batch closing with the commander herself).
New primitives, mostly built for one card and immediately reused:

- **"Spell watchers"** (`GameState.spell_watchers`, Dual Strike's "when
  you next cast an instant or sorcery spell this turn, copy it") — a
  brand-new GameState-level mechanism distinct from both an ordinary
  object-bound `TriggeredAbility` and a step-bound RULE 603.7
  `DelayedTrigger`: a `SPELL_CAST` subscriber (`_check_spell_watchers`)
  consumes a standing "watch for the next qualifying cast" registration.
- `GrantDieToExileThisTurnEffect` (Lava Coil/Smite the Deathless/Torch
  the Tower's "exile instead of graveyard, this turn only") — a turn-
  scoped `ReplacementEffect` appended directly to `target.
  replacement_effects` with the firing turn number baked into a closure
  condition for self-expiry.
- Cost-reduction extended two ways: `continuous.cost_reduction_for`
  (RULE 601.2f, battlefield-sourced) gained a `spell_color` filter for
  the Medallion cycle; `self_cost_reduction_for`'s existing `per`/
  count_selector mechanism (Delve/Affinity-shaped) was reused unchanged,
  with a new unscoped `creatures_on_battlefield` selector, for
  Blasphemous Act.
- `EffectSpec.condition`'s whitelist gained `graveyard_has_type`
  (Trystan) and `target_is_player` (Play with Fire's "if a player is
  dealt damage this way, scry 1").
- The final 10-card singles batch (Display of Power, Gamble, Jaya's
  Immolating Inferno, Jeska's Will, Play with Fire, Vandalblast, Witch's
  Mark, Wheel of Misfortune, Volcanic Spite, and Imodane, the Pyrohammer
  herself) added: `CopySpellEffect.target_count`/`optional` ("copy *any
  number* of target spells", Display of Power — the RULE 601.2c "any
  number" idiom Fire Covenant's own `count=10` UI cap had already
  established, applied to a spell target instead of a permanent one, and
  each target now gets its own `copy_spell` call rather than the effect
  only ever handling one target); `AddManaEffect.target_kind`/
  `amount_from_target_hand_size` (Jeska's Will's "Add {R} for each card
  in target opponent's hand" — the first genuinely *targeted* use of that
  effect; every prior use was untargeted); a new `artifact_you_dont_
  control` target kind (Vandalblast, the artifact-typed mirror of the
  existing `creature_you_dont_control`); and a new `put_hand_card_on_
  bottom_then_draw` primitive (`RulesEngine.put_hand_card_on_bottom_
  then_draw`, Volcanic Spite's "you may put a card from your hand on the
  bottom of your library. If you do, draw a card." — the "may" auto-taken
  as a pure card exchange, the same "auto-pick, no chooser" idiom
  `discard`/`put_hand_cards_on_top` already use).
- **Imodane, the Pyrohammer's own signature ability** ("whenever an
  instant or sorcery spell you control that targets only a single
  creature deals damage to that creature, Imodane deals that much damage
  to each opponent") was this batch's biggest single investment:
  `DealDamageEffect.amount_from_trigger_event` (reading the firing DAMAGE
  event's own `amount` field — every other damage-doubling/mirroring
  effect in this catalogue reads a count selector or a flat override, not
  a firing event's own payload) plus two new DAMAGE-event flags computed
  at the point where both the source's own card type and the *resolving
  effect's own* `target_spec` shape are known — `RulesEngine.deal_damage`
  gained a `single_target_hint` parameter, `DealDamageEffect.apply`
  computes it (`count == 1`, not optional, not a mass selector) and
  passes it through, and `deal_damage` stamps
  `source_is_instant_or_sorcery`/`source_targets_only_single_creature`
  onto the event. Two matching `effect_binder._trigger_condition`
  predicate keys (`requires_source_instant_or_sorcery`/`requires_single_
  creature_target`) check them; "you control" reuses the ordinary
  `"subject": "group", "controller": "you"` group-subject check (DAMAGE's
  group-controller key is already `source_controller_id` from an earlier
  batch). Verified directly against the engine: fires exactly once for a
  single-target burn spell killing a creature, does *not* fire when the
  same spell targets a player directly, and does not double-fire (an
  earlier hand-test that appeared to show a double-trigger turned out to
  be a test-script bug — calling `bind_from_catalogue` a second time on
  top of the bench fixture's own call — not an engine defect).

**Documented simplifications** (the card's real value stays modeled;
only the flagged clause is a deliberate, narrower stand-in — see each
factory's own docstring in `game/ability_catalogue.py` for the exact
reasoning): Chain Lightning's copy-chain; Fireblast's alternative cost;
Voltage Surge/Torch Breath's optional-cost/target-color cost reductions;
Torch the Tower's bargained scry rider; Champions of the Perfect's exile-
vs-sacrifice/hand alternative; Trystan's "transforms into" re-trigger;
High Perfect Morcant's auto-picked blight; Grafted Exoskeleton's
"becomes unattached" trigger (no unattach event exists anywhere in this
engine yet — every detach site is a raw assignment); Sword of Once and
Future's graveyard free-cast (would have needed `dig_until` misapplied to
a graveyard, which it doesn't support); Magda's "commit a crime" trigger
(RULE 701.53 has no unifying event across every targeting-effect family);
Birgi's mana-retention and Boast-doubling (RULE 702.161 Boast has zero
engine presence, so there's nothing to double); Sunbird's Invocation's
top-X breadth; Invasion of Kaldheim's exiled-card play permission;
Display of Power's "can't be copied" (RULE 707.12 — no spell-copy-
immunity primitive exists, harmless since nothing in either deck copies
a spell that's itself a copy target) and its own "choose new targets for
the copies" (the pre-existing `CopySpellEffect` MVP, keeps the original's
targets); Gamble's "at random" (an ordinary discard choice, the same
simplification Indoraptor, the Perfect Hybrid already established);
Jaya's Immolating Inferno's Legendary Sorcery casting-timing restriction
(no card-type-supertype casting gate exists in `can_cast` yet — the
damage itself is fully modeled); Jeska's Will's commander-control gate on
`or_both` (offered unconditionally — every deck this engine plays is a
Commander deck by construction); Vandalblast's Overload (RULE 702.96,
same standing precedent Winds of Abandon/Damn/Cyclonic Rift already set —
no alternative-cost-tracking mechanism exists); Witch's Mark's Role
token (RULE 701.62 — `synthesize_token_card` only builds Creature/
Artifact tokens, not Enchantment-Aura ones; the card's real value, the
loot, is fully modeled); and Wheel of Misfortune's entire "secretly
choose a number, reveal simultaneously, damage the highest/exempt the
lowest" sub-game (no secret-simultaneous-choice primitive exists — a
genuinely new interactive-choice subsystem out of scope for one card's
value; what's modeled instead is the card's Wheel-of-Fortune-shaped
headline effect, every player discarding their hand and drawing seven).

Tests: full backend suite (3,452 passed, 238 skipped) stayed green after
every primitive change, plus direct engine verification via
`engine_bench.py`/ad hoc scripts for every new-primitive card (Display of
Power copying 2 spells on the stack, Vandalblast destroying an opponent's
artifact, Jeska's Will's `mode="both"`, Jaya's Immolating Inferno hitting
3 targets, Play with Fire's conditional scry firing only against a player
target, and Imodane's own trigger firing exactly once and only for a
single-creature-targeted spell) rather than new pytest files, since this
batch's cards are one-offs in `ability_catalogue.py` and the existing
suite already covers every primitive's shared machinery.

## The seven "cEDH"-named saved decks/cubes: first playability pass (2026-08-06)

User request: make every "cEDH"-named saved deck/cube fully playable —
`Ojer cEDH`, `cEDH Rocco`, `[cEDH] Glarb Bloomsday`, `cEDH staples`,
`cEDH staples 2`, `cEDH M-K`, `cEDH Kinnan`. Together a 393-unique-card
pool (heavy overlap — the same real-world cEDH staples recur across most
of the seven), an order of magnitude past any single-deck batch this
project had done before. Given the size, this is tracked as ordinary open
work (`MEC-12` in `BACKLOG.md`) across however many sessions it takes,
not forced to "no deferrals" completion in one sitting the way the
smaller Eliferate/Imodane batches were — this entry covers the first
pass: the highest-frequency shared staples (by how many of the seven
decks each unlocks), prioritized for exactly that leverage.

**Coverage measurement**: `services.deck_database.DeckDatabase`/
`DECKS_DB_PATH` for the real saved-deck rows, `services.card_database.
CardDatabase`/`DEFAULT_DB_PATH` (not the `:memory:` default — costs a
lookup miss on every card if forgotten) for oracle text, decklist lines
parsed by stripping everything from the `(SET)` collector-number marker
onward, "playable" = `parse_oracle(card).modeled or ability_catalogue.
is_registered(card.name)`. Result this pass: **Ojer cEDH 30/77, cEDH
Rocco 67/98, [cEDH] Glarb Bloomsday 69/100, cEDH staples 156/215, cEDH
staples 2 375/607, cEDH M-K 70/97, cEDH Kinnan 68/100** (up from 29/62/
66/147/364/63/61 respectively at the start of this pass) — 13 real cards
fixed, each shared across 2–6 of the seven decks, hence the larger
per-deck deltas.

**Parser fix** (`parser/oracle/segmenter.py`'s `_COST_LOOKS_REAL`):
"Exile this card from your hand: Add `<mana>`." (Simian/Elvish Spirit
Guide) was UNCLAIMED — not because the mechanic is unbuilt (`costs.py`'s
`_EXILE_FROM_HAND_RE`/`exile_self_from_hand` and `mana_abilities.
hand_mana_abilities_for` already fully implement RULE 605.1a hand-zone
mana abilities, per the CLAUDE.md callout this precedes) but because
`_COST_LOOKS_REAL`'s cost-shape sniff — the gate deciding whether an
activated ability's `<cost>: <effect>` line is claimed at all — never
listed "exile from your hand" among its recognized cost verbs (`{...}`,
sacrifice, pay life, discard, put/remove a counter, tap-untapped, return
to hand). Added `exile (?:this \w+|~) from (?:your|their) hand` (the `~`
half needed separately — `normalize.py` folds "this creature" to `~`
*before* the sniff runs, so Elvish Spirit Guide's own "Exile this
**creature** from your hand" only matched once both forms were covered).
Two solo-blocker cards fixed cache-wide, zero regressions
(`parser_probe.py diff`).

**New primitive — `TaxedDrawEffect`** (`game/effects.py`): RULE 118.3's
"you may pay `<cost>`. If you don't, `<effect>`." idiom, already shipped
for a sacrifice (`SacrificeUnlessPayEffect`) and a mass life-loss
(`EachPlayerPayOrEffect`), applied to a *draw* instead — Rhystic Study/
Mystic Remora/Esper Sentinel's shared "whenever an opponent casts a
spell, you may draw a card unless that player pays `<cost>`." template.
The one real difference from its siblings: the *payer* is the triggering
spell's own caster, read off `GameContext.trigger_event`'s `player_id`
(the firing `SPELL_CAST` event), not this ability's own controller —
every prior "unless" effect had the payer and the ability's controller be
the same player. Built on the same `request_pay_cost_then`/
`_can_pay_player_cost` machinery as always; the trigger condition itself
needed no new predicate, since `SPELL_CAST`'s `_GROUP_CONTROLLER_EVENT_
KEYS` entry (`player_id`) already makes `{"subject": "group", "controller":
"not_you"}` mean "an opponent cast this". `amount_from_source_power`
(Esper Sentinel: "unless that player pays {X}, where X is this
creature's power") reads the cost amount off the source's live power at
resolution instead of a fixed printed value. **Documented
simplifications**: Mystic Remora's own Cumulative upkeep (RULE 702.24,
still wholly unbuilt — same drop-precedent as Kyren Negotiations) and
Esper Sentinel's "their **first** noncreature spell each turn" gate (no
per-player per-turn "first qualifying event" counter exists yet — fires
on every qualifying spell instead, a strict upgrade rather than a broken
card) are both dropped.

**RULE 118.9 alt-cost family, dropped and hand-authored for the rest**:
Force of Will, Force of Negation, Force of Vigor, and Daze each print
"You may `<cost>` rather than pay this spell's mana cost." — a genuinely
unbuilt alternative-casting-cost mechanism (confirmed via
`parser_probe.py blocked`: 113 cards cache-wide, 58 solo blockers, so
this is real standalone scope, not a one-off — tracked as its own
open item in `MEC-12` rather than built for one card's sake). Each of the
four is hand-authored for its resolution effect only, fully castable at
its real printed mana cost (all four have one) — `CounterSpellEffect`
covers Force of Will (plain), Force of Negation (`noncreature=True`,
dropping the "exile instead of graveyard" rider too), and Daze
(`unless_pays="1"`, the pre-existing Mana Leak shape); Force of Vigor
reuses the already-shipped RULE 115.1a "up to N targets" idiom
(`DestroyEffect(target_kind="artifact_or_enchantment", count=2,
optional=True)`). Misdirection and Deflecting Swat were investigated and
**left UNMODELED** rather than half-built: both cards' *entire* effect is
"change the target of an existing spell/ability", a distinct RULE 115.4
mechanism from the already-shipped "choose new targets for the copy"
drop (which only ever touches a freshly-made copy) — dropping it would
leave a genuine no-op, not a smaller-but-real card. Also discovered along
the way and recorded in `MEC-12`: `GameEngine.can_cast`/`cast_spell`'s
existing `free=True` RULE 601.2f condition-gated free-cast path
(`free_cast_condition`, `control_commander` condition already live in
`condition_query.py`) has never actually been reachable from a real game
— `legal_actions_mixin._cast_action`/`_offer_cast` never surfaces it and
`services/game_session.py`'s `_dispatch_cast_spell` never round-trips a
`free` flag from the action payload — zero cards use it today because
nothing could ever legally exercise it end-to-end.

**Plain trigger reuse, no new primitive**: City of Brass ("whenever this
land becomes tapped, it deals 1 damage to you" — `EventType.TAPPED`,
already fired for every genuine untapped→tapped transition, `damage`
with `selector="controller"`, the pre-existing Mana Vault shape) and
Forbidden Orchard ("whenever you tap this land for mana, target opponent
creates a 1/1 Spirit" — `EventType.TAPPED_FOR_MANA`, `create_token`).
**Documented simplification**: Forbidden Orchard's "target opponent"
becomes `creators="each_opponent"` (`CreateTokenEffect` has no single-
opponent-target creation shape yet) — correct in 1v1, an overstatement in
multiplayer.

Tests: full backend suite (3,452 passed, 238 skipped) stayed green
throughout. Every new-primitive card verified by direct engine scripting
against real `GameEngine`/`CardDatabase` state rather than just the parse
verdict: Rhystic Study drawing on decline and staying silent on payment,
Esper Sentinel's `{X}` tracking its live power (1), Force of Vigor
resolving and hitting the graveyard, City of Brass/Forbidden Orchard's
triggers firing off real `TAPPED`/`TAPPED_FOR_MANA` events.

Remaining scope (the other ~30 unique high-frequency staples plus the
long tail of once-off inclusions across all seven decks, several
confirmed-missing primitives with design notes already written down, and
the exact currently-open card lists) is `MEC-12` in `BACKLOG.md` — read
that before starting the next pass rather than re-deriving which
primitives are missing from scratch.

## The seven "cEDH"-named saved decks/cubes: RULE 115.4 "change the target" (2026-08-06, second pass)

Continuation of `MEC-12` — this pass built the first pass's own
"confirmed-missing primitive" entry: RULE 115.4/601.2c's "change the
target of target spell/ability," needed by Misdirection ("Change the
target of target spell with a single target.") and Deflecting Swat ("You
may choose new targets for target spell or ability."). Genuinely distinct
from the already-shipped "choose new targets for a freshly-made **copy**"
(RULE 707.10c, `CopySpellEffect`/`RulesEngine.copy_spell`) — that only
ever affects a copy at creation time; this is a live retarget of an
*already-existing* stack item.

**New primitive**: `ChangeTargetEffect` (`game/effects.py`) + `RulesEngine.
change_target` (`game/rules/misc_mixin.py`, next to `_stack_item_for`/
`counter_unless_pays`, the closest existing "act on a named stack item"
precedent). The changing player is *this effect's own controller* (RULE
115.4a — not the targeted spell's controller; a target description's
"you"/"your" still means the original spell's own controller, so
`legal_targets` is computed with the targeted item's `controller_id`, not
the changer's). Legal alternatives are recomputed fresh against the
*current* board (RULE 115.1c) — not whatever was legal when the targeted
spell was originally cast — by re-running `targeting.legal_targets`
against the first targeting effect found on the target's `StackItem.
effects`. A single legal option (which, per 115.4a, always includes the
*current* target — nothing excludes it from being re-picked) auto-applies
without a prompt, the same "forced, asking would be theatre" idiom
`_choose_objects_choice` already uses; zero legal alternatives (the
target-has-no-legal-targets edge, or just "nothing else is out there")
leaves the target untouched by construction, since an empty options list
short-circuits before any assignment happens. `optional=True` (Deflecting
Swat's "you may") adds a `"decline"` option; Misdirection's own "Change
the target" is mandatory (no decline offered).

New `pending_choice` kind `"change_target"` — `GameEngine.
resolve_pending_choice`/`turn_loop_mixin.py` dispatches it to `RulesEngine.
resolve_change_target_choice`, same generic `{"id", "label",
"instance_id"?}` option shape `_trigger_target_choice` already uses (so
the existing choice UI renders it with zero new frontend work). The choice
is deliberately data-only (a stack item can't be stored by live reference
across a `state.clone()` undo snapshot) — it carries `stack_target_
instance_id` and re-finds the live `StackItem` via `_stack_item_for` at
resolve time, mirroring `counter_unless_pays`'s own choice shape exactly.

**Deliberately scoped to spells, not "spell or ability"** as Deflecting
Swat is actually printed, and to a stack item with **exactly one existing
target** (`item.target_groups is not None` — 2+ *different* targeting
effects — is refused outright rather than guessed at). Both are real,
documented simplifications, not laziness:

- Retargeting an *ability* on the stack needs a stable way to name one.
  `StackItem.obj` is `None` for an ability item (the permanent that has it
  lives on `.source` instead — see `StackItem`'s own docstring), so
  `targeting.py`'s `"spell"` kind (which keys every option off `item.obj.
  instance_id`) simply has nothing to identify an ability item by. Building
  that — RULE 115's "target activated/triggered ability" (Stifle/Trickbind-
  shaped) — is a strictly bigger primitive on its own, newly logged in
  `BACKLOG.md`'s `MEC-12` rather than half-built here. No card in the
  catalogue or the cEDH pool needs it yet.
- A spell with 2+ targets (RULE 115.1a's "N target X") retargeting one at a
  time would need per-slot bookkeeping (`target_groups`) this MVP doesn't
  build, since neither real card in scope needs it — Misdirection's own
  printed text restricts to "target spell **with a single target**", and
  Deflecting Swat in practice retargets single-target removal almost
  exclusively.

`targeting.py`: `TargetSpec.spell_filter` gained a `single_target` key
(Misdirection's own restriction) — checked against the stack item's
*current* `len(item.targets)`, not the spell's printed characteristics
(it's a fact about the stack, not the card), so it lives in the `"spell"`
kind's own `legal_targets` branch rather than `_spell_matches_filter`
(which only ever sees the spell's `GameObject`, not its `StackItem`).

**Hand-authored** (`ability_catalogue.py`): Misdirection (`change_target`,
`single_target=True`, mandatory) and Deflecting Swat (`change_target`,
`optional=True`, spell-only per the simplification above) — both at their
real printed mana cost ({3}{U}{U} and {2}{R} respectively; earlier
drafting briefly assumed the wrong printed costs from memory before
checking the real cached Scryfall data, corrected before shipping), RULE
118.9's alternative cost dropped for both (same documented-simplification
precedent as the Force of Will cycle — see the first-pass entry above).

Tests: `tests/test_change_target_family.py` (new file, 12 tests) — the
`"spell"` kind's `single_target` filter in isolation; `RulesEngine.
change_target`'s three branches (auto-apply on a single legal option,
opening a mandatory choice with no decline, opening an optional choice
with one, the 2-existing-targets refusal); `resolve_change_target_choice`
retargeting a pushed spell and leaving it alone on decline; a full
`GameEngine.resolve_pending_choice` → `resolve_until_stable` wiring test
confirming a retargeted damage spell actually lands on the *new* target,
not the old one; and both cards' registration + emitted `EffectSpec`
shape. Full backend suite: 3,464 passed (+12), 238 skipped, zero
regressions.

Coverage re-measured (same script as the first-pass entry, decks a user
can keep editing so per-deck *totals* drift run to run, not just the
playable count): **Ojer 31/77, Rocco 67/98, Glarb Bloomsday 69/100,
staples 157/215, staples 2 392/636, M-K 72/97, Kinnan 68/100** — unique
417/723. Remaining scope unchanged in kind, still `MEC-12`.

A follow-up in the same pass closed a test-coverage gap noticed while
confirming Rhystic Study was already modeled (it was — first-pass work,
above): `TaxedDrawEffect`'s three real cards (Rhystic Study, Mystic
Remora, Esper Sentinel) had shipped with only an ad hoc scratchpad script
verifying them, no committed regression test. `tests/
test_taxed_draw_family.py` (new file, 8 tests, real cached cards per the
`test_cube_batch_a1.py` house style) now covers all three: the plain {1}
tax drawing on decline and staying silent on payment; the "opponent" scope
not firing off the ability's own controller's spell; the no-mana auto-draw
shortcut (`request_pay_cost_then`'s "don't stall on a choice nobody can
act on" branch — worth its own test since two earlier draft tests in this
file wrongly asserted a `pending_choice` while leaving the payer without
enough mana to ever reach that branch, catching the same mistake this
comment warns against); Mystic Remora's noncreature-only filter and {4}
cost; and Esper Sentinel's tax scaling with its own live power (`{1}` off
its printed 1 power) plus the same noncreature filter. The two
creature-spell tests cast from the *active* player rather than the
Remora/Sentinel controller's actual opponent, since a fresh `new_game`
starts p1 active and RULE 307.4a restricts sorcery-speed casting to
the active player — Remora/Sentinel simply changed seats (p2) so p1
remains a legal "opponent" caster either way. Full backend suite: 3,472
passed (+8), 238 skipped, zero regressions.

## ENG-28 · `cast_prohibition`/`activation_prohibition` gated on "during your turn" (2026-08-06)

Sizing confirmed the ticket's own premise was half wrong before touching
any code (per the standing "verify engine ticket claims empirically"
discipline): Linvala, Keeper of Silence and Karn, the Great Creator's
activation-lock clauses carry **no** turn gate at all ("Activated
abilities of creatures/artifacts your opponents control can't be
activated." — permanent, not "during your turn"); only Grand Abolisher
and Myrel, Shield of Argive actually print the gated shape. Real bug
found instead: `continuous.cast_prohibited` never consulted `active_if`
at all (unlike `activation_prohibited`, which already inherited it for
free through `affected_objects`/`group_selector_objects`), and the
`cast_prohibition` `EffectRegistry` factory in `game/effects.py` didn't
even thread the param onto the `StaticAbility` in the first place — a
`cast_prohibition` spec carrying `active_if` was silently dropped at bind
time, the exact "new selector param missing from `_SELECTOR_KEYS`" trap
this repo's own conventions warn about (in this case the factory itself,
not the whitelist — `active_if` was already in `_SELECTOR_KEYS`, just
never read into `cast_prohibition`'s own params dict).

Fixed both: `cast_prohibited` now checks `ability.params.get("active_if")`
(and the three legacy-gate params via `static_conditions.
condition_from_legacy_params`) exactly the way `group_selector_objects`
does, and the `cast_prohibition` factory now spreads `**_selectors(p)`
like every other static factory already does. `group_selector_objects`'s
`card_type` filter also gained list support (`card_type=["artifact",
"creature", "enchantment"]`, OR'd via `_has_card_type`) — needed for Grand
Abolisher's three-way type list, a plain string still works unchanged for
every existing caller.

That engine fix is inert without a way for real card text to reach it, so
the same batch added the parser half: a general "During your turn,
`<static clause>`." wrapper in `parser/oracle/catalogue/static_handlers.
py`'s `_conditional_static_specs` (fixed to the `your_turn` condition
rather than routed through `static_condition`, since the phrase itself
*is* the condition — no separate `cond` to parse a kind out of), sitting
alongside the existing "as long as" wrapper and reusing its exact
recursive-rewrite plumbing. Sized first with `parser_probe.py`: 156 cards
solo-blocked on the literal phrase alone (Ahn-Crop Invader/Blood Burglar/
Colossus, Steel Stalwart-shaped "During your turn, ~ has `<keyword>`."
being the commonest single template) — the wrapper claims whichever inner
clause `static_effect_specs` already knows how to parse, so it's a
one-time addition that keeps paying off as the anthem/keyword-grant
family grows, not a per-card fix. Also added, to close Grand Abolisher/
Myrel's own compound sentence specifically: `_ACTIVATION_PROHIBITION_
OPPONENTS_RE` (the opponent-scoped sibling of the pre-existing board-wide
"activated abilities of `<type>` can't be activated" handler — unlocks
Linvala solo, narrows Karn/Drana and Linvala/Sharkey, Tyrant of the
Shire), and `_CANT_CAST_OR_ACTIVATE_OPPONENTS_RE` + `_type_word_list`
(splits "artifacts, creatures, or enchantments" on comma/and/or into
`_CARD_TYPE_WORDS`, fail-closed on an unrecognised word), which emits one
`cast_prohibition` spec (untyped — "cast spells", no restriction) plus one
`activation_prohibition` spec (`affects="opponents_permanents"`, the new
list-shaped `card_type`) from a single clause, both then gated by the
"during your turn" wrapper that recognised the sentence in the first
place.

Confirmed with `engine_bench.py inspect`: Grand Abolisher and Myrel, Shield
of Argive are now `MODELED` (were `UNMODELED`); Linvala is now `MODELED`
solo; Karn, the Great Creator stays `UNMODELED` (its two loyalty abilities
are unrelated, still-unclaimed clauses — out of this ticket's scope).
Coverage moved 10,561 → 10,599 (+38, 30.87% → 30.98%), and the "during
your turn" solo-blocked count dropped 156 → 119, confirming the wrapper's
yield extends well past the four cards that motivated it.

Tests: `tests/test_during_your_turn_prohibition_family.py` (new file, 5
tests, real cached cards) — Grand Abolisher's cast half gated on/off by
whose turn it is, never touching its own controller; its activation half
against a real mana ability (`Llanowar Elves`), which needed `tap_for_mana`
rather than `can_activate` since a mana ability never lives in `source.
activated_abilities` (`can_activate` refuses it on that unrelated ground
regardless of any prohibition — the first draft of this test suite passed
for the wrong reason before this was caught); Linvala's lock holding on
both players' turns and never touching her own controller's creature.
Full backend suite: 3,477 passed (+5), 238 skipped, zero regressions.

## ENG-26 · RULE 115/608.2b "target an activated or triggered ability" (2026-08-06)

The second cEDH pass's own headline deferred item: `targeting.py`'s
`"spell"` kind only ever matched `StackItem.kind == "spell"`, and an
*ability* `StackItem`'s own `obj` is `None` (the permanent that has the
ability lives on `.source` instead) — so nothing could name "an ability on
the stack" as a target at all, for either counter (Stifle/Trickbind) or
retarget (Deflecting Swat's real "spell or ability" scope) purposes.

The load-bearing piece is `StackItem.stack_id` (`models/game_state.py`) —
a stable identity every stack item gets, spell or ability alike, assigned
by a module-level `itertools.count()` exactly the way `GameObject.
instance_id` already is. A spell target descriptor still keys off its own
`GameObject.instance_id` (unchanged, no reason to disturb an already-working
path); an ability one is keyed by `stack_id` instead, both new `targeting.
py` kinds (`"ability"`, and `"spell_or_ability"` — the literal union, for
Deflecting Swat's own wording). `RulesEngine.change_target`'s own
`stack_target_instance_id` bookkeeping (previously a `GameObject.
find_object` round trip, meaningless for an ability with no object) was
simplified to read `StackItem.stack_id` directly for both shapes, which is
also simply less code — `resolve_change_target_choice` no longer needs the
`find_object` → `_stack_item_for` two-step at all. `GameSession.
_resolve_targets` (the API boundary) gained a matching `"stack_id"`
descriptor branch resolving straight to the live `StackItem`.

Two effects consume the new identity: `CounterAbilityEffect`/
`RulesEngine.counter_ability` (RULE 701.5b, `EffectRegistry`'s
`"counter_ability"`) — new, but its actual stack-removal logic is just a
call to the pre-existing `counter_spell`, which already handled an
`item.obj is None` ability item correctly (no graveyard move, since RULE
701.5g's "owner's graveyard" only ever applies to a spell) the whole time,
once it could be *reached*; and `ChangeTargetEffect`, which gained a
`spell_or_ability` param switching its `target_spec` to the union kind,
with `RulesEngine.change_target` itself reading `item.obj if item.obj is
not None else item.source` as "the thing legality is computed against"
(RULE 115.1c's live recompute) instead of assuming `item.obj`.

Deflecting Swat's hand-authored entry (`game/ability_catalogue.py`) was
updated from spell-only to `spell_or_ability=True` — the first-pass
"documented simplification: narrows to spell only" is resolved, matching
its real printed "target spell or ability" text. Stifle and Trickbind are
newly hand-authored on `counter_ability` — Stifle is a clean one-clause
match; Trickbind keeps two documented simplifications of its own (RULE
702.61 Split Second, not recognized anywhere in the codebase — a
cast-timing restriction, a different kind of primitive than this ticket;
and the post-counter "activated abilities of that permanent can't be
activated this turn" lockout, which would need its own per-object
turn-scoped flag no other card needs yet) so its core "counter target
activated or triggered ability" line is real behaviour without either.

Tests: `tests/test_target_ability_family.py` (new file, 14 tests) —
`stack_id` uniqueness; the `"ability"`/`"spell_or_ability"` targeting
kinds in isolation; `counter_ability` removing an ability item (and
leaving the target undamaged), refusing a spell item (wrong `kind`), and
refusing a "can't be countered" source; `change_target` retargeting an
ability (auto-apply on a single mandatory option, opening a choice with
several, `resolve_change_target_choice` actually moving the target); the
two hand-authored cards' registration; and a full `resolve_until_stable()`
end-to-end Stifle counter. `test_change_target_family.py`'s own Deflecting
Swat spec test was updated for the new `spell_or_ability=True` param.
Full backend suite: 3,489 passed (+12 net — 14 new, 2 rewritten in place),
238 skipped, zero regressions.

## ENG-27 · Bloom Tender / Carpet of Flowers mana primitives (2026-08-06)

Sizing again found the ticket's own premise half wrong before any code
(same discipline as ENG-28): the ticket described Bloom Tender as needing
"a menu restricted to colors of creatures you control" — but the real
*cached* Oracle text is `"Vivid — {T}: For each color among permanents you
control, add one mana of that color."`, a completely different, older
templating with no player choice in it at all. It's a deterministic
*aggregate*: tapping always produces one mana of *every* colour currently
present among the controller's permanents, together, not a menu to pick
one from. New `ManaAbility.color_selector` kind
`"colors_among_permanents_you_control"` (`game/mana_abilities.py`) —
`resolve_options` builds a single option fresh every call by unioning
`permanent.colors` across the controller's board (`{}`/no state → nothing,
same "produces nothing" convention every other empty-options path already
gets); the parser side needed its own new regex
(`_COLORS_AMONG_PERMANENTS_RE`) checked *before* `_ADD_CLAUSE_RE`'s gate,
since "add **one** mana of **that** color" only matches `_ADD_CLAUSE_RE`
mid-sentence in lowercase, and that regex is deliberately case-sensitive
(capital "Add") everywhere else.

Carpet of Flowers' own text held up (X mana of any one color, gated,
opponent-targeted), but RULE 605.5a disqualifies it from ever being a mana
ability in the first place — it targets, so unlike Wild Growth/Kinnan
(RULE 605.1b's genuine off-stack triggered mana abilities, already
shipped) this is an ordinary triggered ability that goes on the stack.
Three new pieces, none of them a menu of colours to restrict, contrary to
the ticket's framing: `AddManaEffect.amount_from_target_count_selector`
(a `continuous.count_selector` — the pre-existing
`lands_you_control_of_type_island` — evaluated against the *resolved
target*, `targets[0].id`, not this effect's own controller the way
`amount_selector` always was); `RulesEngine.add_mana_any_color`'s new
`amount` param (previously hardcoded to producing exactly one mana of the
chosen colour); and `GameObject.added_mana_with_ability_this_turn`
(mirrors `activated_loyalty_this_turn`/`graveyard_casts_this_turn`'s exact
shape — reset alongside them in `turn_loop_mixin.py`'s untap step and
`reset_as_new_object`), consulted by `AddManaEffect`'s new
`once_per_turn_ability` flag. **Documented simplification**: the "if you
haven't added mana…" gate is a resolve-time no-op rather than a full RULE
603.4 intervening-if, so the "you may" prompt can still appear (and be
accepted, producing nothing) on a turn it's already been used — no
observable difference in the resolved outcome either way.

RULE 603.5's existing "you may" machinery
(`triggers_mixin.py`'s `_trigger_target_choice`, `ability.optional`
folded into the target-choice options as a `"decline"`) turned out to
already cover Carpet of Flowers' targeted "you may" outright — a decline
never puts the trigger on the stack at all, so no bespoke optional-effect
plumbing was needed in `AddManaEffect` itself. Carpet of Flowers is
hand-authored as two standing triggered abilities, one per main phase
(`game/ability_catalogue.py` — the engine fires a real `step="main1"`/
`"main2"` event, never a generic `"main"` one; that spelling is `Mana
Drain`'s own delayed-trigger-only sentinel, a different mechanism), each
`phase_relation: "you"` and `target_kind: "opponent"`.

Tests: `tests/test_bloom_tender_carpet_of_flowers_family.py` (new file, 10
tests, real cached cards) — Bloom Tender's aggregate production alone and
combined with a second multicolored permanent (an opponent's colours
correctly excluded), `tap_for_mana` producing it with no choice opening,
and the no-`state` conservative-nothing fallback; Carpet of Flowers'
full `advance_to_main`-driven trigger firing with a real decline path, the
X-from-target's-Islands color choice and its correct mana yield, the
once-per-turn gate blocking (but still *offering*) a same-turn reuse, the
gate resetting after a real untap step, the target's Islands mattering
rather than the controller's own, and the hand-authored spec shape itself.
Full backend suite: 3,499 passed (+10), 238 skipped, zero regressions.

## MEC-15 · RULE 118.9 alternative costs — the pitch-cost family (2026-08-06)

The first cEDH pass (2026-08-06) had hand-authored Force of Will/Negation/
Vigor/Daze at their printed mana cost with the alternative "pitch" cost
itself dropped as "genuinely unbuilt", flagging exactly what it would take:
a structured alt-cost spec, a `can_cast`/`cast_spell` parameter next to the
existing condition-gated `free=True` path, and — the part actually missing
— real UI wiring, since `free=True` casting had been backend-only and
unreachable from a real game session the whole time. This batch built all
three, plus fixed the wiring gap for `free=True` itself along the way
(neither had ever been reachable).

**The payment vocabulary** rides `game/costs.py`'s existing `ActivationCost`
— reused rather than rebuilt, matching `additional_cast_cost`'s own
`parse_activation_cost` dict-to-cost precedent — plus one genuinely new
field, `exile_hand_card_color` (a WUBRG letter; `return_to_hand` already
existed, built for an activated ability's "Return a Forest you control…"
cost, and turned out to need zero changes to serve a spell's alternative
*cast* cost too — Daze reuses it verbatim). **The gate vocabulary**
(Force of Negation/Vigor's own "if it's not your turn") reuses
`free_cast_condition`'s whitelist/evaluator rather than inventing a
second one — both are "is this alternative cast option available right
now" checks — so `condition_query.free_cast_condition_holds` gained
`not_your_turn`/`your_turn` alongside its existing `control_commander`.
`AbilitySpec.alt_cost` is the new structured field (`parser/oracle/
spec.py`'s `ALLOWED_ALT_COST_KEYS`), riding on a spec with no effects of
its own — the same "own oracle-text line, standalone from the spell's real
effect, scanned by `effect_binder.attach_to_object` regardless of which
spec carries it" idiom `additional_cost`/`free_cast_condition` already
use — bound onto `GameObject.alt_cast_cost` (an `ActivationCost`) +
`alt_cast_condition` (the optional gate dict).

**The engine half**: `GameEngine.can_cast`/`cast_spell`/`_cast_current_
face`/`_auto_tap_for_cast_if_needed` all gained an `alt_cost: bool = False`
parameter threaded exactly parallel to the pre-existing `free`, landing a
new `elif alt_cost:` branch in each one's own dispatch (`can_cast` checks
the gate then `_can_pay_alt_cast_cost`; `_cast_current_face` pays via the
same `cast_without_paying` + a follow-up payment call `free`'s own RULE-
118-life-payment sibling branch already established the shape for).
`_can_pay_alt_cast_cost`/`_pay_alt_cast_cost`/`_exile_hand_card_candidate`
(new, `engine/casting_mixin.py`) are a small dedicated pair rather than a
reuse of `_can_pay_activation_cost`/`_pay_activation_cost` — those two are
explicitly documented as being for a *battlefield permanent's* own
ability cost (checking `source.tapped`, exiling being hard-refused for a
hand card, …), so overloading them for a hand-cast spell's alternative
cost risked silent wrong behaviour for the sake of a few shared lines;
`_exile_hand_card_candidate` is the same non-interactive first-match
auto-pick convention `_return_to_hand_candidate`/`_sacrifice_candidate`
already use, `exclude`-guarded against the casting spell targeting itself
(mirroring `_discard_cost_pool`'s identical reasoning).

**The wiring half** (the part that made `free=True` itself unreachable
before this batch, not just `alt_cost`): `_castable_now_or_via_potential`
split its original body out to `_plain_castable_now_or_via_potential` and
now also returns true when a free-cast condition or an alt cost is
currently satisfiable — neither of which the mana-potential probe below
it could ever answer, since both need zero mana at all. `_offer_cast` now
builds up to *three* independent `cast_spell` action entries per card —
plain, free, and alt-cost — each only when that specific payment method is
actually legal right now (a truly-unaffordable-by-mana Force of Will no
longer offers a locked, misleading plain-cost button at all); `_cast_action`
gained matching `free`/`alt_cost` params that skip every mana-cost/{X}/
Kicker/Buyback/cost-reduction field entirely (none apply) and surface
`alt_cost_label` off the bound `ActivationCost.label()`.
`GameSession._dispatch_cast_spell` (`services/game_session.py`) rounds
both flags back off the action payload into `engine.cast_spell(...)` —
the last hop that had been missing.

**The four cards**: each gained a second, effect-less `spell_effect` spec
carrying just `alt_cost` (`game/ability_catalogue.py`) — Force of Will
(`{"pay_life": 1, "exile_hand_card_color": "U"}`, unconditional), Force of
Negation (`{"exile_hand_card_color": "U", "condition": {"not_your_turn":
True}}`), Force of Vigor (same shape, green), Daze
(`{"return_to_hand": "island"}`, unconditional). All four are still also
fully castable at their printed mana cost, unchanged — the alt cost is a
second option, not a replacement. **Documented simplification carried
forward**: Force of Negation's own "exile instead of graveyard" rider on
a spell it counters this way is still dropped (unrelated to the alt cost
itself, a narrower pre-existing gap).

Tests: `tests/test_alt_cast_cost_family.py` (new file, 14 tests, real
cached cards) — the two new `ActivationCost` fields' `label()`/`is_free`;
the shared `not_your_turn` condition read directly; Force of Will
unaffordable by mana but payable by alt cost, illegal with no blue card in
hand, illegal at 0 life, and a full pay-life-exile-then-counter run
through `resolve_until_stable()`; Force of Negation's gate flipping with
whose turn it is; Force of Vigor correctly refusing a blue card and
accepting a green one; Daze needing (and then bouncing) a real Island;
`legal_actions` offering *only* the alt-cost entry with an empty mana pool
and *both* entries once mana is added too; and a full `GameSession.
_dispatch_cast_spell` round trip. Full backend suite: 3,513 passed (+14),
238 skipped, zero regressions.

## MEC-16 · Cumulative upkeep (RULE 702.24) (2026-08-06)

The keyword was already recognized by the oracle-text parser (`parser/
oracle/catalogue/keywords.py`'s catalogue table, `KeywordShape.COST`, RULE
702.24 in the table since day one) — the actual gap was purely on the
binding side: `game/effect_binder.py`'s keyword-to-behaviour dispatch table
had no entry for it at all (nor, it turned out while building this, for
Echo — a separate, still-open gap, out of this ticket's scope), so every
card printing Cumulative Upkeep was inert regardless of whether the rest of
the card was hand-authored or parser-derived.

**The primitive**: `CumulativeUpkeepEffect` (`game/effects.py`) — "put an
age counter on this permanent, then sacrifice it unless you pay its
upkeep cost for each age counter on it" — adds the age counter first,
unconditionally, then reuses RULE 701.17's existing "Sacrifice ~ unless
you pay `<cost>`" pay-or-lose-it machinery (`SacrificeUnlessPayEffect`'s
own `RulesEngine.request_sacrifice_unless_pay`, itself built on ward's
shared cost-payment plumbing) with the parsed cost scaled by the current
age-counter count (`_scale_cumulative_upkeep_cost`). Scaling repeats the
parsed cost's own mana symbols/`pay_life` N times rather than computing a
single multiplied payment — the same total either way for a mana cost,
and the only shape that generalizes correctly to a life payment too.
**Documented simplification**: a non-numeric cost component (sacrifice/
discard/tap-others/return-to-hand, "tap an untapped white creature you
control"-shaped) is left un-scaled, paid once regardless of the counter
count — "pay this cost N *separate* times" is a distinct, more general
primitive genuinely unbuilt both here and in the RULE 701.17 machinery
this reuses. `_kw_cumulative_upkeep` (`game/effect_binder.py`, registered
in `_KEYWORD_TRIGGERED_BUILDERS` alongside Fading) builds the standing
"at the beginning of your upkeep" `TriggeredAbility`, reading the cost off
`spec.keyword["cost"]` rather than the `n` this dispatch table's other
callers all receive — Cumulative Upkeep is `KeywordShape.COST`, not
`NUMBER`, the one keyword in the table so far where the passed-through
``n`` argument is simply unused.

**A confirmed, not a bug**: since keyword recognition binds independently
of hand-authoring, Mystic Remora and Thought Lash — both hand-authored
with "Cumulative upkeep isn't built yet, dropped" as an explicit
documented simplification — picked up real Cumulative Upkeep behaviour
*without either spec being touched*, closing both simplifications for
free. `test_taxed_draw_family.py`'s Mystic Remora test needed a small
fixture fix (landing the creature on the battlefield *after* advancing
past its controller's own upkeep, rather than funding that upkeep, which
RULE 500.4 empties the mana pool before reaching anyway) since the
creature was otherwise sacrificed before the spell it's meant to tax was
ever cast — a real behavioural change the test had been silently relying
on the absence of. Both cards' hand-authored docstrings were updated to
stop claiming the mechanic is unbuilt; Thought Lash's own further
"exile all cards from your library" rider (triggered off cumulative
upkeep going *unpaid*) is still a real, narrower residual gap — the base
mechanic never fires a paid-vs-not-paid event a second trigger could hook.

Tests: `tests/test_cumulative_upkeep_family.py` (new file, 7 tests) — a
synthetic Cumulative-Upkeep-only creature (isolated from Fading's own
unrelated upkeep trigger, which a *bare*-constructed test fixture with no
RULE 702.32a entry counters would otherwise auto-sacrifice through) across
three escalating upkeeps confirming the cost scales 1×/2×/3× correctly;
declining sacrifices (RULE 701.16c, to the graveyard); an unaffordable
cost sacrifices outright with no choice offered; only the controller's own
upkeep triggers it; a life-cost variant (built directly against the effect
class, since "Pay N life" cumulative-upkeep text has no brace-delimited
symbol for the keyword catalogue's existing cost-extraction regex to find
— a separate, real parser gap, not this ticket's own scope); and Old
Fogey (a real cached card) binding a genuine cumulative-upkeep trigger.
Full backend suite: 3,520 passed (+7), 238 skipped, zero regressions.

## MEC-17 · Imprint (RULE 702.45-adjacent) (2026-08-06)

Sized at 26 cards cache-wide but only 1 solo blocker: the other 25
(Clone Shell/Dermotaxi-shaped) pair the "Imprint" ability word with a
*different* body (look-at-top-N-and-exile-face-down, graveyard exile, …),
each needing its own handler on top of this batch's own primitives —
Chrome Mox is the only card whose entire text is the plain "exile from
hand, mana ability reads it back" shape. Two new general primitives, not
Chrome-Mox-specific:

`RulesEngine.request_choose_objects` (`game/rules/misc_mixin.py`) gained a
`remember: bool = False` param, threaded through its own pending-choice
dict and `_apply_chosen_object`: when set and `action="exile"`, the
chosen object's `instance_id` is stamped onto the calling permanent's own
`GameObject.linked_exile_id` — the same field `ExileEffect(remember=True)`
already uses for the unrelated O-Ring return-when-leaves shape, reused
rather than a second "remembered object" field. `ImprintEffect` (`game/
effects.py`) is the ETB half — "you may exile a `<filter>` card from your
hand" — riding this exact chooser (`action="exile"`, `remember=True`)
exactly like Gemstone Caverns' own pregame "exile a card from your hand"
tail already does (that card's own comment already flagged the action as
"general enough for any future 'exile a card from your hand' cost/effect
to reuse" — this is that reuse). `exclude_card_types` filters the hand
pool by `Card.is_<word>` flags — Chrome Mox's own "nonartifact, nonland".

`ManaAbility.color_selector`'s new `"imprinted_card_colors"` kind
(`game/mana_abilities.py`) is the mana-ability half — "Add one mana of any
of the exiled card's colors" — reading `GameObject.linked_exile_id` fresh
every `resolve_options` call and building one option per color in the
referenced card's `color_identity` (a real *menu*, unlike ENG-27's Bloom
Tender aggregate — the payer picks one, mirroring a plain dual land's own
`options` shape); no card imprinted, or a colourless one, both correctly
produce nothing. The parser side needed its own regex
(`_IMPRINTED_COLOR_ADD_RE`) alongside the existing `_CHOSEN_COLOR_ADD_RE`
("…of the chosen color", Throne of Eldraine) it sits next to — a sibling
"the real color isn't printed, read it off the object at tap time" shape,
just sourced from a remembered *exiled* card instead of an ETB pick.
Mana abilities parse straight off the printed card regardless of hand-
authoring (the same reason ENG-27's Bloom Tender/Carpet of Flowers needed
no catalogue entry either), so this half needed no registration; only
Chrome Mox's ETB exile-and-remember is hand-authored
(`game/ability_catalogue.py`). One real wiring subtlety caught while
testing: the `AbilitySpec` itself must **not** also carry `optional=True`
— `ImprintEffect`'s own `optional` default already asks the real "you may
exile…" question at resolution, and the trigger-placement layer's RULE
603.5 "you may" is a *second*, redundant gate that produces a duplicate
prompt if both are set (Chrome Mox has one printed "you may", not two).

Tests: `tests/test_imprint_family.py` (new file, 8 tests, real cached
cards) — hand-authored spec shape; the ETB choice offering only qualifying
hand cards (an artifact and a land both correctly excluded); exiling
remembers the card, declining remembers nothing; no qualifying card never
even opens a choice; the mana ability producing a mono-colored imprint's
own color, offering a real menu for a two-color one (Lightning Helix), and
producing nothing (refusing to tap) with nothing imprinted at all. Full
backend suite: 3,528 passed (+8), 238 skipped, zero regressions.

---

**Batch summary — the six "sort-into-categories" primitives (ENG-26/27/28,
MEC-15/16/17), all shipped 2026-08-06**: every "confirmed-missing
primitive" [MEC-12](BACKLOG.md)'s cEDH batches surfaced along the way is
now closed, not just filed. Two recurring lessons worth carrying forward:
a ticket's own premise is routinely half-wrong even when freshly written
the same week (ENG-28's Linvala/Karn had no "during your turn" gate at
all; ENG-27's Bloom Tender's *real* cached text was a flatly different,
simpler mechanic than the ticket described) — sizing empirically
(`engine_bench.py inspect`, `parser_probe.py`) before designing is what
caught both, not trusting the prose. And a primitive landing is exactly
the moment this repo has historically forgotten to sweep for what else it
closes for free: MEC-16's keyword-binding fix silently resolved Mystic
Remora's and Thought Lash's own long-standing "Cumulative upkeep isn't
built yet" simplifications without either hand-authored spec being
touched, caught only because a pre-existing test's fixture assumptions
broke.

## The seven "cEDH"-named saved decks/cubes: third pass (2026-08-10)

Continuation of `MEC-12` (see the two 2026-08-06 entries above for the
first two passes). Baseline re-measured at the start of this pass: 764
unique cards across the seven decks (up from 723 — these are live,
user-editable saved decks), 430 covered / 334 uncovered. This pass
prioritized the highest deck-frequency remainder rather than working
alphabetically, closing **436/764** by the end (`Ojer cEDH` 48/125,
`cEDH Rocco` 71/98, `[cEDH] Glarb Bloomsday` 74/100, `cEDH staples`
164/215, `cEDH staples 2` 383/607, `cEDH M-K` 74/97, `cEDH Kinnan`
72/100).

**Mana-ability coverage-classification fix, not a behavior change**
(`parser/oracle/segmenter.py`): Bloom Tender ("For each color among
permanents you control, add one mana of that color.") was already fully
playable — `game/mana_abilities.py`'s own `_COLORS_AMONG_PERMANENTS_RE`
(ENG-27) parses and resolves it correctly — but scored UNMODELED anyway,
because the segmenter's mana-ability *claim* check (`_MANA_EFFECT_RE`)
only recognized an activated ability's effect line when it started with
the literal word "add"; this phrasing puts "add" mid-sentence, after the
"for each" clause. Added `_COLORS_AMONG_PERMANENTS_MANA_RE`, a literal
mirror of the `game/` regex (the front-end can't import `game/`, so the
shape is duplicated rather than shared — a documented, deliberate
tradeoff, not an oversight). Deliberately *not* generalized to a looser
"any line containing add + mana" pattern: Nykthos, Shrine to Nyx's "add
an amount of mana … equal to your devotion" and a few other UNCLAIMED
mana-shaped cards were checked and found genuinely unbuilt (no `devotion`
selector exists in `mana_abilities.py` at all) — claiming those too would
have been a silent half-resolve, exactly what this gate exists to catch.

**RULE 118.7/601.2f cost-reduction generalization** — the engine already
had a rich `cost_reduction_for`/`self_cost_reduction_for`/
`activation_cost_reduction_for` family (`game/continuous.py`, built across
several earlier batches for Delve/Affinity, the Medallion cycle's own
`spell_color` param, Power Artifact, and Sam Loyal Attendant's subtype
group scope) — but three shapes it already had *engine* support for had
never had a matching **parser handler**, and one engine branch was
missing outright:

- **Colour-scoped spell-cost tax** ("`<Color>` spells you cast cost `{N}`
  more/less to cast" — the Medallion cycle, Grand Arbiter Augustin IV's
  first two lines): `continuous.cost_reduction_for`'s own `spell_color`
  param was fully wired and tested, just unreachable from oracle text.
  New `_SPELL_COST_TAX_COLOR_RE` (`static_handlers.py`), checked *ahead*
  of the existing `_SPELL_COST_TAX_YOU_CAST_RE` in dispatch order — that
  regex's own `word1` group also matches a bare colour word, and its
  handler fails closed (claims nothing) on a word outside
  `_SPELL_TYPE_WORDS` rather than falling through to try a sibling regex,
  so the colour-specific row has to go first or it's never reached.
- **Opponents-scoped spell-cost tax** ("Spells your opponents cast cost
  `{N}` more/less to cast" — Grand Arbiter's third line): a genuinely new
  `affects="opponents_spells"` branch on `cost_reduction_for` (skip unless
  the caster is *not* the taxing permanent's controller — the mirror image
  of the existing `"your_spells"` check), plus `_SPELL_COST_TAX_OPPONENTS_RE`.
- **Activation-cost group scope by main card type** ("Activated abilities
  of creatures you control cost `{N}` less to activate[, floor]" —
  Training Grounds): `activation_cost_reduction_for` had a `subtype`
  group-scope branch (Sam) but no `card_type` one (a main type, not a
  creature subtype) — added alongside it, reusing `_has_card_type`/
  `_CARD_TYPE_ATTRS` already built for the opponent-scoped-permission
  family. Also switched this function from a flat
  `int(ability.params.get("generic", 0))` to `_cost_static_amount(...)`,
  so a future "for each X" count-selector-scaled *group* activation
  reduction (not needed by any card yet) would work for free. New
  `_ACTIVATION_COST_REDUCTION_TYPE_RE`.

**Otawara, Soaring City** hand-authored (`game/ability_catalogue.py`),
mirroring Eiganjo, Seat of the Empire/Boseiju, Who Endures's existing
Channel + `costs.ActivationCost.dynamic_reduction` shape exactly — the
per-legendary-creature discount is the *same* `legendary_creatures_you_
control` count_selector, not a new mechanism. Its own new piece:
`targeting.py`'s `artifact_creature_enchantment_or_planeswalker` target
kind, the four-permanent-type union Otawara's real printed wording needs
("target artifact, creature, enchantment, or planeswalker") that no
existing union kind covered.

**"[You may c]ast spells this turn as though they had flash."** parser
recognition (`catalogue/handlers.py`, Emergence Zone) — the effect already
shipped as `effects.GrantFlashUntilEndOfTurnEffect` (Borne Upon a Wind,
hand-authored only). The new `HANDLERS` row deliberately claims only the
unrestricted "spells" wording (no type filter exists on that effect at
all), leaving "sorcery spells"/"creature spells"-narrowed variants of the
same template correctly unclaimed rather than silently dropping their
qualifier — a ~87-cache-wide-card template family per
`engine_bench.py cards`, of which this row closes the unrestricted-"this
turn" slice.

**Mindbreak Trap's free-cast condition** — RULE 601.2f's
`free_cast_condition` family (`AbilitySpec.free_cast_condition`,
`game/condition_query.free_cast_condition_holds`) had only ever carried
boolean condition kinds (`control_commander`, `not_your_turn`/
`your_turn`, both reachable only via hand-authored cards per MEC-15).
Mindbreak Trap's "If an opponent cast three or more spells this turn, you
may pay `{0}` rather than pay this spell's mana cost." is the same
free-alternative-cost idiom (paying `{0}` *is* paying nothing) gated by a
board **count** instead — a new `opponent_spells_cast_this_turn_at_least`
key (positive-int-valued, unlike its boolean siblings), reading the
existing `GameState.spells_cast_this_turn` per-player counter
(`TaxedDrawEffect`'s own payer-lookup already relies on the same field).
New `_FREE_CAST_IF_OPPONENT_SPELLS_RE` (`segmenter.py`), mirroring the
existing `_FREE_CAST_IF_COMMANDER_RE`'s standalone-line treatment.
**Documented gap**: Mindbreak Trap's own second clause, "Exile any number
of target spells.", is RULE 601.2c's genuinely unbuilt *unbounded* target
count (distinct from the already-shipped "up to N"/fixed-N
generalization — no `TargetSpec` shape exists for "as many as you choose,
0 to unlimited" yet) — left UNMODELED rather than half-built; 13 cache-wide
cards share the wider "any number of target X" shape per
`engine_bench.py cards`, filed as open scope in `MEC-12` rather than
rebuilt ad hoc here.

**Smothering Tithe** hand-authored — the `TaxedDrawEffect` family's
(Rhystic Study/Mystic Remora/Esper Sentinel) first member whose trigger
isn't `SPELL_CAST`: "Whenever an opponent draws a card, that player may
pay `{2}`. If the player doesn't, you create a Treasure token." needed
`effect_binder._GROUP_CONTROLLER_EVENT_KEYS` to gain a `"DRAW":
"player_id"` row (`RulesEngine.draw` already fired the event with the
right shape — a per-player `count`, mirroring every other player-subject
event in that table — only this row was missing), so the same
`{"subject": "group", "controller": "not_you"}` condition shape Rhystic
Study uses reads it correctly. The payoff isn't a draw, though, so this
isn't `TaxedDrawEffect` itself: `effects.PayCostThenEffect`'s general
RULE 118.3 "you may pay `<cost>`. If you don't, `<effect>`." shape
(`payer="event_player"` reads the *drawing* player off the triggering
DRAW event; `else_effects=[create_token]` resolves under Smothering
Tithe's own controller, matching "**you** create a Treasure token").
One test-writing trap worth flagging for the next hand-authored card
using `PayCostThenEffect`'s `effects`/`else_effects` params: each entry
must be a *nested* `{"type": ..., "params": {...}}` dict (`EffectSpec.
to_dict()`'s own shape, which `RulesEngine._apply_effect_specs` expects) —
a flat `{"type": "create_token", "token_name": "Treasure"}` is silently
accepted (no error) but resolves with every param defaulted, since
`d.get("params")` on a flat dict just returns `None`/`{}`.

Tests: `tests/test_mec_12_cedh_batch_3.py`, eight real execute tests
against a real `GameEngine` (Bloom Tender's mana production, Grand
Arbiter's own reduction/tax numbers, Training Grounds's floor, Otawara's
hand-zone Channel activation and legendary-count discount, Emergence
Zone's flash grant, Mindbreak Trap's condition evaluator, and Smothering
Tithe's both branches — decline-and-create-Treasure, pay-and-drain-mana).
One pre-existing regression test, `test_color_scoped_variant_stays_
unclaimed`, documented the colour-scoped gap this pass closed and was
updated (renamed, its assertion flipped from "stays unclaimed" to the new
claimed shape) rather than deleted. Full backend suite: 3,538 passed
(+8), 238 skipped, 0 regressions. `PARSER_VERSION` bumped 60 → 61 (+13 to
measured cache-wide parser coverage: 10,948 → 10,961/34,811, 31.5%) —
required for a parser-classification change like this, since the
coverage ledger is content-hash-keyed and won't reparse an unchanged
card's cached verdict otherwise.

Remaining scope (the tutor family, Mox Diamond's RULE 614.12 alternative
ETB-or-graveyard replacement, Ghostfire Slice's conditional self
cost-reduction, Eye of Ugin's combined colour+subtype filter, and the
rest of the long tail) is `MEC-12` in `BACKLOG.md`.

## The seven "cEDH"-named saved decks/cubes: fourth pass (2026-08-11)

User request: not just the remaining high-frequency cards this time —
"make the rest of MEC-12's cards fully playable... build not just the
high-frequency cards but all." Baseline: 764 unique cards, 436 covered /
328 uncovered. Rather than picking off single named cards, this pass
worked the pool's own unclaimed-clause list end to end
(`parser_oracle.gate.parse_oracle(card).unclaimed` dumped for all 328),
clustering into shared templates before writing anything, per this
project's own "grep before claiming a new mechanism" convention. Closed
451/764 by the end — real, substantial progress, but the true remaining
residue is roughly 300 cards, several needing subsystems no ticket has
even sketched yet (devotion, a general "players can't `<verb>`" family,
"search library and/or graveyard" for X-cost tutors, a broader
alternative-cost "pitch" family, …) — see the updated `MEC-12` entry in
`BACKLOG.md` for the full list. Consistent with the ticket's own framing
("not no-deferrals scope"): a large batch, not forced completion.

**New general primitives, most valuable well past this one pool:**

- **RULE 603.1's untyped player-subject cast trigger.** "Whenever you
  cast a spell, `<effect>`." had never been recognized at all —
  `_CAST_SPELL_TRIGGER_RE` only ever matched a *typed* variant ("cast
  a/an `<type>` spell"), and only for the `you` subject. The gap: its own
  `types` capture group (`[a-z][a-z,\s]*?`) requires at least one word
  between the article and "spell", so "a spell" (nothing between "a" and
  "spell") never matched — confirmed by a direct `_trigger_condition`
  probe before writing anything. `_CAST_SPELL_TRIGGER_PLAIN_RE` (whole-line,
  parallel to the typed regex, not a widening of it) covers `you`/`an
  opponent`/`a player` alike: `effect_binder`'s existing `{"subject":
  "group", "controller": "you"/"not_you"/None}` scoping already handles
  any player-keyed event with no `type`/`other` filter set — proven
  working for a non-permanent event by Smothering Tithe's own `DRAW`-event
  use last pass, so zero engine changes were needed for the trigger
  condition itself. `_CAST_SPELL_TRIGGER_MV_RE` adds the "with mana value
  N or less" filter sibling, reading `SPELL_CAST`'s already-stamped
  `mana_value` field through one new `effect_binder` predicate
  (`spell_mana_value_at_most`) — the event already carried the value
  (`RulesEngine._track_spell_cast`'s own read), only the predicate was
  missing. Unlocks Spellshock (plain) and Eidolon of the Great Revel/
  Pyrostatic Pillar (mana-value-filtered) directly, +21 cards to measured
  cache-wide coverage on its own.
- **`DealDamageEffect`'s new `"event_player"` selector** — "~ deals N
  damage to **that player**", the player named by the firing trigger's
  own event (`SPELL_CAST`'s `player_id`), read via the same
  `_event_player` helper `PayCostThenEffect`'s `payer="event_player"`
  already uses. Paired with a new `"that player"` entry in
  `handlers.py`'s `_DAMAGE_SELECTOR_WORDS` (alongside the existing "each
  creature"/"each player"/"each opponent"), so the parser recognizes it
  the same way as the other mass-damage selectors.
- **`_EXILE_TOP_PLAY_RE` widened** (RULE 601.3b "impulsive draw") — the
  effect (`ImpulsiveDrawEffect`) was already fully built, hand-authored
  for Light Up the Stage specifically, yet Light Up the Stage's own real
  printed text ("Exile the top two cards of your library. **Until the end
  of your next turn,** you may play those cards.") didn't match the
  existing regex, which only recognized the *trailing*-duration word
  order ("...you may play them [duration]"). Found by testing the card
  the effect was named after, not by assuming a hand-authored primitive
  with a real card's name on it must already be reachable from that
  card's own oracle text. Widened to accept both word orders, "that
  card"/"those cards" pronouns (not just "them"/"it"), a singular "the top
  card" (no digit — `\d+` can't match zero digits, needed its own
  alternative), and `count_or_x_of` for "the top x cards" (Commune with
  Lava's variable count, the same `"x"`-sentinel/`_substitute_x` idiom
  every other X-scaled one-shot effect already uses). Unlocked Blazing
  Crescendo, Commune with Lava, Light Up the Stage, and Reckless Impulse
  directly, +~24 more cache-wide.
- **Search criteria widened**: a colour word ahead of the type list
  ("search your library for a **blue** instant card" — Merchant Scroll;
  "a **green** creature card" — Magus of the Order/Natural Order/
  Shadow-Rite Priest), consumed and dropped rather than modeled as its
  own filter (`SearchLibraryEffect` has no colour criterion yet — a
  documented over-approximation, not a silent behaviour change on any
  card actually in the cache, since every real card found on this shape
  pairs the colour with an already-narrow type search). Caught a real
  regex-precedence bug while widening this: the first attempt wrote
  `(?:white|blue|black|red|green\s+)?`, where `\s+` binds to only the
  last alternative in the group — "green X" matched by pure accident (the
  literal word "green" happened to include its own following space in
  the match) while every other colour silently didn't, until a test with
  more than one colour word caught it. Fixed to
  `(?:(?:white|blue|black|red|green)\s+)?`. Also added "equipment" to the
  searchable-subtype vocabulary (`_SEARCH_TYPE_WORD`) — `models.
  card_query._type_matches` already does a plain substring check against
  the *whole* printed type line ("Artifact — Equipment"), not just the
  pre-em-dash main types, the same reason "Forest"/"Island" already work
  as entries despite being land subtypes too, so this cost nothing
  engine-side. Together these unlocked Merchant Scroll, Magus of the
  Order, Shadow-Rite Priest, Steelshaper's Gift, Honored Knight-Captain,
  and Steelshaper Apprentice.
- **`models/card_query.py` gains `max_power`/`min_power`/`max_toughness`/
  `min_toughness`** criteria keys, mirroring `max_mana_value`'s shape and
  fail-closed treatment exactly (a non-creature card's `None` power never
  matches a power bound). The parser still doesn't parse a power/
  toughness qualifier after a search noun phrase — the same documented
  gap as "with mana value X or less" — so Imperial Recruiter ("with power
  2 or less") and Recruiter of the Guard ("with toughness 2 or less") are
  hand-authored directly onto the new keys rather than waiting on that
  parser work.
- **`effects.WheelOfFortuneEffect`** — "each player discards their hand,
  then draws seven cards." (Wheel of Fortune), the flat-draw-count
  sibling of the already-shipped `WheelEffect` (Timetwister's shuffle-
  into-library variant) and `WindfallEffect` (Windfall's shared-maximum
  variant) — same sequential-discard-then-draw shape, just a fixed count
  instead of a computed one. Hand-authored (this exact printed line is a
  one-card template, not a family worth a parser handler yet).
- **`DestroyEffect`'s mass-wipe `filter` gains a `"nonbasic"` key**
  ("destroy all nonbasic lands." — Ruination), paired with the existing
  `selector="all_lands"` the same "selector picks the zone/type, filter
  narrows it" split every other qualified board wipe already uses.
  Hand-authored (single-card template).

Also fixed a stale regression test, `tests/test_oracle_triggers.py`'s
`test_whenever_you_cast_a_spell_stays_unmodeled`, which had documented
the untyped cast-trigger gap this pass closed — renamed to `_is_modeled`
and its assertion flipped, rather than deleted, per this project's
"update the test that documented a gap you closed" convention.

New tests: `tests/test_mec_12_cedh_batch_4.py` (10 execute tests covering
every primitive above against a real `GameEngine` — the cast-trigger
family with both a firing and a non-firing case for the mana-value
filter, the impulsive-draw exile-and-permission check, the search
criteria's type-filter-without-colour behaviour, both new `card_query`
bounds, and both hand-authored spell effects). Several genuine test-
authoring bugs surfaced and were fixed along the way, not engine bugs:
`Card.is_instant`/`converted_mana_cost` don't default from `type_line`/
`mana_cost_string` and must be passed explicitly (a `{4}{4}`-costed test
card without an explicit `converted_mana_cost=8` silently priced as mana
value 0, making a "shouldn't trigger" assertion pass for the wrong
reason); a land `Card` needs `is_land=True` explicitly too (`type_line`
text alone doesn't make `DestroyEffect`'s `selector="all_lands"` see it);
and `GameState`'s real turn/phase fields are `current_step`/
`active_player_index`-via-`active_player` (mirroring `tests/
test_batch8_permission_statics_family.py`'s established `engine.
begin_turn(); state.current_step = "main1"` idiom), not the `current_phase`/
`active_player_id` names an initial draft guessed at. Full backend suite:
3,548 passed (+10 new, 1 renamed), 238 skipped, 0 regressions (one
pre-existing flaky websocket test, unrelated, confirmed passing in
isolation). `PARSER_VERSION` bumped 61 → 62 (+66 to measured cache-wide
parser coverage: 10,961 → 11,027/34,811, 31.7%).

Remaining scope — both the specific already-diagnosed gaps (tutor
family, Mox Diamond, Mindbreak Trap's unbounded clause, Ghostfire Slice,
Eye of Ugin, Meltdown's X-scaled filter, Stonehewer Giant's search-then-
attach shape) and the broader subsystems this pass's full-pool sweep
surfaced (devotion, a general "players can't `<verb>`" family, phasing/
copy-exception effects, a broader pitch-cost family, conditional extra-
combat grants) — is `MEC-12` in `BACKLOG.md`.

## The seven "cEDH"-named saved decks/cubes: fifth pass (2026-08-11)

Continuation of `MEC-12`, working down the fourth pass's own "specific,
already-diagnosed gaps" list rather than the broader undesigned
subsystems it also flagged (those still need their own tickets, per the
ticket's own text). Closed six real cards outright — Meltdown, Chord of
Calling, Green Sun's Zenith, Finale of Devastation, Wishclaw Talisman,
Ghostfire Slice — each landing a genuinely reusable primitive, not a
one-off:

- **`RulesEngine._substitute_x` now walks a `filter`/`criteria` dict
  attribute**, not just a plain `amount`/`count`/`power`/`toughness`
  field, for its "x"/"-x" sentinel — the fourth pass's own diagnosis of
  Meltdown's block ("`DestroyEffect.filter`'s `max_mana_value` can't
  carry the sentinel yet") turned out to double as `SearchLibraryEffect.
  criteria`'s exact same gap once the tutor grammar below started
  emitting `max_mana_value: "x"` too — one small addition to the
  substitution walk closed both at once, rather than needing two.
- **The mass "destroy all X" family gains a singular "destroy each X"
  alternative** (`_MASS_DESTROY_NOUNS_SINGULAR`, alongside the existing
  plural "all Xs") — Meltdown prints "Destroy **each** artifact", not
  "destroy all artifacts", which the existing regex had never
  accounted for; combined with the "x" sentinel above, `Meltdown` is now
  MODELED outright.
- **The tutor grammar's colour word actually reaches
  `SearchLibraryEffect.criteria["color"]` now.** `models.card_query` has
  had a `color` key (matched against colour identity) since an earlier
  pass, but `_search_criteria_from_match`/`_search_zone_criteria_from_
  match` had only ever *consumed and dropped* the captured word — a real
  gap, not the documented-permanent over-approximation the surrounding
  comment claimed (found by grepping the criteria vocabulary before
  building anything new, per this repo's own "grep before claiming a new
  mechanism" convention). A regression test (`test_mec_12_cedh_batch_4.
  py`'s Merchant Scroll case) had actually been asserting the *old*,
  wrong behaviour — a red instant matching "a **blue** instant card" —
  and needed a real fixture fix, not just a number bump.
- **A "with mana value X or less/greater" trailing qualifier**, shared by
  `_SEARCH_CRITERIA` and `_SEARCH_ZONE_CRITERIA` (`_SEARCH_MV_QUALIFIER`)
  — X is this spell's own announced {X}, carried as the literal `"x"`
  sentinel into `criteria["max_mana_value"]`/`min_mana_value"]` and
  resolved by the `_substitute_x` widening above; a literal digit bound
  works the same way. Unlocks `Chord of Calling` outright (MODELED) and
  the search half of `Green Sun's Zenith`/`Finale of Devastation`.
- **`ShuffleSelfIntoLibraryEffect`/`GameEngine.shuffle_into_library`** —
  "Shuffle ~ into its owner's library." (RULE 701.20, Green Sun's
  Zenith's own trailing sentence), overriding a spell's default RULE
  608.2m "goes to the graveyard as it resolves" routing. No new
  special-casing needed in `_apply_stack_item`: its existing
  `obj.zone != Zone.STACK` check already treats *any* self-move away
  from the stack as an override (built for a trailing self-`ExileEffect`,
  Mnemonic Betrayal/Teferi's Protection-shaped) — this effect is a second
  occupant of that same branch. Combined with the mana-value qualifier
  above, `Green Sun's Zenith` is now MODELED outright.
- **`Finale of Devastation`** hand-authored (its own two-sentence shape —
  a conditional bonus keyed to the *same* spell's {X} as its search — is
  a singleton template cache-wide, not worth a parser handler yet): the
  search half reuses the zone/criteria primitives above; the bonus half
  ("if X is 10 or more, creatures you control get +X/+X and gain haste")
  reuses `Martial Coup`'s own `source_x_paid_at_least` `ConditionalEffect`
  gate, found by grepping `Done_Backend.md` for an equivalently-shaped
  condition before assuming a new one was needed.
- **`ActivationCost.only_during_your_turn`** (RULE 602.5d's *wider*
  sibling of `sorcery_speed_only` — still legal at instant speed with a
  non-empty stack, just not outside the controller's own turn) +
  **`GainControlBySourceEffect`** ("An opponent gains control of ~.",
  RULE 701.10-adjacent — indefinite, always the source itself, moves
  control *away* from the controller, and isn't a RULE 115 target at
  all). Together with the "remove a `<kind>` counter from ~" activation
  cost (already generic since an earlier batch — `costs.py`'s
  `_REMOVE_COUNTERS_RE` needed no change at all), these make
  `Wishclaw Talisman` MODELED outright. `only_during_your_turn` picking
  the *next* opponent in seating order (rather than a real "choose an
  opponent" chooser, which doesn't exist yet for a *player* — only for
  `GameObject` candidates via `request_choose_objects`) is unambiguous
  in every 1v1 goldfish/Replay game and a documented MVP simplification
  for 3+-player tables, the same "auto-pick, no chooser in this MVP"
  idiom `put_hand_cards_on_top` already uses.
- **`continuous.self_cost_reduction_for` now honours an `active_if` gate**
  (RULE 613.6, the same whitelist a battlefield static already reads) and
  **`count_selector` gains `multicolored_permanents_you_control`** —
  Ghostfire Slice's own "This spell costs {2} less to cast if an opponent
  controls a multicolored permanent." `static_handlers.py` gained the
  general "if `<condition>`" recognizer for this shape too (reusing
  `static_condition`'s existing whitelist, plus a new `_opponent_control_
  condition` mirroring `_control_count_condition`'s "you control a/an
  `<x>`" row for the opponent-scoped case) — real, general, and already
  reachable for any *permanent* printing this shape (several real cEDH
  creatures do). Ghostfire Slice itself is an Instant, though, and hit a
  genuine, separate architectural gap on the way: `parser/oracle/
  segmenter.py`'s `allow_spell_effect` routes every clause on a true
  instant/sorcery through the one-shot `spell_effect` dispatch, which has
  no static-ability shape to emit at all — so the new parser recognizer,
  correct as it is, can never actually reach a spell's own oracle text.
  Hand-authored directly instead (`AbilitySpec("static", …)` doesn't care
  what kind of card its owner is, so it reaches `self_cost_reduction_for`
  regardless) rather than widening `attach_to_object`'s `spell_effect`
  branch to split a `StaticAbility` out of its bound effects — a real,
  separate primitive no *other* card needs yet, left as diagnosed
  context for whoever picks it up next rather than built speculatively.

New tests: `tests/test_mec_12_cedh_batch_5.py` (8 execute tests — Meltdown's
mana-value-capped mass destroy, Chord of Calling's search criteria capping
at the announced X, Green Sun's Zenith's search-then-self-shuffle
end-to-end including answering the interactive search choice to let the
deferred shuffle effect actually run, Finale of Devastation's zone search
+ its conditional pump's own `condition` dict, Wishclaw Talisman's real
RULE 614.1 entry counters through a genuine cast + activation + control
change, its own `only_during_your_turn` refusal on an opponent's turn, and
Ghostfire Slice's cost reduction toggling on `active_if`). Three existing
tests had documented the closed gaps as fail-closed and needed updating
rather than deleting, per this project's own convention (`test_search_
effects.py`/`test_effect_families_wave3.py`'s mana-value-qualifier tests,
`test_mec_12_cedh_batch_4.py`'s Merchant Scroll fixture, which had been
silently passing for the wrong reason). Full backend suite: 3,556 passed
(+8 new), 238 skipped, 0 regressions. `PARSER_VERSION` bumped 62 → 63
(measured cache-wide parser coverage: 11,027 → 11,066/34,811, 31.8%).

Remaining scope, now genuinely narrowed and re-diagnosed rather than
just re-counted (Tainted Pact's own two-reasons-to-stop loop shape
confirmed distinct from `dig_until`; Eye of Ugin's search half now just a
missing `"colorless"` vocabulary word, its static half still needing a
combined colour-emptiness-and-subtype cost filter; Transmute Artifact,
Mox Diamond, Mindbreak Trap, and Stonehewer Giant's search-then-attach
shape unchanged) plus the fourth pass's own broader undesigned
subsystems (devotion, "players can't `<verb>`", phasing/copy-exceptions,
a broader pitch-cost family, conditional extra-combat) — is `MEC-12` in
`BACKLOG.md`.

## The seven "cEDH"-named saved decks/cubes: sixth pass (2026-08-11)

Continuation of `MEC-12`: the fifth pass's own "specific, already-
diagnosed gaps" list (Mox Diamond, Mindbreak Trap, Eye of Ugin, Stonehewer
Giant/Quest for the Holy Relic, Tainted Pact, Transmute Artifact) had just
been promoted to next-up, putting all six at this project's own "no
half-implementations" threshold — a second deferral must be built or
explicitly re-promoted, not silently rolled to a third. This pass closed
every one of them:

- **Mox Diamond** (RULE 614.12's own worked example, "if ~ would enter,
  you may discard a land card instead...") — a new general primitive,
  `AbilitySpec.enter_or_graveyard_discard_land` + `RulesEngine._offer_
  enter_or_graveyard`, spliced into `_resolve_permanent_spell`'s existing
  continuation-passing chain (enter-as-copy → protector → enter-choice →
  Read Ahead → `_finish`) *before* every one of those, since declining
  means the object never becomes a permanent at all and none of them
  matter. `_send_to_graveyard_unentered` mirrors `_move_to_graveyard`'s
  own "a spell fresh off the stack has nothing to remove from a per-player
  zone first" shape. A new `shuffle_into_library`-adjacent mover wasn't
  needed here (that was the *fifth* pass's own primitive, for Green Sun's
  Zenith) — `_apply_stack_item`'s existing `obj.zone != Zone.STACK` check
  already recognizes any self-move off the stack as an override of the
  default graveyard routing, so Mox Diamond's "don't pay" branch reaches
  it for free.
- **Mindbreak Trap** ("exile any number of target spells") needed one
  row, not a new primitive: `_multi_target_params`'s "any number of" idiom
  (`_ANY_NUMBER_TARGET_CAP`) was already fully general — Fire Covenant and
  Display of Power both already exercise it — just missing a "target
  spells" target-kind row. Deliberately kept *out* of the shared
  `_MULTI_TARGET_ROWS` every other multi-target family (destroy/damage/
  tap/return_to_hand/...) also reads, since "destroy target spells"/"N
  damage to target spells" aren't real templates (you counter or exile a
  spell, never destroy or damage one) — only `exile`'s own regex opts into
  the wider `_MULTI_TARGET_ALT_WITH_SPELL` alternation. Caught a real
  regression on the way: widening the shared list first let
  `destroy_multi_target` claim "destroy 2 target spells" too, breaking
  `tests/test_multi_target.py`'s own "stays unclaimed" regression test —
  fixed by scoping the new row to `exile` alone rather than by weakening
  the test.
- **Eye of Ugin** — two independent gaps. `models.card_query`'s `color`
  key gained a `"colorless"` special case: an *empty* colour-identity
  check rather than a membership one, kept local to `_SEARCH_COLOR_WORD`
  (the search-only vocabulary) rather than widened into the shared
  WUBRG-only `subgrammars.resolve_color_word`/`COLOR_WORD_ALT`, since
  "colorless" isn't a valid substitute for any of that vocabulary's other
  consumers (target-filter colour adjectives, "if it's `<color>`"
  suffixes). `continuous.cost_reduction_for` gained a `spell_subtype`
  filter (a creature subtype — "Eldrazi" — orthogonal to the existing
  `spell_type`, which only ever checks a main card type), composed with
  `spell_color="colorless"` by plain AND, the same way every other filter
  in that function already composes. Hand-authored (the *combined*
  colour-emptiness-and-subtype shape is a singleton, even though both
  halves are now real, reusable primitives on their own).
- **Stonehewer Giant / Quest for the Holy Relic** ("search for an
  Equipment card, put it onto the battlefield, attach it to a creature you
  control") — `SearchLibraryEffect` gained `attach_to_creature_you_control`,
  applied in `_finish_search` right after `extra_counters` (the same "one
  more step once the found card reaches the battlefield" slot Neoform's
  counter already occupies), auto-picking the first eligible creature the
  searching player controls — the same "no chooser for an equally-valid
  pick" idiom this codebase uses pervasively, since Equipment attachment
  here has no RULE 115 target of its own (the printed line never says
  "target creature"). Reached by a new, fully general oracle-text handler
  (`_SEARCH_PUT_ATTACH_THEN_SHUFFLE_RE`, a strict superset of the existing
  put-then-shuffle family) — both cards MODELED outright, no
  hand-authoring needed. Quest for the Holy Relic's own trigger ("put a
  quest counter on this enchantment") needed only a vocabulary word —
  `_NAMED_COUNTER_KINDS` gains `"quest"` alongside the existing `"spore"`/
  `"burden"`.
- **Tainted Pact** — a genuinely new loop shape, confirmed on inspection
  *not* an instance of `dig_until` (which stops on the first card matching
  one static predicate; this stops for either of two reasons on
  *cumulative* per-iteration state). `ExileUntilDuplicateNameEffect`/
  `RulesEngine.exile_until_duplicate_name` opens a real interactive
  `pending_choice` ("take" the just-exiled card vs. "continue" digging
  further) on every non-duplicate hit with library left — not an
  auto-take, since the actual reason this card is played in cEDH is
  *declining* every hit on purpose (paired with Thassa's Oracle in a
  singleton deck, deliberately milling the whole library to win off an
  empty-library trigger); auto-resolves without a prompt only when there's
  truly nothing to decide (a forced duplicate, or an empty library right
  after a hit).
- **Transmute Artifact** — confirmed a singleton cost-comparison-gated
  placement (a raw-text grep for its own distinctive "put it onto the
  battlefield if its mana value is less than or equal to" phrasing turns
  up only this card). One self-contained bespoke sequence,
  `TransmuteArtifactEffect`/`RulesEngine.transmute_artifact`, with three
  of its own `pending_choice` kinds (sacrifice → search → an optional
  pay-the-difference) rather than composed from the general search/
  sacrifice/`pay_cost_then` primitives — none of which can express "the
  cost is a number computed from what a different, just-made choice
  turned out to be". A player who can't pay the difference is never
  asked, matching `request_pay_cost_then`'s own "don't stall on a choice
  nobody can act on" convention.

New tests: `tests/test_mec_12_cedh_batch_6.py` (12 execute tests, one per
real behavioural branch — Mox Diamond's pay/decline/no-land-available
cases, Mindbreak Trap's parse verdict, Eye of Ugin's combined cost filter
across three spell fixtures plus its colorless-only search, Stonehewer
Giant's real attach-after-search end to end, Quest for the Holy Relic's
parse verdict, Tainted Pact's take-vs-continue-into-a-duplicate cases, and
Transmute Artifact's cheap-find/pricier-find-declined cases). Fixture
gotchas worth recording for the next batch: `Card.is_artifact` is a
derived `@property` off the type line, not a constructor kwarg (unlike
`is_creature`/`is_land`/`is_instant`, which *are* explicit); `GameObject.
colors` falls back to `Card.color_identity`, which is never auto-derived
from `mana_cost_string` and must be set explicitly on a synthetic Card;
and a synthetic Equipment card needs `keywords=["Equip"]` set explicitly —
`parser.oracle.catalogue.keywords.parse_keywords` is anchored on
Scryfall's machine-readable `keywords` array, not parsed out of a raw
"Equip {N}" oracle-text line, so a hand-built fixture with only
`oracle_text` set silently never attaches. Full backend suite: 3,568
passed (+12 new), 238 skipped, 0 regressions (one pre-existing flaky
websocket test, unrelated, confirmed passing in isolation).
`PARSER_VERSION` bumped 63 → 64 (measured cache-wide parser coverage:
11,066 → 11,081/34,811, 31.8%).

No specific per-card gaps remain open on this ticket right now — what's
left is entirely the fourth pass's own broader undesigned subsystems
(devotion, a general "players can't `<verb>`" family, phasing/copy-
exception effects, a broader pitch-cost family, conditional extra-combat
grants, the last of which is what still blocks Godo, Bandit Warlord's own
second ability) — see `MEC-12` in `BACKLOG.md`.

## The seven "cEDH"-named saved decks/cubes: seventh pass (2026-08-11)

Continuation of `MEC-12`. Baseline re-measured at the start of this pass:
723 unique cards across the seven decks (up from 719 — these are live,
user-editable saved decks), 462 covered / 261 uncovered. Rather than
picking off the residue card-by-card, this pass prioritized shapes that
generalize past this pool — every item below was sized against the full
cache (`parser_probe.py`-style grep) before building, and every one landed
as a widened existing primitive rather than a new one:

- **The untap-cap family widened past lands-only.** `continuous.
  untap_cap_for_lands` — Winter Orb's own primitive, hardcoded to
  `obj.is_land` and to a hardcoded `not ability.source.tapped` check — is
  now `continuous.active_untap_caps` (returns a list of `{"count",
  "card_type", "nonbasic"}` dicts, since 2+ differently-scoped caps can be
  active at once and are enforced independently) + `matches_untap_cap_
  filter` (`_has_card_type`/`_is_nonbasic`, the same filters every other
  static family's `affects` selector already applies). The tapped-state
  gate ("as long as this artifact is untapped") now rides the ordinary
  RULE 613.6 `active_if` wrapper instead of a hardcoded check — Winter
  Orb's own hand-authored `ability_catalogue.py` entry was updated to
  carry `active_if={"kind": "source_untapped"}` explicitly rather than
  relying on the old default, with its existing execute tests
  (`test_cube_batch_b1.py`) re-run to confirm no behavior change.
  `GameEngine._step_untap` now tracks one running count per active cap
  rather than a single land count. Closes **Static Orb** ("as long as
  this artifact is untapped, players can't untap more than two
  permanents…") and **Winter Moon** ("…one nonbasic land…") via one new
  parser regex (`static_handlers._UNTAP_CAP_RE`) — Static Orb's own
  "as long as…" gate is peeled off for free by the pre-existing
  `_conditional_static_specs`/`static_condition` "~ is untapped" row
  (self-reference folding already turns "this artifact" into `~` before
  the condition parser ever sees it). Cache-wide this same row also
  claims Damping Field/Imi Statue (artifacts)/Smoke/Stoic Angel
  (creatures) — 9 real cards total print "can't untap more than N `<type>`
  during their untap steps," 6 of them now reachable.
- **Meekstone** — "Creatures with power N or greater don't untap during
  their controllers' untap steps." is the unattached, group-scoped
  sibling of `no_untap`'s existing self/`attached_permanent` shapes: a new
  `_NO_UNTAP_GROUP_POWER_RE` row emits `affects="all_creatures"` plus the
  ordinary `min_power` selector `group_selector_objects` already applies
  to every other static family — no new engine code. Caught two of the
  `no_untap`/`untap_cap` `EffectRegistry` factories dropping every param
  but their own hardcoded ones (`params={}`), silently discarding
  `min_power`/`card_type`/`nonbasic`/`active_if` even once the parser
  started emitting them — fixed to forward `_selectors(p)` like every
  other static factory in the file already does.
- **RULE 115.4 "change the target" got its first oracle-text handler.**
  `ChangeTargetEffect` (built two passes ago for Misdirection/Deflecting
  Swat) had never had a generic parser row at all — both real cards were
  hand-authored individually, and every other card printing the same
  template stayed unclaimed. One new handler (`catalogue.handlers.
  _change_target`, matched by `_CHANGE_TARGET_RE`) claims "Change the
  target of target spell with a single target." and "…target spell or
  ability with a single target." generically — the "or ability" variant
  always uses `spell_or_ability=True` regardless of whether the printed
  text also says "with a single target," since the engine's own
  single-existing-target MVP limit applies inside that branch either way
  (see the effect's own docstring — the printed qualifier and the engine
  limit happen to coincide, they aren't two different restrictions).
  Closes this pool's own **Bolt Bend**/**Redirect Lightning** and, cache-
  wide, **Deflection**/**Shunt**/**Swerve**/**Willbender** for free (24
  cache cards print some variant of the phrase; a few more — Reroute's
  "target activated ability," Rebound's player-only retarget, Torchling's
  self-only variant — print a narrower or differently-scoped version this
  row doesn't claim and stay open).
- **"You control a creature with power N or greater" as a RULE 613.6
  condition** (Bolt Bend's own cost-reduction gate — `_SELF_COST_
  REDUCTION_IF_RE` already existed but its `cond` clause fed into
  `static_condition`, which had no row for a *qualified* existence check).
  `control_count`'s existing `selector`/`min` shape gained an optional
  `min_power` key: `static_conditions.condition_holds`'s `control_count`
  branch scans the battlefield directly when `min_power` + `selector ==
  "creatures_you_control"` are both present, instead of routing through
  `continuous.count_selector` (whose flat vocabulary only counts, never
  filters by a derived characteristic — adding one selector name per
  possible power threshold isn't the right shape). 58 cache cards print
  this exact phrase; only cost-reduction/activation-condition gates reach
  it as `active_if` today, so most of those 58 need their *other* clauses
  closed too before the card itself is MODELED, but the condition itself
  no longer blocks any of them.
- **A spell's own "this spell costs `{N}` less to cast if/for each…" had
  never reached `static_effect_specs` at all for an instant or sorcery.**
  `segmenter.py`'s per-line dispatch only tries `static_effect_specs` when
  `allow_spell_effect` is false (i.e., for a permanent) — an instant/
  sorcery's lines go straight to the resolve-time `spell_effect`/
  additional-cost paths instead, so `_SELF_COST_REDUCTION_IF_RE`/
  `_SELF_COST_REDUCTION_ATTACKING_RE` (both already shipped, both already
  proven on real permanents — Embercleave, Ancient Stone Idol) were simply
  unreachable for the far more common case of the clause printed on the
  spell itself. `continuous.self_cost_reduction_for` already reads a
  `cost`-layer static straight off *any* object's `static_effects`
  regardless of zone — Ghostfire Slice's own hand-authored catalogue entry
  proved the engine half worked, nothing had ever exercised the parser
  half. Fixed with a narrowly-scoped addition to the `allow_spell_effect`
  branch (parallel to the existing additional-cost special case): try
  `static_effect_specs` first, and only accept the result when *every*
  spec is `type == "cost_reduction"` and `affects == "self"` — anything
  else falls through to the ordinary resolve-time parse untouched, so an
  unrelated static-shaped false match can't misfile a genuine effect line.
  123 cache cards print `"this spell costs {N} less to cast if"` in some
  form; most are instants/sorceries newly reachable by this fix (a
  minority were permanents already working via the pre-existing route).
  Full suite re-run after this change specifically (broadest-blast-radius
  edit in the batch, since it touches segmenting for every instant/sorcery
  in the game) — no regressions.
- **"Your opponents can't cast spells during your turn."** (Voice of
  Victory/Dragonlord Dromoka/A-Teferi Time Raveler's static half/Jennifer
  Walters/Tidal Barracuda/Conqueror's Flail) — `cast_prohibition`'s
  existing `scope="opponents"` default (RULE 613.6's own `active_if`
  already general) already expresses this exactly; the only gap was a
  parser row for the *trailing* phrasing (`_CANT_CAST_OPPONENTS_YOUR_
  TURN_RE`, `{"scope": "opponents", "active_if": {"kind": "your_turn"}}`)
  — the existing `_CANT_CAST_OR_ACTIVATE_OPPONENTS_RE` only covers the
  *leading* "During your turn, your opponents can't cast spells or
  activate abilities of `<type>`." shape, a different template. Conqueror
  Flail's own "as long as this Equipment is attached to a creature, …"
  wrapping needs no new code — `_conditional_static_specs` peels it off
  before this row is ever reached, same as any other conditional static.
  Closes this pool's own **Voice of Victory** (Kutzil, Malamet Exemplar
  still has an unrelated second clause open — see below) and, cache-wide,
  Dragonlord Dromoka/A-Teferi/Jennifer Walters (Tidal Barracuda/Conqueror's
  Flail both print an *additional* unrelated clause that keeps them open).

**Left open, diagnosed rather than silently deferred**: Redirect
Lightning's "as an additional cost to cast this spell, pay 5 life **or**
pay `{2}`" is a genuinely new primitive (`AbilitySpec.additional_cost` has
no "choose one of two cost shapes" branch, and `_pay_additional_cast_cost`
pays synchronously inside `cast_spell` with no interactive choice point
today) confirmed a cache-wide singleton — the right call is to
hand-author it next time this ticket is picked up, not build the general
choice machinery for one card. Kutzil, Malamet Exemplar's second ability
("whenever 1 or more creatures you control each with power greater than
its base power deals combat damage to a player, draw a card") needs a
derived-vs-printed-power comparison the trigger-condition vocabulary
doesn't have yet — a different, unrelated shape. Grafdigger's Cage/
Weathered Runestone's pair of zone-scoped restrictions ("players can't
cast spells from graveyards or libraries" / "`<type>` cards in graveyards
and libraries can't enter the battlefield") are real, reusable primitives
neither of which exists in any form today (4 cache cards each,
overlapping) — sized but not built this pass; promoted to `BACKLOG.md`'s
"broader gaps" list alongside devotion/the cast/copy-exception family
rather than attempted as a rushed one-off.

New tests: `tests/test_mec_12_cedh_batch_7.py` (10 execute/parse-verdict
tests — Static Orb's permanent cap and its own tapped-state gate, Winter
Moon's nonbasic-only cap, Meekstone's power threshold, the four
`change_target`-unlocked cards' parse verdicts, Bolt Bend's cost-reduction
condition executed both ways (no big creature / a power-4 creature
present), and `cast_prohibited`'s your-turn-vs-their-turn behavior for
Voice of Victory). Full backend suite: 3,691 passed (+10 new), 238
skipped, 0 regressions (one pre-existing flaky websocket test, unrelated,
confirmed passing in isolation both before and after this batch).
`PARSER_VERSION` bumped 70 → 71 (measured cache-wide parser coverage:
11,489 → 11,509/34,811, 33.1%).

## The seven "cEDH"-named saved decks/cubes: eighth pass (2026-08-11)

Continuation of `MEC-12`. Baseline re-measured at the start of this pass:
467 covered / 723 total across the seven decks. Rather than the two
"broader gap" primitives the seventh pass had explicitly sized-but-not-
built (Grafdigger's Cage/Weathered Runestone's zone-cast-restriction
pair — still open, unchanged, needing two genuinely new primitives no
existing casting/zone-entry choke point covers), this pass picked off a
small, tightly-scoped cluster:

- **Back to Basics** ("Nonbasic lands don't untap during their
  controllers' untap steps.") is `no_untap`'s unconditional, unlimited-
  count sibling to the seventh pass's own `_UNTAP_CAP_RE` (Winter Moon's
  "…can't untap more than one nonbasic land…", a *cap* that still lets the
  first one through each turn — this blocks every one, every turn):
  `affects="all_lands"` plus the ordinary `nonbasic` selector `group_
  selector_objects` already applies to every other static family — no new
  engine code at all, one new parser row (`_NO_UNTAP_NONBASIC_LANDS_RE`).
  Only 1 other cache card prints this exact phrase, but it's a real
  cEDH staple.
- **Auriok Salvagers** ("{1}{W}: Return target artifact card **with mana
  value 1 or less** from your graveyard to your hand.") — `Return
  FromGraveyardEffect` had no mana-value filter at all: no constructor
  param, no capture group in `_RETURN_FROM_GRAVEYARD_RE`, and `targeting.
  py`'s `_GRAVEYARD_TARGET_KINDS` branch never checked `spec.max_mana_
  value` the way every battlefield-object branch already does. Added all
  three, reusing `destroy_mv`'s own `TargetSpec.max_mana_value` field
  rather than inventing a second one. Cache-wide this same widening
  reaches **102 real cards** printing "return target `<type>` card with
  mana value N or less from `<scope>` graveyard to `<dest>`" — Sun Titan,
  Unearth, Teshar Ancestor's Apostle, Ral Zarek Guest Lecturer's own
  static half, and 98 more, most already `MODELED` the instant the filter
  landed (the shape itself — recursion — was already fully general; only
  the qualifier was missing).
- **Assassin's Trophy** ("Destroy target permanent an opponent controls.
  Its controller may search their library for a basic land card, put it
  onto the battlefield, then shuffle.") needed two independent gaps:
  1. **A missing target kind.** `subgrammars._TARGET_ROWS` had "target
     creature an opponent controls" (→ `creature_you_dont_control`) but no
     equivalent unscoped-by-type "target permanent an opponent controls"
     row — `resolve_target_kind` simply had nowhere to send it. Added
     `permanent_you_dont_control` (new row in `_TARGET_ROWS`, new branch in
     `targeting.legal_targets` mirroring the existing `("creature",
     "permanent")` branch but controller-scoped) — and found the plain
     `_destroy` handler function itself was hardcoded to accept only
     `kind in ("creature", "permanent")`, silently discarding *any* other
     kind `resolve_target_kind` might resolve, including this brand-new
     one and, incidentally, `creature_you_dont_control` too (never
     exercised through the *plain* `destroy` handler before — narrower
     dedicated handlers like `destroy_creature_filter` had covered that
     case from a different angle). Widened the whitelist rather than
     special-casing. Reaches 12 cache-wide cards on its own (Teferi, Hero
     of Dominaria; Kiora, the Crashing Wave; Elspeth Conquers Death; Dovin,
     Hand of Control among them) even before the second half below.
  2. **A controller-redirected optional search.** "Its controller" is
     whoever just lost the destroyed permanent, never this spell's own
     caster — the same RULE 608.2 "previous clause's referent" shape
     `PayCostThenEffect`'s `payer="previous_target_controller"` sentinel
     already uses for Chain of Vapor's "that permanent's controller may
     sacrifice a land," just never built for `SearchLibraryEffect`. Added
     the identical sentinel there (`GameContext.previous_targets`, fails
     closed — no search offered — if somehow there's no previous target on
     record) plus one new parser row recognizing the fixed trailing
     sentence (`_DESTROY_CONTROLLER_SEARCH_BASIC_LAND_RE`, `{"criteria":
     {"basic": True}, "destination": "battlefield", "optional": True,
     "player": "previous_target_controller"}`). Closes Assassin's Trophy
     itself plus, cache-wide, **Geomancer's Gambit** and **Ghost Quarter**
     (a hand-authored land whose second activated-ability clause had been
     left an undocumented partial until now) — all three print the exact
     same trailing sentence verbatim.

New tests: `tests/test_mec_12_cedh_batch_8.py` (8 execute/parse tests —
Back to Basics blocking every nonbasic land with no cap, Auriok Salvagers'
activated ability offering only the cheap artifact, Assassin's Trophy
destroying its target and opening the search choice for the *victim's*
controller rather than the caster, confirmed by checking `pending_choice
["player_id"]`, then answering it and confirming the land lands under the
victim's controller's control — plus `permanent_you_dont_control`'s own
legal-target scoping test). Full backend suite: 3,699 passed (+8 new), 238
skipped, 0 regressions (the same pre-existing flaky websocket test,
confirmed passing in isolation both before and after this batch).
`PARSER_VERSION` bumped 71 → 72 (measured cache-wide parser coverage:
11,509 → 11,533/34,811, still 33.1% at this precision).

## The seven "cEDH"-named saved decks/cubes: ninth pass (2026-08-11)

Continuation of `MEC-12`. Baseline re-measured at the start of this pass:
470 covered / 723 total across the seven decks. Closed two items, and
spent real investigation time on a third that turned out to need more
than a quick extension — writing that finding down rather than silently
re-deferring it a third time (this project's own "no half-implementations"
discipline):

- **Slip Out the Back** ("Put a +1/+1 counter on target creature. **It**
  phases out.") — `PhaseOutEffect` had no previous-clause pronoun at all,
  unlike `GrantUntilEffect`/`TapEffect`/`ReturnToHandEffect`, which all
  already carry a `previous_subject` flag reading `GameContext.
  previous_targets` (`_apply_effects_partitioned`'s general per-resolution
  bookkeeping, populated automatically for *any* effect sequence — nothing
  card-specific needed on the counter-placement side). Added the same flag
  to `PhaseOutEffect`, plus one new parser row (`_PHASE_OUT_PREVIOUS_RE`,
  reusing the fight family's own `_PREVIOUS_SUBJECT` pronoun alternation:
  "it"/"that creature"/"the chosen creature"). Closes 8 cache-wide cards
  (Teferi's Veil, The Pandorica, King of the Oathbreakers among them).
- **Snapback / Pyrokinesis** (RULE 118.9: "You may exile a `<color>` card
  from your hand rather than pay this spell's mana cost.") — the pitch-cost
  family MEC-15 built two passes ago (`AbilitySpec.alt_cost`, `GameObject.
  alt_cast_cost`, `GameEngine.can_cast`/`cast_spell`'s `alt_cost=True`
  branch) had **no oracle-text handler at all** — Force of Will/Negation/
  Vigor/Daze, the only four cards exercising it, were each hand-authored
  individually in `ability_catalogue.py`, and every other card printing
  the identical clause stayed unclaimed. Added a segmenter special-case
  (`_ALT_COST_EXILE_HAND_COLOR_RE`, alongside the existing `additional_
  cost`/`free_cast_condition`/`strive_cost` standalone-line rows in the
  `allow_spell_effect` branch — this is a cast-cost-shaped clause, not a
  resolve-time effect, so it needs the same "recognized whole, produces no
  `EffectSpec`" treatment those get) producing `alt_cost={"exile_hand_
  card_color": <letter>}` directly. Reaches **14 cache-wide cards** on the
  clause alone (Bounty of the Hunt/Cave-In/Force of Despair/Force of Rage/
  Force of Virtue/Misdirection/Reverent Mantra/Scars of the Veteran/Unmask/
  Vine Dryad joining the six already-shipped Force-of-Will-shaped cards) —
  Snapback and Pyrokinesis are the two that also had every other clause
  already covered, so they're the two that flip fully `MODELED`; the rest
  still have an unrelated second clause open (Bounty of the Hunt's counter-
  distribution, Cave-In's mass damage, Reverent Mantra's mass protection
  grant, …). Deliberately scoped to the `allow_spell_effect` (instant/
  sorcery) branch only — Vine Dryad prints the identical clause on a
  *creature*, which reaches a structurally different segmenter branch with
  no equivalent "standalone cast-cost line" special case; left unclaimed
  rather than duplicating the branch for a single off-pool card.
- **Grafdigger's Cage / Weathered Runestone** — investigated further
  rather than re-deferred verbatim. `RulesEngine._move_to_graveyard`'s own
  docstring calls itself "the one choke point every graveyard-bound move
  funnels through regardless of cause," which is what made Lurrus's own
  "if a spell cast this way would be put into a graveyard, exile it
  instead" redirect (`GraveyardCastPermissionEffect.exile_if_would_be_put_
  into_graveyard`) a single-site fix. Checking whether "if a card **would
  be put into a graveyard from anywhere**, exile it instead" (Rest in
  Peace/Leyline of the Void — a different, more general card than either
  of this pool's own two, but the same missing primitive shape) could
  reuse that exact choke point found it can't: `mill()` and `discard()`
  (`game/rules/draw_discard_mixin.py`) each move a card to a graveyard via
  their own direct `obj.zone = Zone.GRAVEYARD; player.graveyard.append
  (obj)`, never calling `_move_to_graveyard` at all. A genuinely general
  "any card, any zone, any cause" redirect needs the same replacement
  check added at each of those sites too (and confirming no other bypass
  exists — a resolving instant/sorcery's own move to its owner's graveyard
  wasn't checked either), which is real, multi-site surgery across the
  zone-transition call sites, not a extension of the existing hook.
  Recorded in `BACKLOG.md` rather than attempted rushed or silently
  re-deferred with the same wording a third time.

New tests: `tests/test_alt_cast_cost_family.py` gained 4 (parser-vs-hand-
authored verdict check for all three newly-closed cards, plus one
`can_cast`/exile-execute test each for Snapback/Pyrokinesis/Unmask,
mirroring the file's own existing Force of Vigor pattern — Unmask's own
test needed `current_step = "main1"` since, unlike the four Instants
already in this file, it's the first Sorcery-speed member); `tests/
test_phasing.py` gained 1 (Slip Out the Back's real cached card, cast end
to end via `resolve_until_stable`, confirming the *same* creature both
received the counter and phased out). Full backend suite: 3,704 passed
(+4 new — Slip Out the Back's own suite already existed but gained a case;
the alt-cost family's count includes the Snapback/Pyrokinesis/Unmask
tests), 238 skipped, 0 regressions (the same pre-existing flaky websocket
test, plus one incidentally-flaky Planechase test caught mid-batch that
reproduced only inside a full-suite run and passed standalone every time —
confirmed unrelated to this batch's changes, not touched).
`PARSER_VERSION` bumped 72 → 73 (measured cache-wide parser coverage:
11,533 → 11,537/34,811, still 33.1% at this precision).

## The seven "cEDH"-named saved decks/cubes: tenth pass (2026-08-11)

Continuation of `MEC-12`, this time working the fourth pass's own
"broader gaps, needs real design" list rather than the pool directly —
**devotion**, **phasing out an opponent's permanent as a spell effect**,
**RULE 702.26b extra-combat-phase grants**, and the **remaining
alternative-cost "pitch" shapes**, all four picked in one sitting since
each turned out to lean on the same discovery: the engine primitive each
one needed either already existed (built for an unrelated earlier card)
or was a small, well-contained gap in an existing mechanism, not a
ground-up build. Baseline re-measured at the start: 473/723 unique cards
across the seven decks (a light overlap with this pass's four mechanics,
since none of them are common cEDH-staple shapes); end state 478/722 (the
pool's own live-editing drift between runs, not a regression — see the
ticket's own note on why the denominator moves).

- **Devotion (RULE 700.6)** — `continuous.count_selector`'s own
  `devotion_to_<colour>` selector already existed (built for Thassa's
  Oracle), just single-colour and with no oracle-text route reaching it
  at all. Generalized the selector to a *set* of colours (Athreos/
  Karametra's "white and black"/"green and white") or one of the five
  two-colour wedge names (Devoted Abzan/Jeskai/Mardu/Sultai/Temur), summed
  via "does this mana symbol's colour set intersect the named colours"
  rather than single-letter membership (a hybrid pip still counts once
  even when it matches two named colours). Added `subgrammars.DEVOTION`/
  `devotion_selector` — one shared fragment every devotion handler embeds
  rather than re-deriving the colour/wedge grammar per family. RULE
  613.7f's "isn't a creature" gods (Purphoros/Heliod/Erebos/Karametra)
  needed **no new engine primitive**: `static_conditions.py`'s
  `control_count` condition already supports a `max` bound, and
  `type_change`'s existing `remove_types` static already threads
  `active_if` through `_selectors` — just a `_STATIC_CONDITION_RES` row
  for "your devotion to `<X>` is less than `<n>`" and an unconditional
  `_NOT_A_CREATURE_RE` for the inner "~ isn't a creature." clause
  `_conditional_static_specs` wraps. The amount-scaled family (pump/
  damage/lose_life/gain_life/create_token) all already had
  `amount_from_count_selector`/`count_selector` params (Craterhoof/
  Dockside/Frantic Firebolt-shaped) — only `DealDamageEffect._apply_
  selector` (the *mass* "to each opponent" path) had never actually read
  `amount_from_count_selector`, a latent gap `_amount_for`'s single-target
  path had masked until Fanatic of Mogis exercised mass+dynamic-amount
  together for the first time. `PumpEffect` gained a signed
  `amount_from_count_selector_negative` flag for "-X/-X" (Blight-Breath
  Catoblepas — the param had only ever been read as "+X/+X" before). RULE
  119's "drain" idiom ("`<player(s)>` lose[s] X life. You gain life equal
  to the life lost this way.", Gray Merchant of Asphodel and 15+ other
  cache cards sharing the exact trailing sentence) needed a genuinely new
  primitive: `GameContext.life_lost_this_way`, a per-resolution
  accumulator threaded through `_apply_effects_partitioned`'s existing
  save/reset/restore idiom (`previous_targets`/`created_objects`'s own
  pattern, including `resume_deferred_effects`) and incremented by
  `GameContext.lose_life`'s facade off the *actual* (post-replacement)
  life delta, read by `GainLifeEffect(count_selector="life_lost_this_
  way")`. Also widened `_lose_life_selector` from `NUMBER` to `COUNT_X`
  (Exsanguinate's "loses X life" — the `"x"` sentinel already threads
  through `RulesEngine._substitute_x` for free since `LoseLifeEffect.
  amount` is a plain attribute that walk already covers), added "each
  other player" as a selector alias (Urborg Syphon-Mage), and a
  `creatures_you_control_of_type_<subtype>`-keyed row (Malakir
  Bloodwitch's "the number of Vampires you control"). New tests:
  `tests/test_mec_12_cedh_batch_10.py` (15 devotion cases — multicolour/
  wedge/hybrid selector math, the two static gods, pump ±, mass damage,
  token count, the drain family end-to-end with a real X spell).
- **Phasing out an opponent's permanent as a spell effect (RULE 702.26)**
  — `PhaseOutEffect` already accepted an arbitrary `target_kind` (nothing
  in the engine ever scoped it to "your own permanents"); the gap was
  purely parser-side. Added `PhaseOutEffect.self_target` (Blink Dog/
  Vaporous Djinn-shaped "~ phases out.", distinct from the pre-existing
  untargeted default — Robe of Stars' Equipment-hosted "equipped creature
  phases out") plus three parser rows (self/attached/target, the target
  row reusing the shared `TARGET` macro so an opponent-controlled
  permanent is exactly as legal a target as your own whenever the printed
  phrase says so). Closed 9 cache-wide cards (Blink Dog, Crystal Golem,
  Rainbow Efreet, Reality Ripple, Vodalian Illusionist, Haystack,
  Vanishing, Teferi's Honor Guard, Divine Smite's own phase-out half).
  New tests: 4 (self-phase-out via activated ability, targeting an
  opponent's permanent, an Aura's attached-host phase-out with the
  Aura itself confirmed *not* phasing along per RULE 702.26e).
- **RULE 702.26b extra-combat-phase grants** — genuinely unbuilt (the
  BACKLOG entry's own claim of an "already-shipped flat" primitive was
  stale; grepping `Done_Backend.md`/`game/effects.py` found nothing).
  `phases.default_turn_sequence`'s docstring had already anticipated the
  shape needed ("a fresh instance per call so callers can safely mutate a
  turn's sequence — e.g. add an extra combat phase — without affecting
  others"): `GameEngine.insert_additional_combat_phase` splices a fresh
  `GamePhase("combat", …)` (and, for World at War/Aggravated Assault's
  own "…followed by an additional main phase" wording, a fresh
  `postcombat_main` too) into `_turn_steps`, the same mutable per-turn
  step list `advance_step`'s cursor already walks — inserted right after
  the *next* upcoming `end_combat`, not the raw cursor position, so it
  doesn't reorder the combat still in progress. An effect can't reach
  `_turn_steps`/`_cursor` directly (only `GameContext`/`RulesEngine` are
  visible to it), so `ExtraCombatPhaseEffect` queues onto a new
  `GameState.pending_extra_combats` FIFO instead — the same "queue now,
  the turn loop drains it later" shape `extra_turns`/`TakeExtraTurnEffect`
  already use — drained by `advance_step` before running the next step.
  Two parser rows (`extra_combat_phase`/`extra_combat_and_main_phase`)
  closed Godo/Aurelia/Aggravated Assault outright; Godo's own "untap it
  and all Samurai you control" compound self+subtype-group untap needed
  one more small piece — `TapEffect.selector`'s whitelist widened to admit
  any `creatures_you_control_of_type_<subtype>` name (`continuous.
  group_selector_objects` already handled the selector itself generically,
  just never reached from `TapEffect`). Left open: Combat Celebrant's own
  Exert-gated trigger (Exert isn't modeled as a mechanic at all yet) and
  the ~20-card "intervening if" family (Karlach/Finest Hour/Genji
  Glove-shaped "whenever ~ attacks, **if it's the first combat phase of
  the turn**, …") — a different, unbuilt trigger-condition primitive, not
  an extra-combat gap. New tests: 4 (the splice mechanics directly,
  plus Aurelia attacking and confirmed reaching a second real
  declare_attackers step later in the same turn).
- **The remaining alternative-cost "pitch" shapes (RULE 118.9)** — three
  new `ActivationCost` fields (`return_to_hand_count` — Gush's "return two
  Islands", count-generalizing the existing singular `return_to_hand`;
  `sacrifice_filter` — Flare of Denial's "a nontoken blue creature", a
  `combat.matches_object_filter`-shaped dict, which gained a new
  `nontoken` key for the occasion; and reusing the already-existing
  `sacrifice`/`sacrifice_count` fields, previously activation-cost-only)
  wired into `GameEngine._can_pay_alt_cast_cost`/`_pay_alt_cast_cost`,
  plus a new `condition_query.free_cast_condition_holds` kind
  (`control_land_type` — Snuff Out's "if you control a Swamp, …", the
  single-player generalization of Submerge's own two-player board-state
  gate). Found and fixed a real latent bug on the way: `_matches_
  sacrifice_type`'s fallback for an unrecognized cost word was "any
  permanent matches" rather than a real subtype check — harmless while
  every printed `sacrifice` cost used one of the eight explicitly-handled
  main-type words, but silently wrong the instant a card named a bare
  subtype (exactly what "sacrifice a Mountain" needs); now falls through
  to `continuous.has_subtype` instead. Also found `_can_pay_alt_cast_
  cost`/`_pay_alt_cast_cost` never read `cost.mana` at all — `alt_cost`
  always routed through `RulesEngine.cast_without_paying`, which skips
  every mana cost including the alt cost's *own* (a real, different, RULE
  118.9-legal amount, not "free") — wired that in too, closing the plain
  "You may pay `<mana>` rather than pay this spell's mana cost." shape
  (the Bringer cycle) at the engine level, though the parser only reaches
  it for an instant/sorcery today (`gate.py`'s `_is_spell` scoping the
  whole `allow_spell_effect` standalone-line family to those two types —
  the Bringers are creatures, so their own printing needs a second,
  not-yet-built route to reach the same already-working mechanism).
  Closed Flare of Denial, Snuff Out, and Gush outright; Downhill Charge's
  own alt-cost half works identically (confirmed by the engine test) but
  the card stays UNMODELED on its unrelated "+X/+0, where X is the number
  of Mountains you control" pump clause — deliberately not chased, since
  "X is the number of `<noun phrase>` you control" turned out to be its
  own 400+-card family (`parser_probe.py blocked "where x is the number
  of"`), not a one-off. `parser/oracle/spec.py`'s `ALLOWED_ALT_COST_KEYS`/
  `ALLOWED_FREE_CAST_CONDITION_KEYS` whitelists (the security boundary)
  gained the five new keys plus their own structural validation. New
  tests: 10 (each shape's payability gate and end-to-end payment, plus
  the plain-mana shape exercised directly against `ActivationCost` since
  no cached card reaches it via the parser yet).

Full backend suite: 3,738 passed (+33 new across all four pieces above —
`tests/test_mec_12_cedh_batch_10.py`), 238 skipped, 0 regressions (the
same pre-existing flaky websocket test, confirmed passing in isolation).
`PARSER_VERSION` bumped 73 → 74 (measured cache-wide parser coverage:
11,537 → 11,582/34,811, 33.3%).

## Marchesa V4.2 (saved deck, fully playable) — 2026-08-10

User request: make the "Marchesa V4.2" saved deck (96 cards, commander
Marchesa, the Black Rose) fully playable, using the `hand-author-card`
skill handing over to `extend-parser` where a general handler would close
more than one card. Inventory (`inspect-db` skill + a direct
`parse_oracle`/`ability_catalogue.is_registered` scan, more reliable than
the coverage ledger for a specific decklist) found 21 of the 96 cards
UNMODELED. All 21 are closed; re-running the same scan at the end shows
zero remaining gaps.

### General parser handlers (most of the batch, by cards-unlocked)

- **"Destroy target X. It can't be regenerated."** — the single most
  repeated removal-spell tail in the whole cache. `segmenter.
  _NO_REGEN_SENTENCE_RE` retroactively flags whichever `destroy` spec the
  *previous* sentence produced with `can_be_regenerated=False`, then
  recurses into whatever comes after — the same "split, recurse before
  and after, verify what `before` produced" idiom every other capture in
  this batch reuses. Deliberately anchored so "…can't be regenerated
  **this turn**" (Orcish Healer/Carbonize-shaped — a genuinely different,
  free-standing prevent-regeneration effect) never matches. +40 cards on
  its own measurement pass (Terminate, Big Game Hunter, Putrefy, Execute,
  Pillage, Oxidize, Consume the Meek, …).
- **The "threaten" family** — "Gain control of target creature [with mana
  value N or less] until end of turn. Untap it/that creature. It gains
  haste until end of turn." `catalogue.handlers._gain_control_eot` claims
  the first sentence (`effects.GainControlUntilEndOfTurnEffect`, built
  for the hand-authored Zealous Conscripts, already bundles the control
  change/untap/haste grant into one atomic effect); the untap/haste tail
  is absorbed by a second `_NO_REGEN_SENTENCE_RE`-shaped capture
  (`_GAIN_CONTROL_HASTE_TAIL_RE`) rather than re-modeled as its own
  effect, since re-modeling it would double up RULE 115 targeting onto
  the same creature. `GainControlUntilEndOfTurnEffect` gained
  `max_mana_value` (Claim the Firstborn) and a `selector="all_creatures"`
  mass form (Insurrection's own "untap all creatures and gain control of
  them", its own dedicated whole-body handler, `_GAIN_CONTROL_ALL_RE`,
  since it's the only real card on that exact phrasing). +59 cards (Act
  of Treason, Act of Aggression, Claim the Firstborn, Bond of Passion,
  Conquering Manticore, Insurrection, …).
- **"a basic Island, Swamp, or Mountain card"** — `_SEARCH_CRITERIA`'s
  `basic`/`types` groups were mutually exclusive (`{"basic": True}` *or*
  `{"type": [...]}`, never both); widened to combine freely, since "basic
  land" bare still collapses to the old `{"basic": True}` shape (dropping
  the now-redundant `type: "land"`, matching every pre-existing test's
  exact expected dict). Closes the whole Panorama/Landscape/Monument
  tri-land fetch-land cycles — Maestros Theater's own cycle (Streets of
  New Capenna) additionally needed **"Sacrifice it. When you do,
  `<effect>`."** collapsed to a plain sequence
  (`_SACRIFICE_THEN_WHEN_YOU_DO_RE`) — RULE 603.3's "when you do" only
  fires *if* the antecedent happened, which for an unconditional
  "Sacrifice it." (no "may") is a certainty, so the two clauses safely
  collapse to one list with no interactive branch. Deliberately **not** a
  general "you may `<action>`. When you do, `<effect>`." handler — that's
  a real, much bigger family (~200 cache hits, its own genuine
  optional-then-branch primitive) left for a future batch; this only
  matches when the clause immediately before "When you do," is exactly a
  bare self-sacrifice, so it can never misfire onto one of those. +94
  cards combined across both fixes.
- **Mass edicts** — "each player/opponent sacrifices `<n>` `<type>` of
  their choice" (`_sacrifice_edict`, closing Accursed Marauder and (with
  Liliana below) Liliana, Dreadhorde General's own +1/-4). `what="nontoken_
  creature"` is new on `_matches_permanent_type` (all three near-duplicate
  copies — see bug list below).
- **"Whenever you/an opponent draws a card, `<effect>`."** — the
  Sheoldred/Underworld Dreams/Consecrated Sphinx trigger family,
  previously unrecognized despite `effect_binder`'s `DRAW`-event group
  scoping already being proven (Smothering Tithe's hand-authored entry).
  Purely a missing recognizer (`_DRAW_TRIGGER_PLAIN_RE`), mirroring
  `_CAST_SPELL_TRIGGER_PLAIN_RE` exactly. Paired with a new `lose_life`
  selector, `"event_player"` (the same "that player" idiom
  `DealDamageEffect.selector` already had, reused via the shared
  `_event_player` helper rather than reimplemented) for Sheoldred's own
  "they lose 2 life" half. +34 cards.
- **"sacrifice an artifact or creature"** additional cost — a new
  `additional_cost` sacrifice sentinel, `"artifact_or_creature"`, plumbed
  through `spec.py`'s whitelist and all three `_matches_*` copies. +16
  cards (Deadly Dispute, Costly Plunder, Artillerize, …).
- **"each creature deals N damage to its controller"** (Rakdos Charm's
  third mode) — a new `DealDamageEffect` selector,
  `"each_creature_controller"`, where the recipient varies per creature
  (N independent hits) rather than one amount fanned to a fixed group.

Net measured effect of the parser batch: **coverage 31.83% → 32.22%
(11,081 → 11,215 / 34,811)**, +134 cards, **0 regressions** (`parser_probe.py
diff` after every single change).

### Hand-authored (`game/ability_catalogue.py`)

- **Liliana, Dreadhorde General** — +1/-4 reuse the mass-edict handler
  above verbatim (`author_card.py reuse` pasted as-is); only −9 ("each
  opponent chooses a permanent they control of each permanent type and
  sacrifices the rest") needed a hand spec, reframed as six independent
  `EffectSpec("sacrifice", {"selector": "each_opponent", "what": <type>,
  "count": "all_but_one"})` calls (one per RULE 300ish permanent type) —
  RULE 608.2's existing "suspend the rest when one effect opens a
  pending_choice" sequencing handles running them one at a time with no
  bespoke chaining. New `count="all_but_one"` sentinel on
  `RulesEngine.sacrifice`, resolved against the *live* candidate count at
  each call. Documented simplification: a multi-typed permanent kept by
  one type's cut can still be swept by a different type's own cut if a
  different permanent is kept for that type instead — real Liliana lets
  the same permanent count as the kept pick for two types at once;
  unobservable on an ordinary single-typed board.
- **Kiki-Jiki, Mirror Breaker** / **Puppeteer Clique** — share a new
  general primitive: "create/reanimate a permanent with haste, `[sacrifice/
  exile]` it at the beginning of the next end step." `CopyPermanentEffect`
  and `ReturnFromGraveyardEffect` both gained a `haste` param and now
  populate `GameContext.created_objects` (the RULE 608.2 "the tokens…"
  referent `CreateTokenEffect` already had), and `create_delayed_trigger`
  gained `capture="created_objects"`, mutating a freshly-registered
  `sacrifice_specific`/the existing `exile` effect's `.objects`/`.target`
  directly — the same "capture a resolve-time fact the delayed firing
  can't see anymore" idiom `target_mana_value` already used, just for an
  object reference instead of a magnitude. Kiki-Jiki's own "**non
  legendary** creature you control" restriction isn't modeled (no
  "nonlegendary" target kind exists yet — copying a legendary just runs
  into the ordinary legend-rule SBA instead of being refused as an
  illegal target).
- **Mikaeus, the Unhallowed** — the anthem clause is a new
  `group_selector_objects` branch, `"other_nonhuman_creatures_you_
  control"` (the negated-subtype sibling of the existing
  `nonlegendary_creatures_you_control`). "Whenever a Human deals damage
  to **you**, destroy it" needed two small additions: `effect_binder`'s
  new `condition["recipient_is_you"]` (the *existing*
  `condition["recipient"]` only ever matches a **permanent** recipient's
  controller — `RulesEngine.deal_damage` stamps `target_controller_id` as
  `None` for a player target, so it can never match "to you" directly),
  and `DestroyEffect`'s new `target_from_trigger_event="source_id"` to
  destroy the Human that actually fired the trigger (a group-subject
  trigger has no single chosen creature the way a self-subject trigger's
  implicit "it" would).
- **Spark Double** — `EnterAsCopyReplacement` gained
  `extra_counter_if_creature`/`extra_counter_if_planeswalker` (applied
  post-copy, once the resulting permanent's real type is known), and
  `targeting.py` gained `creature_or_planeswalker_you_control` (the
  controller-scoped sibling of the existing bare union kind). "…and it
  isn't legendary" isn't modeled — no "strip a supertype" primitive
  exists on the copy mechanism yet.
- **Danny Pink** — `grant_triggered_ability` (the same mechanism the
  hand-authored Dionus, Elvish Archdruid uses for its own per-creature
  "once each turn" grant) watching each creature's own `EventType.COUNTER`
  firing. Exposed the `COUNTER`-event gap in both "which event field names
  the firing object" tables (see bug list).
- **Arcane Denial** — the second sentence ("You draw a card at the
  beginning of the next turn's upkeep.") is exactly what the parser
  already claimed on its own, pasted as-is; only "Its controller may draw
  up to two cards…" needed a hand spec —
  `create_delayed_trigger`'s new `capture="target_controller"` (reads the
  *countered spell's* controller off the resolving target, since the
  delayed draw belongs to them, not this ability's caster) directly
  mutates the constructed inner `draw` effect's `.player`. "Up to two"
  is modeled as an unconditional draw of 2 (declining is a real but
  exceedingly rare choice with no delayed-trigger chooser to offer it).
- **Black Market Connections** — a `STEP_BEGIN` main-phase trigger
  (`filter: {"step": "main1"}`, `phase_relation: "you"`) wrapping the
  exact `modes={"choose": 1, "at_least": True, "options": [...]}` shape
  Farewell's own hand-authored "choose one or more" spell already uses —
  no new modal machinery needed, just the trigger wrapper around it.
- **Agatha's Soul Cauldron** — deliberately partial: only the activated
  ability ("{T}: Exile target card from a graveyard… put a +1/+1 counter
  on target creature you control", counter placement made unconditional
  rather than gated on the exiled card's type) is modeled. The other two
  clauses — an "any color, purpose-restricted" mana-spend permission, and
  a dynamic "borrow every activated ability of every card exiled with
  this source" grant onto counter-bearing creatures — are real,
  substantial, unbuilt primitives, left as an open, documented gap rather
  than silently modeled or forced into an unrelated shape.
- **Mutiny** — the one-sided-fight shape (`DamageEqualToPowerEffect`,
  built for Rabid Bite) with *both* sides independently targeted
  (`extra_target_specs`, `creature_you_dont_control` for each) — the
  RAW-printed "same specific opponent" constraint on the second target
  isn't tracked (no such targeting relation exists; coincides by
  construction in any 2-player game).

### Five dormant engine bugs found and fixed (none previously exercised)

1. **`SacrificeEffect`'s `each_player`/`each_opponent` selector** looped
   every matching player synchronously in one `apply()` call — fine for
   the pre-existing `each_opponent` uses (Professor Onyx's `greatest_
   power` auto-pick, or a mass "sacrifice everything" force-take, neither
   ever opens a real chooser), but the moment 2+ players simultaneously
   need a genuine interactive pick (Accursed Marauder/Liliana −4 with
   both players over the count), the second player's `request_choose_
   objects` call silently overwrote the first's still-unanswered
   `pending_choice` — one player's sacrifice was simply skipped forever.
   Fixed by sequencing through `GameState.deferred_effects`
   (`SacrificeEffect._sacrifice_each_in_order`, the same RULE 608.2
   "suspend the rest when one effect opens a pending_choice" idiom
   `_apply_effects_partitioned` already used for sibling *effects*, one
   level down for remaining *players* within one effect).
2. **`_matches_permanent_type`'s three near-duplicate copies**
   (`misc_mixin.py`/`damage_death_mixin.py`/`rules_engine.py`, kept
   separate per the mixin-split architecture to avoid import cycles) had
   no `"planeswalker"`/`"battle"` branch — either word silently fell
   through to `return True` (matches *any* permanent), discovered when
   Liliana's −9 sacrificed nearly an opponent's entire board because its
   "battle"/"planeswalker" passes matched everything, not nothing. All
   three now handle both, plus the `"nontoken_creature"`/`"artifact_or_
   creature"` words this batch's other primitives needed.
3. **`DrawCardEffect`** read `targets[0]` whenever its own `self.player`
   was unset and *any* `targets` list was non-empty — never checking
   whether it had declared a `target_spec` of its own first, unlike
   `GainLifeEffect`/`LoseLifeEffect`'s existing guard against exactly this
   ("Destroy target creature. Draw a card."-shaped resolutions sharing one
   `targets` list). Surfaced by Arcane Denial's own delayed-trigger
   `draw`, which inherited the arming resolution's `[countered_spell]`
   target and tried to hand it to `RulesEngine.draw` as a player. Same
   `target_spec is not None` guard added.
4. **`resolve_trigger_target_choice`'s own `answer` param** expects one
   scalar id — not a caller bug in the engine, but the shape of the
   *fifth* bug's discovery: this batch's own test scripts double-checked
   assumptions from documented method signatures rather than working
   backwards from silent-no-op behaviour, and the interactive-choice
   plumbing is otherwise sound end to end (Kiki-Jiki, Puppeteer Clique,
   Spark Double, Liliana −9, Black Market Connections all round-trip a
   real `pending_choice` correctly).
5. **`COUNTER` missing from both "which event field names the firing
   object" tables** — `effect_binder._SUBJECT_EVENT_KEYS` (parser-facing
   self/group-subject triggers) and `continuous._GRANTED_EVENT_KEYS`
   (layer-6 granted-ability per-object scoping) both defaulted to
   `instance_id` for any event not explicitly listed; `RulesEngine.
   add_counters`'s own `COUNTER` event actually names its subject
   `target_id`. No prior card had a self-subject or granted `COUNTER`
   trigger, so this was silently unreachable — Danny Pink's grant fired
   for *no* creature at all until both tables got a `"COUNTER":
   "target_id"` row.

Full backend suite: 3,568 passed (+0 net — no new dedicated test file this
batch; every primitive was instead verified against a real `GameEngine`
via `engine_bench.py`-style scripts, end to end, per card), 238 skipped,
0 regressions (the one pre-existing flaky websocket test, confirmed
passing in isolation, unrelated to any change here). `PARSER_VERSION`
bumped 64 → 65.

**Left open, tracked for a future batch** (none block Marchesa V4.2 —
recorded so the next session doesn't have to re-derive them):
- The "you may `<action>`. When you do, `<effect>`." optional-antecedent
  family (RULE 603.3's genuine sub-trigger) — ~200 cache hits, the single
  biggest template blocker found this batch. Needs a real "did the
  optional action happen" interactive gate; this batch's own "when you
  do" handling deliberately only covers the unconditional/mandatory-
  antecedent case and cannot be widened to this family without it.
- "Becomes the target of a spell/ability" as a real `EventType` — Ward is
  checked directly at cast-time today, not through the event bus, so no
  general "X becomes a target" trigger exists. Blocks Goldspan Dragon's
  own "attacks **or becomes the target of a spell**" half (modeled as
  "attacks" only this batch) and Tectonic Giant (2 cards total).
  Goldspan's other simplification — Treasures keep their default 1-mana
  sacrifice ability rather than the printed "add two mana of any one
  color" upgrade — is a separate gap: `grant_mana_ability`'s granted
  options are always a repeatable tap-only ability, with no way to
  express a *replacement* sacrifice-cost one.
- The RULE 601.2f "Expertise" cycle template ("you may cast a spell with
  mana value N or less from your hand without paying its mana cost") —
  8 real cards (Kari Zev's/Sram's/Yahenni's/Baral's/Rishkar's Expertise,
  Electrodominance, Epistolary Librarian, Coveted Prize). Kari Zev's
  Expertise ships this batch with only its threaten half; the free-cast
  half needs a genuinely new interactive "which hand card, if any" choice
  opening a temporary free-cast window.
- Agatha's Soul Cauldron's mana-spend-restriction-lift and dynamic
  ability-borrowing clauses (see above) — both real, both substantial,
  neither built.

**MEC-22 · Graveyard-sourced statics: the Anger cycle's other four**
(2026-08-10, same day as the batch above). Anger's own build left its four
siblings deliberately unregistered ("none were in the deck that prompted
Anger's own build") — this closed that gap directly rather than letting it
roll to a second deferral. All four are the identical `"from_graveyard":
True` shape `_anger` already established, just the granted keyword/land
type swapped: Brawn (trample/Forest), Filth (swampwalk/Swamp), Valor
(first strike/Plains), Wonder (flying/Island) — each a `grant_keyword`
static with an `active_if` `control_count` gate on
`lands_you_control_of_type_<x>`, exactly Anger's own params shape. A
fifth card from the same real Incarnation/Portal cycle, Riftstone Portal,
is the one structural variant: it grants a **mana ability**
(`grant_mana_ability`, `affects="lands_you_control"`, `mana=[{"G": 1},
{"W": 1}]`) rather than a keyword, and has no board-state gate at all
(unconditional once in the graveyard) — same `"from_graveyard": True`
marker, since `_battlefield_static_abilities`'s graveyard scan checks
only `isinstance(ab, StaticAbility)` and the marker, not which kind of
static it is. None of the five cards' own printed keyword/mana ability
(Brawn's Trample, Riftstone Portal's own "{T}: Add {C}.") needed an
`AbilitySpec` — those are read directly off `Card.keywords`/the printed
mana-ability text by `combat.py`/`continuous.py`/`mana_abilities.py`,
independent of the catalogue, the same reason Anger's own entry never
declared a keyword for itself. Verified end to end against a real
`GameEngine` per card (graveyard placement + the relevant basic land →
`continuous.recompute` → the keyword/mana option appears; removing the
land, or leaving the graveyard, removes it again) rather than a dedicated
test file — no new engine behaviour, same idiom Anger's own closure used.
Full suite: 3,567 passed, 238 skipped, 1 pre-existing flaky websocket
test (passes in isolation, unrelated). No `PARSER_VERSION` bump — these
are catalogue registrations, not parser-classification changes, and
`coverage_db.content_hash` already folds `is_registered()` into its key
for exactly this case (`services/coverage_db.py`'s own doc comment).
Coverage: 11,215 → 11,220 / 34,811 (32.2%, unchanged at this precision).

## Vivi B4 (saved deck, fully playable) — 2026-08-10

Made the "Vivi B4" saved deck (a 99-card storm-shell Commander deck, commander
Vivi Ornitier) fully playable — 18 of its 99 unique cards were `UNMODELED`;
all 18 closed (11 via general parser handlers, 7 hand-authored), plus one
card (Hadoken) that resolved for free once identified as a flavor-name
printing of an already-`MODELED` Lightning Bolt, never a real gap. Explicitly
used the `hand-author-card` skill handing over to `extend-parser` whenever a
general handler would close more cards than a one-off — several of the 11
parser wins turned out to be the single biggest templates found to date,
well past the Marchesa V4.2 batch's own headline items. Coverage 32.23% →
32.6% (11,220 → 11,365/34,811), `PARSER_VERSION` 65 → 66. Full suite: 3,568
passed, 238 skipped throughout (one pre-existing flaky websocket test seen
intermittently, confirmed unrelated — passes in isolation every time).

### Parser handlers (11 templates, cache-wide side effects far larger than the deck itself)

**`look_top_select`** (`RulesEngine.look_top_select`/`LookTopSelectEffect`,
`search_mixin.py`) — "Look at the top N cards of your library. Put M of them
into your hand and the rest `<destination>`." (Anticipate/Dig Through Time/
Diabolic Vision/Ancestral Memories-shaped, closing **Stock Up** — 38 cards on
first measurement, since risen past 40 as later handlers in this same batch
unblocked siblings). The fixed-selection-count sibling of `scry`/`surveil`'s
per-card away/stay decision (`_LOOK_TOP_KINDS`): there the count going away
is the player's own per-card choice, here the count going to hand is fixed
by the card text, so the shape is instead a two-phase decision — "pick
exactly M of these for hand", then (only when the card says "in any order")
order what's left before it goes to `rest_destination`
(`"library_bottom"`/`"library_top"`/`"graveyard"`). A `"random"` order
shuffles with no choice; `"graveyard"` is never ordered either way (RULE
701.31b's own precedent — a surveil/mill pile is never ordered). The
segmenter recognition (`_LOOK_TOP_SELECT_RE`) is a `parse_effect_body`-level
special case, not an ordinary `HANDLERS` row: "Look at the top N…" and "Put M
of them…" are two sentences that are one indivisible instruction (neither
alone means anything), so — same idiom `_NO_REGEN_SENTENCE_RE` established —
it's checked on the whole span *before* the ordinary connector-split loop
would otherwise shatter it into two unmatchable halves, with an optional
trailing sentence (Bitter Revelation's "You lose 2 life.") recursed into via
its own `after` group. Deliberately doesn't handle a *leading* clause before
"look at the top…" (Creative Outburst's "~ deals 5 damage… Look at…") — the
connector loop splits that off before the special case ever sees both halves
together, a narrow, one-card, fail-closed gap rather than an oversight.

**Cast-spell trigger `subj` widening** (`segmenter.py`'s
`_CAST_SPELL_TRIGGER_RE`/`_CAST_SPELL_TRIGGER_NEG_RE`, closing **Bonus
Round**) — both rows previously matched only "whenever **you** cast…"; widened
to "whenever you/an opponent/a player casts…", reusing the untyped sibling's
(`_CAST_SPELL_TRIGGER_PLAIN_RE`) own proof that the "an opponent"/"a player"
subjects need no new engine primitive (`effect_binder`'s existing
group/controller scoping over `SPELL_CAST`). A new shared helper,
`_cast_spell_trigger_condition(subj)`, centralizes the three-way
`{"subject": …}` mapping so the now five rows sharing it (`_RE`, `_NEG_RE`,
`_PLAIN_RE`, `_MV_RE`, `_DRAW_TRIGGER_PLAIN_RE`) stay in one place instead of
drifting. +51 cards measured via `parser_probe.py diff` (well under the
naive ~420 SOLO estimate `blocked` gave both widened rows combined — most of
that gap turned out to need a *second* still-unclaimed clause of their own,
the same "SOLO is an upper bound" lesson the Marchesa batch already
documented; not chased further, in-scope for a future batch). "That player
copies it and may choose new targets for the copy" (Bonus Round's own
trigger *body*, once its condition was reachable) is a new one-shot handler,
`trigger_copy_spell` — RULE 603.1's "it" names the *firing SPELL_CAST
event's own object*, not a RULE 115 target, so `CopySpellEffect` gained
`spell_from_trigger_event`/`controller_from_trigger_event` params (find the
object via `context.state.find_object(event.get(field))`, same "resolve off
the firing event" idiom `DestroyEffect.target_from_trigger_event` already
established) alongside its existing targeted mode. "May choose new targets"
stays the same accepted simplification the class's docstring already
documents for every other consumer (Reiterate/Dualcaster Mage-shaped): the
copy keeps the original's target.

**Delirium** (RULE 702.137, closing **Dragon's Rage Channeler** + 3 more
SOLO siblings) — `normalize._strip_ability_words` gained `"delirium"`
alongside `landfall|constellation|battalion|enrage` (the label itself
carries no rules meaning, RULE 207.2c, so stripping it and letting the bare
"as long as…" clause fall through the existing RULE 613.6 machinery is
correct); a new `static_conditions.py` kind, `card_types_in_graveyard_at_least`
(distinct printed card types among graveyard cards, explicitly excluding the
synthetic `"permanent"` marker `GameObject.type_words` always includes,
since that's not a real card type Delirium's own count should see). Its own
compound anthem shape — "~ gets +N/+N, has `<keyword>`, **and attacks each
combat if able**" — needed `_SELF_ANTHEM_RE` widened for an Oxford-comma
third list item (previously only "~ gets +N/+N and has `<keyword>`"'s single
`and`-joined pair): "attacks each combat if able" turned out to already be
the synthetic flag keyword `"attacks_if_able"` through the exact same
`grant_keyword` machinery "has flying" uses (`_ATTACKS_IF_ABLE_RE` proved
this standalone already) — no new spec shape, just one more keyword folded
into the same list.

**`return_to_library`** (`RulesEngine.return_to_library`/
`ReturnToLibraryEffect`, closing **10 cards** — Time Ebb/Griptide/Roil
Spout/Vedalken Dismisser among them) — "put target creature on top/the
bottom of its owner's library" (RULE 701.3's "put"), `ReturnToHandEffect`'s
library-destination sibling, same "move to another zone, from wherever it
is" shape `return_to_hand`/`exile` use. RULE 903.9b's commander redirect
applies here exactly as it does for hand, which surfaced a real (if
cosmetic) latent bug fixed on the way: `_commander_zone_choice`'s German
prompt hardcoded "aus dem `<zone>`"/"Im `<zone>` bleiben" keyed only on
`zone != Zone.HAND`, silently mis-declining Hand's own feminine article
("Im Hand bleiben" instead of "In der Hand bleiben") since the check was
never really about gender, just a HAND-shaped special case. Replaced with a
proper `_COMMANDER_ZONE_FEMININE` set (Hand, Bibliothek) the new Library
label joins correctly. **`ReturnToHandEffect`** also gained `selector`/
`filter` (RULE 601.2c mass "return all X" support, `DestroyEffect`'s own
`_MASS_DESTROY_SELECTORS`/`_mass_selector_objects` shared verbatim, plus a
new `"all_nonland_permanents"` selector) for **Displacement Wave**'s "return
all nonland permanents with mana value X or less to their owners' hands" —
the `"x"` filter sentinel needs no new substitution code, since
`RulesEngine._substitute_x` already walks any effect's `filter` dict
attribute generically by name, not by type.

**Submerge's free-cast condition** — "If an opponent controls a Forest and
you control an Island, you may cast this spell without paying its mana
cost." A new named boolean key,
`opponent_controls_forest_and_you_control_island`, joining
`AbilitySpec.free_cast_condition`'s existing whitelist
(`control_commander`/`not_your_turn`/`your_turn`/
`opponent_spells_cast_this_turn_at_least`) — a fixed compound condition
rather than a generic "controls type X and type Y" combinator, matching
`control_commander`'s own "one named condition, not a general vocabulary"
precedent (no other card in the cache prints this exact combination).
Evaluated live off the board in `condition_query.py`, same "check it fresh
each time" shape as every sibling key.

**Mistrise Village** — "The next spell you cast this turn can't be
countered." `arm_spell_watcher`'s existing "when you next cast a spell this
turn, `<effect>`" mechanism (built for Dual Strike's "…copy it") reused with
a new payload, `MarkCantBeCounteredEffect` — appends a
`CantBeCounteredEffect` marker onto the *next-cast* spell's own
`GameObject.spell_effects` once the watcher fires, the resolve-time
counterpart to that marker class's own bind-time use.
`RulesEngine._is_cant_be_countered`'s existing scan finds it with no new
consumer-side code.

**`grant_graveyard_cast_permission_this_turn` — second card** (closing
**Past in Flames**) — "Each instant and sorcery card in your graveyard gains
flashback until end of turn. The flashback cost is equal to its mana cost."
The primitive already existed (built for Backdraft Hellkite), just never had
an oracle-text recognizer — a clean instance of the project's own "sweep for
what a primitive should also close" discipline, since `blocked` showed 11
SOLO cards on this exact clause family (Recoup/Snapcaster Mage/Slickshot
Lockpicker among the *targeted*-singular siblings, deliberately left for a
future batch — see Notable gaps below).

**`LookAtCardsEffect`** (closing **Mishra's Bauble** + **Urza's Bauble**) —
"Look at the top card of target player's library."/"Look at a card at
random in target player's hand." A genuine RULE 115 target (hexproof still
matters) with no other game-state consequence: this engine has no reason to
hide a peeked card from the querying player (a solo/goldfish board already
shows every zone to its one real player; a bot never reads hidden
information regardless), so there's nothing left for "look" to actually
*do* — kept as its own effect rather than dropped to an empty `effects`
list specifically so the RULE 115 target requirement survives.

**Vexing Bauble** — "Whenever a player casts a spell, if no mana was spent
to cast it, counter that spell." A new `effect_binder.py` trigger predicate,
`spell_no_mana_spent` (reads `SPELL_CAST`'s existing `mana_spent` field,
already zero for any free-cast/alt-cost spell — `RulesEngine.cast_spell`'s
own free/alt-cost branches never bump it), and `CounterSpellEffect` gained
`target_from_trigger_event` (the same "resolve off the firing event" idiom
as `DestroyEffect`'s own — "that spell" is the trigger's object, not a RULE
115 target). Verified end to end: a real-mana Lightning Bolt resolves
untouched, a `cast_without_paying`-cast Ancestral Recall gets countered.

**`pump_up_to_two`** (closing **Opera Love Song**'s second mode + 19 more
SOLO cards, the single biggest pump template found in the whole cache) — "Up
to two target creatures each get +N/+N [and gain `<keywords>`] until end of
turn." (Dauntless Onslaught-shaped) / "One or two target creatures…" (Opera
Love Song's own phrasing) both fold to `PumpEffect`'s existing RULE 115.1a
"up to N" idiom (`count=2, optional=True`) — no new engine primitive, purely
the missing recognizer. **Documented simplification**: "one or two" (a real
minimum of one) is modeled as fully optional like "up to two" (0–2) — a
card offering this is always worth taking, so declining below the printed
minimum isn't a choice any player would make differently in practice.

### Hand-authored (7 cards)

**Chain of Vapor** — "Return target nonland permanent to its owner's hand.
Then that permanent's controller may sacrifice a land of their choice. If
the player does, they may copy this spell and may choose a new target for
that copy." `return_to_hand` for the bounce; `PayCostThenEffect` (RULE
118.3's "may pay `<cost>`. If you do, `<effect>`.") for the land sacrifice,
with a new `payer="previous_target_controller"` mode reading
`GameContext.previous_targets` — the *bounced permanent's* controller is
being asked, almost always an opponent, not this spell's own caster (no
existing `payer` value covered "whoever this same resolution's earlier
clause targeted"). **Documented simplification**: the "copy this spell"
tail is dropped rather than approximated. Built `CopySpellEffect.copy_self`
for it first (reads `self.source` directly, no target/trigger-event needed)
and confirmed by direct engine test that it **doesn't actually work** for
this card's real shape: `PayCostThenEffect`'s "if you do" branch only runs
once the player answers a `pending_choice`, by which point the *original*
Chain of Vapor has already finished resolving and left the stack for the
graveyard (RULE 608.2m) — `copy_spell`'s underlying `_stack_item_for` needs
the source to *still be on the stack*, which it no longer is. Rather than
ship a re-bounce approximation (which turns out to be mechanically wrong
too — the already-bounced permanent is sitting in hand, no longer a legal
"target nonland permanent" for a same-target copy to hit), the tail is
simply not modeled; sacrificing the land is still a real, correctly-costed
decision on its own. `copy_self` itself is kept — a real, correctly-scoped
primitive for a future *non-deferred* "copy this spell" card, just not this
one.

**Intuition** — "Search your library for three cards and reveal them.
Target opponent chooses one. Put that card into your hand and the rest into
your graveyard. Then shuffle." A new self-contained primitive,
`IntuitionEffect`/`RulesEngine.request_intuition` (`search_mixin.py`) — two
chained `pending_choice`s (`kind="intuition_search"` then
`"intuition_choose"`): the caster picks the three cards first, then a real
RULE 115 target (`TargetSpec(kind="opponent")`) — not the searcher — picks
one of them for the searcher's hand, the rest to the searcher's graveyard,
then shuffle. Not composed from `request_search`, whose single `destination`
has no way to express "hold these aside for a *second* player's pick."
Verified end to end (search phase picks all three, opponent's choice lands
in the searcher's hand, the other two in their graveyard).

**Ral, Monsoon Mage // Ral, Leyline Prodigy** — "Whenever you cast an
instant or sorcery spell during your turn, flip a coin. If you lose the
flip, ~ deals 1 damage to you. If you win the flip, you may exile ~. If you
do, return him to the battlefield transformed under his owner's control." A
new `CoinFlipEffect` (RULE 705.1) branching into `win_effects`/`lose_effects`
off `RulesEngine.coin_flip` — a reproducible RNG primitive that already
existed (`mana_counters_mixin.py`) but had **no consumer anywhere in the
codebase** until this card, a dormant primitive finally exercised. The loss
branch reuses `DealDamageEffect`'s existing `selector="controller"` (Mana
Vault's own "deals 1 damage to you" shape); the win branch reuses
`exile_return_transformed` (RULE 400.7/712.8, already built). "During your
turn" reuses `phase_relation="you"` — built for RULE 500.7 "at the
beginning of your `<step>`" triggers, but its predicate only ever checks
whose turn it currently is, gating a `SPELL_CAST` trigger exactly as well
with no changes needed. Verified over 30 real casts: life loss and the
transform both happen at roughly a 50/50 split, and the transform correctly
produces a genuine new "Ral, Leyline Prodigy" object on the battlefield.
**Documented simplification**: the win branch's "you may exile" is
unconditional, same accepted shape as every other undecided "may" in this
codebase.

**Talon Gates of Madara** — "When this land enters, up to one target
creature phases out. `{T}`: Add `{C}`. `{1}, {T}`: Add one mana of any
color. `{4}`: Put this card from your hand onto the battlefield." The ETB
trigger is a plain `PhaseOutEffect` (already existed); the two mana
abilities were already oracle-parsed. The last line needed a genuinely new
zone-of-activation primitive: `PutSelfOntoBattlefieldFromHandEffect` +
`ActivationCost.hand_zone` — `graveyard_zone`'s hand-zone sibling (PAR-10's
"Return this card from your graveyard to the battlefield" precedent, same
inference idiom in `effect_binder.bind_ability`: an ability whose effects
include this class gets `cost.hand_zone = True` stamped automatically, no
per-card wiring). Threaded through `can_activate`'s zone-legality branch and
`legal_actions_mixin.py`'s existing hand-zone-ability scan loop (which
already handled `discard_self`/Cycling — widened to `or hand_zone` rather
than duplicated). Doesn't consume the land-per-turn drop, since it's a
genuine activated ability, not RULE 305.1's "play a land" action. Verified:
tapping for `{C}`, activating the `{4}` ability from hand, and the land
correctly landing on the battlefield afterward all work.

**Urza's Saga** — the full 3-chapter Saga, the batch's largest single card.
Chapters I/II ("This Saga gains '`<ability>`.'") needed a new *lasting*
self-grant, `GrantSelfActivatedAbilityEffect` — RULE 714.2c's grant outlives
the one-shot chapter trigger that creates it, unlike the turn-scoped
`grant_graveyard_cast_permission_this_turn` shape it otherwise mirrors:
appends a real `grant_activated_ability`-shaped `StaticAbility`
(`affects="self"`) straight onto the Saga's own `static_effects`, permanent
(no `expires_turn`). Chapter II's Construct token needed its own self-
scaling "+1/+1 for each artifact you control" ability baked onto the
*created token itself* — a new `CreateTokenEffect.grant_self_anthem` param,
appending a real `anthem`-shaped `StaticAbility` (reusing its existing
`power_count`/`toughness_count` per-count scaling, `continuous.
_pt_mod_count`'s vocabulary) onto each token right after `create_token`
returns it. Chapter III is a plain `search`.

This surfaced a real, significant, **cache-wide** dormant engine bug on the
way: every "create an N/N `<color>` `<Subtype>` **artifact** creature
token" clause — a very common template (Construct/Thopter/Servo/Golem
tokens across dozens of cards) — silently produced a token typed as a bare
Creature, missing the Artifact card type entirely.
`services/token_database.py`'s `synthesize_token_card` derived `kind =
"Creature" if is_creature else "Artifact"` as a strict either/or, and all
three of the parser's independent "`<mid>` creature token" word-splitting
loops (`_xx_token_mid_params`/`_inline_create_token_params`/
`_create_named_legendary_token`, `catalogue/handlers.py`) already correctly
recognized "artifact" as a `_TOKEN_NOISE_WORDS` supertype marker — and then
just **discarded** it, never threading an `is_artifact` flag anywhere.
Found because it wasn't cosmetic here: Urza's Saga's Construct starts 0/0
and only survives via its own artifact-counting anthem counting *itself* —
with the type bug, the freshly-created token was invisible to its own
"artifacts you control" count, stayed 0/0, and got swept by RULE 704.5f's
zero-toughness state-based action the very next SBA pass, one step after
`create_token` had genuinely already returned a real object into
`state.battlefield`, which is what made this so non-obvious to trace (three
layers removed from the actual defect). Fixed at the root: `synthesize_
token_card` gained `is_artifact: bool`, combining "Artifact Creature"
instead of choosing one or the other; the three duplicated word-splitting
loops were consolidated into one shared `_split_token_mid_words` helper
(recognizing "artifact" and returning it as a third value) so a future
noise word only needs adding in one place, not independently drifting
across three near-identical copies — the same "duplicated per-mixin table"
lesson the Marchesa V4.2 batch already flagged, here found in the parser's
`catalogue/handlers.py` instead of `game/`'s mixins. `CreateTokenEffect`
gained the matching `is_artifact` param. Verified with and without other
artifacts on the board (0/0 base → 1/1 counting itself alone, 2/2 with one
more artifact in play) — a real, previously-silent gap now fixed
cache-wide, not just for this card.

### Left open, tracked for a future batch

- **Quicksilver Elemental** — "`{U}`: ~ gains all activated abilities of
  target creature until end of turn." needs a genuinely new "temporarily
  copy every one of a target's activated abilities onto self" primitive —
  no existing mechanism does this (the layer-6 `grant_activated_ability`
  static grants *one fixed printed ability* to an attached/self permanent;
  this needs the *whole, currently-live set* of a different object's
  abilities, snapshotted at resolve time). Deliberately not rushed at the
  end of this batch — filed as **MEC-23**.
- **The single-target "target instant or sorcery card in your graveyard
  gains flashback…" flashback-grant family** (Recoup/Snapcaster Mage/
  Slickshot Lockpicker/Sphinx of Forgotten Lore among ~10 real cards) —
  `grant_graveyard_cast_permission_this_turn`'s existing shape only grants
  *broadly* (every instant/sorcery in the graveyard); a single *named*
  card's flashback needs a per-object marker the primitive doesn't have.
  Filed as **MEC-24**.
- **Creative Outburst**'s own narrow gap in `look_top_select` (a *leading*
  clause before "Look at the top…" isn't absorbed by the segmenter special
  case) — one real card, documented inline in `segmenter.py`, not filed
  separately (too narrow to be worth its own ticket).

### Skill efficiency (continuing the running assessment from the Marchesa V4.2 batch)

Both skills held up well across a much larger single-session batch than
Marchesa's — `author_card.py reuse`/`scaffold` and `parser_probe.py diff`
remained the two most-reached-for commands, no change from that batch's
assessment. Two things worth adding:

- **The single biggest time sink this batch wasn't parsing or hand-authoring
  at all — it was *debugging a resolve-time engine primitive against the
  real stack/SBA loop*** (Urza's Saga's Construct token dying to RULE
  704.5f one SBA pass after `create_token` had already, genuinely,
  returned a real object). Neither skill's tooling caught this — `author_
  card.py` doesn't touch runtime behavior, and `parser_probe.py diff` only
  proves *parsing* didn't regress, not that a newly-wired effect actually
  survives a full resolve cycle. `engine_bench.py play`/`inspect` from the
  `game-engine` skill would have caught it faster than the ad hoc `python
  -c` scripts reached for here — worth defaulting to `engine_bench.py`
  first for any new *resolve-time* primitive (not just a parser-adjacent
  one), rather than reaching for it only after a manual test already
  looked broken.
- **A hand-authored `EffectSpec` dict silently missing one param is
  invisible until you actually resolve it.** Both Urza's Saga's `is_artifact`
  omission and an earlier `copy_self` dead-end in Chain of Vapor were only
  caught by direct engine testing, not by `is_registered()`/`specs_for()`
  static checks (which only prove a spec *parses into an effect*, not that
  the effect *does the right thing*). The hand-author-card guide's own
  checklist doesn't currently say "execute-test every new param you added
  this session, not just the card that motivated it" — worth adding, since
  both misses here were exactly that: a param built correctly in `effects.py`
  but not actually passed at the call site that needed it.

Coverage: 11,220 → 11,365 / 34,811 (32.23% → 32.6%), `PARSER_VERSION` 65 →
66.

## MEC-18/MEC-19 (2026-08-11)

Two tickets closed together, both RULE 603.1-adjacent trigger-family gaps
found the same way (a `parser_probe.py` scan turning up a repeated template
far bigger than the filing session had scoped it): MEC-18's RULE 603.5 "You
may `<action>`. When you do, `<effect>`." optional-antecedent family, and
MEC-19's RULE 115/601.2c "becomes the target of a spell/ability" as a real
`EventType`. Both tickets' own card-count estimates were wrong in the
direction `PARSER_LONG_TAIL.md` already warns about — MEC-18 filed as "~200
cache hits," MEC-19 as "2 cards found so far" — re-scoping each against the
live cache first (`parser_probe.py blocked`/a direct SQL sweep over raw
`oracle_text`) is what turned up the real shape of both.

### MEC-18 — no new engine primitive, a parser-recognition gap

`PayCostThenEffect`/`RulesEngine.request_pay_cost_then` (RULE 118.3) already
generalized "ask an interactive yes/no, pay `<cost>` (mana/sacrifice/
discard/life) if yes, resolve `<effects>`" behind one `_can_pay_player_cost`/
`_pay_player_cost` gate — Mana Vault's upkeep untap and Wandering Archaic's
tax already proved it. The gap was purely that its oracle-text recognition
covered only two hardcoded shapes: a bare mana cost paired with a fixed
"draw a card" (`_pay_cost_then_draw`), and `{E}` pips paired with an
arbitrary follow-up (`_pay_energy_then`). `catalogue.handlers.
_pay_cost_then_general` widens this to the whole vocabulary
`ActivationCost`/`costs.parse_activation_cost` already supports — a closed
whitelist of atomic antecedent shapes (`_MAY_COST_THEN_CLAUSE`: a mana cost,
"sacrifice a/another `<type>`", "discard a card"/"your hand"/"N cards", "pay
N life") rather than running the antecedent through `costs.py`'s lenient
substring search, which finds a cost fragment inside arbitrary text but
never confirms the fragment is the *whole* clause — a compound antecedent
("discard your hand and draw two cards") could otherwise have its unmatched
tail silently dropped. The follow-up is recursively parsed via
`parse_effect_body` and rejected if it carries a RULE 115 target
(`PayCostThenEffect`'s branch effects resolve off-stack, with no
target-gathering step of their own — the same restriction `_pay_energy_then`
already had).

The mana alternative deliberately excludes the `{E}` symbol:
`_can_pay_player_cost`/`_pay_player_cost` never charge
`ActivationCost.pay_energy` at all (that's `pay_energy_then`'s own,
separately-tried job), so letting `{E}` through here would have silently
made an energy antecedent free.

**A real bug found and fixed on the way, not just a coverage gap.** The
generic "you may " optionality stripper (`segmenter._peel_optional`, which
turns a trigger's outer "you may" into `AbilitySpec.optional` — a
*different*, whole-ability optionality than RULE 118.3's own embedded one)
runs before every trigger body reaches the handler table. It already had a
narrow guard (`_PAY_ENERGY_THEN_PEEL_GUARD_RE`) protecting the two old
hardcoded shapes from being stripped, but widening the handler without
widening the guard alongside it left every trigger-based card in the new
family broken: "whenever ~ deals combat damage to a player, you may discard
a card. if you do, draw a card." (Academy Raider) would peel to "discard a
card. if you do, draw a card." — losing the "you may" `pay_cost_then_
general` itself needs to recognize the clause as a whole. `_MAY_COST_THEN_
CLAUSE` is now a single shared constant both `catalogue.handlers.
_PAY_COST_THEN_GENERAL_RE` and `segmenter._PAY_ENERGY_THEN_PEEL_GUARD_RE`
build from, so the two can't drift apart again.

**A second, narrower bug found while chasing that fix.** The first version
of `_MAY_COST_THEN_CLAUSE` included bare self-sacrifice forms ("sacrifice
it"/"this `<type>`"/"~") — widening the peel guard to protect those too
broke 4 cards (Flaxen Intruder, Spare Dagger, Sunfire Torch, The Falcon,
Airship Restored) that had been correctly modeled through the *older*,
narrower `_SACRIFICE_THEN_WHEN_YOU_DO_RE` collapse (an unconditional
sequence — self-sacrifice can never fail once declared, so RULE 603.5's
antecedent is a certainty, letting that path allow a *targeted* follow-up
`pay_cost_then_general` can't). Fixed by narrowing `_MAY_COST_THEN_CLAUSE`'s
sacrifice alternative to typed sacrifice only ("sacrifice a/another
`<type>`") — a genuinely different case, since a *typed* sacrifice/discard/
life cost can really fail (no legal permanent of that type/no cards in
hand), which is exactly what the new interactive gate is for. Caught via
`parser_probe.py diff` against a true pre-change baseline (`git stash` on
just the two touched files) — 0 regressions in the shipped version.

89 real cache cards fully MODELED through the new general handler (verified
by checking each one's bound `pay_cost_then` spec directly, not just the
raw-text hit count) — Abandon Attachments/Academy Raider/Akki Ronin/Akoum
Firebird among them. `tests/test_mec18_optional_antecedent_family.py`
covers parse-level MODELED verdicts, the two regression guards above, and
execute tests (Abandon Attachments as a spell, Academy Raider as a
triggered ability — pay/decline/unpayable-with-an-empty-hand branches).

### MEC-19 — one real new event, a Ward-shaped effect adapter, and a much bigger family than filed

RULE 115/601.2c targeting had never reached the event bus at all — Ward
(RULE 702.21) was the only consumer, checked directly by
`RulesEngine.check_ward` right after a spell/activated-ability/triggered-
ability's targets are finalized (the one choke point all three call sites
already reach unconditionally). `EventType.BECOMES_TARGET` now fires once
per target from that same choke point (`_fire_becomes_target_events`,
folded into `check_ward` itself rather than a fourth sibling call, so a
future call site can't add one but forget the other) — carrying
`instance_id`/`target_controller_id` (RULE 603.1's ordinary default subject/
group keys, no `_SUBJECT_EVENT_KEYS` override needed), `is_player`, the
*targeting* spell/ability's own `controller_id`/`item_kind`
("spell"/"ability")/`stack_id`. Ward itself is completely unchanged — a
parallel consumer of the same moment, not a rewire.

Two `effect_binder` additions power the trigger grammar: `_GROUP_
CONTROLLER_EVENT_KEYS["BECOMES_TARGET"] = "target_controller_id"` (so "a
creature **you control** becomes the target…" scopes to the target, the
ordinary group-subject mechanism), and a new `caster_relation` predicate
("opponent"/"you", mirroring `phase_relation`'s shape) comparing the event's
`controller_id` (the *caster*) against the triggered ability's own source —
a third-party comparison neither the existing group-`controller` key (which
scopes the *acting* object) nor `phase_relation` (whose event carries no
controller at all) could express.

**The real size of this ticket only showed up once measured against the
live cache, not the "2 cards" the filing session estimated.** A raw SQL
sweep over `oracle_text` for "whenever … becomes the target of a[n] …" found
177 hits — but most of those are printed **Ward** with its reminder text
included in `oracle_text` (already `MODELED` via the keyword catalogue,
invisible in `normalize`'s output since reminder-text stripping removes it
before the parser ever sees it). Filtering to cards whose *normalized* text
still contains the sentence narrowed it to 87 real, non-reminder-text hits —
a whole un-keyworded cycle that prints Ward's exact RULE 702.21a outcome
("counter it unless that player pays `<cost>`") as ordinary card text
instead of the keyword, which the keyword catalogue can never reach.
`CounterUnlessPayEffect`/`counter_unless_pay` closes that cycle: a
deliberately thin adapter onto the existing `RulesEngine.resolve_ward_effect`
(found via `GameContext.trigger_event`'s own `stack_id`/`controller_id`),
reusing ward's exact "can they afford it? open a real pay-or-not choice
(the same `"ward"` `pending_choice` kind); if not, counter outright" flow
rather than a parallel implementation — the two are rules-identical from
that point on. `catalogue.handlers._counter_unless_pay` normalizes the
printed "pays"/"discards" to the imperative "pay"/"discard"
`costs.parse_activation_cost`'s regexes actually anchor on (the printed verb
would otherwise silently fail to match and the cost would resolve as free).

`segmenter._BECOMES_TARGET_TRIGGER_RE` recognizes the self/attached/group
subject grammar (mirroring `_DAMAGE_TRIGGER_RE`'s shape) plus this family's
own two qualifiers: `item_kind` ("of a spell"/"of a spell or ability"/"of an
ability", fed through the ordinary `"filter"` exact-match mechanism) and the
optional `caster_relation` scoping. A trailing "**for the first time each
turn**" (Angelic Cub/Heartfire Hero-shaped) sets `trigger["limit"]` directly
— RULE 603.2's existing `TriggeredAbility.once_per_turn`, previously only
reachable through a *trailing-sentence* marker
(`TRIGGER_ONCE_PER_TURN_MARKER`); here the qualifier is embedded in the
condition clause itself, so no marker round-trip is needed.

14 real cache cards are fully `MODELED` through the new mechanism end to end
(Battle Mammoth/Angelic Cub/Mossdog/Segmented Wurm/Reality Smasher among
them), plus the two ticket's own named cards, hand-authored directly:
**Goldspan Dragon** (a second `AbilitySpec` alongside its existing "attacks"
one — the same "one spec per compound-triggered event" idiom
`_SELF_MULTI_EVENT_RE`/Matoya, Archon Elder's "you scry or surveil" already
use, rather than a generalized "attacks or becomes the target of a spell"
parser grammar for what only 2-3 real cards print) and **Tectonic Giant**
(same idiom, plus `caster_relation: "opponent"` and a modal body — one mode
a plain `damage`/`each_opponent` selector, the other a documented
simplification: "exile the top two, **choose one of them**, until your next
turn you may play *that* card" is a genuinely different RULE 601.3b shape
from the already-shipped `ImpulsiveDrawEffect` — "exile N, *all* stay
playable" — that no primitive covers yet (7 real cache cards total, its own
small, real gap, orthogonal to this ticket and not built here); modeled
instead as `impulsive_draw` at `count=2`, strictly more generous than
print). Left open and split into its own ticket (**MEC-25**, unrelated to
targeting): Goldspan Dragon's granted Treasure ability still keeps the
default 1-mana tap ability rather than the real printed *replacement*
sacrifice-cost ability, since `grant_mana_ability` still can't express an
upgrade to an existing matching ability.

Many more real cards (Frost Titan, Diffusion Sliver, and others) now have
their `BECOMES_TARGET` clause correctly parsed and `MODELED` in isolation
but stay overall `UNMODELED` — blocked by a *different*, unrelated clause on
the same card (docs/09's fail-closed whole-card gate; verified directly,
e.g. Frost Titan's own "enters or attacks, tap target permanent… doesn't
untap during its controller's next untap step" is a separate, unbuilt
duration shape). Also deliberately out of scope, both real, distinct
grammars: the player-subject/compound "you or a permanent you control
becomes the target…" shape (Leovold, Rayne, Surrak, Unsettled Mariner,
Parnesse) and a group subject qualified by a *subtype* word rather than
`_GROUP_TYPE_WORDS`'s closed main-type list ("a Dragon you control becomes
the target…" — Thunderbreak Regent/Dragon's Disciple/Scalelord Reckoner).

`tests/test_mec19_becomes_target_family.py` covers the event firing itself,
both Goldspan Dragon trigger halves (including that its plain "of a spell"
clause fires off the controller's *own* spell too, unlike Tectonic Giant's
opponent-scoped one), Tectonic Giant's modal choice and its `caster_relation`
gate, `CounterUnlessPayEffect`'s three branches (open the choice and decline
→ countered, pay → resolves, unpayable → auto-countered with no choice
offered) via a synthetic `bind_ability`-built ability (no real un-keyworded
"counter unless pay" card is *itself* fully `MODELED` — every real one has
at least one other unclaimed clause), and parse-level coverage for Battle
Mammoth/Angelic Cub/Frost Titan (the last confirming the clause parses
correctly even though the whole card doesn't).

Coverage after both tickets: 11,471 / 34,811 (33.0%), `PARSER_VERSION` → 68
(the working tree's prior uncommitted state had already drifted through 66
and 67 from earlier, unrelated session work before this batch started —
68 is the first version number with no stale ledger rows, so this is a
genuinely fresh full re-measurement, not a delta cleanly attributable to
only these two tickets).

## User-reported bug: Mox Amber/Exotic Orchard/Fellwar Stone ignored board state (2026-08-11)

`game/mana_abilities.py`'s `_parse_clause` matched the bare substring "any
color" (`_ANY_COLOR_PHRASES`) before ever looking at what came after it, so
every *qualified* "add one mana of any color `<condition>`" clause fell
through to the unconditional 5-colour branch with the qualifying condition
silently discarded — Mox Amber ("...among legendary creatures and
planeswalkers you control"), Exotic Orchard/Fellwar Stone/Quirion Explorer/
Sylvok Explorer ("...that a land an opponent controls could produce"), and
Harvester Druid (the same, self-scoped) all behaved like an unconditional
5-colour Command Tower regardless of board state — never producing nothing
even with no qualifying permanent in play. Not previously tracked in
`BACKLOG.md`; found by a user playing a real goldfish game.

Fixed with two new `_parse_mana_ability_lines`-level regexes dispatched
before the generic `_ADD_CLAUSE_RE`/`_parse_clause` path (the same
standalone-dispatch shape `_COLORS_AMONG_PERMANENTS_RE`/Bloom Tender already
used) and two new `ManaAbility.color_selector` pairs, each a genuine menu
(the payer still picks one colour, unlike Bloom Tender's aggregate) built
fresh off the live board every call, same shape as `"imprinted_card_colors"`:

- `_LEGENDARY_AMONG_RE` → `"colors_of_legendary_creatures_planeswalkers_
  you_control"` (Mox Amber) / `"colors_of_legendary_permanents_you_control"`
  (Plaza of Heroes' own second mana ability, a strictly broader scope —
  found for free while sizing the regex against the cache, and picked up
  the same pass since the only difference is one filter check).
- `_LAND_COULD_PRODUCE_RE` → `"colors_lands_you_control_could_produce"`/
  `"colors_lands_opponents_control_could_produce"`, resolved by a new
  `_colors_a_land_could_produce` helper that reads a qualifying land's own
  *live* mana abilities (not its printed colour identity — a land's mana
  ability is what "could produce" means, RULE 605.1a) via `mana_abilities_
  for`. Two mutually-reflecting lands (an Exotic Orchard facing another
  Exotic Orchard) can't be allowed to ask each other the same question
  forever — `_LAND_REFLECTION_SELECTORS` short-circuits by checking a
  candidate land's own *unresolved* `parse_mana_abilities` output before
  ever calling the eager-resolving `mana_abilities_for` on it, since that
  function resolves every printed ability (including a reflecting one) as
  part of building its own return list — filtering the returned list
  afterward is too late, the recursive call has already happened by then.
  Deliberately doesn't cover Reflecting Pool/Naga Vitalist's "any **type**
  that a land you control could produce" (colourless-inclusive, a wider
  shape) — left for a future pass.

`tests/test_reflecting_lands_and_legendary_mox_family.py` covers both
selector families against the real cached cards: empty board → no options
(and `tap_for_mana` refuses to raise a `ValueError` rather than silently
succeeding), a qualifying permanent → the right board-dependent menu, an
opponent's/own-side's permanent correctly excluded per scope, Mox Amber's
narrower creature/planeswalker filter vs. Plaza of Heroes' broader
any-legendary-permanent one (Bolas's Citadel — legendary, black, neither a
creature nor a planeswalker — distinguishes the two), and the mutual-
reflection guard actually terminating.

## MEC-25/MEC-20/MEC-21 (2026-08-11)

Three tickets closed together, all found while chasing MEC-19's own
"cite or rule out an existing primitive" sweep — none needed a genuinely
novel mechanism from scratch; each was a real, named gap in an existing one.

### MEC-25 — `grant_mana_ability`'s upgrade shape

Goldspan Dragon's "Treasures you control have '{T}, Sacrifice this
artifact: Add two mana of any one color.'" needed two things the shipped
layer-6 mana grant (Tyvar Kell-shaped) never had: a non-``{T}``-only cost,
and *replacing* a matching printed ability rather than stacking a second
one alongside it. `grant_mana_ability`'s new ``cost`` param threads an
`ActivationCost`-shaped dict through `continuous._apply_layer_6_ability`'s
new ``mana_ability_cost`` branch onto a new `GameObject.
granted_mana_ability_upgrades` field (kept separate from the existing
tap-only `_granted_mana`/`granted_mana_options`, which every pre-existing
caller — Tyvar Kell — still uses unchanged). `mana_abilities.
mana_abilities_for` then drops any printed ability whose cost has the same
*shape* as an upgrade's (`_cost_shape` — `dataclasses.replace(cost,
raw="")` before comparing, so "Sacrifice this token" and "Sacrifice this
artifact" still count as the same shape despite differing wording) before
adding the upgraded one in its place. Goldspan Dragon's Treasures now keep
exactly one mana ability, at the real printed two-mana amount, with the
real sacrifice cost — verified by actually tapping one and checking both
the production and that it left the battlefield.

### MEC-21 — Agatha's Soul Cauldron's own two clauses, plus a real generalization

Both of this card's previously-unmodeled clauses shipped, plus the
generalization the user asked for explicitly: any future "exile with ~"
card (~185 cached cards print that shape) can now reuse the same tracking
rather than each needing its own bespoke linked-zone field.

**"Cards exiled with ~" — a genuinely reusable primitive.** `GameObject.
linked_exile_id` (the O-Ring shape) is a single slot, overwritten each
time — wrong for a repeatable "{T}: Exile target card from a graveyard."
ability that should *accumulate* a list across many activations. The new
`GameObject.exiled_with_ids` (a plain list) is stamped by `ExileEffect`'s
new ``track_exiled_with=True`` mode (independent of, and combinable with,
the existing ``remember`` flag) — appending rather than overwriting. A
consumer re-resolves each id fresh via `GameState.find_object` and checks
it's still genuinely sitting in exile (`obj.zone == "exile"`, cheap since
`Zone` is a `str, Enum` — no `models/` import needed in `continuous.py`,
keeping that file's existing model-import discipline) rather than pruning
the list on removal, the same "dead reference is harmless, re-check it"
contract `linked_exile_id`'s own `imprinted_card_colors` reader already
uses — except zone-checked too, since (unlike an Imprint permission) a
*borrowed ability* would otherwise still apply after its source card left
exile for hand or battlefield.

**The ability-borrowing grant itself.** `effects.
grant_borrowed_activated_ability` is a new layer-6 static
(`continuous._apply_borrowed_activated_abilities`, called right after the
ordinary `_apply_layer_6_ability` pass) whose granted-ability *set* is read
live off the board rather than fixed at parse time — the gap
`grant_activated_ability`'s existing single-fixed-ability shape
(Umbral Mantle/Squirrel Nest) could never close. For each creature
matching the scope (a new `has_counter_kind` filter on
`continuous.group_selector_objects`, generalizing the existing min/max
power-toughness qualifiers to an arbitrary counter kind) and each still-
exiled creature card in the source's `exiled_with_ids`, it builds one
fresh `ActivatedAbility` per (grantee, exiled card, ability index): the
exiled card's own cost/effects — already bound once at bind-on-load, like
any other permanent's — with every nested effect's `.source` redirected to
the *grantee* via a new `_retarget_effect_source` (a shallow `copy.copy`
per effect, safe since `GameEffect` subclasses hold no per-instance
mutable state beyond `.source`), per RULE 113.7c ("Any ability that a
permanent gains by another spell/ability applies to that permanent, not to
the object that granted it"). Cached in a new, separate `GameState.
_borrowed_ability_cache` (a 4-element key, `(ability, grantee, exiled
card, ability index)`) rather than reusing `_granted_ability_cache` —
exactly the collision `_hand_cycling_ability_cache` was already split out
to avoid, since `_apply_layer_6_ability`'s own end-of-pass pruning loop
only recognizes its own key shapes and would otherwise delete this
function's entries every single pass, before it ever got to re-add them.
Verified end-to-end: activating a borrowed ability taps and costs the
*grantee* (not the original, still-untapped exiled card), the grant
vanishes the instant the exiled card leaves exile for any reason, and a
noncreature card exiled the same way contributes nothing.

**The any-color mana permission.** `effects.
grant_any_color_for_activation` is a standing RULE 605.1a wildcard
*permission*, not a layer-6 characteristic grant — it rides its own
non-RULE-613 bucket (`continuous.any_color_for_activation`, same
"permission static outside the layer engine proper" treatment as
`has_no_maximum_hand_size`/`no_untap_optional`), consulted by all three
activation-cost payment sites in `game/engine/activation_mixin.py`
(`_max_x_for_mana`/`_can_pay_activation_cost`/`_pay_activation_cost`),
each now passing ``wildcard="color"`` through to `ManaPool.can_pay`/`pay`
— the same ``wildcard`` param RULE 605.1a's *casting*-side grant
(`GameState.mana_wildcard_permission`) already used, just newly reached
from the activation-cost path too. Distinct from the shipped RULE 605.3a
`restriction_predicate_for_cast`/`_for_activation` machinery, which
restricts *what a lot of mana can pay for*, never *what color it counts
as* — the two now coexist in the same `can_pay`/`pay` call rather than one
having been rebuilt to imitate the other. Scoped by
``creature_abilities_only`` (default `True`, matching print) to abilities
whose *source* is a creature.

Found two more real cards while sizing this (Drana and Linvala, Scheming
Fence) printing the identical "any color to activate **those** abilities"
wildcard, narrower-scoped than Agatha's own "creatures you control" —
not built here since both also need the *targeted*/chosen-permanent
ability-borrowing primitive MEC-23 still names, not the exiled-with one;
folded into MEC-23's own BACKLOG entry rather than left to be
rediscovered a third time.

### MEC-20 — RULE 601.2f "Expertise" cycle

The missing piece was never the payment mechanism — `GameState.
free_cast_instance_ids` already existed and already zeroed a cast's mana
cost (RULE 702.88b Rebound/Beseech the Mirror already used it, from
*exile*) — it was the interactive "which hand card, if any, meets the
mana-value cap" choice itself. `effects.FreeCastFromHandEffect` opens
`RulesEngine.request_choose_objects` with a new ``"grant_free_cast"``
action that only *arms* the picked card's `free_cast_instance_ids` entry
rather than casting it immediately (deliberately not the existing
``"cast_free"`` action's `cast_without_paying`, which puts a chosen card
straight on the stack with no further interaction) — a hand card is
already a legal cast zone (`can_cast`'s `in_castable_zone` check doesn't
even consult `free_cast_instance_ids`, only the *payment* step does), so
arming the flag is enough; the caster casts it (or doesn't) through the
ordinary `legal_actions` cast option afterward, getting its full
targeting/modal choices exactly like `grant_free_cast_window_from_exile`'s
own "goes through the ordinary action loop" shape for an *exiled* card.
The armed flag is also registered in `temp_play_permissions` (same-turn-
only) purely so the existing cleanup sweep tears both down together —
`free_cast_instance_ids`'s own sweep only keeps entries also found there.
**Documented simplification**: RULE 601.2f/718 rulings actually require
this free cast to happen *as the Expertise spell resolves*, not at
leisure later in the turn; this engine has no "pause mid-resolution for a
full nested cast+targeting cycle" primitive, so a same-turn window is
offered instead — strictly more permissive than print, never less.

`FreeCastFromHandEffect` covers three real shapes in one primitive:
a literal cap (the five Expertise sorceries), the caster's own announced
{X} (Electrodominance — ``criteria={"max_mana_value": "x"}`` mirrors
`SearchLibraryEffect`'s own key so `RulesEngine._substitute_x`'s existing
``filter``/``criteria`` walk resolves it for free, no separate wiring),
and a board-read cap (Epistolary Librarian's "where X is the number of
attacking creatures" — a *triggered* ability, never itself cast for an
{X} of its own — ``max_mana_value_selector``, resolved via the existing
`continuous.count_selector`).

**Parser recognition** (`catalogue.handlers._free_cast_from_hand`) covers
the whole family in one row: a literal N, the ``x`` sentinel via the
existing `COUNT_X`/`count_or_x_of`, and the optional "where x is the
number of attacking creatures" tail. Closed Sram's/Yahenni's Expertise
and Epistolary Librarian outright. Hit — and worked around rather than
side-stepped — two real, separate pre-existing gaps along the way:
`segmenter._peel_optional` strips a leading "you may " before any handler
ever sees the clause (MEC-18's own "the generic 'you may' stripper eats
the clause first" lesson, recurring a second time), fixed by making the
prefix optional in the regex itself rather than special-casing the peel
again; and "Veil of Time —" (Epistolary Librarian's own RULE 207.2c
ability-word label) wasn't in `normalize`'s deliberately-conservative
whitelist, fixed by adding it there (the whitelist's own documented
extension point — "safe to extend as more are checked"). Baral's/
Rishkar's Expertise stay UNMODELED — both fully closed on this clause,
blocked only by unrelated pre-existing gaps in their *other* sentence
(returning up to N targets, drawing off greatest power). Electrodominance
and Kari Zev's Expertise (the latter already partially hand-authored)
are hand-authored rather than reached through the parser's own ``damage``
handler, which is digit-only (`NUMBER`, not `COUNT_X`) — widening it to
accept "X damage" is a separate, real gap of its own (X-cost burn spells
generally: Fireball/Rolling Thunder/Banefire-shaped) left for a future
ticket rather than folded in unreviewed. Coveted Prize stays UNMODELED
entirely — blocked on RULE 301.7's Party mechanic (cost reduction +
condition), which nothing in this engine models yet.

`PARSER_VERSION` → 69. Coverage after this batch: 11,475 / 34,811 (33.0%).
`tests/test_mec25_mana_ability_upgrade.py`, `test_mec21_agathas_soul_
cauldron.py`, `test_mec20_free_cast_from_hand.py` cover all three, each
with a real-card end-to-end check alongside the synthetic-fixture ones.

## MEC-23/MEC-24 (2026-08-11)

Two tickets, both left open by the Vivi B4 batch (2026-08-10), closed
together.

### MEC-23 — Quicksilver Elemental's own two clauses

"{U}: This creature gains all activated abilities of target creature
until end of turn." needed the resolve-time, single-target sibling MEC-21's
own ability-borrowing static (Agatha's Soul Cauldron) explicitly deferred:
that one is a *standing* layer-6 grant, re-deriving its borrowed set live
off `GameObject.exiled_with_ids` every `continuous.recompute` pass — wrong
shape for "snapshot **one target's** ability set, once, for the rest of
the turn." The new `effects.GainActivatedAbilitiesOfTargetEffect`
(``"gain_target_activated_abilities"``) is a plain one-shot `GameEffect`
with a ``target_kind="creature"`` `TargetSpec`: at resolution it reads
``target.activated_abilities`` once and, for each, builds a fresh
`ActivatedAbility` — same cost/effects, every nested effect's ``.source``
redirected to the grantee via the *existing* `continuous.
_retarget_effect_source` (RULE 113.7c), reused rather than reimplemented
per the ticket's own note — appended onto a new turn-scoped
`GameObject.temp_granted_activated_abilities` field (the `temp_keywords`
shape: initialized in `__init__`, *not* reset by `reset_derived` since it
must survive a mid-turn recompute, cleared unconditionally at cleanup,
RULE 514.2). `GameObject.granted_activated_abilities` — the one property
every consumer (`can_activate`/`activate_ability`/`legal_actions`) already
reads — now unions this list with the pre-existing layer-6
`_granted_activated_abilities`, so no call site needed to change at all.
A later change to the target's own ability set doesn't retroactively
change what was copied, matching the card's own printed ruling.

The second clause — "You may spend blue mana as though it were mana of
any color to pay the activation costs of this creature's abilities." —
is *not* Agatha's own unscoped wildcard reused verbatim: Agatha's lets
*any* of the five colors pay *any* colored pip, for *any* creature the
controller controls; this is self-scoped (only this permanent's own
abilities) and single-color (only blue substitutes — a red pip still
needs real red or blue, never green/white/black). `continuous.
any_color_for_activation` gained two params to cover both without a
second function: ``self_only`` (checks ``ability.source is source``
instead of Agatha's controller-wide check) and ``from_color`` (returned
in place of the literal ``"color"`` wildcard token). `ManaPool._solve`
gained the matching branch: a WUBRG letter as ``wildcard`` (as opposed to
the literal string ``"color"``) widens a colored pip's candidates to
``[real_color, wildcard_color]`` rather than all five — genuinely
different arithmetic, not a relabeling of the existing branch. All three
of `game/engine/activation_mixin.py`'s cost-paying call sites already
computed ``wildcard`` from this one function's return value, so widening
it from `bool` to `Optional[str]` (the wildcard token itself, or `None`)
needed no new call site, only dropping each one's own
``"color" if ... else None`` ternary.

Hand-authored (`game/ability_catalogue.py`) — a genuine singleton shape
(`engine_bench.py cards 'gains all activated abilities of target
creature'` found exactly one cached card) per the authoring guide's own
"a card the parser can't fully claim" criterion, not a deferred parser
gap. Found two more real cards printing the same wildcard phrasing while
sizing this (Drana and Linvala, Scheming Fence) — their own grant is
*standing* and *group/choice-scoped* rather than resolve-time/targeted,
a genuinely different shape needing its own selector on the MEC-21 static
plus a scoped activation-prohibition and (Scheming Fence) an ETB
chosen-permanent primitive; filed as `MEC-26` rather than silently
re-deferred a third time under the old ticket's stale wording.

### MEC-24 — the targeted "target instant or sorcery card in your graveyard gains flashback…" family

Past in Flames's own untargeted "each instant and sorcery card in your
graveyard gains flashback…" sibling (`grant_graveyard_cast_permission_
this_turn`, appended onto the *granting permanent's own*
`GameObject.static_effects`, scanned by `game/graveyard_cast.py`) doesn't
fit the far more common *targeted*-singular phrasing (Recoup/Snapcaster
Mage/Slickshot Lockpicker/Sphinx of Forgotten Lore/Katilda and Lier — 5
of the ticket's ~10 named cards, the other, The Fugitive Doctor, remains
blocked on an unrelated pre-existing gap below): that marker lives on the
*grantee*, discoverable only by scanning the granting permanent's own
battlefield presence, but a targeted grant must survive independently of
whatever granted it (the creature that triggered it may attack into
removal, or simply leave play, before the graveyard card is ever cast)
and must apply to exactly the one chosen card, not every instant/sorcery
in the graveyard.

New primitive: `GameState.temp_flashback_grants` (``instance_id ->
cost``), a marker on the *graveyard card itself* — the same "per-object
marker" shape `GameState.temp_play_permissions` already uses for a
temporarily-castable *exiled* card, just keyed to a graveyard object
instead. `effects.GrantFlashbackToTargetEffect`
(``"grant_flashback_to_target"``) stamps it at resolution, defaulting the
cost to the target's own `Card.mana_cost_string` (every real card but The
Fugitive Doctor, whose flat ``{2}{R}{G}`` overrides it via the effect's
own ``cost`` param). Consulted by exactly two existing choke points —
`game/engine/lands_mixin.py`'s `_graveyard_cast_keyword` (now returns
``"flashback"`` for a granted card too, alongside the printed-keyword and
Underworld-Breach-granted-Escape checks already there) and
`game/engine/casting_mixin.py`'s `_flashback_cost` (converted from
`@staticmethod` to an instance method so it can read `self.state`,
matching `_escape_cost`'s own printed-vs-granted split) — so cost
computation (`effective_cast_cost`), the `legal_actions` "cast_from_
graveyard" UI tag, and the RULE 702.34a exile-after-cast
(`GameObject.cast_via_flashback`, already keyed off the same
`_graveyard_cast_keyword` return value) all fall out of the existing
Flashback machinery unchanged — no new casting/exile code at all. Cleared
unconditionally at cleanup (RULE 514.2, `GameEngine._step_cleanup`) — a
flat "until end of turn" grant, unlike `temp_play_permissions`' own
"until your next turn" turn-number bookkeeping the sibling mechanism
needs.

**Parser recognition** (`catalogue.handlers._grant_flashback_target`)
reuses the graveyard-recursion family's own `_GRAVEYARD_TYPE_WORD`/
`_GRAVEYARD_SCOPE_WORD`/`_graveyard_target_kind` vocabulary (Regrowth/
Reanimate-shaped) rather than a bespoke grammar — one regex covers every
real card's variation: the common "the flashback cost is equal to
[its/that card's] mana cost" trailing sentence (optional, dropped once
matched — restated prose, not a second effect), a literal inline cost
with no trailing sentence (The Fugitive Doctor), and a bare "target
**sorcery** card" narrowing (Recoup) that needed a new
`targeting._GRAVEYARD_TYPE_FILTERS["sorcery"]` entry (the existing
vocabulary only had the combined `instant_or_sorcery` filter). The Fugitive
Doctor stays UNMODELED: its clause is wrapped in "you may sacrifice a
Clue. When you do, `<effect>`." (RULE 603.5), and `_pay_cost_then_
general`'s own, already-documented restriction against a *targeted*
follow-up (`PayCostThenEffect`'s branches resolve off-stack, with no
RULE 601.2c target-gathering step of their own) correctly still applies —
a real, separate, pre-existing limitation, not something this ticket's
own primitive touches.

`PARSER_VERSION` → 70. Coverage after this batch: 11,487 / 34,811 (33.0%).
`tests/test_mec23_quicksilver_elemental.py`/`test_mec24_targeted_
flashback_grant.py` cover both, each with parser-unit-level regex tests,
synthetic-fixture engine tests, and a real-card end-to-end cast (Snapcaster
Mage's own ETB interactively targeting a graveyard Lightning Bolt, then
actually casting it for the granted cost).

## MEC-26 · Drana and Linvala / Scheming Fence (2026-08-11)

The second of MEC-23's own two open cards (found while sizing MEC-21,
2026-07-22; deferred again by MEC-23 the same day this ticket was filed —
the mandatory hand-author-or-promote close per CLAUDE.md's no-half-
implementations rule, so this shipped in the same session rather than
rolling to a third deferral). Both print a **standing, group-scoped**
ability-borrowing static — genuinely closer to MEC-21's own
`grant_borrowed_activated_ability`/`continuous.
_apply_borrowed_activated_abilities` (Agatha's Soul Cauldron: a live,
every-`recompute`-pass re-derivation) than to MEC-23's resolve-time,
single-target snapshot — just reading their donor set off something other
than `GameObject.exiled_with_ids`:

- **Drana and Linvala** ("has all activated abilities of all creatures
  your opponents control"): a new ``source_mode="group"`` reads a live
  `affects` selector straight off the battlefield every recompute
  (``source_affects="creatures_opponents_control"``) — no exiling
  involved, so `exiled_with_ids` doesn't apply, but the "read the donor
  set live" shape is identical. Confirmed dynamic (not a snapshot) with a
  test that removes the donor creature mid-game and checks the grant
  disappears on the next recompute.
- **Scheming Fence** ("has all activated abilities of the chosen
  permanent except for loyalty abilities"): a new
  ``source_mode="chosen_permanent"`` reads a *single* donor named once by
  a new interactive ETB pick. Its own "As this creature enters, you may
  choose a nonland permanent" turned out **not** to need a pre-entry RULE
  601.2b replacement like `chosen_type`/`chosen_color`
  (`RulesEngine._offer_enter_choices`) — unlike those, the chosen
  permanent never feeds back into *Scheming Fence's own* printed
  characteristics, only into other statics that already re-read live
  state every recompute regardless of when the choice landed — so it's
  modeled as an ordinary interactive ETB trigger instead
  (`ChoosePermanentEffect`/``"choose_permanent"``, a new
  `RulesEngine.request_choose_objects` action alongside ``"tap"``/
  ``"sacrifice"``/``"exile"``/etc. that stamps the pick onto a new
  `GameObject.chosen_permanent_id` field rather than acting on the chosen
  object itself). "You may" makes the pick genuinely optional
  (`request_choose_objects(optional=True)`, its existing decline
  affordance) — unlike `chosen_type`/`chosen_color`'s always-mandatory
  pick, which defaults to the first option when declined. Candidates are
  *any* nonland permanent on the whole battlefield, not scoped to the
  controller — Scheming Fence borrows an opponent's ability just as
  readily as its own controller's. A new `continuous.
  group_selector_objects` selector, ``"chosen_permanent"``, reads the id
  back every recompute — the `attached_permanent` idiom (an Aura's
  `.attached_to`), just for a chosen id instead of an attachment.
  ``exclude_loyalty=True`` drops any donor ability whose cost
  `is_loyalty` (RULE 606.5c is planeswalker-only and makes no sense
  copied onto a creature) — needed here because, unlike Drana's
  creature-only donor pool, "a nonland permanent" can be an artifact,
  enchantment, planeswalker, or battle, so `creature_only=False` on this
  card's own static.

Both also print "Activated abilities of `<the same donor scope>` can't be
activated" and needed **no new code at all** for it: `continuous.
activation_prohibited` already reuses the ordinary `affects` selector
vocabulary (Collector Ouphe-shaped), so scoping it to
``"creatures_opponents_control"``/``"chosen_permanent"`` was just a matter
of a real card finally using those selector values there. Likewise "you
may spend mana as though it were mana of any color to activate **those**
abilities" needed no third param on `grant_any_color_for_activation`
either: the ticket's own filing worried MEC-23's ``self_only=True`` would
over-scope to "any ability this permanent has," not just the borrowed set
specifically, but neither Drana and Linvala nor Scheming Fence prints any
*other* activated ability of its own — so in practice the two sets are
identical, and the worry didn't survive contact with the actual cards. Genuinely
three real gaps closed by one new `source_mode` param plus one new ETB
choice primitive, not three separate mechanisms.

One latent bug surfaced and was fixed on the way: `grant_borrowed_
activated_ability`'s registration defaulted ``has_counter_kind`` to
``"+1/+1"`` for *every* caller, not just Agatha's own "creatures you
control **with +1/+1 counters on them**" qualifier — since that filter is
applied to the *grantee* selector's own result (`continuous.
group_selector_objects`), Drana and Linvala (an ``affects="self"`` grantee
with no +1/+1 counters of her own) was silently filtered down to an empty
grantee set by a qualifier her printed text never mentions. Fixed at the
default (now `None` unless a caller explicitly asks for it — Agatha's own
catalogue entry already passed it explicitly, so this was a pure
narrowing, not a behavior change for the one card that needed it).

`tests/test_mec26_group_scoped_ability_borrowing.py` (23 tests) covers
both cards: the donor set updating live (not a snapshot) as a creature
leaves the battlefield, opponent-only scoping, the ETB pick's optional
decline, loyalty-ability exclusion, choosing the permanent itself being a
harmless no-op (the existing donor-is-grantee guard in
`_apply_borrowed_activated_abilities`), the scoped activation prohibition
in both directions, and the any-color wildcard paying a borrowed colored
cost off each card. Coverage after this batch: 11,489 / 34,811 (33.0%) —
+2 from the two new hand-authored (`AUTHORED`) cards; no `PARSER_VERSION`
bump, since neither card involved a new oracle-text handler.

## PLR-4 · Client-token identity stub (2026-08-11)

Narrowed, not closed — real accounts are still [PLR-9]. Before this,
`services/lobby.py`'s only identity was the display name
(`normalize_name`), so two browsers saving the same Profil name genuinely
merged into one seat, the second to connect taking it over. This batch
gives a browser that *has* saved a Profil name a second, independent
handle that disambiguates it from another browser sharing that name,
without building any part of real accounts (no login, no server-issued
credential, no password) — deliberately scoped to "stop the accidental
collision," per the user's own framing of it as a stub.

**Client side** (`settings.js`'s `ensureClientToken`): a random
`crypto.randomUUID()`, minted into the `mtg_client_token` cookie the first
time the Profil tab's "Speichern" button is pressed (same moment the name
itself is saved) and never before — a client that has never opened Profil
still resolves purely by name, the original PLR-4 behaviour, unchanged.
The cookie's `Max-Age` is a sliding 90 days, renewed on every save.

**Server side** (`services/lobby.py`): `LobbyPlayer.client_token` +
`token_expires_at` (wall-clock, since it has to slide independently of the
monotonic disconnect/idle deadlines already on the class) and a new
`Lobby._by_token` index. `Lobby.connect`'s reclaim order is now
`player_id` → `client_token` (if the caller has one) → `name` (only when
the caller has *no* token — the legacy path). The key behavioural change
is that once a client presents a token, name is never consulted for that
client's identity at all: an unrecognized token mints a brand-new player
rather than falling back to a name match, which is exactly what stops two
same-name browsers from merging. `client_token` is deliberately never
included in `LobbyPlayer.to_dict()` — the lobby snapshot is broadcast to
every connected client, and leaking a token would let an opponent replay
it to steal the reconnect. Wired through both connect paths: `/ws/lobby`
(`api/multiplayer_ws.py`, a new `client_token` query param) and the REST
`POST /api/multiplayer/connect` fallback (`LobbyConnectRequest.
client_token`, `api/schemas.py`).

**Expiry ("player-data can/will be deleted")**: `Lobby.
expired_token_players()` (swept once a second by `api/multiplayer_ws.
sweep_once`, alongside the existing idle/disconnect-grace jobs) is gated
the same cautious way the disconnect-grace sweep already is — never a
player who's currently connected, never one seated in a `RUNNING` game —
so a live browser's identity never expires mid-session regardless of the
clock, only a genuinely abandoned one (`config.
CLIENT_TOKEN_VALIDITY_SECONDS`, 90 days, `MTG_CLIENT_TOKEN_VALIDITY` env
override). Once forgotten, if no *other* still-recognized player shares
that display name (`Lobby.name_in_use_by_other` — connected, or holding
an unexpired token of their own), that name's `player_assets.py` uploads
(sleeves, token art, favorite decks — still name-keyed, untouched by this
batch otherwise) are purged too, via the new `PlayerAssetStore.
delete_all_for_player`. The `name_in_use_by_other` guard exists
specifically because two browsers can now legitimately share a display
name at once (that's the point) — without it, one stale browser expiring
would delete a still-active namesake's uploads out from under them.

**What this deliberately doesn't do**, all requiring real accounts
(PLR-9, left as the actual next step, not narrowed by this batch): the
token is unsigned, client-trusted data — nothing stops it being copied,
cleared, or forged, so it's a UX safeguard against *accidental* collision,
not a security boundary; a client with cookies cleared (or one that never
opened Profil) is indistinguishable from a stranger and falls back to the
original name-only behaviour; and saved decks stay globally unscoped
(anyone hitting the API sees every deck) exactly as before — the token
lives entirely in the lobby's presence layer, `services/deck_database.py`
was not touched.

Tests: `tests/test_api_multiplayer.py`'s `TestClientTokenIdentity` (same
token reclaims across a rename; two tokens under one name stay distinct;
an anonymous connect is never silently reclaimed by a later tokened one;
the legacy no-token path is unchanged; a repeated token still takes over
its own old socket) and `TestClientTokenExpiry` (expiry forgets the
player; a connected or mid-game token is never swept; asset purge fires
when the name is unshared and is skipped when a still-valid namesake
exists) plus `tests/test_player_assets.py`'s `TestDeleteAllForPlayer`.

## DB-2 · Ban-list live sync (2026-08-10)

Closed, not narrowed: DB-2's actual complaint was "no live source, needs
manual updates against the official page" — that's fixed. `RawCardStore`
(`services/raw_card_store.py`) already keeps each card's full raw Scryfall
`legalities` dict alongside the rest of its JSON (it exists precisely so a
model change never forces a re-download — see its own module docstring),
so the ban list was never actually missing a live source, just not reading
the one already on disk. `scripts/update_ban_lists.py` closes that: it
re-derives the live "banned" set for a format straight from
`RawCardStore.iter_raw()`, diffs it against the hand-maintained constant
(parsing the source with `ast`, not importing the module, so it has no
dependency on the rest of `mtg_analyzer` being importable), and rewrites
the constant in place with a round-trip check. `BAN_LIST_TARGETS` is a
one-entry-per-format registry (`commander` → `commander_legality.
BANNED_COMMANDER_CARDS` today) so a second enforced format is one new
entry, not new plumbing; `update_card_pool.py`'s own routine-refresh
ban-list report reuses the same registry so the two can't drift apart.

`BANNED_COMMANDER_CARDS` itself deliberately stays a frozen Python
constant read at legality-check time rather than a live per-card lookup —
same reasoning as the rest of this app's cache-primary posture (`CLAUDE.md`'s
`SCRYFALL_PRIMARY`): a deck-legality check shouldn't touch the raw store on
every call. Syncing is still a deliberate, run-it-yourself step (`python
scripts/update_ban_lists.py`, after `update_card_pool.py` if the raw store
itself might be stale) rather than automatic on every startup — consistent
with how the rest of the card pool refreshes, and not a gap worth tracking
on its own.

## DB-1 · Stale pre-`mana_cost_string` cache rows (audit closed, 2026-08-11)

Closed as already-structurally-impossible, not by any code change. DB-1
worried that a row cached before `Card.mana_cost_string` existed
(2026-07-06) could keep serving lossy legacy pip-tally mana data
indefinitely, healed only opportunistically by `Card.has_mana_cost_data` /
`LazyCardLoader`'s stale-refetch path. That refetch path only fires under
`scryfall_primary=True` (not this app's default) — but the premise doesn't
survive contact with `services/schema_version.py`, which predates the
field itself (2026-07-04): `CardDatabase` hashes `models/card.py` (+ its
own file) on every open and **wipes the entire cache** on any mismatch
(`_clear_on_schema_change`, whose own comment already names this exact
case: "this is what heals e.g. stale mana-cost data"). `models/card.py`
has changed 14 times since the field was added, most recently 2026-07-27
— so any row present in today's cache was necessarily written by
present-day code, whether via a live Scryfall fetch or a
`RawCardStore`-backed reseed (both paths always populate
`mana_cost_string`). Verified empirically against the live cache
(`inspect-db` skill, 34,811 rows): 541 non-land rows do carry a blank
`mana_cost_string`, but every sampled one — Conspiracies, Un-set
Contraptions/Stickers, Ancestral Vision (castable only via Suspend) — is
blank in the *raw* Scryfall JSON too (`scryfall_raw.db`), i.e. a real
costless card, not lossy cache data. Restoring an old cache export
(docs/Reference/08) doesn't reopen the window either — `_reconcile_schema`
runs in `CardDatabase.__init__`, so an imported stale file gets wiped on
the very next server start against current code, before anything can read
it. No code changed; `Card.has_mana_cost_data`/`_is_fresh` stay as they
are since `scryfall_primary=True` mode still wants them for the narrower,
real risk of a `scryfall_client.py` parsing-logic improvement not
reaching already-cached *values* (deliberately excluded from the schema
hash, per that file's own comment) — a different, still-open risk that
was never what DB-1 was describing.

## MEC-12: the nine "broader gaps" batch (2026-08-12)

Closed every item MEC-12's own "Broader gaps" section had accumulated
(2026-08-11's fourth-through-tenth-pass sweeps), each real and shipped with
execute tests, not just parse coverage:

**Exert (RULE 702.19)** — a declare-attackers-time choice
(`GameEngine.declare_attackers`'s new `exert` flag per attacker, decided in
the same breath as the attack itself, no separate `pending_choice`) rather
than a resolve-time prompt. `GameObject.skip_next_untap` is a genuinely new
one-shot flag (consumed and cleared by the very next `_step_untap`),
deliberately distinct from the sticky `skip_untap` toggle "may choose not
to untap" already used. `combat.has(obj, "exert")` needed no catalogue
change — Scryfall already tags these `keywords: ['Exert']` even with no
bare reminder-text line — just `COMBAT_KEYWORDS` widened to include it.
Oracle-text: `EventType.EXERTED`, a self-scoped "when you do" trigger and a
player-scoped "whenever you exert a creature" one (`_GROUP_CONTROLLER_
EVENT_KEYS["EXERTED"] = "player_id"`), plus a bare-keyword-only claim for
the ~1/3 of exert creatures with no rider at all. Combat Celebrant is hand-
authored: its own "if ~ hasn't been exerted this turn" guard is a real
correctness requirement (without it, its own granted extra combat phase
lets it exert, and grant, another extra combat forever), not a flavour
nuance — `ConditionalEffect`'s new `not_already_exerted` key reads the
firing `EXERTED` event's own pre-set `already_exerted` snapshot rather than
the object's live flag (already true by the time the trigger resolves).
`legal_actions`' attack offer gained `can_exert`. 21/36 exert cards MODELED
(was 5); the untap-all-other-creatures gap this surfaced closed for free by
widening `tap_selector`'s regex to accept "all other" alongside "each
other". Files: `game/engine/combat_mixin.py`, `game/engine/turn_loop_mixin.py`,
`game/combat.py`, `models/game_object.py`, `models/events.py`,
`game/effect_binder.py`, `game/effects.py`, `parser/oracle/segmenter.py`,
`parser/oracle/catalogue/handlers.py`, `game/ability_catalogue.py`.

**Stasis's "players skip their untap steps"** — the last open member of
the "players can't `<verb>`" family (untap's own *capped* sibling had
already shipped as `active_untap_caps`/`"untap_cap"`). Unlike a cap this is
unconditional and total — nothing about the step happens for *any* player,
not even bookkeeping — so it gets `should_skip_step`'s "whole step
skipped" treatment, not `has_no_untap_static`'s "just don't untap this
one": a new `skip_untap_step` `StaticAbility` layer,
`continuous.all_untap_steps_skipped`, checked once at the top of
`GameEngine._step_untap` rather than per-permanent.

**`devotion_to_hybrid`** (Blended Twistling) — any hybrid mana symbol
counts once, regardless of which two colours it's between (unlike ordinary
devotion, where a hybrid pip counts toward *both* colours); a mono-hybrid
pip doesn't count at all (not a colour mix). `continuous.count_selector`'s
`devotion_to_<colour>` family gained the reading; `subgrammars.DEVOTION`/
`devotion_selector` gained the `hybrid` alternative. The card's own
*permanent* self-anthem shape ("~ gets +X/+X, where X is …", no "until end
of turn") needed a new `static_handlers.py` row too — the existing
devotion-scaled handlers were all resolve-time `pump`, none of them a
standing `anthem`.

**Nykthos, Shrine to Nyx** — the one mana ability where the colour
*choice* and the produced *amount* are coupled (every other
`ManaAbility.color_selector` menu is either a fixed amount or a board-
read amount with no choice involved). New `color_selector`s
`"devotion_to_chosen_color"`: `resolve_options` builds a live 5-colour
menu, each option's own amount being *that* colour's devotion — colours
with 0 devotion are left off (a legal but pointless pick, same "produces
nothing" shape every other board-dependent menu already gives). Needed its
own segmenter claim too (`_DEVOTION_CHOSEN_COLOR_MANA_RE`) since "Choose a
color. Add …" doesn't start with "add" the way `_MANA_EFFECT_RE`'s bare
claim expects.

**Alt-cost creature-spell gate (the Bringer cycle)** — widening `gate.py`'s
`_is_spell` to include creatures was tried and reverted: `allow_spell_
effect` also gates unrelated bare-imperative rows (Strive, free-cast
conditions, …) that broke 88 real tests once creature cards started
reaching them for the first time. The actual fix: the whole RULE 118.9
alt_cost family (`pitch`/`sac_filter`/`sac_type`/`ret_two`/`pay_if`/
`pay_mana`) was pulled out of the `allow_spell_effect` gate and made
unconditional — a spell's mana cost doesn't care what it becomes once it
resolves, so these six checks are safe on any card type. 4 of 5 Bringers
now MODELED.

**Snuff Out's alt-cost siblings** — a board condition paired with a *non-
mana* payment (Dark Triumph's "if you control a Swamp, you may sacrifice a
creature…", Angelic Favor's "…tap an untapped creature you control…"), a
combined mana-plus-return-to-hand cost (the Borderpost cycle), and a
counted sacrifice beyond "one". None needed new *payment* machinery —
`_can_pay_alt_cast_cost`/`_pay_alt_cast_cost` already read `mana`/
`sacrifice`/`sacrifice_count`/`return_to_hand_count` independently, so
pairing two in one `alt_cost` dict just worked. The one real gap was
`tap_others` (RULE 602.1's "tap N untapped `<type>`s", previously paid
only on an *activated* ability's own cost, never an alt-cast one) — wired
into both payment methods, plus `_tap_others_pool` matching a bare main
type ("creature") via the new `continuous.has_card_type` public wrapper,
not just a real subtype. `_return_to_hand_count_candidates` gained a
`"basic land"` qualifier (RULE 205.4a's supertype, not a subtype at all).

**Grafdigger's Cage / Weathered Runestone** — the pair the ticket itself
flagged as "a real multi-site unification, not a regex". The cast half is
one choke point: `GameEngine.can_cast` now checks `continuous.graveyard_
library_cast_prohibited` once, for any object sitting in a graveyard or
library, covering Flashback/Escape, a Lurrus-shaped grant, and the
top-of-library permission alike without touching any of them. The entry
half is deliberately *not* a universal `GameState.add_to_battlefield`
hook — there's no single site every graveyard/library-to-battlefield route
already funnels through — so `continuous.graveyard_library_entry_
prohibited` is checked at the two real ones instead:
`ReturnFromGraveyardEffect._apply_one` (reanimation) and
`RulesEngine._finish_search`'s battlefield-destination branch (a tutor). A
prohibited card simply stays in its zone's list (`_finish_search` had
already popped it off; `obj.zone` still names where it came from, so
putting it back is a plain re-add), matching the real card's own ruling. A
rarer per-card reanimation route missing this check is a documented gap,
not chased further.

**Copy-except-also** — `Card.as_copy` (the one root primitive `copy_
mechanics.become_copy`/`RulesEngine.copy_permanent`/the enters-as-a-copy
replacement all funnel through) gained `not_legendary` (RULE 205.4a,
strips both `is_legendary` and the printed "Legendary" word — Multiversal
Recruitment/Impostor Syndrome/Hall of Mirrors-shaped, the single biggest
real template in the family). `CopyPermanentEffect` had *none* of
`add_types`/`add_subtypes`/`not_legendary` before this — only `EnterAsCopy
Replacement` did — so it gained all three, threaded through `RulesEngine.
copy_permanent`. New parser row: `create_token_permanent_not_legendary`.

**General count-amount resolver** — 446 cards solo-blocked on "X is the
number of `<noun phrase>` you control". The engine primitives already
existed (`continuous.count_selector`'s `creatures_you_control`/
`attacking_creatures_you_control`/`tapped_creatures_you_control`/
`creatures_you_control_of_type_<x>`/`legendary_creatures_you_control`, …) —
the gap was purely parser-side. Folded into the *same* `subgrammars.
DEVOTION` fragment (not a sibling constant) rather than a parallel one, so
every handler that already embeds `{DEVOTION}` — the target/group/negative
pump family, damage-to-players, life-loss, the devotion-scaled token count
— picks up the new reading for free, no per-handler change; one new
embedding was added, the devotion/count-scaled sibling of `_pump_self_
subject`'s fixed-int "it gets +N/+N" self-buff-on-attack row (Bag End
Porter-shaped), which had none before. Deliberately narrow: only the
plain noun phrases a `count_selector` entry already exists for (bare
"creatures/permanents/artifacts/lands you control", "attacking creatures[
you control]", "tapped creatures you control", a single creature-type
word via `_singularize`'s trailing-"s" strip, and three two-word compounds
— "legendary creatures"/"multicolored permanents"/"artifacts and/or
enchantments"). A qualified phrase ("… with power 2 or less") stays
unclaimed. Residual (599 cards still touch the template; most need a
qualifier grammar or a different verb-family embedding): **MEC-27**.

**Intervening-if (RULE 603.4)** — "if it's the first combat phase of the
turn, `<effect>`." (Karlach, Fury of Avernus/Finest Hour/Genji Glove/
Raiyuu-shaped — every one an extra-combat-granting trigger that must not
re-trigger itself in the extra phase it just made, the same self-loop
Exert's `not_already_exerted` guards). New `GameState.combats_this_turn`
counter (incremented once per `begin_combat` step, game-wide not
per-player, reset in `begin_turn`) backs a new `ConditionalEffect`
condition key `is_first_combat_phase`, wired into `parse_effect_body` via
the exact "wrap the rest, tag the condition" idiom every other
intervening-if row already uses (`_KICKED_CONDITION_RE`/`_TARGET_IS_
CONTROLLER_RE`/the Ring-bearer rows) — no new grammar shape, one more row
in an existing family. Genji Glove itself surfaced a *separate*,
pre-existing gap this batch didn't touch (filed as **ENG-29**): validated
instead against a plain self-subject creature. Residual (mass "untap all
attacking creatures" + "they" pronoun; "that creature" bound to a group-
subject trigger condition rather than a target): **MEC-28**.

Also surfaced, filed rather than fixed here: **PAR-18** (copy-except-also's
own wider residual — 188 cards, mostly self-referential "it" copies and
compound "except" clauses) and **PAR-19** (the alt-cost family's own wider
tail — 81 cards, "discard a `<type>` card"/"exile N `<color>` cards"/
"spend only mana produced by X" and other shapes Snuff Out's siblings
didn't cover).

Every shape above shipped with an execute test (build a real `GameEngine`,
bind, exercise the effect, assert the board changed), not just a parse-
coverage assertion — this repo's own standing lesson that parse-only
verification has masked real runtime bugs before. Full backend suite green
throughout (3804 passed at the end of the batch); `PARSER_VERSION` bumped
once per parser-classification change, 74 → 83.

## ENG-29: an `"attached_permanent"`-subject trigger's "it" now retargets a self-acting effect (2026-08-12)

Fixed the gap Genji Glove surfaced in the MEC-12 nine-broader-gaps batch
above: `parse_effect_body`'s generic trigger dispatch only unlocks
`self_subject=True` for an exact `{"subject": "self"}` condition
(`segmenter.py`'s `effects = parse_effect_body(body, self_subject=condition
== {"subject": "self"})`), so a `{"subject": "attached_permanent"}` trigger
("whenever equipped/enchanted creature `<verb>`, it `<effect>`") passed
`self_subject=False` — but a bare "it" in the effect body was *still*
recognized regardless of that flag, by the unconditional `_SELF_SUBJECT`
regex alternation every self-acting handler (`_tap_self`, and its siblings
across other effect types) already matches on. The clause parsed fine either
way; only its *meaning* was wrong — `TapEffect(target_kind=None)` always
means "the ability's own source," so "untap it" untapped the Equipment
itself instead of the creature it was attached to.

Fixed at bind time rather than parse time (`effect_binder.
_retarget_attached_permanent_effects`, called from `bind_ability` right
before `build_effects`, for the `"triggered"` ability kind only): when a
trigger's condition subject is exactly `"attached_permanent"`, every effect
in its body whose type is one of the five that already understand the
`"attached_permanent"` implicit-subject sentinel (`TapEffect`/`PumpEffect`/
`CopyPermanentEffect`'s `target_kind`, `FightEffect`'s `fighter_kind`,
`DamageEqualToPowerEffect`'s `dealer_kind` — confirmed via each class's own
`_attached_mode` branch in `game/effects.py`) gets that field rewritten from
`None` to `"attached_permanent"` if and only if the key is already present
with an explicit `None` value (never invented — `tap`'s own registry lambda
defaults an *absent* key to `"permanent"`, a real RULE 115 target, so
merely adding the key would be wrong for any row that never meant "self" in
the first place). Deliberately a narrow five-type whitelist, not "rewrite
every `target_kind: None`" — most self-acting effect types (`regenerate`/
`exile`/`return_to_hand`/`goad`) have no `"attached_permanent"` mode in
`game/effects.py` at all (no matching `_attached_mode` branch — verified by
grep before assuming), so a blind rewrite would have hand them a target
kind their own `TargetSpec` construction doesn't recognize instead of
leaving them alone. Also deliberately scoped to the plain
`"attached_permanent"` subject only, not its `"self_or_attached_permanent"`
sibling (Simian Sling-shaped "whenever this creature or equipped creature
becomes blocked") — that shape needs a genuinely dynamic "whichever one
actually fired" resolution a static bind-time rewrite can't express, and no
shipped card combines it with a self-acting "it" effect body today, so it's
left unhandled (fails closed) rather than silently retargeted wrong.

`tests/test_intervening_if_first_combat_phase.py` gained the real
regression: Genji Glove (its actual printed text, `keywords=["Equip"]` set
so the RULE 704.5m/n attachment-legality SBA doesn't detach it mid-test —
the one real trap in writing this test, `_attachment_kind` reads
`parametric_keywords["equip"]`, which only a bound `Equip` keyword ability
populates) attached to a bear, attacking, correctly untaps the bear and not
the Equipment. No parser-classification change (the clause already parsed
identically before and after — only the *bound* effect's `target_kind`
differs), so no `PARSER_VERSION` bump. Full suite green (3810 passed).

## MEC-28: RULE 603.1 group-subject retarget + a mass "attacking creatures" untap selector (2026-08-12)

Built the two primitives MEC-28's own residual named, both real and
verified, though neither of the ticket's two headline cards (Karlach,
Fury of Avernus/Finest Hour) turned out to close on these alone — see
BACKLOG.md's rewritten MEC-28 entry for exactly what each of the family's 7
cards is *still* blocked on (five separate, unrelated trigger-condition
gaps this batch didn't touch).

**Group-subject retarget**: the ENG-29 sibling. `TapEffect` gained a
`"trigger_subject"` target_kind mode (`game/effects.py`) reading
`GameContext.trigger_event` live at resolution — the same "read the
current firing's own payload" idiom `GrantKeywordToTriggerSubjectEffect`
already used for Tyvar Kell's emblem, just applied to tap/untap instead of
a keyword grant. `effect_binder._retarget_implicit_subject_effects`
(renamed from ENG-29's `_retarget_attached_permanent_effects`, since it now
covers two subject kinds) grew a second branch: a `{"subject": "group"}`
trigger condition ("whenever a creature you control attacks alone, untap
**it**.") retargets a `target_kind: None` effect to `"trigger_subject"` and
stamps `trigger_event_key` from `_subject_event_key` — the same per-event
lookup (`instance_id` default, `source_id` for DAMAGE) the trigger
*condition* side already uses to decide whether it fires, now reused to
decide *which* object the effect body acts on. Scoped to `tap` alone (a new
`_GROUP_SUBJECT_RETARGET_FIELDS` whitelist, sibling to the attached-
permanent one) — no shipped card needs this for `pump`/`fight`/
`copy_permanent`/`damage_equal_to_power` yet, and each would need
confirming its own `trigger_event_key` plumbing before extending, not
assumed to transfer for free. Verified against a minimal synthetic clause
that fully parses today ("Whenever a creature you control attacks alone,
untap it.") rather than a real card, since every real card printing this
shape has its own separate blocker (`tests/test_group_subject_retarget.py`)
— including the negative case (two attackers, RULE 508.1a's `ATTACKS_ALONE`
event never fires, nobody untaps).

**Mass "attacking creatures" selector**: `TapEffect._TAP_SELECTORS` gained
`"attacking_creatures"`, reusing `continuous.group_selector_objects`'s
existing branch of the same name (already built for Motivated Pony's
"Attacking creatures get +1/+1" anthem — the selector-resolution primitive
was never tap-specific, it just hadn't been reached from `TapEffect.
selector` before). One new parser row (`catalogue.handlers.
_tap_attacking_creatures`) claims "untap all attacking creatures"/"untap
each attacking creature". This closed **Hellkite Charger** outright (its
`pay_cost_then`-wrapped "untap all attacking creatures and after this
phase, there is an additional combat phase" was previously unclaimed on the
untap clause alone) and claims Hexplate Wallbreaker's own untap clause,
though that card stays UNMODELED on its unrelated "For Mirrodin!" line.

No `PARSER_VERSION` bump math surprises: `parser_probe.py diff` showed
exactly `+1 newly covered` (Hellkite Charger) / `-0 REGRESSED`, matching the
one genuine new-coverage card these two primitives reach on their own.
Full suite green throughout (3817 passed at the end, up from 3810 — seven
new tests, zero regressions).

## MEC-27: the counter and token-creation families read the count-amount resolver too (2026-08-12)

Closed the two verb families MEC-27's own residual named as entirely
unwired to `subgrammars.DEVOTION`'s "the number of `<noun phrase>` you
control" reading — grep-checked first per this repo's own standing rule
("before writing 'needs a new primitive', grep for one already shaped this
way"), which turned up a real surprise: `CreateTokenEffect` already had a
fully-wired `count_selector` field reading `continuous.count_selector` at
resolution (built for `_CREATE_TOKEN_NUMBER_EQUAL_DEVOTION_RE`'s "create a
number of `<p>/<t>` tokens equal to your devotion to `<colour>`" phrasing)
— the actual gap there was parser recognition surface, not a missing
engine primitive.

**Counters**: `AddCountersEffect` gained `amount_from_count_selector`
(mirroring `DealDamageEffect`'s own field/resolution exactly —
`continuous.count_selector(state, controller_id, selector, source=...)` at
apply time), wired to a new `add_counters_devotion` parser row: "put X
`<±1/±1>` counters on `<target/self>`, where X is `<DEVOTION>`" — a
genuinely separate row from the plain `add_counters` handler (that one's
`{COUNT}` group is digits/"a"/"an" only, no "x", so there's no dispatch
ambiguity registering both). Closed **Leyline Invocation** (a
self-referential "put X counters on **it**" onto a token the same clause
just created) and **Strength Bobblehead** (a subtype-count "the number of
Bobbleheads you control").

**Tokens**: `_CREATE_TOKEN_XX_WHERE_RE`'s "create X `<p>/<t>` `<mid>`
tokens, where X is `<...>`" tail was previously its own narrow subtype/
attacking-creatures-only alternation (`_count_selector_for_phrase`) even
though the sibling "equal to" row next to it already used the full
`DEVOTION` fragment — widened to match, so the same row now reads any bare
`DEVOTION` noun phrase ("the number of creatures/permanents/artifacts/
lands you control", the two-word compounds), not just the two words it
happened to be built for. Confirmed backward-compatible (the pre-widening
attacking-creatures phrasing still resolves, since `attacking_creatures` is
itself one of `DEVOTION`'s own readings) and confirmed via a real execute
test (an ETB trigger creating one 1/1 Soldier token per creature the
controller has when it resolves) rather than a parse-only assertion. Found
no card in the cache solely blocked on this widening alone — it removes
one blocking clause from cards that (per the fail-closed gate) usually have
another, unrelated one too, the same "a correct primitive can still show
zero new coverage today" shape this repo's own lessons document already
names.

Real, measured yield: `engine_bench.py cards "where x is the number of"`
went 26→28 MODELED / 599→597 UNMODELED. `parser_probe.py diff` showed
exactly `+2` on top of MEC-28's own `+1` in the same session (Leyline
Invocation, Strength Bobblehead) / `-0 REGRESSED`. This ticket stays open
in BACKLOG.md rather than closing — 597 cards remain, most blocked on the
qualifier grammar ("creatures you control with power N or less") or the
draw/life-gain/loss verb families the original ticket also named and this
pass didn't touch; genuine standing long-tail work, not a one-sitting
ticket. 18 new/extended tests in `tests/test_count_amount_resolver.py`
(parse-level *and* execute-level — an ETB trigger actually placing counters
sized by live board state, not just a spec assertion). Full suite green
throughout (3823 passed at the end, up from 3817).

## PAR-18: copy-except's add_types/add_subtypes gain an oracle-text route (2026-08-12)

MEC-12's 2026-08-12 batch had threaded `add_types`/`add_subtypes`/
`not_legendary` through `CopyPermanentEffect` and `Card.as_copy`, but only
`not_legendary` ever got a parser handler (`_copy_permanent_not_legendary`)
— `add_types`/`add_subtypes` were reachable only by hand-authoring, a
pure recognition gap this pass closed: `_copy_permanent_add_types`
("…create a token that's a copy of target creature, except it's an
artifact/a Shapeshifter Rogue in addition to its other types") reuses
`_split_token_mid_words` — the same colour/subtype/is-artifact word
classifier every "`<mid>` creature token" handler already shares — rather
than a new word list, and is tried before the bare `copy_permanent` row so
its trailing "except" clause isn't left dangling. Closed **Saheeli's
Artistry** (its second mode).

One real bug found and fixed on the way: `Card.as_copy` splices
`add_types`/`add_subtypes` straight into the type line with no case
normalization of its own (`f"{main} {' '.join(add_types)}"`), and the
existing MEC-12 test/hand-authored convention always passed pre-capitalized
words ("Artifact") — the new parser handler's first draft passed
`_split_token_mid_words`'s raw lowercase output straight through,
producing a real but wrongly-cased type line ("Legendary Creature artifact
— Human" instead of "Legendary Artifact Creature — Human"). An execute
test (not just the parse-level assertion) caught it immediately; fixed by
capitalizing at the parser boundary rather than pushing case-normalization
into `as_copy` itself, keeping that function's existing "caller passes the
final words" contract unchanged for its other callers.

Re-scoped rather than closed the ticket's own original two named shapes,
both still open: the "create a token that's a copy of **it**" self-
reference turns out, on inspection of the real cards, to usually mean a
card an *earlier clause of the same ability* exiled or found (Abyssal
Harvester: "exile target creature card…create a token that's a copy of
it") rather than the ability's own source — a `previous_subject`-shaped
retarget onto whatever was just exiled, not a true self-reference the way
the ticket's original framing assumed; and compound "except" clauses
combining 2+ modifiers in one sentence remain deliberately excluded
(`_COPY_PERMANENT_RE`'s own standing docstring). `engine_bench.py cards
"copy.*except it"` went 17→18 MODELED / 188→187 UNMODELED.
`tests/test_copy_except_family.py` gained 5 new tests (2 clause-level, 1
end-to-end card, 1 execute-level effect test that's what actually caught
the capitalization bug, plus the modeled-card check). Full suite green
throughout (3827 passed at the end, up from 3823).

## PAR-19: alt-cost's combat-count gate, plus a much bigger unrelated find (2026-08-12)

Closed the board-count-conditioned gate PAR-19 named — "If N or more
creatures are attacking, you may pay `<cost>` rather than pay this spell's
mana cost." (Lethargy Trap/Arrow Volley Trap) — with a new
`AbilitySpec.alt_cost` condition key, `creatures_attacking_at_least`
(`condition_query.free_cast_condition_holds`'s new branch, a live
`.attacking` scan over the battlefield with no controller scoping, matching
RULE 508's "creatures are attacking" having no controller qualifier of its
own). Shares `ALLOWED_FREE_CAST_CONDITION_KEYS`/the evaluator with the
already-shipped `opponent_spells_cast_this_turn_at_least`
(`free_cast_condition`'s own int-threshold key) — which surfaced a real,
previously-latent bug: `_validate_alt_cost`'s own inline condition check
(a second, independent validator from `_validate_free_cast_condition`,
since `alt_cost`'s `condition` sub-key reuses the same whitelist but isn't
validated by the same function) only special-cased `control_land_type`'s
string value, treating *every other key* as boolean-only — meaning
`opponent_spells_cast_this_turn_at_least` was structurally never usable as
an `alt_cost` condition (only as a `free_cast_condition`) even though
nothing else in the system would have stopped a card from needing it that
way. No card happened to need that combination before, so it went
unnoticed; fixed by widening the same int-threshold branch to cover both
keys rather than just adding a third special case next to it.

The bigger find was unrelated to alt-cost entirely: Lethargy Trap's own
second clause, "Attacking creatures get -3/-0 until end of turn.", doesn't
parse either — and checking why turned up that `catalogue.handlers`'s
shared `_GROUP`/`_GROUP_SELECTORS` mass-pump vocabulary (the fragment
several existing pump/keyword-grant rows already read, the "creatures you
control"/"all creatures"/"elves you control" family) had never included
"attacking creatures" at all, despite `continuous.group_selector_objects`'s
own `"attacking_creatures"` branch already existing (built for Motivated
Pony's anthem, and reused again by MEC-28's `TapEffect.selector` earlier in
this same session) — a pure recognition gap, zero new engine primitive.
Adding one alternation entry and one dict row closed it for every rule
already built on top of `_GROUP`, not just the pump case Lethargy Trap
needed — 24 real cards outright (Army of Allah/Morale's "+N/+N", Headlong
Rush's "gain first strike", and 21 more), the single highest-yield one-line
change of this whole five-ticket session. `engine_bench.py cards "rather
than pay this spell"` itself only shows 27→28 MODELED/81→80 UNMODELED,
since most of the 24 newly-closed cards print no alt-cost line at all —
worth recording so a future re-measurement of *this* ticket's own search
term doesn't undercount what actually shipped from it.

Not attempted: "you may discard a `<type>` card"/"you may exile N `<color>`
cards" (PAR-19's other two named shapes) and "…spend only mana produced by
Treasures to cast it this way" — checked against `game/mana_abilities.py`
before deferring rather than assumed: the existing RULE 605.3a spend-
restriction machinery (tagged mana lots, a caller-supplied predicate for
*what a lot can be spent on*) is the wrong shape for "which lot must be
spent" — this needs the mana pool to track *provenance* (which permanent
produced a given lot), a genuinely new primitive, not a rename of an
existing one. `tests/test_alt_cost_snuff_out_siblings.py` gained 3 new
tests (modeled-card, a `can_cast(alt_cost=True)` gate test needing 3 live
`.attacking` flags before it opens, and a direct `PumpEffect` execute test
for the mass debuff — which caught a test-setup mistake of its own on the
first pass: `group_selector_objects`'s `attacking_creatures` branch still
reads `self.source.controller_id` on the way in, so a sourceless effect in
a synthetic test resolves to nothing even though the selector is otherwise
unscoped by controller; every real bound ability always has a real source,
so this never bites in practice, but the test needed one too). Full suite
green throughout (3829 passed at the end, up from 3827 — one flaky,
unrelated websocket test reconfirmed in isolation both before and after).
