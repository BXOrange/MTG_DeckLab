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
        `docs/implementation-state/ToDo_EdgeCases.md`'s new entry on
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
        Command text parses fully `MODELED`. Scope: fixed N only —
        "choose one or more —" (Farewell, a variable N) is a different
        grammar axis, not attempted.
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

- [x] **Per-effect target partitioning, `StackItem.target_groups`
      (2026-07-16)** — the "targeting / hexproof / ward" edge-case chapter's
      biggest entry: `docs/implementation-state/ToDo_EdgeCases.md` had
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
