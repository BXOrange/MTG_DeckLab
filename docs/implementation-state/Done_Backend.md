# Backend — Done

Completed backend work, split out of
[`../../backend/ToDo_Backend.md`](../../backend/ToDo_Backend.md) (which now
holds only open items). Section headers mirror the ToDo file so a
`Done_Backend.md "<section>"` reference in the code lands here. Remaining
work: [10_COMPLETION_ROADMAP.md](10_COMPLETION_ROADMAP.md).
The original Weeks 1–4 roadmap is archived at
[history/IMPLEMENTATION_STATUS.md](history/IMPLEMENTATION_STATUS.md).

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
      `RulesEngine._attachment_legal` — creatures for Equip/Reconfigure,
      the Aura's `enchant` quality otherwise). RULE 704.5m/n on the host
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
