# Backend — Done

Completed backend work, split out of
[`../../backend/ToDo_Backend.md`](../../backend/ToDo_Backend.md) (which now
holds only open items). Section headers mirror the ToDo file so a
`Done_Backend.md "<section>"` reference in the code lands here. Remaining
work: [10_COMPLETION_ROADMAP.md](10_COMPLETION_ROADMAP.md).

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
      every other pending choice. **Known narrow gap**: a trigger placed
      via the separate RULE 603.3b interactive-ordering choice above
      (`resolve_trigger_order_choice`) still places directly without a
      target-choice pause — combining manual trigger ordering with a
      targeted trigger among the ordered set isn't handled (both features
      are individually solid; the two together is untested/unhandled).
      Tests: `test_trigger_targeting.py`.
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
      built exactly that). Tracked in `ToDo_Backend.md`. Tests:
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
  (2026-07-15):** the last open M2 keyword family (`backend/ToDo_Backend.md`)
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
  see `backend/ToDo_Backend.md`. **Buyback (RULE 702.27):** an optional
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
    `backend/ToDo_Backend.md`).
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
  - Still open (see `backend/ToDo_Backend.md`): mana *spend* restrictions
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
      not a coverage-% win by itself — see `backend/ToDo_Backend.md` and
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
      target kind next — see `backend/ToDo_Backend.md`), not a
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
      frontend display yet — see `frontend/ToDo_Frontend.md`).

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
      `frontend/ToDo_Frontend.md`; today's board still only offers the
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
      yet — see `frontend/ToDo_Frontend.md`.

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
      `docs/implementation-state/ToDo_Backend.md`'s "cEDH staples cube"
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
      soulbond) — each a real feature, tracked in `ToDo_Backend.md`'s
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
        needs a second gap — see `ToDo_Backend.md`), but it's proven
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
      `ToDo_Backend.md`); the remaining seven are being worked through
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
      program (`docs/implementation-state/ToDo_Backend.md`), run
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
          doesn't exist yet (already tracked: `ToDo_Backend.md` #35,
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
        `ToDo_Backend.md` #16); group-subject damage triggers ("a creature
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
        `ToDo_Backend.md`-tracked, unrelated to this batch's
        recognition-only scope); generic Cycling *execution* for an
        unregistered card (the `discard_self` hand-zone activated-ability
        primitive already exists from earlier Channel/Cycling work, but
        binding a bare oracle-recognized "cycling" keyword spec into a real
        activatable ability for *any* card, not just the two hand-authored
        ones, is still unbuilt).

- [x] **(2026-07-16) "Play/cast from the top of your library" permission**
      (Oracle of Mul Daya/Glarb, Calamity's Augur-shaped — the frontend's
      library-zone visualization, `frontend/ToDo_Frontend.md`/
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
      deferred `ToDo_Backend.md` items:

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
      gap still open in `ToDo_Backend.md`.

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
        closed (`backend/ToDo_Backend.md`).
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
        `docs/implementation-state/ToDo_Backend.md`'s new entry on
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
      verification (`backend/ToDo_Backend.md` doesn't currently list them
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
      follow-up — `backend/ToDo_Backend.md` — that recovered most of the
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
      biggest entry: `docs/implementation-state/ToDo_Backend.md` had
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
        that's still a genuine follow-up (`backend/ToDo_Backend.md`)
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
    `ToDo_Backend.md` "Equipment / Auras / 'combat damage to a player'
    triggers" for narrower per-card edge cases left open, and the entry
    just below for the 8 real architecture gaps that batch surfaced,
    since closed.

- **The 8 real feature gaps the Wyleth Equip batch surfaced** (2026-07-17,
  `backend/ToDo_Backend.md`'s former "Feature gaps surfaced by hand-
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
    separate keyword-mechanic build tracked in `backend/ToDo_Backend.md`.
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
      section that was open in `backend/ToDo_Backend.md`; what remains
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
      deliberately left open, so `ToDo_Backend.md`'s "Combat statics" entry
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
      open, so `ToDo_Backend.md`'s "Combat statics" entry is fully closed —
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
      UI remain — see `backend/ToDo_Backend.md` "Game Engine (Phase 3)".
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

## Card-type & structural coverage

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
      `backend/ToDo_Backend.md` rather than re-derived from scratch later.
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
      `backend/ToDo_Backend.md`.

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

## cEDH staples cube

- [x] **Batch 25 (2026-07-22): all 43 cards of the cEDH cube pool.** The
      whole "cEDH staples cube" section moved here from
      `backend/ToDo_Backend.md`; that file now keeps only the narrow
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
`backend/ToDo_Backend.md`. All nine are now closed. Six of them needed a
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
      /api/import/archidekt/{deckId}`) — Moxfield (`backend/ToDo_Backend.md`
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
