# Backend — Done

**Catalogue** (organized by game mechanic/feature, not by date): what has
shipped and *why it was built that way*, grouped under the same subsystem
names used throughout `CLAUDE.md` and `game/`'s own module layout. Open work
lives in [BACKLOG.md](BACKLOG.md); parser-tail strategy and worked examples
in [PARSER_LONG_TAIL.md](PARSER_LONG_TAIL.md). Remaining plan:

## Configuration & Persistence

### Configuration: centralized on-disk paths and runtime constants

- **What:** Consolidated previously hard-coded module constants (cache/data dirs, DB paths, Scryfall User-Agent/rate limit) into `mtg_analyzer/config.py`, overridable via `…
- **Files:** `mtg_analyzer/config.py`, `api/dependencies.py`, `card_database.py`, `deck_database.py`, `player_assets.py`
- **Why:** Service modules keep their old constant names as backward-compatible aliases onto the new `config.py` values, so nothing importing them broke.

### Configuration: JSON config file + worker/concurrency knobs + log level

- **What:** Every `config.py` value now resolves `MTG_* env var > backend/mtg_analyzer/config.json > built-in default` (the file is `json.load`-ed once at import; missing/m…
- **Files:** `mtg_analyzer/config.py`, `mtg_analyzer/config.json`, `api/app.py`, `services/dynamic_analysis.py`, `setup/start.py`, `tests/test_config_and_workers.py`
- **Why:** One uvicorn process is deliberate — the game-session manager, lobby and analysis job registry are in-memory process-wide singletons (`api/dependencies.py`), so…

### Configuration: offline-safe startup

- **What:** Made `./start.sh` guaranteed connectionless: `setup/install.py` installs `pip --no-index [--find-links wheelhouse]` first (fast + offline-safe) and only falls b…
- **Files:** `setup/install.py`, `setup/start.py`, `setup/wheels/`
- **Why:** An audit found the only network dependency in the whole startup path was an unconditional `pip install --upgrade pip` in the setup script, not the app itself (f…

### Data Layer: DecklisteParser

- **What:** Server-side decklist text parser ported line-for-line from the frontend's own parser (multiple qty formats, tag/set suffix stripping, structural Commander valid…
- **Files:** `mtg_analyzer/parser/deckliste_parser.py`, `frontend/src/js/parser.js`

### Validator: Commander legality checker

- **What:** Real Commander legality — color identity (union of all commanders' identity vs.
- **Files:** `mtg_analyzer/services/commander_legality.py`, `services/lazy_card_loader.py`, `services/card_database.py`
- **Why:** `color_identity` is read straight from Scryfall's precomputed field, so hybrid/Phyrexian/MDFC identity is correct for free.

### Data Layer: GameState / Player / ManaPool models

- **What:** Core Phase-1 game models: `GameState` (battlefield/stack, turn/phase/step/priority pointers, an event bus `fire_event`/`subscribe`), `Player` (life, per-player…
- **Files:** `models/game_state.py`, `models/player.py`, `models/mana_pool.py`, `models/game_object.py`, `models/events.py`

### Data Layer: CardDatabase + Scryfall integration + LazyCardLoader

- **What:** SQLite card cache storing each card's `to_dict()` JSON so the schema stays in sync with `Card`; `ScryfallIntegration` batches lookups via Scryfall's `/cards/col…
- **Files:** `services/card_database.py`, `services/scryfall_client.py`, `services/lazy_card_loader.py`, `services/image_cache.py`

### Data model / cache schema versioning

- **What:** Detects when a database's on-disk row format has drifted from the current model code: a SHA-256 over the source files defining each DB's stored format is stampe…
- **Files:** `services/schema_version.py`
- **Why:** Both SQLite DBs store `to_dict()` JSON blobs, so a model change silently strands old rows — the "Sol Ring cast for free" bug was exactly this class of problem.

## HTTP API

### HTTP API foundation: server framework

- **What:** Picked and set up FastAPI + uvicorn (`mtg_analyzer/api/app.py`) with CORS open to any localhost port for the static frontend dev server.
- **Files:** `mtg_analyzer/api/app.py`

### Decklist validation endpoint (POST /api/decks)

- **What:** Server-side decklist parse + structural validation mirroring the frontend's own parser request/response shape, with real Commander legality (color identity, ban…
- **Files:** `mtg_analyzer/api/decks.py`, `services/commander_legality.py`, `parser/deckliste_parser.py`

### Card lookup & image API

- **What:** `GET /api/cards` (list cached cards), `GET /api/cards/search?name=` (exact-name resolve via `LazyCardLoader`), `POST /api/cards/resolve` (bulk name resolution i…
- **Files:** `mtg_analyzer/api/cards.py`, `api/images.py`, `services/image_cache.py`

### Deck persistence: save/load/delete/validate saved decks

- **What:** `POST /api/decks/save`, `GET /api/decks`, `GET /api/decks/{id}`, `DELETE /api/decks/{id}` persist a decklist distinct from the parse-only `POST /api/decks`; `GE…
- **Files:** `mtg_analyzer/api/saved_decks.py`, `services/deck_database.py`, `services/deck_validation.py`

### WebSocket game session channel

- **What:** `WebSocket /ws/game/{game_id}` groups connections by game id and runs each client's `player_action` through the same `GameSession`/`GameSessionManager` the REST…
- **Files:** `mtg_analyzer/api/game_ws.py`, `api/dependencies.py`
- **Why:** Built as the future channel for pushing an opponent's moves in interactive multiplayer; solo goldfish play still uses REST directly and the channel wasn't wired…

### Archidekt deck import proxy (Import — follow-up from the frontend)

- **What:** `GET /api/import/archidekt/{deckId}` fetches Archidekt's unauthenticated public deck JSON endpoint (confirmed not Cloudflare-blocked, unlike Moxfield which was…
- **Files:** `services/archidekt_client.py`, `api/import_external.py`

## Mana System

### Mana cost model: Hybrid and Phyrexian mana

- **What:** A real per-symbol mana cost model (`ManaCost.parse` → `ManaSymbol`s tagged generic/variable/color/colorless/hybrid/mono-hybrid/Phyrexian, exposing `payment_opti…
- **Files:** `models/mana_cost.py`, `models/mana_pool.py`, `services/scryfall_client.py`

### Mana cost model: self-healing stale cache rows

- **What:** `Card.has_mana_cost_data` flags a non-land row with a blank `mana_cost_string` as pre-dating that field (Scryfall always gives a real, even if `"{0}"`, cost str…
- **Files:** `models/card.py`, `services/lazy_card_loader.py`
- **Why:** Prevents a "Sol Ring cast for free" class of bug where a stale cached row missing `mana_cost_string` was read as free.

### Mana cost model: X-spell casting

- **What:** RULE 601.2b — `{X}` parses to a `VARIABLE` symbol worth 0 until announced; `ManaCost.has_variable`/`.with_x(x)` resolve every `{X}` in a cost, `GameEngine.can_c…
- **Files:** `models/mana_cost.py`, `game/game_engine.py`, `game/rules_engine.py`

### Mana abilities on tap (RULE 605) — dual-land production choice

- **What:** A permanent's tap ability is modeled as a list of mutually-exclusive production options; `GameEngine.tap_for_mana` takes an `option_index` so a dual land makes…
- **Files:** `game/mana_abilities.py`, `game/game_engine.py`

### Mana-ability costs redone properly (RULE 605.1a/602.1)

- **What:** `tap_for_mana` previously only ever taxed the source's own tap; now charges a mana ability's full printed cost (mana pips, {T}/{Q}, life, sacrifice, `tap_others…
- **Files:** `game/mana_abilities.py`, `game/game_engine.py`, `game/costs.py`
- **Why:** `tap_others` deliberately became a real player choice rather than an engine auto-pick, since the printed cost has no "other" qualifier and Birchlore Rangers can…

### "Add 1 mana of any color" resolve-time color choice

- **What:** A spell/ability's bare "Add 1 mana of any color." now opens a genuine `add_mana_any_color` `pending_choice` (W/U/B/R/G) at resolution instead of guessing a colo…
- **Files:** `game/effects/core.py`, `game/rules_engine.py`, `parser/oracle/catalogue/handlers.py`
- **Why:** Built as shared infrastructure for Deathrite Shaman rather than a coverage play — zero real cards were unlocked by this alone at ship time.

### Leveler-gated mana abilities (RULE 711.4c)

- **What:** A Leveler's own mana ability, printed inside a `LEVEL n-m` tier, now only applies while the object's level counter is in that tier's range — `ManaAbility` gaine…
- **Files:** `game/mana_abilities.py`

### Mana spend restrictions (RULE 605.3a)

- **What:** `ManaPool` gained a `restricted` lot structure alongside its flat pool, tagged with a caller-opaque restriction dict and consumed via an `allows_restriction` pr…
- **Files:** `models/mana_pool.py`, `game/mana_abilities.py`, `game/game_engine.py`
- **Why:** `ManaPool` stays ignorant of what a restriction *means* (models/ must not import game/) — it only calls a caller-supplied predicate, preserving the module bound…

### "Any combination of colors" mana (RULE 605.1a)

- **What:** "Add N mana in any combination of colors" (Selvala, Flamebraider) — the payer splits the resolved total across colors instead of picking one repeated color.
- **Files:** `game/mana_abilities.py`, `game/game_engine.py`

### Hand-zone mana abilities (RULE 605.1a)

- **What:** "Exile this card from your hand: Add …" (Elvish/Simian Spirit Guide) — a mana ability activated straight from the hand, with no battlefield permanent or {T} at…
- **Files:** `game/mana_abilities.py`, `game/game_engine.py`
- **Why:** No prior "from hand" activation surface existed to extend (cycling/unearth aren't modeled either), so this was a genuinely new activation path.

### "Tapped for mana" event primitive (RULE 605.1)

- **What:** `tap_for_mana` fires a new `EventType.TAPPED_FOR_MANA` after mana lands in the pool, off a genuine mana-ability tap only — carrying `instance_id`, `object_types…
- **Files:** `models/events.py`, `game/game_engine.py`, `game/binding/core.py`

### Two RULE 605.3a Mana-Spend-Restriction Kinds

- **What:** `chosen_type_spell` (Cavern of Souls/Unclaimed Territory, resolved per-instance off the tapped land's own RULE 601.2b `chosen_type`) and `mana_value_or_x_spell`…
- **Files:** `game/mana_abilities.py`, `game/game_engine.py`

### Throne of Eldraine Fully Modeled

- **What:** Chosen-colour mana production (`ManaAbility.color_selector="chosen_color"`), a `chosen_color_monocolored_spell` spend restriction, and a colour-locked activatio…
- **Files:** `game/mana_abilities.py`, `game/game_engine.py`, `game/costs.py`

### Quoted Mana-Ability Grants

- **What:** "Elves you control have '{T}: Add {B}.'" (Tyvar Kell) — recognized directly by `static_handlers._granted_mana_options` since a plain top-level mana ability is c…
- **Files:** `parser/oracle/catalogue/static_handlers.py`

### Mana-spent-to-cast tracking

- **What:** `GameObject.mana_spent_to_cast` plus a `SPELL_CAST` event `mana_spent` key distinguish "cast for an alternative/reduced cost of {0}" (still a paid cast) from th…
- **Files:** `game/game_engine.py`, `models/events.py`

### Triggered mana ability (RULE 605.1b/605.4)

- **What:** `TriggeredAbility.mana_ability` resolves off-stack the instant it fires, so mana from an ability triggered off another mana ability is spendable within the same…
- **Files:** `game/effects/core.py`, `game/rules_engine.py`

### Mirrored/matching mana effects (Kinnan, Mana Web)

- **What:** `MirrorProducedManaEffect` adds only the mana a triggering permanent actually produced (narrower than a plain "any colour" add); `TapMatchingLandsEffect` locks…
- **Files:** `game/effects/core.py`

### Open mana-potential display aggregate

- **What:** A per-colour (WUBRGC) display computation via six independent greedy maximizations, each seeded from an empty virtual pool (not the real pool) so open+used equa…
- **Files:** `game/mana_potential.py`

### Mana-Potenzial: auto-tap execution (`find_tap_plan`, `GameEngine.auto_tap_for`)

- **What:** A DFS-based planner seeded from the real current pool, with a bounded fixed-point retry (so a converter needing another source's output still resolves) and a no…
- **Files:** `game/mana_potential.py`, `game/engine/mana_mixin.py`

### Automatic silent auto-tap on cast/activate

- **What:** A new `assume_mana_available` param on `can_cast`/`can_activate` skips only the mana-pool check so the engine can probe "is mana the only thing blocking this pl…
- **Files:** `game/game_engine.py`, `game/engine/mana_mixin.py`, `services/game_session.py`

### Distinct-colour mana spend restriction (PAR-7, RULE 605.3a-shaped)

- **What:** "Spend only colored mana on X.
- **Files:** `models/mana_pool.py`, `game/engine/casting_mixin.py`, `game/ability_catalogue.py`

### Auto-tap offer bounded by mana potential for X/Kicker (MEC-13)

- **What:** `auto_tap_for` itself already handled a chosen X/Kicker value, but `max_affordable_x`/`max_affordable_kicker`/`max_affordable_kicker_x` (which drive the fronten…
- **Files:** `game/mana_potential.py`, `game/engine/legal_actions_mixin.py`

### Face-down (morph) cast offer and auto-tap ordering fix (MEC-13)

- **What:** The face-down cast offer used a real-pool-only `can_cast` check instead of the potential-aware one, so the offer itself never appeared unless mana was already f…
- **Files:** `game/game_engine.py`, `game/engine/legal_actions_mixin.py`

### Auto-tap dynamic colour-preference recompute (MEC-13)

- **What:** `_choose_option`'s colour preference was a static set computed once from the cost, so two different flexible dual lands searching for a two-colour cost would bo…
- **Files:** `game/mana_potential.py`

### Bloom Tender / Carpet of Flowers mana primitives (ENG-27)

- **What:** New `ManaAbility.color_selector` kind `"colors_among_permanents_you_control"` — Bloom Tender's real cached text is a deterministic aggregate ("one mana of every…
- **Files:** `game/mana_abilities.py`, `game/effects/core.py`, `models/game_object.py`, `game/ability_catalogue.py`
- **Why:** Sizing first found the ticket's own framing wrong for both cards — Bloom Tender has no player choice, and Carpet of Flowers can't be a mana ability at all per R…

### User-reported bug: qualified "any color" mana clauses ignored board state (Mana System)

- **What:** `game/mana_abilities.py`'s `_parse_clause` matched the bare substring "any color" before checking any qualifying condition after it, so every *qualified* clause…
- **Files:** `game/mana_abilities.py`

### MEC-25: `grant_mana_ability` upgrade shape (Mana System)

- **What:** Goldspan Dragon's "Treasures you control have '{T}, Sacrifice this artifact: Add two mana of any one color.'" needed a non-`{T}`-only cost and *replacement* of…
- **Files:** `game/continuous.py`, `game/mana_abilities.py`, `game/ability_catalogue.py`

### MEC-21: `grant_any_color_for_activation` wildcard permission (Mana System)

- **What:** A standing RULE 605.1a wildcard permission over *activation*-cost mana (not a characteristic grant), consulted by all three activation-cost payment sites via `M…
- **Files:** `game/continuous.py`, `game/engine/activation_mixin.py`

### MEC-23: self-scoped, single-colour mana wildcard (Mana System)

- **What:** `any_color_for_activation` gained `self_only` (this permanent's abilities only) and `from_color` (only one specific WUBRG letter substitutes, not all five); `Ma…
- **Files:** `game/continuous.py`, `models/mana_pool.py`

### Hybrid-Mana Devotion Counting

- **What:** `devotion_to_hybrid` (Blended Twistling) counts any hybrid mana symbol once regardless of which two colours it spans (unlike ordinary devotion, which counts a h…
- **Files:** `game/continuous.py` (`count_selector`), `parser/oracle/catalogue/subgrammars.py`, `parser/oracle/catalogue/static_handlers.py`.

### Devotion-Coupled Mana Choice (Nykthos)

- **What:** New `ManaAbility.color_selector` `"devotion_to_chosen_color"` — the one mana ability where the colour choice and produced amount are coupled: `resolve_options`…
- **Files:** `game/mana_abilities.py`, `parser/oracle/segmenter.py`.

### Mana Production Multiplier (Nyxbloom Ancient)

- **What:** New `mana_multiplier` static + `continuous.mana_production_multiplier_for`, consulted directly by `GameEngine.tap_for_mana` — deliberately excludes triggered/ha…
- **Files:** `game/continuous.py`, `game/engine/mana_mixin.py`.

## Rules Engine Core Loop

### Effect system foundation

- **What:** Core effect hierarchy — `GameEffect`, `StaticEffect`, `TriggeredAbility`, `ReplacementEffect`, `ActivatedAbility`, `WinConditionEffect` — plus a `GameContext` f…
- **Files:** `game/effects/core.py`

### EffectRegistry and core one-shot effects

- **What:** A name-keyed `EffectRegistry` (hybrid class+registry design) with the first core one-shot effects: `DealDamageEffect`, `DrawCardEffect`, `DiscardEffect`, `Destr…
- **Files:** `game/effects/core.py`

### Turn phases and steps as sequences (RULE 500)

- **What:** `TurnSequence`/`GamePhase`/`GameStep` model the turn structure as data the engine walks, consulting skip effects per step instead of hardcoding phase logic.
- **Files:** `game/phases.py`

### Casting/Stack/Mana/Priority/Triggers/SBA core loop

- **What:** Foundational implementation of Casting (RULE 601), Stack (RULE 608 LIFO), Mana (RULE 504), Priority (RULE 117), Triggered Abilities (RULE 603/607), and State-Ba…
- **Files:** `game/rules_engine.py`

### Interactive stack (RULE 608)

- **What:** Casting leaves the spell on the stack instead of auto-resolving; `GameEngine.pass_priority` resolves the top object one at a time so instants can be cast in res…
- **Files:** `game/game_engine.py`

### Library search and the general pending-choice mechanism (RULE 701.19)

- **What:** `SearchLibraryEffect` (type-restricted) plus `RulesEngine.request_search`/`resolve_search_choice` established the general `state.pending_choice` pattern: a JSON…
- **Files:** `game/effects/core.py`, `game/rules_engine.py`

### GainLifeEffect and CounterSpellEffect

- **What:** `GainLifeEffect` and `CounterSpellEffect` (removes a spell from the stack to its owner's graveyard, RULE 701.5) registered alongside damage/draw/discard/destroy…
- **Files:** `game/effects/core.py`

### Maximum life total — MEC-54

- **What:** "For the rest of the game, your maximum life total is N." (You Compleat Me — the only printed card with this wording, no CR rule number).
- **Files:** `game/rules/damage_death_mixin.py` (`_MaxLifeTotalMarker`, `_max_life_total`, `set_max_life_total`, `gain_life` clamp), `game/effects/core.py` (`SetLifeEffect.only_reduce`, `SetMaxLifeTotalEffect`), `tests/test_mec54_max_life_and_you_compleat_me.py`
- **Why:** A single choke point (`gain_life`) already routes every effect-driven life gain, so the cap needed no new event/replacement — just one `min()` there plus the im…

### "X loses N life" effect family and gain/lose-life controller fallback

- **What:** Added `lose_life`/`lose_life_selector` handlers and registered `LoseLifeEffect` (previously only reachable internally by Afflict) with the same mass-selector sh…
- **Files:** `game/effects/core.py`, `parser/oracle/catalogue/handlers.py`

### Surveil (RULE 701.31)

- **What:** Mirrors the existing Scry implementation exactly: new `EventType.SURVEIL`, `RulesEngine.surveil` (always resolves the "keep everything on top" outcome non-inter…
- **Files:** `game/effects/core.py`, `game/rules_engine.py`, `parser/oracle/catalogue/handlers.py`

### Explore (RULE 701.44) (PAR-29, PARSER_VERSION 106)

- **What:** A new engine primitive for the Ixalan keyword action, the biggest single item in the PAR-29 RULE 701 residue.
- **Files:** `game/rules/search_mixin.py`, `game/effects/core.py` (+ `EffectRegistry`), `models/events.py`, `game/engine/turn_loop_mixin.py` (`resolve_pending_choice` dispatch), `parser/oracle/catalogue/handlers.py` (`explore_self_named` / `explore_self_pronoun` / `explore_previous` / `explore_target`), `frontend/src/js/gameBoardView.js` (`explore_bin` icon).

### Populate (RULE 701.36) (PAR-29, PARSER_VERSION 107)

- **What:** The next item off the PAR-29 RULE 701 residue, a small primitive on top of existing machinery.
- **Files:** `game/rules/copies_mixin.py` (`populate` / `resolve_populate_choice`), `game/effects/core.py` (`PopulateEffect` + `EffectRegistry`), `game/engine/turn_loop_mixin.py` (`resolve_pending_choice` dispatch), `parser/oracle/catalogue/handlers.py` (`populate` handler — a bare-word fullmatch), `frontend/src/js/gameBoardView.js` (`populate` icon).

### Bolster (RULE 701.39) + Support (RULE 701.41) (PAR-29, PARSER_VERSION 108)

- **What:** The +1/+1 keyword-action pair, off the PAR-29 RULE 701 residue.
- **Files:** `game/rules/mana_counters_mixin.py` (`bolster` / `resolve_bolster_choice`), `game/effects/core.py` (`BolsterEffect` + `EffectRegistry`), `game/engine/turn_loop_mixin.py` (`resolve_pending_choice` dispatch), `parser/oracle/catalogue/handlers.py` (`bolster` / `support` handlers), `frontend/src/js/gameBoardView.js` (`bolster` icon). The `when ~ enters, <kw> N` and `<cost>: <kw> N` wrappers come free from the existing trigger/activated-ability grammar.

### Suspect (RULE 701.60) (PAR-29, PARSER_VERSION 109) + one-off shapes residue closed (PAR-30, PARSER_VERSION 210)

- **What:** The Murders at Karlov Manor designation, off the PAR-29 residue.
- **Files:** `models/game_object.py` (`is_suspected` + `reset_as_new_object` + `to_dict`), `models/events.py` (`SUSPECTED`), `game/rules/misc_mixin.py` (`suspect` / `remove_suspected`), `game/combat.py` (`is_suspected` / `has_menace`), `game/engine/combat_mixin.py` (`can_block`), `game/effects/core.py` (`SuspectEffect` / `RemoveSuspectedEffect` + `EffectRegistry`), `parser/oracle/catalogue/handlers.py` (`suspect_self` / `suspect_previous` / `suspect_attached` / `suspect_target` / `remove_suspected_all`).

### Detain (RULE 701.35) (PAR-29, PARSER_VERSION 110)

- **What:** The Return to Ravnica designation, off the PAR-29 residue — the same shape as Suspect/goad.
- **Files:** `models/game_object.py` (`detained_by` + `reset_as_new_object` + `to_dict`), `models/events.py` (`DETAINED`), `game/rules/misc_mixin.py` (`detain`), `game/engine/turn_loop_mixin.py` (`begin_turn` sweep), `game/combat.py` (`is_detained`), `game/engine/combat_mixin.py` (`_can_attack` / `can_block`), `game/engine/activation_mixin.py` (`can_activate`), `game/effects/core.py` (`DetainEffect` + `EffectRegistry`), `parser/oracle/catalogue/subgrammars.py` (TARGET row), `parser/oracle/catalogue/handlers.py` (`detain` / `detain_multi`).

### Blight N — standalone form (PAR-29, PARSER_VERSION 111)

- **What:** "Blight N" (Bloomburrow — reminder text "put N -1/-1 counters on a creature you control"), the negative sibling of Bolster.
- **Files:** `game/rules/mana_counters_mixin.py`, `game/effects/core.py` (+ `EffectRegistry`), `game/engine/turn_loop_mixin.py` (`resolve_pending_choice`), `parser/oracle/catalogue/handlers.py`.

### Endure N (RULE 701.63) (PAR-29, PARSER_VERSION 112)

- **What:** The Bloomburrow keyword action — the permanent's controller **either** puts N +1/+1 counters on it **or** creates an N/N white Spirit creature token.
- **Files:** `game/rules/misc_mixin.py` (`endure` / `_endure_make_token` / `resolve_endure_choice`), `game/effects/core.py` (`EndureEffect` + `EffectRegistry`), `game/engine/turn_loop_mixin.py` (`resolve_pending_choice`), `parser/oracle/catalogue/handlers.py` (`endure_self_named` / `endure_self_pronoun` / `endure_previous` / `endure_target`), `frontend/src/js/gameBoardView.js` (`endure` + the previously-missing `blight` icon).

### Recruit (RULE 701.70) (PAR-29, PARSER_VERSION 113)

- **What:** The Tales of Middle-earth keyword action — "draw a card, then discard a card.
- **Files:** `game/rules/misc_mixin.py` (`recruit` / `_recruit_discard` / `resolve_recruit_choice`), `game/effects/core.py` (`RecruitEffect` + `EffectRegistry`), `game/engine/turn_loop_mixin.py` (`resolve_pending_choice`), `parser/oracle/catalogue/handlers.py`, `frontend/src/js/gameBoardView.js` (`recruit` icon).

### PAR-29: Parser-shaped only residue (PARSER_VERSION 114)

- **What:** The whole "Parser-shaped only (engine already fine)" bullet BACKLOG.md's PAR-29 entry had left after Explore/Populate/Bolster+Support/Suspect/Detain/Blight/Endu…
- **Files:** `game/effects/core.py` (`ConniveEffect`, `PumpEffect._pump_one`/`self_multiplier`, `ExchangeControlEffect`, `ExchangeLifeTotalsEffect`, `AddCountersEffect.apply`'s bug fix, `PopulateEffect`/`EndureEffect`'s `"x"`-sentinel widening, `BolsterEffect.amount_from_count_selector`), `game/targeting.py` (`land_you_dont_control`), `game/continuous.py` (`creatures_died_this_turn` DEVOTION branch, `distinct_named_artifact_tokens_you_control`), `game/combat.py` (`matches_object_filter`'s `is_suspected` key), `game/ability_catalogue/entries_005.py` (Gilded Drake's explicit `optional=True`), `parser/oracle/catalogue/handlers.py` (every new row named above), `parser/oracle/catalogue/subgrammars.py` (`land_you_control`/`land_you_dont_control` TARGET rows, `DEVOTION`'s `creatures_died_this_turn` branch), `parser/oracle/catalogue/handlers.py`'s `_pay_cost_then_general` (`self_subject=True` on its recursive follow-up parse).

### MEC-93 · Clash (RULE 701.30) (PAR-29, PARSER_VERSION 115) + win-branch residue batch 1 (PAR-30, PARSER_VERSION 147)

- **What:** The Lorwyn/Shadowmoor keyword action, and the biggest single item left in the PAR-29 "needs an engine primitive first" list by cache count.
- **Files:** `models/events.py`, `game/rules/misc_mixin.py` (`clash`), `game/effects/core.py` (`ClashEffect` + `EffectRegistry`, `GameContext.clash_won`, `_apply_effects_partitioned` save/restore, `ConditionalEffect._condition_holds`'s `clash_won` key), `game/binding/core.py` (`_GROUP_CONTROLLER_EVENT_KEYS`), `parser/oracle/spec.py` (`_ALLOWED_CONDITION_KEYS` + bool check), `parser/oracle/segmenter.py` (`_IF_YOU_WIN_CLASH_RE` / `_OTHERWISE_CLASH_RE` + `_PLAYER_TRIGGER_CONDITIONS`), `parser/oracle/catalogue/handlers.py` (`_clash`), `parser/oracle/gate.py` (PARSER_VERSION 115).

### Firebending — printed-keyword behaviour (RULE ~702.189) (PAR-29)

- **What:** "Firebending N" (Doctor Who) was parser-*recognized* (`keywords.py` `_N` shape) but inert.
- **Files:** `game/binding/core.py` (`_kw_firebending`, `_KEYWORD_TRIGGERED_BUILDERS`, `AddManaEffect` import).
- **What:** every real Firebending card *grants* the keyword — "target creature you control gains firebending N until end of turn" (Fire Nation Palace), "creatures you cont…
- **What:** the last open sub-bullet of PAR-29's parser trail — Avatar Aang's "Whenever you waterbend, earthbend, firebend, or airbend, draw a card.

### Time Travel (RULE 701.56) (PAR-29, PARSER_VERSION 127)

- **What:** The Doctor Who keyword action.
- **Files:** `game/rules/misc_mixin.py` (`time_travel`), `game/effects/core.py` (`TimeTravelEffect` + `EffectRegistry`), `parser/oracle/catalogue/handlers.py` (inline `EffectHandler`), `parser/oracle/gate.py` (PARSER_VERSION 127).

### Face a Villainous Choice (RULE 701.55) (PAR-29 / MEC-94, PARSER_VERSION 126)

- **What:** The Doctor Who forced-modal-on-an-opponent action.
- **Files:** `game/rules_engine.py` (`_pending_villainous`), `game/rules/misc_mixin.py` (`request_villainous_choice`/`_advance_villainous_choice`/`resolve_villainous_choice`), `game/engine/turn_loop_mixin.py` (dispatch), `game/effects/core.py` (`FaceVillainousChoiceEffect` + `EffectRegistry`), `parser/oracle/catalogue/handlers.py` (`_VILLAINOUS_HEADER_RE`/`_villainous_option_specs`/`_face_villainous_choice` + `EffectHandler`; `_inline_create_token_params` `who` fix), `parser/oracle/gate.py` (PARSER_VERSION 126).
- **What:** the shipped `face_villainous_choice` / `vote` parsers only claim a card when *every* option/outcome body is modelable.

### Reanimator-token residue — the graveyard-exile-copy cluster (PAR-30 close-out, PARSER_VERSION 216)

- **What:** three cards the ENG-33 connector (above) left `UNMODELED`, each on a small gap around a `CopyPermanentEffect` primitive that already existed.
- **Files:** `game/targeting.py` (`_GRAVEYARD_TYPE_FILTERS["non_aura_enchantment"]`, `_GRAVEYARD_TYPE_LABELS`), `game/effects/core.py` (`CreateTokenEffect.count_from_context` + `_TOKEN_COUNT_CONTEXT_ACCUMULATORS` + its `EffectRegistry` entry), `parser/oracle/catalogue/handlers.py` (`_GRAVEYARD_TYPE_WORD`, `_graveyard_target_kind`, `_COPY_EXCEPT_PT_RE` + `_copy_except_modifier`), `parser/oracle/segmenter.py` (`_EXILE_X_GY_FOR_EACH_CREATE_RE` + its `parse_effect_body` branch), `parser/oracle/gate.py` (PARSER_VERSION 216).

### Vote (RULE 701.38) (PAR-29, PARSER_VERSION 124) + outcome bodies that needed new primitives (MEC-46, PARSER_VERSION 173)

- **What:** The Conspiracy / "Will of the Council" / "Council's Dilemma" voting subsystem.
- **Files:** `models/game_state.py` (`_pending_vote`/`_pending_object_vote` — actually on `RulesEngine.__init__`, `game/rules_engine.py`; `forced_vote_controller_id`), `game/rules/misc_mixin.py` (`request_vote`/`_advance_vote`/`_vote_decider`/`resolve_vote_choice`/`_tally_and_apply_vote`/`_advance_expropriate_gain_control`/`request_object_vote`/`_advance_object_vote`/`resolve_object_vote_choice`/`_tally_and_apply_object_vote`; `CHOOSE_OBJECT_ACTIONS` + `_apply_chosen_object` `gain_control`), `game/engine/turn_loop_mixin.py` (`vote`/`vote_object` dispatch; `_step_cleanup` clears `forced_vote_controller_id`), `game/effects/core.py` (`VoteEffect.winner_specs`, `ObjectVoteEffect`, `SetForcedVoterEffect`, `ExpropriateGainControlEffect`, `TakeExtraTurnEffect.count`, `GrantUntilEffect.self_subject`, `AddCountersEffect.ring_bearer` + `EffectRegistry`), `game/static_conditions.py` (`another_subtype_entered_this_turn`), `parser/oracle/catalogue/handlers.py` (`_vote_winner_protection`/`_vote_object`/`_vote_expropriate`/`_forced_vote`/`_add_counters_ring_bearer` + `EffectHandler`s), `parser/oracle/segmenter.py` (`_ANOTHER_SUBTYPE_ENTERED_IF_RE` in the phase-trigger branch), `parser/oracle/gate.py` (PARSER_VERSION 124 → 173), `services/bots.py` (`Bot.answer_choice` random vote), `frontend/src/js/gameBoardView.js` (`CHOICE_ICONS`, `vote_object` thumbnails).

### Airbend (RULE 701.65) (PAR-29, PARSER_VERSION 123) + qualifier widening & trigger-subject form (PAR-30, PARSER_VERSION 144) + airbend-a-spell — PAR-30 Airbend residue cluster closed (PARSER_VERSION 145)

- **What:** The second Avatar: The Last Airbender bending action.
- **Files:** `models/game_state.py` (`exile_cast_cost_override`), `game/effects/core.py` (`ExileEffect.owner_play_permission_cost` + registry passthrough; v144 `_post_exile` helper shared by the trigger-subject branch; v145 `ExileEffect.spell_or_permanent` + stack-spell branch + registry passthrough), `game/engine/casting_mixin.py` (`effective_cast_cost`), `parser/oracle/catalogue/handlers.py` (`_AIRBEND_RE`/`_airbend`, v144 widening + v145 `or spell` tail; `_AIRBEND_TRIGGER_SUBJECT_RE`/`_airbend_trigger_subject` + `EffectHandler`s), `parser/oracle/gate.py` (PARSER_VERSION 123 / 144 / 145).

### Waterbend (RULE 701.67) (ENG-32 / MEC-96, PARSER_VERSION 131) + optional-additional-cost-paid tracker (PAR-30, PARSER_VERSION 155)

- **What:** the last of the "bending quartet".
- **Files:** `parser/oracle/segmenter.py` (`_DRAW_CARD_TRIGGER_NTH_RE` + dispatch, `_ADDITIONAL_COST_WATERBEND_RE` `{X}`), `parser/oracle/catalogue/subgrammars.py` (`permanent_you_control` + `other target nonland permanent` rows), `parser/oracle/catalogue/handlers.py` (`_TAP_TARGET_KINDS`), `game/engine/legal_actions_mixin.py` (`has_x` off a mandatory variable additional cost), `parser/oracle/gate.py` (v215).

### Earthbend (RULE 701.66) (PAR-29, PARSER_VERSION 122) + dynamic X & pronoun tail (PAR-30, PARSER_VERSION 134) + "When you do" collapse (PAR-30, PARSER_VERSION 142) + dying-subject power X (PAR-30, PARSER_VERSION 143) + Earthshape hand-authored — PAR-30 Earthbend residue cluster closed

- **What:** The Avatar: The Last Airbender keyword action — the first of the "bending quartet" built.
- **Files:** `game/rules/mana_counters_mixin.py` (`earthbend`), `game/rules/damage_death_mixin.py` (`power=obj.power` on the DIES `GameEvent`, v143), `game/effects/core.py` (`EarthbendEffect` + `EffectRegistry`; `PumpEffect`'s `selector`-group branch now honours `creature_filter`, Earthshape), `game/binding/core.py` (`_build_group_ok`'s `want_nonland`, v143), `game/continuous.py` (`creature_cards_in_your_graveyard` was v133), `game/ability_catalogue/entries_016.py` (`_earthshape`), `parser/oracle/segmenter.py` (`_announces_creature_target` earthbend recognition; `_EARTHBEND_THEN_WHEN_YOU_DO_RE` + its `parse_effect_body` dispatch, v142; `_GROUP_SUBJECT_RE`'s `nonland` qualifier, v143), `parser/oracle/catalogue/handlers.py` (`_earthbend`, `_earthbend_x`/`_EARTHBEND_X_RE`, `_EARTHBEND_THAT_CREATURES_POWER_RE`/`_earthbend_that_creatures_power`, `_TAP_PREVIOUS_SUBJECT_RE`/`_tap_previous_subject` + `EffectHandler`s), `parser/oracle/gate.py` (PARSER_VERSION 122 / 134 / 142 / 143).

### Blight (RULE 701.68) — cost forms (PAR-29, PARSER_VERSION 121)

- **What:** The Bloomburrow keyword action's *cost* integration (the standalone-verb effect form — `effects.BlightEffect` / `RulesEngine.blight` opening a `blight` `pending…
- **Files:** `game/costs.py` (`blight` field, `_BLIGHT_RE`), `game/rules/mana_counters_mixin.py` (`blight` `interactive` param, `blight_possible`), `game/rules/misc_mixin.py` (`_can/_pay_player_cost`), `game/engine/activation_mixin.py` (`_can/_pay_activation_cost`), `game/engine/casting_mixin.py` (`_pay_additional_cast_cost`), `parser/oracle/spec.py` (`_validate_additional_cost`), `parser/oracle/segmenter.py` (`_ADDITIONAL_COST_BLIGHT_RE`, `_additional_cost_dict`), `parser/oracle/catalogue/handlers.py` (`_MAY_COST_THEN_CLAUSE`, `_PAY_COST_THEN_OR_ELSE_RE`, `_pay_cost_then_or_else`), `parser/oracle/gate.py` (PARSER_VERSION 121).

### Behold (RULE 701.4) (PAR-29, PARSER_VERSION 120)

- **What:** The Tarkir: Dragonstorm keyword action, reached in the current card pool only as an *additional cast cost* — "As an additional cost to cast this spell, behold a…
- **Files:** `models/events.py` (`BEHELD`), `game/costs.py` (`behold` field + `is_free`/`label`/`to_dict`/`parse_activation_cost`), `game/rules/misc_mixin.py` (`behold`), `game/engine/casting_mixin.py` (`_can/_pay_additional_cast_cost`), `game/binding/core.py` (`_GROUP_CONTROLLER_EVENT_KEYS`), `parser/oracle/spec.py` (`_validate_additional_cost` `behold` key), `parser/oracle/segmenter.py` (`_ADDITIONAL_COST_BEHOLD_RE`, `_additional_cost_dict`, `_PLAYER_TRIGGER_CONDITIONS`, ungated `_ADDITIONAL_COST_LINE_RE`), `parser/oracle/gate.py` (PARSER_VERSION 120).

### Forage (RULE 701.61) (PAR-29, PARSER_VERSION 119)

- **What:** The Bloomburrow cost mechanic, and the direct sibling of Collect Evidence's build one version earlier.
- **Files:** `models/events.py`, `game/costs.py`, `game/rules/misc_mixin.py` (`forage` / `forage_possible`, `_can/_pay_player_cost`), `game/engine/activation_mixin.py`, `game/effects/core.py` (`ForageEffect` + `EffectRegistry`), `game/binding/core.py`, `parser/oracle/segmenter.py`, `parser/oracle/catalogue/handlers.py` (`_MAY_COST_THEN_CLAUSE`, `_forage_bare`, `_forage`), `parser/oracle/gate.py` (PARSER_VERSION 119).

### Additional cast cost: "exile N [<type>] cards from your graveyard" (PAR-41, PARSER_VERSION 234)

- **What:** RULE 601.2b's "As an additional cost to cast this spell, exile N [creature] cards from your graveyard." — the Innistrad Skaab family (Cobbled Lancer / Headless…

### PAR-41 residue: X-scaled non-mana additional costs (v367)

- **What:** `discard X cards` and `exile X [creature] cards from your graveyard` now share the announced spell X with mana and pay-X-life costs.
- **Files:** `game/costs.py` (`exile_from_graveyard_filter` field, dict-path branch, `to_dict`), `game/engine/casting_mixin.py` (`_graveyard_exile_cost_candidates`, `_can_pay_/_pay_additional_cast_cost` branches), `parser/oracle/segmenter.py` (`_ADDITIONAL_COST_EXILE_GRAVEYARD_RE`, `_additional_cost_dict`), `parser/oracle/spec.py` (`_validate_additional_cost` `exile_from_graveyard` key), `parser/oracle/gate.py` (PARSER_VERSION 234).

### Collect Evidence (RULE 701.59) (PAR-29, PARSER_VERSION 118)

- **What:** The Murders at Karlov Manor cost mechanic.
- **Files:** `models/events.py`, `game/costs.py` (`collect_evidence` field, `_COLLECT_EVIDENCE_RE`, `is_free`/`describe`/`to_dict`/`from_dict`), `game/rules/misc_mixin.py` (`collect_evidence` / `collect_evidence_possible`, `_can/_pay_player_cost`), `game/engine/activation_mixin.py` (`_can/_pay_activation_cost`), `game/effects/core.py` (`CollectEvidenceEffect` + `EffectRegistry`), `game/binding/core.py` (`_GROUP_CONTROLLER_EVENT_KEYS`), `parser/oracle/segmenter.py` (`_PLAYER_TRIGGER_CONDITIONS`), `parser/oracle/catalogue/handlers.py` (`_MAY_COST_THEN_CLAUSE`, `_collect_evidence_bare`, `_collect_evidence`), `parser/oracle/gate.py` (PARSER_VERSION 118).

### Learn (RULE 701.48) (PAR-29, PARSER_VERSION 117)

- **What:** The Strixhaven keyword action.
- **Files:** `game/rules/misc_mixin.py` (`learn`), `game/effects/core.py` (`LearnEffect` + `EffectRegistry`), `parser/oracle/catalogue/handlers.py` (`_learn` + `EffectHandler`), `parser/oracle/gate.py` (PARSER_VERSION 117).

### Incubate (RULE 701.53) — literal `incubate N` (PAR-29 / MEC-95, PARSER_VERSION 116) + dynamic X (PAR-30, PARSER_VERSION 133 / 160 / 162) + residue closed (PAR-30, PARSER_VERSION 205)

- **What:** "Incubate N" — create an Incubator token (a power/toughness-less colourless artifact token) with N +1/+1 counters on it.
- **Files:** `parser/oracle/catalogue/handlers.py` (`_incubate`, `_incubate_x`/`_INCUBATE_X_RE`, `_exile` kind list, `_counter` reflexive tail, `_IF_PREV_CREATURE_CANT_BLOCK_RE`), `parser/oracle/catalogue/subgrammars.py` (`_SPELL_TYPE_WORD` + `"battle"`), `parser/oracle/segmenter.py` (`_CAST_SPELL_TARGETS_PERMANENT_TRIGGER_RE`), `parser/oracle/spec.py` (`previous_target_is_creature`), `game/effects/core.py` (`GameContext.objects_exiled_this_way` + `exile`, `_characteristic_of_subject`, `_apply_effects_partitioned`, `CreateTokenEffect._resolve_extra_counter_amount` + `creators`, `CounterSpellEffect.on_pay_effect_specs`, `CantBlockEffect.previous_subject`, `RevealHandChooseDiscardEffect.optional`/`else_specs`, `SearchLibraryEffect.track_exiled_with`, `GameContext.choose_objects`/`request_search` passthroughs), `game/rules/casting_mixin.py` (deferred-resume threading, `_targets_a_permanent`), `game/rules/misc_mixin.py` (`counter_unless_pays` on-pay specs, `request_choose_objects`/`_choose_objects_choice`/`resolve_choose_objects_choice` `else_specs`), `game/rules/search_mixin.py` (`track_exiled_with` through `request_search`/`_search_choice`/`_finish_search`), `game/binding/core.py` (`requires_spell_targets_permanent` predicate), `game/continuous.py` (`creature_cards_in_your_graveyard`, `source_x_paid` selectors), `game/targeting.py` (`_spell_matches_filter` `"battle"`, `incubator_token_you_control` kind), `game/ability_catalogue/entries_016.py` (`_traumatic_revelation`, `_phyrexian_incubator`, `_progenitor_exarch`), `parser/oracle/gate.py` (PARSER_VERSION 116 / 133 / 160 / 162 / 205).

### Reproducible random numbers (RULE 705/706)

- **What:** `RulesEngine.random_int`/`random_choice`/`coin_flip` draw off `GameState`'s own `(rng_seed, rng_counter)` pair, so randomness survives clone/undo/rewind determi…
- **Files:** `game/rules_engine.py`, `models/game_state.py`

### RULE 400.7 "new object" identity reset (blink / return from graveyard)

- **What:** New `GameObject.reset_as_new_object()` is the single shared fix point clearing counters, attachment linkage, control/copy state, cast-time flags, combat state,…
- **Files:** `models/game_object.py`, `game/rules_engine.py`

### Targeted "target player gains/loses N life"

- **What:** `GainLifeEffect` gained an opt-in `target_kind`, mirroring `LoseLifeEffect`'s existing one, so a targeted life-total clause isn't misread against a shared multi…
- **Files:** `game/effects/core.py`, `parser/oracle/catalogue/handlers.py`

### Exile Target Player's Graveyard

- **What:** `ExileTargetGraveyardEffect` targets one player and empties their whole graveyard (Bojuka Bog), distinct from single-card graveyard exile and the untargeted "ex…
- **Files:** `game/effects/core.py`, `parser/oracle/catalogue/handlers.py`

### Counter-Family Parser Additions (Spells)

- **What:** Spell target filters (noncreature/card-type list/mana-value on `TargetSpec.spell_filter`), "unless its controller pays `{…}`" via a `counter_unless_pays` intera…
- **Files:** `parser/oracle/catalogue/handlers.py`, `game/effects/core.py`

### New One-Shot Effect Families (Bounce/Recursion/Tutor/Mass Damage/Self-Attach)

- **What:** One parser-expansion wave added return-to-hand (bounce), graveyard recursion (new `graveyard_creature`/`creature_you_control`/`land_you_control` target kinds),…
- **Files:** `parser/oracle/catalogue/handlers.py`, `game/effects/core.py`

### Generalized "Search Your Library for X" Grammar (RULE 701.19)

- **What:** `SearchLibraryEffect`/`RulesEngine.request_search` was already generic (criteria, destination, count); parser recognition was widened to combine criteria phrase…
- **Files:** `game/effects/core.py`, `game/rules/search_mixin.py`, `parser/oracle/catalogue/handlers.py`

### Mass "Destroy/Exile All X" Board Wipes

- **What:** `DestroyEffect`/`ExileEffect` gained a `selector` (`all_creatures`/`all_artifacts`/`all_enchantments`/`all_permanents`/`all_planeswalkers`) plus an optional fil…
- **Files:** `game/effects/core.py` (`_MASS_DESTROY_SELECTORS`, `_mass_selector_objects`), `parser/oracle/catalogue/handlers.py`

### New One-Shot Effect Batch (Wyleth Equip)

- **What:** A cluster of one-off effect classes each backing one clause shape: `ExileGainLifeToControllerEffect` (Swords to Plowshares), `TargetPlayerDrawLoseLifeEffect` (S…
- **Files:** `game/effects/core.py`

### Impulsive-Look Effect

- **What:** "Look at the top N cards, take one matching a filter, put the rest into Y" (Grisly Salvage/Commune with the Gods-shaped) — a new `ImpulsiveLookEffect`/`RulesEng…
- **Files:** `game/effects/core.py`, `game/rules_engine.py`

### Impulsive Draw (Exile + Temporary Play Permission)

- **What:** "Exile, you may play until the end of your next turn" (Light Up the Stage-shaped): `GameState.temp_play_permissions` (instance_id → turn granted) since the card…
- **Files:** `game/rules_engine.py`, `game/game_engine.py`

### Impulsive Draw's Dual-Player Extension + Mana-Wildcard Permission

- **What:** `GameState.temp_play_permission_player` extends impulsive draw to a permission granted to a *different* player than the exiling one (Ragavan's per-firing combat…
- **Files:** `game/rules_engine.py`, `game/game_engine.py`, `models/mana_pool.py`

### ENG-1: Re-Validate Attachment Legality Every SBA Pass

- **What:** RULE 704.5m/n (an illegally-attached Aura/Equipment) had only ever been checked when a host *left* the battlefield.
- **Files:** `game/rules/sba_mixin.py`, `game/combat.py`

### ENG-2: Interactive Sacrifice Choice for `SacrificeEffect`

- **What:** RULE 701.17's "player sacrifices N permanents matching `<type>`" (Annihilator) now funnels through `request_choose_objects` instead of auto-picking the first ma…
- **Files:** `game/rules_engine.py`, `game/effects/core.py`
- **Why:** `greatest_power` (Professor Onyx) deliberately keeps its own recompute-after-each-removal `max()` auto-pick rather than routing through the chooser, since no sh…

### Turn/phase/step loop, event system

- **What:** `run_turn` walks the `TurnSequence`, runs each step body (untap, first-turn draw-skip, combat damage, cleanup discard-to-7), opens priority windows, and empties…
- **Files:** `game/game_engine.py`

### Mulligan/setup phase gating

- **What:** `GameSession(require_setup=True)` starts a goldfish game with only `mulligan`/`keep_hand` legal until every card is kept; `mulligan` reshuffles and draws a fres…
- **Files:** `services/game_session.py`

### Structured internal turn and player-facing Turn_Nr

- **What:** `GameState.internal_turn` carries the sequential internal turn number, the player-facing `turn_nr` (one complete circuit around the table), and the active playe…
- **Files:** `game/engine/turn_loop_mixin.py`, `models/game_state.py`, `services/dynamic_analysis.py`, `services/replay.py`, `services/game_session.py`

### First-draw-skip fixed for 3+ player pods (RULE 103.8c)

- **Files:** `game/game_engine.py`

### Vancouver mulligan + interactive scry

- **What:** `RulesEngine.scry` became a real two-phase interactive `pending_choice` (repeated bottom question, then a repeated order question, each independently declinable…
- **Files:** `game/rules_engine.py`, `services/game_session.py`
- **Why:** Vancouver had been deliberately left unbuilt until scry had a real effect, since its whole point is the resulting choice.

### Two-way control exchange (RULE 701.10)

- **What:** A genuine one-shot two-way controller swap (Gilded Drake) — distinct from the layer-2 `control_change` static and the duration-bounded `GainControlUntilEndOfTur…
- **Files:** `game/effects/core.py`

### Mass phasing + life-total lock (Teferi's Protection)

- **What:** Mass phasing (RULE 702.26b) phases host and attachment out together (unlike the single-permanent `PhaseOutEffect`, which unattaches); `PlayerShieldEffect` adds…
- **Files:** `game/effects/core.py`

### Pulling a spell off the stack (RULE 400.1)

- **What:** `RulesEngine.move_spell_off_stack` moves a `StackItem` into hand or exile — no existing bounce effect could touch the stack, only battlefield permanents; practi…
- **Files:** `game/rules_engine.py`

### Cloudstone Curio bounce + hand-to-battlefield tutoring

- **What:** `ReturnSharedTypePermanentEffect` computes its legal-return set dynamically off the entering permanent (Cloudstone Curio); `PutFromHandOntoBattlefieldEffect` re…
- **Files:** `game/effects/core.py`

### Naming a card (unenumerable choice)

- **What:** `RulesEngine.request_name_card` — the only choice in the engine whose answer space isn't enumerable from game state; offers visible cards as suggestions while a…
- **Files:** `game/rules_engine.py`

### `dig_until` — parameterized cascade-style dig

- **What:** The cascade/discover dig generalized with a predicate and both destinations as parameters, plus a `not_name` key on card-query criteria.
- **Files:** `game/rules_engine.py`

### Repeat-until-a-predicate loop (Helm of Obedience)

- **What:** `MillUntilCreatureEffect` — the first "repeat until a predicate is met" loop primitive; bounded on both sides by construction (X caps it, an empty library ends…
- **Files:** `game/effects/core.py`

### Open-ended pay-life loop (Lim-Dûl's Vault)

- **What:** `request_look_top_pay_life_loop` — the first open-ended loop primitive, bounded only by the player's own life payment (RULE 118.4) rather than a safety cap, dri…
- **Files:** `game/rules_engine.py`

### Scramble-the-spell effect (Possibility Storm, Tibalt's Trickery)

- **What:** `ScrambleSpellEffect` — one atomic effect for "exile the spell, then reveal/dig for a replacement and cast it" since every clause concerns the same spell and it…
- **Files:** `game/effects/core.py`

### Bespoke wave-6 effects (Dauntless Dismantler, Tevesh Szat, Jeska, loyalty -X)

- **What:** `DestroyEachWithManaValueEffect` (mass destroy filtered by the announced X); `SacrificeEffect` gained `each_opponent`/`greatest_power` selectors; `GainControlOf…
- **Files:** `game/effects/core.py`, `game/costs.py`

### RULE 608.2 suspended resolutions (`deferred_effects`)

- **What:** `GameState.deferred_effects` parks the remainder of a multi-clause resolution's effect list whenever an earlier effect opens an interactive choice, and `RulesEn…
- **Files:** `game/effects/core.py`, `game/rules_engine.py`

### Conditional search destinations (RULE 701.19c)

- **What:** `SearchLibraryEffect.destination_if` is a list of `{criteria, destination}` rules checked per found card, resolved only once the player names what they found —…
- **Files:** `game/effects/core.py`

### Face-down exile round trip (RULE 701.20a)

- **What:** A search destination of `"exile_face_down"` sets `GameObject.face_down_in_exile` (the first real use of the board's sleeve-art fallback); `CastExiledFaceDownEff…
- **Files:** `game/effects/core.py`, `game/rules_engine.py`

### General interactive object chooser

- **What:** `RulesEngine.request_choose_objects` replaced the "auto-pick the first candidate" convention across seven cards at once — every effect naming what kind of objec…
- **Files:** `game/rules_engine.py`

### Minor gap-fills found during Batch 26

- **Files:** `game/effects/core.py`, `game/rules_engine.py`

### `request_each_player_pay_or` (PAR-13, RULE 101.4 APNAP "unless")

- **What:** "Each player loses N life unless they `<pay cost>`." (Veils of Fear, Sandfall Cell) as a chained sequence of the existing single-player `request_pay_cost_then`…
- **Files:** `game/rules_engine.py`, `game/costs.py`

### RULE 119/701.8 hand-disruption "reveal, choose, discard"

- **What:** Duress/Thoughtseize-shaped — the caster (not the hand's owner) chooses which revealed card gets discarded, reusing the existing `request_choose_objects` chooser…
- **Files:** `game/effects/core.py`, `parser/oracle/catalogue/handlers.py`

### `RevealTopConditionalToHandEffect`

- **What:** RULE 701.28's "defending player reveals the top card… if it's a land, puts it into their hand" (Goblin Guide) — reveal itself has no separate game state, so the…
- **Files:** `game/effects/core.py`

### Miscellaneous small primitives (Imodane final singles batch)

- **What:** `CopySpellEffect.target_count`/`optional` ("copy any number of target spells", Display of Power); `AddManaEffect.target_kind`/`amount_from_target_hand_size` (Je…
- **Files:** `game/effects/core.py`, `game/rules_engine.py`, `game/targeting.py`

### RULE 119 "drain" idiom — life-lost-this-way accumulator (Rules Engine Core Loop)

- **What:** `GameContext.life_lost_this_way`, a per-resolution accumulator (the same save/reset/restore idiom as `previous_targets`/`created_objects`), incremented by `Game…
- **Files:** `game/effects/core.py`, `game/rules/misc_mixin.py`

### Grafdigger's Cage / Weathered Runestone Graveyard-Library Prohibition

- **What:** `continuous.graveyard_library_cast_prohibited` is one choke point in `GameEngine.can_cast` covering Flashback/Escape/Lurrus-shaped grants/top-of-library casting…
- **Files:** `game/continuous.py`, `game/effects/core.py`, `game/rules/misc_mixin.py`.

### Force-End-the-Turn (Day's Undoing)

- **What:** `GameState.end_turn_requested` + `GameEngine.advance_step`'s drain — a `RulesEngine` effect can't reach the turn-loop cursor directly, so `end_the_turn` exiles…
- **Files:** `models/game_state.py`, `game/engine/turn_loop_mixin.py`, `game/rules_engine.py`.

### Mass Board-Wipe Damage Selectors (Opponents + Their Permanents)

- **What:** `DealDamageEffect.selector`'s new `each_opponent_and_their_creatures[_and_planeswalkers]` (opponents-only, unlike the existing global `each_creature_and_player`…
- **Files:** `game/effects/core.py`, `parser/oracle/catalogue/handlers.py`.

### "~ deals N damage to you" self-damage (PAR-38, v229)

- **What:** `_SELECTOR_WORD_MAP` and the `damage_selector` handler's regex alternation gained `"you" → "controller"`, routing to `DealDamageEffect`'s pre-existing `"control…

### PAR-38 residue: scaled upkeep damage and conditional draw-step skip (v366)

- **What:** `DealDamageEffect` now multiplies a live `count_selector`, with a `treasures_you_control` selector for Black Market Tycoon; the self-scoped `unless you pay` tem…
- **Files:** `parser/oracle/catalogue/handlers.py`.

### "Skip your draw step." oracle-text route (PAR-38, v229)

- **What:** `static_handlers._SKIP_YOUR_STEP_RE` → `EffectSpec("skip_step", {"step": "draw"})` — the oracle-text front-end for MEC-38's already-shipped self-scoped step-ski…
- **Files:** `parser/oracle/catalogue/static_handlers.py`.

### Search/Extra-Turn Prohibition Grants (Stranglehold)

- **What:** `GrantSearchProhibitedEffect`/`RulesEngine.request_search`'s guard (RULE 701.19a: a prohibited player instructed to search simply doesn't) and `GrantSkipExtraTu…
- **Files:** `game/effects/core.py`, `game/engine/turn_loop_mixin.py`.

## Targeting

### Structural target frames — `kind` decomposed (ENG-34, `14_` S0b)

- **What:** `TargetSpec.kind` was 59 opaque strings dispatched by **58**
- **Files:** `game/targeting.py`, `tests/test_target_frames.py` (153 tests)

### Generalized graveyard-card targeting and Deathrite Shaman

- **What:** The Regrowth/Reanimate recursion family generalized to the full real-card vocabulary (card type × graveyard scope — own/any/an opponent's).
- **Files:** `game/targeting.py`, `parser/oracle/catalogue/handlers.py`

### "Up to one" targets (RULE 115.1a, N=1)

- **What:** The shared `TARGET` regex fragment grew an optional "up to one" prefix consumed by `TargetSpec(optional=True)`, so every existing `{TARGET}`-based handler recog…
- **Files:** `parser/oracle/catalogue/subgrammars.py`, `parser/oracle/spec.py`
- **Why:** Deliberately N=1 only — "up to two/three/N" needs a genuinely bigger interactive multi-select feature, since the engine's `targets` list is one entry per target…

### Divided damage (RULE 601.2d)

- **What:** `DealDamageEffect(divided=True)` splits a total {X} pool evenly across the chosen targets, with an optional doubling threshold (`double_at`) — Shatterskull Smas…
- **Files:** `game/effects/core.py`

### "Target creature with power/toughness/keyword" targeting filter

- **What:** New `TargetSpec.creature_filter` narrows `DestroyEffect`/`ExileEffect`'s target pool by power/toughness threshold or a closed keyword list (flying, first strike…
- **Files:** `game/targeting.py`, `parser/oracle/catalogue/handlers.py`

### N>=2 Multi-Target Generalization (RULE 115.1a)

- **What:** `TargetSpec` gained a `count` field (`optional` becoming the 0-vs-`count` lower bound); `DestroyEffect`/`ExileEffect`/`DealDamageEffect` gained a matching `coun…
- **Files:** `game/targeting.py`, `game/effects/core.py`, `parser/oracle/catalogue/handlers.py`
- **Why:** Slicing off the front of a *shared* list (not consuming the whole thing) was needed so an unrelated single-target effect on the same stack item isn't over-consu…

### Per-Effect Target Partitioning (`StackItem.target_groups`)

- **What:** A stack item's `targets` list used to be shared flat across every effect on it, so two *different* targeting effects on one spell/ability would have the second…
- **Files:** `models/game_state.py` (StackItem), `game/effects/core.py`, `game/rules_engine.py`, `game/game_engine.py`
- **Why:** `None` (the default) keeps every pre-existing flat-`targets` consumer byte-for-byte unaffected — this is additive, not a rewrite.

### New Target Kinds (Wyleth Equip Batch)

- **What:** `nonbasic_land` (Encroaching Wastes), `attached_equipment_you_control`/`equipment_you_control` (Akiri's unattach / Nahiri, Heir of the Ancients' +1).
- **Files:** `game/targeting.py`

### N>=2 Multi-Target for `return_to_hand`/`tap`/`add_counters`/`return_from_graveyard`

- **What:** The existing `count`-slicing idiom extended to four more effect families.
- **Files:** `game/effects/core.py`, `parser/oracle/catalogue/handlers.py`

### Compound Creature-Target Filter

- **What:** "power 4 or greater and flying" — `TargetSpec.creature_filter` already ANDed every dict key; the gap was purely that the parser only ever emitted one key.
- **Files:** `parser/oracle/catalogue/handlers.py`

### Cross-Target "Controlled by Different Players"

- **What:** `TargetSpec.distinct_controllers` (Protector of the Wastes-shaped) constrains the *relationship* between targets chosen for one requirement — enforced at offer/…
- **Files:** `game/targeting.py`, `game/game_engine.py`

### Pronoun Bound to Previous Clause

- **What:** `GameContext.previous_targets` records what the last *targeting* effect actually chose, so a later clause can name it with `previous_target`/`previous_target_2`…
- **Files:** `game/effects/core.py`

### Per-Effect Target Partitioning for Spell/Ability Casting (ENG-5)

- **What:** `targeting.partition_targets` splits a flat, in-printed-order target list into one group per requirement, derived automatically by `_cast_current_face`/`activat…
- **Files:** `game/targeting.py`, `game/game_engine.py`

### RULE 109.5 Cross-Requirement "Another"

- **What:** `TargetSpec.distinct_from_others` excludes a sibling requirement's own pick ("target creature you control fights **another** target creature") — an offer-time e…
- **Files:** `game/targeting.py`, `game/effects/core.py`

### Goad Target Count Read Off the Board

- **What:** "For each opponent, goad up to one target creature that player controls" combines a `TargetSpec.count_selector` (RULE 601.2c, resolved at announce time) with th…
- **Files:** `game/targeting.py`, `game/rules_engine.py`

### Naming What the Previous Clause Created

- **What:** `GameContext.created_objects` (sibling of `previous_targets`) lets a later clause refer to tokens a previous clause in the same resolution just made, which were…
- **Files:** `game/effects/core.py`

### Equip/Fortify/Reconfigure control restriction fix

- **Files:** `game/targeting.py`, `game/rules_engine.py`

### "Another creature you control" target kind

- **Files:** `game/targeting.py`

### Two independently-chosen targets in one clause

- **What:** `GameEffect.extra_target_specs` lets one effect gather 2+ independently-typed targets in a single clause (Brass Squire, Halvar, Archdruid's Charm's second mode)…
- **Files:** `game/effects/core.py`

### RULE 115.1a "any number of target `<X>`" (PAR-15 + residue)

- **What:** `catalogue.handlers._MULTI_TARGET_QUANTIFIER` gained an "any number of" alternative (capped at 10, `optional=True`), widening nine existing multi-target handler…
- **Files:** `parser/oracle/catalogue/handlers.py`, `game/effects/core.py`, `game/rules_engine.py`

### Polarity-aware targeting classification (PLR-7/PLR-8)

- **What:** `GameEffect.target_polarity()` classifies an effect as `"harmful"`/`"beneficial"`/`None` (best-effort, non-rules), including sign-aware classification for `Pump…
- **Files:** `game/effects/core.py`, `game/targeting.py`, `services/bots.py`

### Saved-deck-priority parser batch: mass "destroy/exile all X" board wipes (PAR-12)

- **What:** The engine primitive already existed (hand-authored per card); no parser handler recognized the general English phrasing.
- **Files:** `parser/oracle/catalogue/handlers.py`

### General N-way "target artifact, enchantment[, or land]" (PAR-12, RULE 115)

- **What:** One general regex covering any 2+ combination of artifact/creature/enchantment/land/planeswalker, mapping to the existing broad `"permanent"` target kind, rathe…
- **Files:** `parser/oracle/catalogue/subgrammars.py`

### Mass-destroy power filter + negated creature filters (Hobbits batch)

- **What:** `min_power`/`max_power` joined the pre-existing mana-value/toughness mass-destroy filters (Elspeth, Sun's Champion).
- **Files:** `game/effects/core.py`, `game/combat.py`

### Filtered creature-target family widenings + `creature_filter` bug fix

- **What:** `RulesEngine.blink` gained a `controller` param (Restoration Angel's "under your control" vs.
- **Files:** `game/rules_engine.py`, `game/combat.py`, `game/effects/core.py`, `game/targeting.py`

### RULE 115.4 "change the target of target spell" (cEDH second pass)

- **What:** A live retarget of an already-existing stack item — genuinely distinct from the pre-existing "choose new targets for a freshly-made copy" (RULE 707.10c).
- **Files:** `game/effects/core.py`, `game/rules/misc_mixin.py`, `game/targeting.py`, `game/ability_catalogue.py`

### RULE 115/608.2b "target an activated or triggered ability" (ENG-26)

- **What:** `StackItem.stack_id` gives every stack item (spell or ability alike) a stable identity, backing two new targeting kinds (`"ability"`, `"spell_or_ability"`).
- **Files:** `models/game_state.py`, `game/targeting.py`, `game/rules/misc_mixin.py`, `game/ability_catalogue.py`
- **Why:** An ability `StackItem`'s own `.obj` is `None` (the permanent lives on `.source` instead), so nothing could previously name "an ability on the stack" as a target…

### Otawara, Soaring City + four-permanent-type union target (Targeting)

- **What:** Otawara hand-authored reusing Eiganjo/Boseiju's existing Channel + `ActivationCost.dynamic_reduction` shape; new `targeting.py` kind `artifact_creature_enchantm…
- **Files:** `game/ability_catalogue.py`, `game/targeting.py`

### Mindbreak Trap: "exile any number of target spells" (Targeting)

- **What:** `_multi_target_params`'s existing "any number of" cap (`_ANY_NUMBER_TARGET_CAP`) gained a "target spells" row, scoped only to `exile` (destroy/damage never lega…
- **Files:** `parser/oracle/catalogue/handlers.py`

### RULE 115.4 "change the target" gets its first oracle-text handler (Targeting)

- **What:** `ChangeTargetEffect` (previously only hand-authored per card) gained a generic parser row for "Change the target of target spell [or ability] with a single targ…
- **Files:** `parser/oracle/catalogue/handlers.py`

### Auriok Salvagers: mana-value filter on graveyard-recursion targeting (Targeting)

- **What:** `ReturnFromGraveyardEffect` gained a mana-value filter (constructor param, regex capture group, and a `targeting.py` check reusing `destroy_mv`'s `TargetSpec.ma…
- **Files:** `game/effects/core.py`, `game/targeting.py`, `parser/oracle/catalogue/handlers.py`

### Assassin's Trophy: unscoped permanent target + controller-redirected search (Targeting)

- **What:** New `permanent_you_dont_control` target kind ("target permanent an opponent controls," no type restriction) plus a widened `destroy` handler whitelist (previous…
- **Files:** `parser/oracle/subgrammars.py`, `game/targeting.py`, `game/rules/misc_mixin.py`, `game/effects/core.py`

### Mutiny: independently-targeted damage-equal-to-power (Targeting)

- **What:** `DamageEqualToPowerEffect` (built for Rabid Bite) with `extra_target_specs` giving *both* fighters their own `creature_you_dont_control` target.
- **Files:** `game/effects/core.py`, `game/ability_catalogue.py`

### Bug: `DrawCardEffect` read a shared `targets` list without checking its own target spec (Targeting)

- **What:** Unlike `GainLifeEffect`/`LoseLifeEffect`, `DrawCardEffect` fell back to `targets[0]` whenever `self.player` was unset and *any* `targets` list was non-empty, re…
- **Files:** `game/effects/core.py`

### `LookAtCardsEffect` (Targeting)

- **What:** "Look at the top card of target player's library." — a genuine RULE 115 target with no other game-state consequence, kept as its own effect (rather than an empt…
- **Files:** `game/effects/core.py`, `game/ability_catalogue.py`

### `pump_up_to_two` (Targeting)

- **What:** "Up to two target creatures each get +N/+N…" (Dauntless Onslaught-shaped) / "One or two target creatures…" both fold to `PumpEffect`'s existing "up to N" idiom…
- **Files:** `parser/oracle/catalogue/handlers.py`

### MEC-19: `EventType.BECOMES_TARGET` + `CounterUnlessPayEffect` (Targeting)

- **What:** RULE 115/601.2c targeting had never reached the event bus — `EventType.BECOMES_TARGET` now fires once per target from the same choke point `check_ward` already…
- **Files:** `game/rules_engine.py`, `game/binding/core.py`, `game/effects/core.py`, `parser/oracle/segmenter.py`

### RULE 601.2c Target-Count Range (`count_max`) (ENG-30)

- **What:** `TargetSpec.count_max` plus `effective_count` property express "N or M target `<X>`" (at least N, at most M) — a genuine third shape alongside exact `count` and…
- **Files:** `game/targeting.py`, `game/effects/core.py`, `game/rules/misc_mixin.py`, `frontend/src/js/gameBoardView.js`.
- **Why:** Slicing by the minimum (the pre-existing convention) would silently drop a legally-chosen second target for a range spec.

### Bounce a Spell Still on the Stack (Sink into Stupor)

- **What:** `RulesEngine.bounce_spell_or_permanent` + `ReturnToHandEffect.spell_or_permanent` pulls a target directly out of `GameState.stack`, since ordinary zone-removal…
- **Files:** `game/effects/core.py`, `game/rules_engine.py`, `game/targeting.py`.

### Forced Retarget-to-Source (Spellskite, Hydroelectric Specimen)

- **What:** `ChangeTargetEffect.redirect_to_source` + a `card_types` filter — a *forced* redirect onto the effect's own source, implemented by narrowing `legal_targets` to…
- **Files:** `game/effects/core.py`, `game/rules/misc_mixin.py`.

### Colour-OR Targeting (`TargetSpec.colors`)

- **What:** `TargetSpec.colors` (OR of 2+ WUBRG letters) + shared `_color_ok` helper replacing inline per-branch colour checks across `legal_targets`; `DealDamageEffect(col…
- **Files:** `game/targeting.py`, `game/effects/core.py`.

### "Target attacking/blocking/tapped/untapped creature" silently dropped the qualifier (v409, live bug fix)

- **What:** `subgrammars._TARGET_ROWS`' row for "target attacking/blocking/
- **Files:** `parser/oracle/catalogue/subgrammars.py`, `catalogue/

### Linked-Exile Tracking (`remember` on Exile/Search)

- **What:** `ExileEffect`/`SearchLibraryEffect` both gained a `remember` flag stamping `GameObject.linked_exile_id`, backing `Cemetery Gatekeeper`'s `shares_type_with_linke…
- **Files:** `game/effects/core.py`.

### MEC-85: Cast-time-conditional target legality / selection count (RULE 702.194b Teamwork's *other* "instead" shape)

- **What:** PAR-68 (`amount_if_teamwork`, see the Casting & Costs section) closed Teamwork's flat-magnitude "instead" override, but three cards change *which* targets are l…
- **Files:** `game/targeting.py`, `game/effects/exile_control.py`, `game/effects/returns_graveyards.py`, `game/rules/search_mixin.py`, `game/effects/registry.py`, `game/ability_catalogue/value.py`.

## Replacement Effects

### Replacement effect stacking (RULE 616)

- **What:** `RulesEngine.apply_replacements` rewrites an event through each applicable replacement at most once — draw→draw-2→mill chains and full prevention both work.
- **Files:** `game/rules_engine.py`

### Interactive replacement ordering (RULE 616.1e/f)

- **What:** When exactly one replacement applies it's used automatically; when 2+ apply simultaneously, `apply_replacements` opens a `replacement_order` `pending_choice` fo…
- **Files:** `game/rules_engine.py`, `game/effects/core.py`, `game/ability_catalogue.py`, `gameBoardView.js`
- **Why:** Mirrors RULE 603.3b's trigger-order pause/resume but is always interactive rather than opt-in, since replacement collisions are rare and always rules-meaningful…

### Conditional enters-tapped choice (RULE 614.1 replacement)

- **What:** `land_tap_condition` classifies a land's tapped-entry clause (`always`/`never`/`pay_life` shock lands/`unless_types` check lands/`unless_count` fast-slow lands)…
- **Files:** `game/ability_catalogue.py`, `game/rules_engine.py`

### Fourth land-tapped clause variant: opponents'-lands count

- **What:** "~ enters tapped unless your opponents control N or more lands" (the Turbulent cycle) — a new `unless_opponents_count` kind summing lands across every player ex…
- **Files:** `parser/oracle/catalogue/lands.py`, `game/rules_engine.py`

### Fifth land-tapped clause variant: life-total (PAR-42, v230)

- **What:** "~ enters tapped unless a player has N or less life." — the Innistrad-block "slow land" life cycle (Abandoned Campground / Bleeding Woods / Lakeside Shack / Pec…
- **Files:** `parser/oracle/catalogue/lands.py`, `game/rules/casting_mixin.py`

### Replacement-clause oracle-text recognition (double_tokens/double_counters/additional_damage)

- **What:** New `parser/oracle/catalogue/replacements.py` recognizes 3 of the 5 already-bound `ReplacementRegistry` families straight from oracle text — Doubling Season's t…
- **Files:** `parser/oracle/catalogue/replacements.py`, `parser/oracle/segmenter.py`

### Innkeeper's Talent Causer-Scoped Counter-Doubling

- **What:** "If **you** would put one or more counters on a permanent or player, put twice that many instead" scopes by who's *causing* the placement, distinct from Doublin…
- **Files:** `game/effects/core.py`, `game/rules_engine.py`

### Mechanized Warfare Compound Damage-Doubling Filter

- **What:** `additional_damage`'s single `color` param generalized to OR-combined `colors`/`types` lists, so a source qualifies if it matches *any* listed colour or type wo…
- **Files:** `game/effects/core.py`, `parser/oracle/catalogue/replacements.py`

### `prevent_damage` One-Shot Shield

- **What:** `PreventDamageEffect`/`RulesEngine.prevent_damage_to_player` — a resolve-time-built `ReplacementEffect` living on `Player.player_effects` rather than a permanen…
- **Files:** `game/effects/core.py`, `game/rules_engine.py`, `game/game_engine.py`

### Damage-Multiplying Replacement Family Recognition

- **What:** `_double_damage_replacement` gained a `multiplier` param (Fiery Emancipation's "triple") and a `creature_only` param for Gratuitous Violence's "a creature you c…
- **Files:** `parser/oracle/catalogue/replacements.py`, `game/effects/core.py`

### Lurrus Trailing "Exile Instead of Graveyard" Clause

- **What:** `GraveyardCastPermissionEffect.exile_if_would_be_put_into_graveyard` redirects a graveyard-cast-permission spell to exile instead, via `RulesEngine._move_to_gra…
- **Files:** `game/effects/core.py`, `game/rules_engine.py`

### Life-Gain Rewrite Replacement

- **What:** `gain_life_replacement` (`plus`/`multiplier` params) covers Angel of Vitality's additive "plus N instead" and Boon Reflection/Alhammarret's Archive's multiplica…
- **Files:** `game/effects/core.py`, `game/rules_engine.py`

### Recipient-Scoped +1/+1 Counter Replacement

- **What:** `_double_counters_replacement` gained `plus`/`multiplier`/`recipient` params for Hardened Scales/Conclave Mentor's additive "that many plus one" (creature you c…
- **Files:** `game/effects/core.py`

### "If ~ Would Die, Exile It Instead" Replacement

- **What:** `die_to_exile`, subject-scoped (self/you-control/any/opponent), fired off a new `EventType.WOULD_DIE` that `RulesEngine._move_to_graveyard` raises for any creat…
- **Files:** `game/effects/core.py`, `game/rules_engine.py`

### Targeted/divided damage prevention (PAR-15 residue, RULE 615)

- **What:** "Prevent the next N damage… to any number of targets, divided as you choose" (Embolden/Angel of Salvation).
- **Files:** `game/effects/core.py`, `game/rules_engine.py`

### "Prevent the next N damage… to any target this turn" singular (PAR-12, RULE 615)

- **What:** The singular-target sibling of the already-shipped plural "divided among any number of targets" prevention shape — `PreventDamageEffect`'s `target_kind` branch…
- **Files:** `parser/oracle/catalogue/handlers.py`

### RULE 615 Fog-shaped unscoped prevention

- **What:** "Prevent all combat damage that would be dealt this turn" — no chosen recipient at all, unlike the pre-existing per-recipient prevention shields.
- **Files:** `game/effects/core.py`, `game/rules_engine.py`

### Turn-scoped exile-instead-of-graveyard grant (Imodane batch)

- **What:** `GrantDieToExileThisTurnEffect` (Lava Coil/Smite the Deathless-shaped "exile instead of graveyard, this turn only") — a turn-scoped `ReplacementEffect` appended…
- **Files:** `game/effects/core.py`

### Mox Diamond: RULE 614.12 "would enter, discard a land instead" (Replacement Effects)

- **What:** New `AbilitySpec.enter_or_graveyard_discard_land` + `RulesEngine._offer_enter_or_graveyard`, spliced into `_resolve_permanent_spell`'s continuation chain *befor…
- **Files:** `game/rules/casting_mixin.py`, `parser/oracle/spec.py`

### Spark Double: copy-with-extra-counter (Replacement Effects)

- **What:** `EnterAsCopyReplacement` gained `extra_counter_if_creature`/`extra_counter_if_planeswalker` (applied post-copy, once the resulting permanent's real type is know…
- **Files:** `game/effects/core.py`, `game/targeting.py`, `game/ability_catalogue.py`

### Prevent Life Gain This Turn (RULE 119.3)

- **What:** `RulesEngine.prevent_life_gain_this_turn`/`PreventLifeGainEffect` — an absolute LIFE_GAIN cancel, the first sibling of `prevent_damage_to_player`'s numeric-shie…
- **Files:** `game/rules_engine.py`, `game/effects/core.py`.

### Power-Floor Damage Replacement (Ojer Axonil)

- **What:** `_damage_floor_from_source_power_replacement` — sibling of `_additional_damage_replacement`, where the threshold and the replacement amount are the same live va…
- **Files:** `game/effects/core.py`.

### MEC-30: standing `prevent_damage` replacement family, carded end to end (RULE 615/616.1)

- **What:** The long-dormant, fully-built standing `_prevent_damage_replacement` (`"prevent_damage"` in `ReplacementRegistry`) got its first real card bindings.
- **Files:** `game/effects/core.py`, `game/binding/core.py`, `parser/oracle/catalogue/replacements.py`, `game/ability_catalogue.py`.
- **What:** 32 more Family B cards hand-authored (full Circle of Protection and Rune of Protection cycles, Story Circle, Prismatic Circle, Circle of Solace, and others).
- **Why:** Registering Haazda Shield Mate for its shield clause alone would have silently dropped its already-parser-`MODELED` upkeep sacrifice-unless-pay clause (`specs_f…
- **What:** Closed the last 7 Family A cards.
- **Why:** Re-verifying each card's real `parse_oracle unclaimed` output before writing anything, rather than trusting the ticket's prior scoping, avoided building an unne…
- **What:** Five small, individually-scoped extensions to `RequestPreventDamageSourceEffect`: `recipient="attached_permanent"` (Kithkin Armor); `RulesEngine.prevent_damage_…
- **Why:** Kithkin Armor's Enchant keyword and combat restriction were already independently `MODELED` — registering it for the shield alone would have silently dropped th…
- **What:** `RequestRedirectDamageSourceEffect`/`RulesEngine.redirect_damage_from_source` — the first genuine damage redirection this engine modeled, distinct from preventi…
- **What:** `ActivationCost.any_player_may_activate` (RULE 602.2b eligibility widening) + `GameContext.resolving_controller_id`, the activator set/restored by `RulesEngine.…
- **Why:** Deliberately kept `_controller_of`'s global resolution order unchanged (97 call sites, several plausibly relying on live `source.controller_id`) — the new field…
- **What:** `ChooseSourceCoinFlipEffect` — the chosen-source chooser family's third member (candidates scoped to "a source you control," not "of your choice"); the coin (`R…
- **Why:** Closes the whole standing `prevent_damage` replacement family (MEC-30) — every card from the original 80-row cache search is now MODELED or hand-authored, and e…

### "A Source of Your Choice" One-Shot Prevention Family (RULE 615/616.1d)

- **What:** A genuinely new primitive (choosing a source is not RULE 115 targeting — no `"source"` target kind exists): `prevent_damage_to_player`/`_to_target` gained optio…
- **Files:** `game/effects/core.py`, `game/rules_engine.py`, `game/rules/misc_mixin.py`.

### Damage-Can't-Be-Prevented / Damage-Multiplier-This-Turn (Insult // Injury, Isengard Unleashed)

- **What:** New `ReplacementEffect.prevents_damage` marker stamped on every prevention-shaped effect construction site, plus a turn-scoped `GameState.damage_prevention_disa…
- **Files:** `game/rules_engine.py`, `game/effects/core.py`, `models/game_state.py`, `game/rules/damage_death_mixin.py`.
- **Why:** Deliberately not reusing the existing `damage_prevention_shield` cleanup-sweep flag despite the similar name — that flag means "sweep me at cleanup, I'm one-tur…

### RULE 616.1e `can_replace` Condition Fix

- **What:** Extracted each of the 12 `ReplacementRegistry` factories' inline applicability guard into a named `_applies(event, context)` closure wired as `effect.condition`…
- **Files:** `game/effects/core.py`.

### Discard-destination replacement, opponent-caused (MEC-102, RULE 614.1)

- **What:** "If a spell or ability an opponent controls causes you to discard this
- **Files:** `models/game/events.py` (`WOULD_DISCARD`), `game/effects/

## Triggered Abilities & Trigger Ordering

### Trigger ordering within a controller (RULE 603.3b)

- **What:** When `state.interactive_ordering` is on and the active player has 2+ simultaneous triggers, `put_triggers_on_stack` opens an `order_triggers` `pending_choice`;…
- **Files:** `game/rules_engine.py`

### Triggered-ability target choice (RULE 115/603.3c/603.5)

- **What:** A queued trigger with a targeting effect now opens a `trigger_target` `pending_choice` (one option per legal target) instead of placing blind; a required target…
- **Files:** `game/rules_engine.py`, `game/game_engine.py`

### ENG-4: manual trigger ordering combined with a targeted/modal/optional trigger

- **What:** `resolve_trigger_order_choice` used to place the picked ability with a bare, pause-skipping call, so an ordered targeted/optional trigger lost its target/"you m…
- **Files:** `game/rules_engine.py`

### Leaves-the-battlefield triggers "look back in time" (RULE 603.6a)

- **What:** `_move_to_graveyard`/`exile`/`return_to_hand` now fire `LEAVES_BATTLEFIELD`/`DIES` while the object is still spliced into the battlefield, then remove it — the…
- **Files:** `game/rules_engine.py`

### "When you control no `<basic land type>`, sacrifice ~." (RULE 603.8 state trigger — PARSER_VERSION 180)

- **What:** the original colour-gated creature cycle (Bog Serpent, Sea Serpent, Dandân, Island Fish Jasconius, Barbarian Outcast, Gorilla Pack, …; 11 SOLO).
- **Files:** `parser/oracle/segmenter.py`, `game/binding/core.py`. `tests/test_par30_control_none_sacrifice_trigger.py`.

### Modal triggered abilities (RULE 700.2 wrapped in RULE 603)

- **What:** "When ~ enters, choose one —" on a permanent now parses and binds (previously only a modal spell's header worked).
- **Files:** `parser/oracle/gate.py`, `parser/oracle/catalogue/modal.py`, `game/binding/core.py`, `game/rules_engine.py`
- **Why:** Real-cache yield was much smaller than a template-based estimate suggested (6 cards, all still blocked by an unrelated missing effect family) — logged as a corr…

### EventType.SACRIFICE (RULE 701.17)

- **What:** A move to the graveyard whose cause is a sacrifice now fires a distinct `SACRIFICE` event in addition to DIES/LEAVES, routed through the single `put_into_gravey…
- **Files:** `models/events.py`, `game/rules_engine.py`

### Reflexive per-firing "that object" trigger (RULE 603.3d)

- **What:** `TriggeredAbility.reflexive` lets a triggered ability's targeting effect act on the exact object that fired the event (resolved from the event's `instance_id` a…
- **Files:** `game/effects/core.py`, `game/binding/core.py`, `game/rules_engine.py`

### Delayed triggered abilities (RULE 603.7)

- **What:** `GameState.delayed_triggers` + `DelayedTrigger` + a `create_delayed_trigger` effect let a resolving spell arm a trigger for a future step, fired at `STEP_BEGIN`…
- **Files:** `models/game_state.py`, `game/game_engine.py`, `game/effects/core.py`
- **ENG-50 (2026-09-28):** Mana Drain's delayed `{C}` resolved to 0 — PAR-124's nested-`inner_specs` X substitution in `_substitute_x` (built for Storm King's Thunder's `CreateTurnTriggerEffect`) also walked `CreateDelayedTriggerEffect.inner_specs` and filled the `"x"` sentinel with Mana Drain's own announced X (0) before `capture="target_mana_value"` could. Effects whose `capture` owns the sentinel (`casting_mixin._X_OWNING_CAPTURES`) are now skipped. Hand-authoring stays the path: the parser still reports Mana Drain `UNMODELED`.

### Reflexive "When you do, `<targeted payoff>`." after an optional cost (RULE 603.11, PARSER_VERSION 206)

- **What:** "You may `<cost>`.
- **Files:** `game/effects/core.py` (`PayCostThenEffect.then_trigger_specs`, `pay_cost_then` factory), `game/rules/misc_mixin.py` (`request_pay_cost_then`/`resolve_pay_cost_then_choice`/`_enqueue_pay_cost_then_trigger`), `parser/oracle/catalogue/handlers.py` (`_pay_cost_then_general`), `parser/oracle/gate.py` (PARSER_VERSION 206).

### Card-resolution packages: Dance residual bodies (MEC-76)

- **What:** Hand-authored the four residual card bodies that did not justify a
- **Why:** Impulsivity now moves the chosen card to exile and opens the
- **Files:** `game/ability_catalogue/entries_016.py`, `game/continuous.py`,

### Haunt (RULE 702.55, MEC-70)

- **What:** The Haunt keyword now binds its inherent dies trigger.
- **Files:** `models/game_object.py`, `game/effects/core.py`,

### Self-referential-trigger family: ability words, controller-scoped phases, self-damage

- **What:** Three related gaps closed together: RULE 207.2c ability-word stripping ("Landfall —"/"Constellation —" have no rules meaning and were blocking the trigger match…
- **Files:** `parser/oracle/normalize.py`, `parser/oracle/segmenter.py`, `game/binding/core.py`, `game/continuous.py`

### Trigger-Condition Scoping (RULE 603.1)

- **What:** The segmenter emits a `trigger.condition` ({subject: self} or {subject: group, type/controller/other}); ENTERS_BATTLEFIELD/DIES/ATTACKS/BLOCKS events carry `ins…
- **Files:** `parser/oracle/segmenter.py`, `game/binding/core.py`

### "Draw a Card at the Beginning of the Next Turn's Upkeep" (RULE 603.7 Recognition)

- **What:** The RULE 603.7 delayed-trigger mechanism already existed (built for Mana Drain); this added the first parser recognition of the phrase, emitting `create_delayed…
- **Files:** `parser/oracle/catalogue/handlers.py`

### Attached-Permanent & "Deals Combat Damage to a Player" Trigger Families

- **What:** A new `{"subject": "attached_permanent"/"self_or_attached_permanent"}` trigger subject ("whenever equipped/enchanted creature `<verb>`", live-checked off the so…
- **Files:** `game/binding/core.py`

### `spell_subtype_any` Cast-Trigger Gate

- **What:** "Whenever you cast an Aura/Equipment/Vehicle spell" (Sram, Senior Edificer) needs a card-subtype check a `"group"` condition's main-type filter can't express —…
- **Files:** `game/binding/core.py`

### Delayed-Trigger Showcase Primitives

- **What:** Ephemerate's Rebound (RULE 702.88b, a standing free-cast window via `GameState.free_cast_instance_ids`), Marchesa the Black Rose's per-firing "counter-death ret…
- **Files:** `game/effects/core.py`, `game/rules/misc_mixin.py`, `game/ability_catalogue.py`

### Group-Subject Damage Triggers

- **What:** RULE 120.3 + 603.1's "a/an/another `<type>` [you control] deals combat damage to a player" subject, needing DAMAGE's own `source_controller_id` threaded through…
- **Files:** `game/binding/core.py`

### "Sacrifice ~ Unless You Pay `<cost>`." (RULE 701.17)

- **What:** A real interactive pay-or-lose-it choice for the biggest remaining upkeep-trigger template (45 cards), built by renaming and sharing ward's existing "can this p…
- **Files:** `game/effects/core.py`, `game/rules_engine.py`, `parser/oracle/catalogue/handlers.py`
- **Why:** Handing free text to the generic cost parser would return a "free" cost for anything unrecognized — silently reading as "pay nothing to keep it."

### Quoted Granted Phase/Upkeep Triggers

- **What:** `STEP_BEGIN` joined the grantable trigger events (Commander's Authority/Clawing Torment-shaped) — the one grantable event with no object subject, so its `phase_…
- **Files:** `game/continuous.py`

### Aura Lifecycle Triggers

- **What:** RULE 700.4's long "is put into a graveyard from the battlefield" phrasing folds to "dies" (`normalize._fold_dies_long_form`), and `ReturnToHandEffect` gained a…
- **Files:** `parser/oracle/normalize.py`, `game/effects/core.py`, `game/rules_engine.py`

### Trigger Subject Filtered on a Designation ("Goaded")

- **What:** "Whenever a goaded creature attacks/dies" is neither a type, subtype nor controller, so `goaded`/`in_combat` are snapshotted onto the firing event at fire time…
- **Files:** `game/binding/core.py`, `game/rules_engine.py`

### ENG-11: Granted Trigger Fails Closed Without Identity Key

- **What:** `continuous._granted_trigger_condition` now refuses (rather than passes) a firing event whose type has no entry in `_GRANTED_EVENT_KEYS` — mirroring the ordinar…
- **Files:** `game/continuous.py`

### ENG-13: Per-Firing Dynamic Reference for Granted Abilities

- **What:** `GameContext.trigger_event` (already used by an ordinary printed trigger's per-firing pronoun) is demonstrated on a *granted* ability's own resolution via two b…
- **Files:** `game/effects/core.py`, `game/ability_catalogue.py`

### Mill-trigger family (`EventType.MILL_CARD`)

- **What:** A new per-nonland-card `MILL_CARD` event (alongside the existing aggregate `MILL`) lets "whenever a player/an opponent mills a nonland card" bind via the existi…
- **Files:** `models/events.py`, `game/rules_engine.py`, `game/binding/core.py`
- **Why:** Infesting Radroach's ability must keep functioning from the graveyard rather than the battlefield, so it's read fresh off every player's graveyard by a dedicate…

### Trigger-condition vocabulary widened (RULE 603.1/500.7)

- **What:** `segmenter._TRIGGER_VERBS` consolidated into one table feeding every subject regex, adding "is turned face up," "leaves the battlefield," "becomes blocked," "be…
- **Files:** `parser/oracle/segmenter.py`
- **Why:** A verb earns a row only if the engine fires an event carrying an `instance_id` for it — "becomes untapped" is deliberately absent since `UNTAP` fires once per s…

### Interactive surveil + "whenever you scry/surveil" trigger family

- **What:** Scry and surveil unified onto one internal implementation differing only in destination (bottom of library vs.
- **Files:** `game/rules_engine.py`, `parser/oracle/segmenter.py`, `game/binding/core.py`
- **Why:** Deliberately not routed through `mill` — surveil and mill are distinct RULE 701.31b/701.13 keyword actions.

### `GameContext.trigger_event` — per-firing event exposure

- **What:** Exposes the event that fired a trigger for exactly one resolution window (threaded through `StackItem.trigger_event` across every pause/resume path), letting an…
- **Files:** `game/effects/core.py`, `game/rules_engine.py`

### Recipient-side damage trigger ("is dealt damage") — Enrage family

- **What:** The mirror image of the existing "deals damage" trigger family — `segmenter._DAMAGE_RECIPIENT_TRIGGER_RE` recognizes "whenever ~/a `<type>`/enchanted-or-equippe…
- **Files:** `parser/oracle/segmenter.py`, `game/binding/core.py`, `game/rules_engine.py`

### "It" pronoun disambiguation in recipient-subject effects

- **Files:** `game/effects/core.py`, `parser/oracle/segmenter.py`

### "Return this card from your graveyard to your hand" + graveyard-sourced triggers (PAR-16)

- **What:** The hand-destination sibling of PAR-10's battlefield-return effect (`ReturnSelfFromGraveyardToHandEffect`), plus a genuinely new engine primitive for the trigge…
- **Files:** `game/effects/core.py`, `game/binding/core.py`, `game/rules_engine.py`

### Triggered ability's own "if it was kicked" gate (PAR-17)

- **What:** Widened from spell-only "if this spell was kicked" to also cover "it" (a triggered ability's own body, Heartstabber Mosquito-shaped), "kicked twice" (Multikicke…
- **Files:** `parser/oracle/catalogue/handlers.py`, `game/rules_engine.py`

### RULE 603.2 once-per-turn trigger limiter, oracle wiring (PAR-14)

- **What:** `TriggeredAbility.once_per_turn` already existed (built for a granted ability) but no printed-card oracle-text path ever set it.
- **Files:** `parser/oracle/segmenter.py`, `game/binding/core.py`

### "Whenever you cast a/an `<type>` spell" trigger (PAR-12)

- **What:** A genuinely new trigger-condition family (607 SOLO-blocked cache-wide, the single largest template found in this batch).
- **Files:** `parser/oracle/segmenter.py`

### Heroic — "Whenever you cast a spell that targets ~" (PARSER_VERSION 242)

- **What:** RULE 702.34a's un-keyworded **Heroic** template — the whole Theros + Guilds of Ravnica + LOTR Heroic cycle (Akroan Skyguard / Battlewise Hoplite / Hero of Iroas…
- **Files:** `parser/oracle/segmenter.py` (`_CAST_SPELL_TARGETS_SOURCE_TRIGGER_RE` + dispatch), `game/rules/casting_mixin.py` (`_target_instance_ids`, both SPELL_CAST event sites), `game/binding/core.py` (`requires_spell_targets_source` predicate), `parser/oracle/gate.py` (PARSER_VERSION 242).

### "Whenever ~ or another creature dies" self_or_group trigger (PAR-12)

- **What:** Blood Artist/Falkenrath Noble's plain main-type, no-controller-restriction sibling of the existing subtype-scoped `self_or_group` variant.
- **Files:** `parser/oracle/segmenter.py`

### "Whenever you gain life, `<effect>`" trigger wiring (PAR-12, RULE 119.3)

- **What:** Ajani's Pridemate/Archangel of Thune-shaped.
- **Files:** `parser/oracle/segmenter.py`, `game/binding/core.py`

### "Whenever ~ attacks, it gets +N/+N…" self-subject trigger (PAR-12)

- **What:** Borderland Marauder/Kiln Walker-shaped vanilla-creature template, where the body refers to the source as "it" (the trigger's subject) rather than `~`.
- **Files:** `parser/oracle/catalogue/handlers.py`

### "Whenever you gain life, `<effect>`" dynamic-amount family (Hobbits batch)

- **What:** "that much"/"that many" reading `LIFE_GAINED`'s own amount off the firing trigger event: `LoseLifeEffect`/`AddCountersEffect`/`PumpEffect.amount_from_trigger_ev…
- **Files:** `game/effects/core.py`

### `LIFE_GAINED` as a granted player-subject trigger event (Hobbits batch)

- **What:** "Equipped/enchanted creature has 'whenever you gain life, …'" now resolves "you" against the granted-to permanent's controller, the same treatment `STEP_BEGIN`'…
- **Files:** `game/continuous.py`

### "Whenever you sacrifice a Food/Clue/Treasure" (Hobbits batch)

- **What:** `EventType.SACRIFICE` gained a `subtypes` payload (mirroring `DIES`'s existing split from main types), plus a new `sacrifice_type` trigger-condition predicate.
- **Files:** `models/game_state.py`, `game/binding/core.py`, `game/effects/core.py`

### Conditional granted-trigger effects + `ring_tempted_at_most` (Frodo Sauron's Bane)

- **What:** A granted triggered ability's own effect list had no way to condition an entry ("…loses the game if tempted 4+ times.
- **Files:** `game/continuous.py`, `game/effects/core.py`

### Card-type-excluding and creature-subtype spell-cast triggers

- **What:** "Whenever you cast a **non**creature spell" (new `spell_exclude_card_types` predicate, tried before the positive row) and "Whenever you cast an **Elf** spell" (…
- **Files:** `parser/oracle/segmenter.py`, `game/binding/core.py`

### COUNTER/CREATE_TOKENS events never fired (Eliferate finish)

- **What:** `RulesEngine.add_counters`/`add_player_counters` and `create_token` each computed their event through `apply_replacements` but the `_finish` closure never calle…
- **Files:** `game/rules/mana_counters_mixin.py`, `game/rules/misc_mixin.py`

### RULE 603.3d trigger doubling

- **What:** Roaming Throne's "if a triggered ability of a permanent you control triggers, it triggers an additional time." New `continuous.trigger_doubler_bonus` + `Trigger…
- **Files:** `game/continuous.py`, `game/rules_engine.py`

### "Spell watchers" (Imodane batch)

- **What:** `GameState.spell_watchers` — a GameState-level mechanism distinct from both an object-bound `TriggeredAbility` and a step-bound RULE 603.7 `DelayedTrigger`.
- **Files:** `models/game_state.py`, `game/rules_engine.py`

### Imodane, the Pyrohammer's own trigger

- **What:** "Whenever an instant/sorcery you control that targets only a single creature deals damage to that creature, Imodane deals that much damage to each opponent." Ne…
- **Files:** `game/rules_engine.py`, `game/effects/core.py`, `game/binding/core.py`

### `TaxedDrawEffect` — RULE 118.3 "unless" applied to a draw

- **What:** Rhystic Study/Mystic Remora/Esper Sentinel's "whenever an opponent casts a spell, you may draw a card unless that player pays `<cost>`." The one real difference…
- **Files:** `game/effects/core.py`

### Smothering Tithe: DRAW group-subject trigger + pay-or-create-Treasure (Triggered Abilities & Trigger Ordering)

- **What:** `effect_binder._GROUP_CONTROLLER_EVENT_KEYS` gained a `"DRAW": "player_id"` row so "whenever an opponent draws a card" group-subject scoping works; `PayCostThen…
- **Files:** `game/binding/core.py`, `game/effects/core.py`, `game/ability_catalogue.py`

### Untyped player-subject cast trigger + mana-value filter (Triggered Abilities & Trigger Ordering)

- **What:** New `_CAST_SPELL_TRIGGER_PLAIN_RE` recognizes "whenever you/an opponent/a player casts a spell" (the previous regex required a typed variant); `_CAST_SPELL_TRIG…
- **Files:** `parser/oracle/segmenter.py`, `game/binding/core.py`

### `DealDamageEffect` "event_player" selector (Triggered Abilities & Trigger Ordering)

- **What:** New `"event_player"` selector — "~ deals N damage to **that player**", the player named by the firing trigger's own event — reused by a new `"that player"` entr…
- **Files:** `game/effects/core.py`, `parser/oracle/catalogue/handlers.py`

### "Sacrifice it. When you do, `<effect>`." collapsed to a plain sequence (Triggered Abilities & Trigger Ordering)

- **What:** RULE 603.3's "when you do" only fires if the antecedent happened; for an unconditional (no "may") self-sacrifice that's a certainty, so `_SACRIFICE_THEN_WHEN_YO…
- **Files:** `parser/oracle/catalogue/handlers.py`

### Mass edicts + "Whenever you/an opponent draws a card" trigger family (Triggered Abilities & Trigger Ordering)

- **What:** "Each player/opponent sacrifices `<n>` `<type>` of their choice" (`_sacrifice_edict`, new `"nontoken_creature"` word on `_matches_permanent_type`); a new `_DRAW…
- **Files:** `parser/oracle/catalogue/handlers.py`, `game/effects/core.py`

### Kiki-Jiki / Puppeteer Clique: haste-copy-with-end-step-cleanup primitive (Triggered Abilities & Trigger Ordering)

- **What:** "Create/reanimate a permanent with haste, [sacrifice/exile] it at the beginning of the next end step." `CopyPermanentEffect`/`ReturnFromGraveyardEffect` gained…
- **Files:** `game/effects/core.py`, `game/ability_catalogue.py`

### Mikaeus, the Unhallowed: negated-subtype anthem + damage-sourced destroy trigger (Triggered Abilities & Trigger Ordering)

- **What:** New `group_selector_objects` branch `"other_nonhuman_creatures_you_control"` for the anthem; a new `effect_binder` condition `recipient_is_you` (RULE recipient-…
- **Files:** `game/binding/core.py`, `game/effects/core.py`, `game/continuous.py`, `game/ability_catalogue.py`

### Danny Pink: per-creature "first time each turn" COUNTER-event watch (Triggered Abilities & Trigger Ordering)

- **What:** Reuses `grant_triggered_ability` (Dionus, Elvish Archdruid's own mechanism) watching each creature's own `EventType.COUNTER`.
- **Files:** `game/ability_catalogue.py`

### Arcane Denial: controller-redirected delayed draw (Triggered Abilities & Trigger Ordering)

- **What:** `create_delayed_trigger`'s new `capture="target_controller"` reads the *countered spell's* controller off the resolving target and mutates the constructed inner…
- **Files:** `game/effects/core.py`, `game/ability_catalogue.py`

### Black Market Connections: standing "choose one or more" main-phase trigger (Triggered Abilities & Trigger Ordering)

- **What:** A `STEP_BEGIN` main-phase trigger wraps Farewell's own hand-authored `modes={"choose": 1, "at_least": True, ...}` modal shape — no new modal machinery needed.
- **Files:** `game/ability_catalogue.py`

### Bug: `SacrificeEffect`'s multi-player selector overwrote pending choices (Triggered Abilities & Trigger Ordering)

- **What:** `each_player`/`each_opponent` looped every matching player synchronously in one `apply()`, so a second player's real interactive pick silently overwrote the fir…
- **Files:** `game/effects/core.py`

### Bug: `COUNTER` missing from "which event field names the firing object" tables (Triggered Abilities & Trigger Ordering)

- **What:** Both `effect_binder._SUBJECT_EVENT_KEYS` and `continuous._GRANTED_EVENT_KEYS` defaulted to `instance_id` for `COUNTER`, but `RulesEngine.add_counters`'s own eve…
- **Files:** `game/binding/core.py`, `game/continuous.py`

### Cast-spell trigger subject widened to you/opponent/player + `trigger_copy_spell` (Triggered Abilities & Trigger Ordering)

- **What:** `_CAST_SPELL_TRIGGER_RE`/`_CAST_SPELL_TRIGGER_NEG_RE` widened from "you"-only to all three subjects via a shared `_cast_spell_trigger_condition` helper (+51 car…
- **Files:** `parser/oracle/segmenter.py`, `game/effects/core.py`

### Mistrise Village: spell-watcher payload for "can't be countered" (Triggered Abilities & Trigger Ordering)

- **What:** Reuses `arm_spell_watcher` (built for Dual Strike's "copy it") with a new payload, `MarkCantBeCounteredEffect`, appending a `CantBeCounteredEffect` marker onto…
- **Files:** `game/effects/core.py`, `game/ability_catalogue.py`

### Vexing Bauble: counter-if-free-cast trigger (Triggered Abilities & Trigger Ordering)

- **What:** New `effect_binder` predicate `spell_no_mana_spent` (reads `SPELL_CAST`'s `mana_spent` field, already zero for a free/alt-cost cast); `CounterSpellEffect` gaine…
- **Files:** `game/binding/core.py`, `game/effects/core.py`

### Chain of Vapor: controller-redirected pay-or-not (Triggered Abilities & Trigger Ordering)

- **What:** `PayCostThenEffect` gained a `payer="previous_target_controller"` mode reading `GameContext.previous_targets` — the bounced permanent's controller, not the cast…
- **Files:** `game/effects/core.py`, `game/ability_catalogue.py`

### MEC-18: RULE 118.3 optional-antecedent family generalized (Triggered Abilities & Trigger Ordering)

- **What:** `catalogue.handlers._pay_cost_then_general` widens `PayCostThenEffect`'s recognition from two hardcoded shapes to the whole "you may `<sacrifice/discard/pay-man…
- **Files:** `parser/oracle/catalogue/handlers.py`, `parser/oracle/segmenter.py`

### Intervening-If: First Combat Phase of the Turn (RULE 603.4)

- **What:** New `GameState.combats_this_turn` counter (incremented per `begin_combat`, reset each turn) backs a new `ConditionalEffect` key `is_first_combat_phase`, closing…
- **Files:** `models/game_state.py`, `game/effects/core.py`, `parser/oracle/segmenter.py`.

### Attached-Permanent "It" Retargeting for Self-Acting Effects (ENG-29)

- **What:** For a `{"subject": "attached_permanent"}` trigger ("whenever equipped/enchanted creature `<verb>`, it `<effect>`"), `effect_binder._retarget_attached_permanent_…
- **Files:** `game/binding/core.py`.
- **Why:** The clause always parsed correctly; only its bound meaning was wrong — `target_kind=None` always means "the ability's own source," so "untap it" was untapping t…

### Group-Subject Retarget (`trigger_subject`) (MEC-28)

- **What:** `TapEffect` gained a `"trigger_subject"` `target_kind` mode reading `GameContext.trigger_event` live at resolution; `effect_binder._retarget_implicit_subject_ef…
- **Files:** `game/effects/core.py`, `game/binding/core.py`.

### MEC-49 / MEC-91: Per-turn damage-source attribution (PARSER_VERSION 219)

- **What:** "Whenever a creature **dealt damage by ~ this turn** dies, `<effect>`." (Baron Sengir, Abattoir Ghoul, Blood Cultist, Sengir Vampire / Sengir Bats / Vampiric Dr…
- **Files:** `models/game_state.py` (the map), `game/rules/damage_death_mixin.py` (`deal_damage` records it), `game/engine/turn_loop_mixin.py` (`begin_turn` clears it), `game/binding/core.py` (`_build_group_ok`), `parser/oracle/segmenter.py` (`_DAMAGED_BY_SOURCE_SUBJECT_RE` + its dispatch), `parser/oracle/gate.py` (v219).

### MEC-28: Group-Subject / Previous-Selector Trigger Flags

- **What:** New `group_subject` flag threaded through `segmenter.parse_effect_body`/`handlers.match_clause` (closing "untap that creature" — Finest Hour) and new `GameConte…
- **Files:** `parser/oracle/segmenter.py`, `parser/oracle/catalogue/handlers.py`, `game/effects/core.py`, `game/binding/core.py`.

### Bare "Whenever You Attack" Trigger Condition

- **What:** RULE 506.4's bare "whenever you attack" recognized via `_PLAYER_TRIGGER_CONDITIONS`'s new `"you attack"` row, reusing the already-firing `EventType.PLAYER_ATTAC…
- **Files:** `parser/oracle/segmenter.py`, `game/binding/core.py`.

### Aggregate "One or More Creatures Deal Combat Damage to a Player" Event (MEC-29)

- **What:** New `EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER`, fired once per (contributing creatures' controller, player hit) pair per damage step — not once per qua…
- **Files:** `game/engine/combat_mixin.py`, `game/binding/core.py`.
- **Why:** Mirrors the existing `EventType.PLAYER_ATTACKED` shape (built for "a player attacks you with one or more creatures"), the same "one or more X `<verb>`" template…

### Aggregate Combat-Damage Event Widened: Subtypes/Amount/Commander (MEC-12)

- **What:** `EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER` gained `subtypes` (union of contributing creatures' real subtypes, re-derived honouring layer-4 overwrites),…
- **Files:** `game/engine/combat_mixin.py`, `game/binding/core.py`.

### Non-Mana-Ability Activation Trigger Event

- **What:** `EventType.ACTIVATED_ABILITY` (RULE 602.2) fired by `GameEngine.activate_ability` — mana abilities never reach the stack (RULE 605.1a) so no filter is needed to…
- **Files:** `game/engine/activation_mixin.py`, `game/binding/core.py`.

### Land-Tap-for-Mana Punisher Family

- **What:** New `"nonbasic"` supertype filter key on `_build_group_ok` plus `DealDamageEffect.selector`'s `event_player`/`event_controller`/`active_player` close the Manaba…
- **Files:** `game/binding/core.py`, `game/effects/core.py`.

### "No Mana Spent" Counterspell Trigger Generalization

- **What:** The "whenever a player casts a spell, if no mana was spent to cast it, `<effect>`." trigger generalized from Vexing Bauble's hardcoded row to a reusable general…
- **Files:** `game/binding/core.py`, `parser/oracle/catalogue/handlers.py`.

### Nth-Spell/Noncreature-Spell-Count Tracking

- **What:** Fixed `RulesEngine.__init__`'s subscription order (`_track_spell_cast` now runs before `_collect_triggers`) so `spells_cast_this_turn` is current by the time a…
- **Files:** `game/rules_engine.py`, `models/game_state.py`, `game/binding/core.py`, `game/effects/core.py`.

### "Caused you to discard" event provenance (MEC-101, RULE 603.1)

- **What:** `EventType.DISCARD_CARD` gained `cause_controller_id` — whoever controls the
- **Files:** `game/rules/draw_discard_mixin.py`, `game/effects/core.py`, `game/effects/

## Continuous Effects & Layer System

### Perpetual P/T and keyword changes (MEC-98, Alchemy "perpetually")

- **What:** "`<subject>` perpetually gets +N/+N [and gains `<kw>`]" / "… perpetually gains `<kw>`". `GameObject.perpetual_power`/`perpetual_toughness`/`perpetual_keywords` (+ display-only `perpetual_effects`) are never cleared: not at cleanup, not by `reset_derived`, and not by `reset_as_new_object`. That makes them the one exception to RULE 400.7's "effects are not retained". `continuous.recompute` folds them into layer 7d (beside the until-EOT pump) and layer 6, traced with `duration="permanent"`. The off-battlefield `power`/`toughness` fallback adds them too, so a card in hand shows its perpetual size. `copy_perpetual_from` carries them onto a copy (`copy_permanent` token copies, `conjure_duplicate_into_hand`). Engine entry: `PumpEffect.perpetual` writes to these fields instead of `temp_*`, keeping every pump addressing mode. `card_zones` + `card_type` + `subtypes` also reach the controller's cards in hand/library/graveyard, and are added to any `selector` group. Parser: `handlers._perpetual_pump_specs`, the `match_clause` fallback, rewrites the clause into its "… until end of turn" form, runs the ordinary pump table on it and flips the result to `perpetual`. It fails closed on anything but plain pumps (no "can't be blocked" rider, no parametric keyword). Its own zone-subject grammar covers "[creatures you control and] [each] creature card(s) in your hand/library/graveyard". PARSER_VERSION 497: +15 cards, 0 regressed. Stalwart Speartail's enrage is hand-authored on the same primitive (it had been dropped for lack of one).
- **Files:** `models/game/game_object.py`, `game/continuous.py`, `game/effects/counters_tokens.py`, `game/effects/registry.py`, `game/rules/copies_mixin.py`, `parser/oracle/catalogue/handlers.py`, `game/card_catalogue/s/stalwart_speartail.py`, `tests/test_mec98_perpetual.py`
- **Why:** Perpetual is an Arena/Alchemy duration and isn't in the paper CR, so there is no RULE number to cite (the ticket's "RULE 121.5" was a mis-citation). Riding on `PumpEffect` and on a text rewrite reuses the ~40 pump rows' subject/amount/keyword grammar rather than duplicating it. Separate fields rather than a `durations.py` window, because nothing ever ends a perpetual change.

### Layer-6 grant of a non-keyword ability (RULE 613.7f)

- **What:** New `grant_mana_ability`/`grant_triggered_ability` `EffectSpec` types let a static grant something richer than a bare keyword slug (Tyvar Kell's "{T}: Add {B}."…
- **Files:** `game/binding/core.py`, `game/continuous.py`, `models/game_state.py`, `game/ability_catalogue.py`
- **Why:** Needed a genuine `TAPPED` event (RULE 701.21b, only on a real untapped→tapped transition) as a new primitive to scope the granted trigger correctly.

### Become a copy of target permanent/creature (RULE 706/707)

- **What:** Three mechanisms sharing one mutate/snapshot/restore primitive (`game/copy_mechanics.py`): (1) permanent ETB copy (Clever Impersonator) via true RULE 614.1c/614…
- **Files:** `game/copy_mechanics.py`, `game/continuous.py`, `game/rules_engine.py`, `models/card.py` (`as_copy`)

### Board-wide ability strip (layer 6, RULE 613.7f)

- **What:** A `remove_all_abilities` static sets `GameObject.loses_all_abilities`, stripping every keyword and gating both triggered and activated abilities — Humility (pai…
- **Files:** `game/continuous.py`, `game/effects/core.py`

### MEC-47: Licid — a creature that turns itself into an Aura (first pass, hand-authored)

- **What:** the Tempest Licid cycle's shared ability — "{cost}, {T}: This creature loses this ability and becomes an Aura enchantment with enchant creature.
- **Files:** `models/game_object.py`, `game/static_conditions.py`, `game/effects/core.py`, `game/ability_catalogue/entries_016.py`.

### Aura/Equipment attached-permanent grants: control magic and quoted abilities

- **What:** "You control enchanted creature/permanent." (Control Magic-shaped) needed zero new code, just a parser row onto the existing `control_change` static.
- **Files:** `parser/oracle/catalogue/static_handlers.py`, `game/effects/core.py`
- **Why:** Deliberately fails closed on a quoted activated-ability grant (needs a "grant an activated ability" primitive not yet built) and a quoted DAMAGE/phase-scoped gr…

### RULE 613 Layer System — Full Layer Coverage & Ordering

- **What:** `game/continuous.py` re-derives every battlefield permanent's characteristics across layers 2, 4, 5, 6, 7a-e each recompute, stamping derived P/T, added types,…
- **Files:** `game/continuous.py`, `game/effects/core.py`
- **Why:** Layer 3's text substitution deliberately isn't a full oracle re-parse — bound abilities/keywords stay fixed at bind time — since no real card needed more than p…

### Attached-Permanent Static Parsing

- **What:** "equipped/enchanted/fortified … gets +N/+N [and has `<kw>`]" and "… has `<kw>`" now parse to `anthem`/`grant_keyword` specs with `affects="attached_permanent"`…
- **Files:** `parser/oracle/catalogue/static_handlers.py`

### Layer-6 Grant of an Activated Ability

- **What:** "`<host>` has '`{cost}`: `<effect>`.'" (Umbral Mantle/Squirrel Nest-shaped) — the activated sibling of the existing triggered/mana/keyword layer-6 grants.
- **Files:** `game/continuous.py`, `game/effects/core.py`, `game/game_engine.py`

### Layer-6 Grant of a Static Ability — MEC-55

- **What:** "X have '`<static ability>`'" where the quoted body is itself a *static* — an anthem / lord (Inspiring Leader: "Commander creatures you own have 'Creature token…
- **Files:** `models/game_object.py`, `game/continuous.py` (`_apply_layer_6_ability`, `_battlefield_static_abilities`, `recompute` re-gather), `game/effects/core.py` (`grant_static_ability` registry), `parser/oracle/catalogue/static_handlers.py`, `tests/test_mec55_granted_static_ability.py`

### Granted Extra Entry Counter — MEC-56

- **What:** "X have '`<static ability>`'" where the quoted body is itself a RULE 614.1-style entry-counter *replacement*, not a trigger — Master Chef: `Commander creatures…
- **Files:** `game/effects/core.py` (`extra_etb_counter` registry), `game/continuous.py` (`extra_etb_counters_for`), `game/rules/casting_mixin.py` (`_apply_granted_entry_counters` + its call site), `game/rules/misc_mixin.py` (token-creation call site), `game/ability_catalogue/entries_016.py` (`_master_chef`), `tests/test_par32_master_chef.py`

### Granted Replacement Effect — MEC-57

- **What:** "X have '`<static ability>`'" where the quoted body is itself a *replacement* effect (RULE 616), not a trigger/static/mana/activated ability — Scion of Halaster…
- **Files:** `game/effects/core.py` (`first_draw_look_two` factory + `ReplacementRegistry` entry), `game/continuous.py` (`_apply_layer_6_ability`'s registry fallback + dispatch), `models/game_object.py` (`_granted_replacement_effects`), `models/game_state.py` (`first_draw_replaced_this_turn`), `game/engine/turn_loop_mixin.py` (`begin_turn` clear), `game/rules_engine.py` (`_all_replacement_effects`), `game/ability_catalogue/entries_016.py` (`_scion_of_halaster`), `tests/test_par32_scion_of_halaster.py`

### Impulse-Draw Pump-From-Exiled-Mana-Value — MEC-58

- **What:** "X have '`<static ability>`'" where the quoted body is a two-clause granted trigger whose second clause reads a value off what the first clause just exiled — Ta…
- **Files:** `game/effects/core.py` (`ImpulsiveDrawEffect.apply`, `GameContext.exile_with_play_permission`, `PumpEffect.amount_from_created_object_mana_value`), `game/ability_catalogue/entries_016.py` (`_tavern_brawler`), `tests/test_par32_tavern_brawler.py`

### Becomes-Tapped Tribal Pump — MEC-59

- **What:** "X have '`<static ability>`'" where the quoted body is a granted `TAPPED` trigger pumping a *dynamic* tribal group — Haunted One: `Commander creatures you own h…
- **Files:** `game/effects/core.py` (`PumpEffect.apply`'s new selector branch), `game/ability_catalogue/entries_016.py` (`_haunted_one`), `tests/test_par32_haunted_one.py`

### Per-Turn-First Subtype Cost Reduction — MEC-60

- **What:** "X have '`<static ability>`'" where the quoted body is a cost reduction gated on RULE 601.2f's "the first `<subtype>` spell" pattern — Acolyte of Bahamut: `Comm…
- **Files:** `game/static_conditions.py` (`first_subtype_spell_this_turn`), `models/game_state.py` (`creature_type_spells_cast_this_turn`), `game/engine/turn_loop_mixin.py` (`begin_turn` clear), `game/rules/misc_mixin.py` (`_track_spell_cast`), `game/ability_catalogue/entries_016.py` (`_acolyte_of_bahamut`), `tests/test_par32_acolyte_of_bahamut.py`

### Dungeon-Room Trigger Doubling — MEC-61

- **What:** "X have '`<static ability>`'" where the quoted body is a RULE 603.3d trigger doubler scoped to dungeon room abilities specifically — Dungeon Delver: `Commander…
- **Files:** `game/effects/core.py` (`dungeon_room_trigger_doubler` registry entry), `game/continuous.py` (`dungeon_room_trigger_doubler_bonus`), `game/rules/misc_mixin.py` (`_collect_dungeon_room_triggers`'s doubling append), `game/ability_catalogue/entries_016.py` (`_dungeon_delver`), `tests/test_par32_dungeon_delver.py`

### Per-Player "May" Counters + Protection-From-a-Player — MEC-62

- **What:** "X have '`<static ability>`'" where the quoted body is a compound trigger over a genuinely new interactive shape — Noble Heritage: `Commander creatures you own…
- **Files:** `game/effects/core.py` (`EachPlayerMayCounterThenProtectionEffect`, `PlayerShieldEffect.protected_from_player_id`), `game/rules/damage_death_mixin.py` (`_player_protected_from_source_controller` + `deal_damage`'s check), `game/ability_catalogue/entries_016.py` (`_noble_heritage`), `tests/test_par32_noble_heritage.py`

### Per-Count Static Anthem Multiplier

- **What:** Layer 7d `pt_mod` gained optional `power_count`/`toughness_count` params for "+1/+1 for each land you control" (Blackblade Reforged, reusing the controller-scop…
- **Files:** `game/continuous.py`

### Layer-6 Keyword Removal

- **What:** A new `remove_keyword` static type mirrors `grant_keyword`, populating `GameObject._removed_keywords`, subtracted last in keyword display/combat checks (Colossu…
- **Files:** `game/continuous.py`, `game/combat.py`

### Standing Granted Protection (RULE 702.16, Layer 6)

- **What:** `grant_protection_static` → `GameObject._granted_protections`, stamped every recompute and unioned by `combat.is_protected_from`, so it stops applying the insta…
- **Files:** `game/continuous.py`, `game/combat.py`

### Type Grants Past the Battlefield (RULE 613.4a, Layer 4)

- **What:** `continuous._apply_off_battlefield_types` is a dedicated pass over a controller's hand/graveyard/library/exile plus stack spells, stamping `_added_subtypes` for…
- **Files:** `game/continuous.py`

### RULE 613.6 Static Condition Vocabulary

- **What:** `game/static_conditions.py` is a single whitelisted `active_if` vocabulary (state, characteristics, whose turn it is, board counts, life/hand/cards-drawn) carri…
- **Files:** `game/static_conditions.py`, `game/effects/core.py`
- **Why:** "As long as" leads ~250 cache clauses across five+ unrelated families; the old one-parameter-per-card pattern would have meant a new whitelist entry for every f…

### RULE 611 Duration System

- **What:** `game/durations.py` plus `GameState.floating_statics` model any RULE 611 continuous effect duration the `temp_*` fields can't express ("until your next turn", "…
- **Files:** `game/durations.py`, `models/game_state.py`, `game/effects/core.py`

### Condition Subject (`of`: source/attached/affected)

- **What:** `static_conditions.condition_holds` resolves a subject first (`source` default, `attached`, `affected`), so every existing `source_*` condition kind works on an…
- **Files:** `game/static_conditions.py`
- **`is_you` on an object (ENG-50, 2026-09-28):** `is_you` only compared a *player's* id, so the atomized Geistwave (`{"kind": "is_you", "of": "previous_target"}`, which replaced the retired `return_to_hand_draw_if_controlled` fusion) never drew. An object subject (has `instance_id`) now compares its `controller_id` — "if you control(led) that permanent", RULE 109.4. Correct for a stolen permanent (controller ≠ owner) too, since the bounce doesn't reset `controller_id` before the rider resolves. Geistwave stays hand-authored (parser: `UNMODELED`).

### Dynamic Threshold on a Group Scope

- **What:** `continuous.dynamic_threshold` reads either the source's own derived characteristics or a full `count_selector` list, for group scopes like "creatures your oppo…
- **Files:** `game/continuous.py`

### Counter-presence group scope + Odyssey Threshold phrasing (PAR-34, PARSER_VERSION 237)

- **What:** Two static shapes.
- **Files:** `parser/oracle/normalize.py` (`_ABILITY_WORD_RE`), `parser/oracle/catalogue/static_handlers.py` (`_GROUP_COUNTER_GRANT_RE`, `_STATIC_CONDITION_RES`), `game/effects/core.py` (`_SELECTOR_KEYS` += `has_counter_kind`), `parser/oracle/gate.py` (PARSER_VERSION 237).

### ENG-22: `continuous.py` `recompute()` Split into Per-Layer Functions

- **What:** The single 424-line `recompute()` became a ~15-line dispatcher over seven top-level layer functions (`_apply_layer_2_control` through `_apply_layer_7_pt`, plus…
- **Files:** `game/continuous.py`
- **Why:** Verified harder than the other mixin splits since layer *order* is load-bearing (unlike method order in a mixin file) — full suite plus explicit layer-named tes…

### ENG-8: Layer 3 Text-Change Reaches Landwalk

- **What:** `combat._landwalk_slugs` now scans `obj.effective_oracle_text` (the layer-3 word-substitution output) instead of `obj.card.oracle_text` directly, so a text-chan…
- **Files:** `game/combat.py`

### ENG-9: RULE 613.8 Dependency Ordering Re-Verified

- **What:** Checked whether any selector added since the layer engine shipped now reads another object's *derived* state outside layer 2 (the ticket's own trigger condition…
- **Files:** `game/continuous.py`

### New count-selector kinds (devotion, legendary creatures, named-in-graveyard)

- **What:** `continuous.count_selector` gained `devotion_to_<colour>` (RULE 202.2f, hybrid pips count for both colours), `legendary_creatures_you_control`, and `cards_named…
- **Files:** `game/continuous.py`

### Land-type ability removal (RULE 305.7)

- **What:** Setting a land's subtype to a basic land type now correctly strips its rules text/abilities (a Blood-Moon'd Underground Sea makes only {R}); the layer-4 subtype…
- **Files:** `game/continuous.py`, `game/mana_abilities.py`

### MEC-12 — "as long as you're the monarch/have the initiative" conditional statics

- **What:** `static_conditions.py`'s RULE 613.6 whitelist gained `is_monarch`/`has_initiative`, consulted with no `of` subject (always the static's own controller), the sam…
- **Files:** `game/static_conditions.py`, `parser/oracle/catalogue/static_handlers.py`
- **Why:** Most of the 56 UNMODELED cards the ticket estimated turned out to be blocked on a separate, already-documented gap (non-creature group scopes like "permanents y…

### "As ~ enters, choose a basic land type" (PAR-4, RULE 305.6)

- **What:** A third `enter_choice_effects` sibling alongside creature-type/colour choice (`ChooseBasicLandTypeReplacement`), stamping the same `GameObject.chosen_type` fiel…
- **Files:** `game/effects/core.py`, `parser/oracle/catalogue/static_handlers.py`, `game/engine/casting_mixin.py`

### Non-creature group scopes for grant families (PAR-3)

- **What:** Keyword-grant/quoted-grant statics (`_GRANT_RE`/`_QUOTED_GRANT_RE`) now recognize a bare card-type word ("Artifacts you control have hexproof.", "Other enchantm…
- **Files:** `parser/oracle/catalogue/static_handlers.py`, `game/continuous.py`

### Standing protection self-exemption for own Aura (PAR-6, RULE 702.16n/p)

- **What:** A trailing "This effect doesn't remove this Aura." clause is now recognized and honored: a new per-source `GameObject._protection_self_exempt` flag (stamped by…
- **Files:** `game/continuous.py`, `parser/oracle/catalogue/static_handlers.py`

### grant_until P/T-delta and combat-restriction durations (PAR-13)

- **What:** `grant_until`'s new P/T-delta route (`_pump_until`, riding the general layer-7c anthem static) and its "can't attack/block until `<duration>`" sibling — resolve…
- **Files:** `game/effects/core.py`, `parser/oracle/catalogue/static_handlers.py`

### "Commander creatures you own have `<ability>`" grant (PAR-12)

- **What:** A new `continuous.group_selector_objects` selector, `"commander_creatures_you_own"` — scoped by ownership (not control), since RULE 108.3 ownership is what this…
- **Files:** `game/continuous.py`, `parser/oracle/catalogue/static_handlers.py`

### Dynamic-magnitude pump effects

- **What:** `PumpEffect.amount_from_count_selector` ("+X/+X where X is the number of creatures you control", Craterhoof Behemoth) and `PumpEffect.per_recipient_controller_c…
- **Files:** `game/effects/core.py`

### Selector/filter reach widenings (Keywords Showcase batch)

- **What:** `creatures_you_control_of_type_<X>` and `permanents_you_control` reached `group_selector_objects` for the first time so a one-shot `PumpEffect.selector` can tar…
- **Files:** `game/continuous.py`, `game/effects/core.py`

### RULE 601.2b resolve-time interactive choices (choose type / choose player)

- **What:** A category distinct from the existing enter-battlefield choice pipeline: "choose a creature type, then grant it something" (Selfless Safewright) and "choose a p…
- **Files:** `game/rules/turn_loop_mixin.py`

### `cast_prohibition`/`activation_prohibition` gated on "During your turn" (ENG-28)

- **What:** `cast_prohibited` now consults `active_if` (RULE 613.6) like every other static; a general "During your turn, `<static clause>`." parser wrapper reuses the exis…
- **Files:** `game/continuous.py`, `game/effects/core.py`, `parser/oracle/catalogue/static_handlers.py`
- **Why:** Sizing first showed the ticket's own premise was half wrong — Linvala/Karn's lock clauses carry no turn gate at all; only Grand Abolisher/Myrel print the gated…

### Untap-cap family generalized past lands-only (Static Orb/Winter Moon) (Continuous Effects & Layer System)

- **What:** `continuous.untap_cap_for_lands` (Winter Orb-only, hardcoded) became `continuous.active_untap_caps` (a list of `{count, card_type, nonbasic}` dicts — 2+ caps ca…
- **Files:** `game/continuous.py`, `game/engine/turn_loop_mixin.py`, `parser/oracle/catalogue/static_handlers.py`

### Meekstone: unattached group-scoped no-untap (Continuous Effects & Layer System)

- **What:** "Creatures with power N or greater don't untap…" — a new `_NO_UNTAP_GROUP_POWER_RE` row emits `affects="all_creatures"` plus the ordinary `min_power` selector,…
- **Files:** `parser/oracle/catalogue/static_handlers.py`

### "You control a creature with power N or greater" as a RULE 613.6 condition (Continuous Effects & Layer System)

- **What:** `control_count`'s `selector`/`min` shape gained an optional `min_power` key, scanning the battlefield directly instead of routing through the flat `count_select…
- **Files:** `game/static_conditions.py`

### Back to Basics: unconditional nonbasic-land no-untap (Continuous Effects & Layer System)

- **What:** The unconditional, unlimited-count sibling of the seventh pass's capped Winter Moon shape — `affects="all_lands"` plus the ordinary `nonbasic` selector, one new…
- **Files:** `parser/oracle/catalogue/static_handlers.py`

### Devotion (RULE 700.6) generalized selector + wedge names (Continuous Effects & Layer System)

- **What:** `continuous.count_selector`'s single-colour `devotion_to_<colour>` selector generalized to a colour set or one of five two-colour wedge names, via a shared `sub…
- **Files:** `game/continuous.py`, `parser/oracle/subgrammars.py`, `game/static_conditions.py`

### MEC-22: Anger cycle's other four graveyard-sourced statics (Continuous Effects & Layer System)

- **What:** Brawn/Filth/Valor/Wonder registered on the exact `"from_graveyard": True` `grant_keyword` shape Anger already established (a per-land-type `control_count` `acti…
- **Files:** `game/ability_catalogue.py`

### Urza's Saga: lasting self-granted activated ability + self-scaling token anthem (Continuous Effects & Layer System)

- **What:** `GrantSelfActivatedAbilityEffect` (RULE 714.2c) appends a real `grant_activated_ability`-shaped, permanent `StaticAbility` onto the Saga's own `static_effects`…
- **Files:** `game/effects/core.py`, `game/ability_catalogue.py`

### MEC-21: `grant_borrowed_activated_ability` (RULE 113.7c) (Continuous Effects & Layer System)

- **What:** A new layer-6 static reading a live, board-derived set of granted abilities (rather than one fixed printed ability) — for each matching grantee and each still-e…
- **Files:** `game/continuous.py`, `game/effects/core.py`, `models/game_state.py`

### MEC-26: group/chosen-permanent-scoped ability borrowing (Continuous Effects & Layer System)

- **What:** `grant_borrowed_activated_ability` gained `source_mode="group"` (Drana and Linvala — reads a live `affects` selector off the battlefield every recompute, no exi…
- **Files:** `game/continuous.py`, `game/effects/core.py`, `game/rules_engine.py`, `models/game_object.py`

### Stasis Untap-Step Skip

- **What:** "Players skip their untap steps" — a new `skip_untap_step` `StaticAbility` layer / `continuous.all_untap_steps_skipped`, checked once at the top of `GameEngine.…
- **Files:** `game/continuous.py`, `game/engine/turn_loop_mixin.py`.

### Anthem Non-Creature-Subtype Scope Guard

- **What:** `_ANTHEM_RE`'s `_scope` gained `_ARTIFACT_SUBTYPES`/`_vehicle_scope_params` so a bare non-creature subtype word ("Vehicles") isn't guessed as a creature subtype…
- **Files:** `parser/oracle/catalogue/static_handlers.py`.

### Dynamic P/T-Equals-Mana-Value Type Change (Karn, the Great Creator)

- **What:** `type_change`'s new `pt_selector="mana_value"` plus a new `"noncreature_artifact"` target kind for "becomes an artifact creature with power/toughness equal to i…
- **Files:** `game/continuous.py`, `game/targeting.py`, `game/rules_engine.py`.

## Combat

### PAR-79 — "Can't be blocked this turn" broad recognition (closed)

- **What:** `UnblockableEffect`/the `"unblockable"` `EffectRegistry` key

### MEC-78 — Graveyard-exit batch triggers (RULE 603.3f)

- **What:** `CARDS_LEFT_GRAVEYARD` carries a last-known-information card

### MEC-77 — Attack taxes (RULE 508.1g)

- **What:** The `attack_tax` marker static now supports both a fixed amount
- **Files:** `parser/oracle/catalogue/static_handlers.py`, `game/effects/core.py`,

### MEC-89: rules-correct entering-attacking combat primitive (RULE 506.3, 508.3a/508.4)

- **What:** Corrected the shared `put_onto_battlefield_attacking` primitive
- **What:** `RulesEngine.put_onto_battlefield_attacking(obj, defender=None)` — an already-on-the-battlefield creature is placed into the current combat *attacking* without…
- **Files:** `game/rules/misc_mixin.py`, `game/effects/core.py` (`CreateTokenEffect`), `parser/oracle/catalogue/handlers.py` (`_TOKEN_TAPPED_ATTACKING` suffix). `tests/test_par30_token_tapped_and_attacking.py`.

### M2 combat-math keywords and hexproof

- **What:** Annihilator (702.86), Afflict (702.130), and Bushido (702.45) synthesized as real `TriggeredAbility` objects at bind time so they go through the normal stack/pr…
- **Files:** `game/binding/core.py`, `game/combat.py`, `game/targeting.py`, `models/events.py`
- **Why:** Rampage was deliberately deferred here because its pump amount needs a per-firing dynamic amount a bind-once `TriggeredAbility` can't carry (built later, see M2…

### M2 Rampage (RULE 702.23)

- **What:** `RulesEngine.check_rampage(attacker, blocker_count)` builds a fresh `TriggeredAbility` with a `PumpEffect` sized to `n * max(0, blocker_count - 1)` and pushes i…
- **Files:** `game/rules_engine.py`, `game/game_engine.py`
- **Why:** Needed the same "build the effect fresh per firing" trick Ward used, since Rampage's amount depends on the specific block, which a bind-once `TriggeredAbility`…

### Firebreathing / until-end-of-turn activated pumps

- **What:** "{cost}: this creature gets ±N/±N until end of turn." and its keyword-granting sibling now MODELED with no new effect type — the existing `pump` handler plus `<…
- **Files:** `parser/oracle/catalogue/handlers.py`

### Combat/evasion static-restriction family (RULE 508.1a/509.1a)

- **What:** "~ can't attack"/"can't block"/"can't be blocked" (and combinations) modeled as synthetic layer-6 keyword flags reusing the existing `grant_keyword`/`activation…
- **Files:** `game/continuous.py`, `game/game_engine.py`, `game/combat.py`

### Combat Blocking & Creature-vs-Creature Damage Core

- **What:** `GameEngine.declare_blockers`/`can_block`/`_step_combat_damage` handle blocked/unblocked attackers, gang blocks (lethal-first damage spread), and blockers strik…
- **Files:** `game/combat.py`, `game/game_engine.py`

### Combat Statics — Qualified/Conditional Restriction Family

- **What:** A new `combat_restriction` static (a non-RULE-613 bucket, evaluated at combat time since who's defending/attacking doesn't exist yet at layer-engine time) cover…
- **Files:** `game/effects/core.py`, `game/combat.py`, `game/game_engine.py`

### Combat Statics — Requirements + Multi-Block Permissions

- **What:** RULE 509.1c/d requirements ("must be blocked if able"/"all creatures able to block ~ do so") as synthetic layer-6 flag keywords, checked by `_enforce_block_requ…
- **Files:** `game/game_engine.py`, `game/combat.py`, `models/game_object.py`

### Combat Statics — Count-Selector Threshold + Qualified Group Scope

- **What:** `matches_object_filter` gained a `power_lt_count_selector` key (a board-count threshold re-evaluated at combat time, e.g.
- **Files:** `game/combat.py`, `game/continuous.py`

### Fight (RULE 701.14, MEC-1)

- **What:** `FightEffect` is one atomic effect, not two `DealDamageEffect`s, because 701.14b's cancellation is mutual (either fighter gone/non-creature at resolution → neit…
- **Files:** `game/effects/core.py`, `parser/oracle/catalogue/handlers.py`, `parser/oracle/catalogue/subgrammars.py`

### One-Sided Fight / Damage Equal to Power

- **What:** `DamageEqualToPowerEffect` — "target creature deals damage equal to its power to target creature" (Rabid Bite) and the "when ~ dies, it deals damage equal to it…
- **Files:** `game/effects/core.py`

### MEC-99 — "Have it deal damage equal to its power" + "assigns no combat damage" (RULE 510.1e)

- **What:** Gaze of Pain's turn-scoped trigger ("Until end of turn, whenever a creature you control attacks and isn't blocked, you may choose to have it deal damage equal t…
- **Files:** `game/effects/library.py` (`_IMPLICIT_FIGHT_SUBJECTS`/`_implicit_fight_subject`), `game/effects/damage_draw.py` (`PreventCombatDamageDealtEffect`), `game/effects/registry.py`, `game/effects/composition.py` (`OptionalEffect.apply`), `game/rules/damage_death_mixin.py` (`deal_damage`'s comment), `parser/oracle/catalogue/handlers.py`, `tests/test_mec99_gaze_of_pain.py`

### ENG-14: "Defending Player" Resolution Sees Through Reconfigure

- **What:** `effects._defending_player_of` (shared by annihilator/afflict) now falls back to the object its source is `attached_to` before giving up, so Simian Sling's payo…
- **Files:** `game/effects/core.py`

### Interactive blocker declaration (RULE 509.1a)

- **What:** `legal_actions` now offers `declare_blockers`, one entry per eligible blocker carrying which attackers `can_block` legally permits it to be assigned to; the UI…
- **Files:** `game/game_engine.py`

### ENG-15 — subset attacker selection confirmed already supported

- **What:** Verified `GameEngine.declare_attackers` has been additive (not "attack with everything, one control") since the combat-restriction family shipped; the backlog t…
- **Files:** `game/game_engine.py`

### Exert (RULE 702.19)

- **What:** A declare-attackers-time choice (`GameEngine.declare_attackers`'s `exert` flag per attacker) rather than a resolve-time prompt; `GameObject.skip_next_untap` is…
- **Files:** `game/engine/combat_mixin.py`, `game/engine/turn_loop_mixin.py`, `game/combat.py`, `models/game_object.py`, `game/binding/core.py`, `game/ability_catalogue.py`.
- **Why:** Combat Celebrant needs a `not_already_exerted` guard reading the firing event's own pre-set snapshot (not the object's live flag, already true by trigger time)…

### Mass "Attacking Creatures" Untap Selector

- **What:** `TapEffect._TAP_SELECTORS` gained `"attacking_creatures"`, reusing the existing `continuous.group_selector_objects` branch (built for an anthem) for "untap all…
- **Files:** `game/effects/core.py`, `parser/oracle/catalogue/handlers.py`.

### RULE 702.122 Crew — Real Behaviour (MEC-29)

- **What:** "Crew N" went from parser-recognized-but-inert to real behaviour for every ~238 cached "Crew N" cards at once: `ActivationCost.crew_power` (an "any number from…
- **Files:** `game/costs.py`, `game/engine/activation_mixin.py`, `game/binding/core.py`, `models/game_object.py`.

### `"crewed_by_self"` Trigger Condition (Balthier and Fran, MEC-29)

- **What:** New RULE 603.1 group-subject trigger-condition key checking whether the acting object's live `crewed_by_ids` contains the ability's source, closing "whenever a…
- **Files:** `game/binding/core.py`.

### Blocker-Side Characteristic Restriction (Void Winnower)

- **What:** New `even_mana_value` filter key on `matches_object_filter`/`cast_prohibited` plus `cant_block_self_filtered` combat-restriction kind — the first restriction th…
- **Files:** `game/combat.py`, `game/continuous.py`.

## Casting & Costs

### Commander tax (RULE 903.8)

- **What:** `Player.commander_casts` (instance id → count) increments on each command-zone cast; `effective_cast_cost` adds `{2}` per previous cast (floored generic), surfa…
- **Files:** `game/game_engine.py`, `models/player.py`

### M2 alt-cost keywords: Kicker/Multikicker, Buyback, Escape, Flashback

- **What:** All four went from parsed-but-inert to real cast/resolve behavior.
- **Files:** `models/mana_cost.py`, `models/game_object.py`, `game/game_engine.py`, `game/costs.py`

### "If this spell was kicked, effect" conditional (RULE 702.33b, additional-effect shape)

- **What:** New `EffectSpec.condition` field (whitelisted to `{"kicked": bool}`) and a `ConditionalEffect` wrapper let a second sentence gate on the spell having been kicke…
- **Files:** `parser/oracle/spec.py`, `game/effects/core.py`, `parser/oracle/segmenter.py`

### {X} cost value threading through resolution

- **What:** `StackItem.x` → `RulesEngine._substitute_x` lets an effect's own amount reference the announced X value at resolution time, not just at the payment step.
- **Files:** `game/rules_engine.py`, `models/game_state.py`

### Channel / Cycling activation cost

- **What:** `ActivationCost.discard_self` models the "discard this card: effect" cost shape shared by Channel and Cycling.
- **Files:** `game/costs.py`

### Conditional Flash / instant-speed loyalty

- **What:** `AbilitySpec.conditional_flash` plus a new `game/condition_query.py` let a card gain Flash, or a planeswalker activate at instant speed, only while a board cond…
- **Files:** `game/condition_query.py`, `parser/oracle/spec.py`

### Impulsive look and impulsive draw

- **What:** `ImpulsiveLookEffect`/`ImpulsiveDrawEffect` plus `GameState.temp_play_permissions` model "exile the top card, you may play it this turn"-shaped effects.
- **Files:** `game/effects/core.py`, `models/game_state.py`

### Board-count cost reduction for a card in hand

- **What:** `continuous.self_cost_reduction_for` reads a live board count to reduce a hand card's own cast cost.
- **Files:** `game/continuous.py`

### Spell-copy on the stack (RULE 707.10)

- **What:** `RulesEngine.copy_spell` builds a fresh token `GameObject` of the spell's copiable card, controlled by the copier, keeping the original's targets/{X}, pushed ab…
- **Files:** `game/rules_engine.py`, `game/effects/core.py`

### Sorcery-speed-only activation marker (RULE 602.5d)

- **What:** "Activate only as a sorcery."/"…any time you could cast a sorcery." is claimed and folded into `ActivationCost.sorcery_speed_only`, already enforced by `GameEng…
- **Files:** `parser/oracle/catalogue/handlers.py`, `game/binding/core.py`

### Standing Graveyard-Cast Permission

- **What:** `GraveyardCastPermissionEffect` lets a permanent grant "you may cast spells from your graveyard" at the card's own normal mana cost — a genuine permission, not…
- **Files:** `game/effects/core.py`, `game/graveyard_cast.py`, `game/ability_catalogue.py`
- **Why:** Paid at the card's own printed cost rather than a keyword cost, so `effective_cast_cost` needed no change at all.

### Retrace (RULE 702.81) — MEC-53

- **What:** A third graveyard-cast keyword next to Flashback/Escape, but shaped unlike either: the spell pays its **normal** mana cost (`effective_cast_cost`'s default `alt…
- **Files:** `game/engine/lands_mixin.py` (`_graveyard_cast_keyword`), `game/engine/casting_mixin.py` (`can_cast` gate, `_pay_retrace_discard`), `game/continuous.py` (`granted_retrace_for`, `_NON_RULE_613_LAYERS`), `game/effects/core.py` (`grant_retrace` registry), `parser/oracle/catalogue/static_handlers.py`, `tests/test_mec53_retrace.py`
- **Why:** Mirrored `grant_escape`/`granted_escape_for` rather than inventing a new grant shape — the "layer-6 ability grant onto graveyard cards, kept out of `recompute`…

### Modal Spells "Choose One / Choose One or Both" (RULE 700.2)

- **What:** Modal blocks parse into `AbilitySpec.modes`; casting offers one `cast_spell` action per mode (the MDFC per-face pattern), and the chosen mode's effects become t…
- **Files:** `parser/oracle/catalogue/modal.py`, `game/game_engine.py`

### Additional Cast Costs (RULE 601.2b/601.2h)

- **What:** "As an additional cost …, sacrifice a creature/artifact/land | discard a card | pay N/X life" parses onto `AbilitySpec.additional_cost`, gates cast legality, an…
- **Files:** `game/costs.py`, `parser/oracle/catalogue/handlers.py`

### Modal "Choose N —" / "Choose N or More —" (RULE 700.2)

- **What:** `AbilitySpec.modes` gained a `choose` int (fixed N, Kolaghan's/Austere Command-shaped) and an `at_least` bool (variable N, Farewell-shaped).
- **Files:** `parser/oracle/catalogue/modal.py`, `parser/oracle/spec.py`, `game/game_engine.py`, `game/rules_engine.py`

### `{X}` Cost Threading

- **What:** `StackItem.x` (set at cast/activate time) is substituted into a resolving effect's `"x"`-sentinel `amount`/`count` fields by `RulesEngine._substitute_x`, called…
- **Files:** `game/rules_engine.py`, `parser/oracle/spec.py`

### Board-Count Cost Reduction (Delve/Affinity)

- **What:** `continuous.cost_reduction_for` gained an optional `per: <count_selector>` param for battlefield-static reductions; a new `self_cost_reduction_for` reads a `lay…
- **Files:** `game/continuous.py`, `game/game_engine.py`

### Conditional Flash / Conditional Instant-Speed Loyalty Activation

- **What:** A new `AbilitySpec.conditional_flash` field gates cast/activation *legality* live against board state (e.g.
- **Files:** `game/condition_query.py`, `game/game_engine.py`, `models/game_object.py`

### Library-Top/Impulsive-Draw Permission Closeout

- **What:** A generic oracle-text static for "you may play lands [and cast spells] from the top of your library" (the parser-recognized sibling of the hand-authored `top_li…
- **Files:** `parser/oracle/catalogue/static_handlers.py`, `game/top_library.py`, `game/game_engine.py`

### Interactive Sacrifice-as-Cost & Discard Choices

- **What:** An activated ability's own "Sacrifice a `<type>`" cost and looting/forced-discard both became real player choices instead of auto-picking the first candidate.
- **Files:** `game/game_engine.py`, `game/effects/core.py`, `services/game_session.py`

### ENG-3: Interactive Cost-Payment Sacrifice/Discard Choices

- **What:** A spell's own additional-cost "sacrifice/discard" (RULE 601.2b) and a plain "discard N cards" activation cost both gained the same choice shape as ENG-2, but as…
- **Files:** `game/game_engine.py`, `game/costs.py`

### Conditional cast prohibition (`cast_prohibition` static)

- **What:** The conditional sibling of the flat per-turn `cast_limit` static (RULE 601.3a), evaluated against the *casting* player's own board (e.g.
- **Files:** `game/continuous.py`
- **Why:** That evaluation-against-the-casting-player property is exactly why it can't be expressed as a layer value.

### History-scoped cast restriction (Hope of Ghirapur)

- **What:** `GameState.combat_damage_to_players_this_turn` and the `player_dealt_combat_damage_by_source` target kind answer a "history" question no live board state can an…
- **Files:** `models/game_state.py`, `game/effects/core.py`, `game/game_engine.py`

### Sacrificed-cost mana value tracking (Eldritch Evolution/Neoform)

- **What:** `GameObject.sacrificed_cost_mana_value` plus new `SearchLibraryEffect` params (`mana_value_from`, `extra_counters`) — `StackItem.x` only ever threads an announc…
- **Files:** `models/game_object.py`, `game/effects/core.py`

### `pay_cost_then` — general optional-payment primitive (RULE 118.3)

- **What:** Generalized the previously energy-only optional payment into a general "pay a cost, with an 'if you don't' branch and an event-named payer" primitive, built on…
- **Files:** `game/effects/core.py`, `game/rules_engine.py`
- **ENG-48 — announcing X (RULE 107.3a):** a cost with {X} ("you may pay {X}. If you do, …") used to offer one "pay" button, charge X = 0 and leave the branch's `"x"` sentinel to read the source's `x_paid` (0) — Vigil for the Lost gained 0 life, Squealing Devil pumped +0/+0, Taj-Nar searched for mana value ≤ 0. `_request_pay_cost_then` now scans the payer's pool for the largest affordable X (`_max_payable_x`, capped at `PAY_COST_THEN_MAX_X` = 30) and offers one `pay_x:<n>` option per value, largest first (a bare `"pay"` still answers, as the largest). The generic option buttons render it, so no board-UI change was needed. `_resume_pay_cost_then` prices the cost with `ManaCost.with_x`, then binds X into the paid branch's specs, the reflexive "when you do" trigger and its modes (`_substitute_x_specs` → `composition._resolve_x`, recursive so a search's nested `criteria.max_mana_value` is reached); the declined branch sees X = 0. A cost *without* {X} substitutes nothing, so a branch whose "X" is the enclosing spell's own X still reads `x_paid`.
- **Why the `owns_x_sentinel` guard:** `RulesEngine._substitute_x` also walks every effect's `inner_specs` to fill a spell's X into nested bodies (PAR-124), and `PayCostThenEffect.inner_specs` is exactly that attribute — it overwrote the payoff's `"x"` with the *trigger's* X (0) in place before the choice ever opened. `PayCostThenEffect.owns_x_sentinel` (true when its cost text carries {X}) opts it out, next to ENG-50's `_X_OWNING_CAPTURES`. The parser's refusal of "pay {X}. If you do, put X counters" was lifted: Hero of Leina Tower and Wildborn Preserver are MODELED. Tests: `tests/test_eng48_pay_x_then.py`.

### Bargain

- **What:** A genuinely payable optional additional cost plus an "if bargained" `EffectSpec.condition`, reusing exactly the shape Kicker's "kicked" gate already had.
- **Files:** `game/costs.py`, `game/effects/core.py`

### Entwine (RULE 702.42a)

- **What:** A real, separately-priced "choose all modes" upgrade offered alongside an ordinary single-mode modal cast, replacing the free `or_both` flag Tooth and Nail had…
- **Files:** `game/binding/core.py`, `game/game_engine.py`, `services/game_session.py`

### Optional free cast offered, not forced (Tibalt's Trickery, Possibility Storm)

- **What:** `dig_until`'s new `"cast_free_window"` destination grants the same exile-cast window Rebound/Beseech use, and `ReturnUncastExiledEffect` bottoms the card at the…
- **Files:** `game/rules_engine.py`, `game/effects/core.py`

### MEC-6 — self-scoped attacking-creature cost reduction

- **What:** Added the missing `attacking_creatures_you_control` (and unscoped `attacking_creatures`) `count_selector` entry to the pre-existing but never-exercised `self_co…
- **Files:** `game/continuous.py`, `game/effects/core.py`, `parser/oracle/catalogue/static_handlers.py`

### MEC-7 — targets-a-commander conditional flash

- **What:** `"targets_a_commander"` joined the allowed conditional-flash keys; since RULE 601.3a's timing check runs before targets are chosen (RULE 601.2c), `can_cast`/`ef…
- **Files:** `game/game_engine.py`, `game/rules_engine.py`, `parser/oracle/segmenter.py`

### MEC-4 — Strive cost escalation

- **What:** `AbilitySpec.strive_cost` rides as its own field (Strive isn't a numbered RULE 702 keyword); `effective_cast_cost` adds one full copy of the cost per target bey…
- **Files:** `game/binding/core.py`, `game/game_engine.py`, `parser/oracle/segmenter.py`
- **Why:** Lands with zero cards reaching full MODELED — every real Strive card also needs a still-unmodeled "any number of target creatures" targeting family (PAR-15), so…

### Compound "Activate only as a sorcery and only if `<condition>`" (PAR-10)

- **What:** A new `ActivationCost.activation_condition` field, checked live via the same RULE 613.6 `game/static_conditions` whitelist a permanent's own "as long as" static…
- **Files:** `parser/oracle/catalogue/handlers.py`, `game/engine/activation_mixin.py`, `game/static_conditions.py`, `models/game_state.py`

### "Return this card from your graveyard to the battlefield[, tapped]" (PAR-10 discovery)

- **What:** A full-cache scan (motivated by Dread Wanderer) found 69+ cards using this shape (Reassembling Skeleton, Bloodsoaked Champion, …).
- **Files:** `game/effects/core.py`, `game/costs.py` (`ActivationCost.graveyard_zone`)

### Kicker's own announced {X} (PAR-7, RULE 702.33b)

- **What:** `GameEngine.can_cast`/`effective_cast_cost`/`cast_spell` all gained a `kicker_x` parameter, wholly independent of a spell's own `x` announcement (two separate R…
- **Files:** `game/game_engine.py`, `game/engine/casting_mixin.py`, `services/game_session.py`, `frontend/src/js/gameBoardView.js`

### ImpulsiveDrawEffect's first oracle-text route + free-cast draw-reveal (PAR-13)

- **What:** `_exile_top_play` (Runestone Caverns' "Exile the top two cards.
- **Files:** `game/effects/core.py`, `game/rules_engine.py`

### "`<Type>` spells you cast cost `<N>` less/more" (PAR-12)

- **What:** The self-scoped ("you cast") sibling of the already-shipped unscoped cost-tax shape (Baral, Chief of Compliance).
- **Files:** `parser/oracle/catalogue/static_handlers.py`, `game/continuous.py`

### RULE 702.33b override kicked-conditional

- **What:** "Deals N damage… if kicked, deals M damage **instead**" — a different shape from the additive "if kicked, `<effect>`" already supported.
- **Files:** `game/effects/core.py`

### RULE 118.3 `pay_cost_then`, first oracle-text recognizer

- **What:** "You may pay `<cost>`.
- **Files:** `parser/oracle/catalogue/handlers.py`

### Colour/board-scoped cost reduction widenings (Imodane batch)

- **What:** `continuous.cost_reduction_for` gained a `spell_color` filter for the Medallion cycle; `self_cost_reduction_for`'s existing count-selector mechanism (Delve/Affi…
- **Files:** `game/continuous.py`

### RULE 118.9 alternative-cost family, dropped for four cards

- **What:** Force of Will/Force of Negation/Force of Vigor/Daze each print an alt-cost pitch — confirmed genuinely unbuilt (113 cache-wide cards) and tracked as its own ope…
- **Files:** `game/ability_catalogue.py`
- **Why:** Dropping the alt-cost rider for Misdirection/Deflecting Swat would have left a genuine no-op card, worse than staying UNMODELED — so those two were left unclaim…

### RULE 118.9 alternative costs — pitch-cost family + free/alt-cost UI wiring (MEC-15)

- **What:** `AbilitySpec.alt_cost` (new structured field), `GameObject.alt_cast_cost`/`alt_cast_condition`, and an `alt_cost: bool` parameter threaded through `can_cast`/`c…
- **Files:** `game/costs.py`, `parser/oracle/spec.py`, `game/engine/casting_mixin.py`, `game/game_engine.py`, `services/game_session.py`, `game/ability_catalogue.py`
- **Why:** `free=True` casting had been backend-only and unreachable from a real game session the whole time (`_offer_cast` never surfaced it) — this batch fixed that wiri…

### Colour-scoped and opponent-scoped spell cost tax (Casting & Costs)

- **What:** New `_SPELL_COST_TAX_COLOR_RE` parser row reaches `cost_reduction_for`'s already-built `spell_color` param (Medallion cycle); a genuinely new `affects="opponent…
- **Files:** `parser/oracle/catalogue/static_handlers.py`, `game/continuous.py`

### Activation-cost group scope by main card type (Casting & Costs)

- **What:** `activation_cost_reduction_for` gained a `card_type` group-scope branch (Training Grounds's "Activated abilities of creatures you control cost `{N}` less") alon…
- **Files:** `game/continuous.py`, `parser/oracle/catalogue/static_handlers.py`

### "Cast spells this turn as though they had flash" parser recognition (Casting & Costs)

- **What:** New `HANDLERS` row for Emergence Zone claims the unrestricted-"spells" wording of the already-shipped `GrantFlashUntilEndOfTurnEffect` (previously reachable onl…
- **Files:** `parser/oracle/catalogue/handlers.py`

### Mindbreak Trap's board-count free-cast condition (Casting & Costs)

- **What:** New `opponent_spells_cast_this_turn_at_least` key on `AbilitySpec.free_cast_condition` — the family's first count-valued (not boolean) condition, reading `GameS…
- **Files:** `parser/oracle/segmenter.py`, `game/condition_query.py`

### Impulsive-draw regex widened to real printed word orders (Casting & Costs)

- **What:** `ImpulsiveDrawEffect`'s regex (RULE 601.3b) widened to accept both duration-word orders, "that card"/"those cards" pronouns, a singular "the top card," and `cou…
- **Files:** `parser/oracle/segmenter.py`

### `ActivationCost.only_during_your_turn` + `GainControlBySourceEffect` (Wishclaw Talisman) (Casting & Costs)

- **What:** `only_during_your_turn` (RULE 602.5d's wider sibling of `sorcery_speed_only` — legal at instant speed on your own turn only) plus `GainControlBySourceEffect` ("…
- **Files:** `game/costs.py`, `game/effects/core.py`, `game/ability_catalogue.py`
- **Why:** With no real "choose an opponent" chooser for a player (only `request_choose_objects` for `GameObject` candidates exists), the *next* opponent in seating order…

### Ghostfire Slice: self-cost-reduction `active_if` + multicolour-count selector (Casting & Costs)

- **What:** `self_cost_reduction_for` now honours an `active_if` gate; `count_selector` gained `multicolored_permanents_you_control`; a general "if `<condition>`" recognize…
- **Files:** `game/continuous.py`, `parser/oracle/catalogue/static_handlers.py`, `game/ability_catalogue.py`

### "Costs {N} less to cast if it targets a `<criteria>`" (RULE 601.2f, PARSER_VERSION 181)

- **What:** the Ajani's Response / Knockout Blow / Depower cycle (28 SOLO).
- **Files:** `game/continuous.py`, `game/effects/core.py` (`cost_reduction` factory), `game/engine/casting_mixin.py`, `game/combat.py`, `parser/oracle/catalogue/static_handlers.py`. `tests/test_par30_cost_less_if_it_targets.py`.

### Eye of Ugin: "colorless" search criterion + spell-subtype cost filter (Casting & Costs)

- **What:** `models.card_query`'s `color` key gained a `"colorless"` special case (empty colour-identity check, search-only); `continuous.cost_reduction_for` gained a `spel…
- **Files:** `models/card_query.py`, `game/continuous.py`, `game/ability_catalogue.py`

### Spell-side self-cost-reduction reaches `static_effect_specs` (Casting & Costs)

- **What:** An instant/sorcery's own "this spell costs `{N}` less to cast if/for each…" line had never reached `static_effect_specs` at all (only permanents did).
- **Files:** `parser/oracle/segmenter.py`

### "Your opponents can't cast spells during your turn" trailing phrasing (Casting & Costs)

- **What:** `cast_prohibition`'s existing `scope="opponents"` + `active_if={"kind": "your_turn"}` already expressed this; only the *trailing*-phrasing parser row (`_CANT_CA…
- **Files:** `parser/oracle/catalogue/static_handlers.py`

### Snapback/Pyrokinesis: pitch-cost oracle-text handler (Casting & Costs)

- **What:** MEC-15's pitch-cost family (`AbilitySpec.alt_cost`) had no oracle-text recognizer at all — every card besides the four hand-authored Force-of-Will-shaped ones s…
- **Files:** `parser/oracle/segmenter.py`

### Remaining RULE 118.9 "pitch" cost shapes (Casting & Costs)

- **What:** Three new `ActivationCost` fields — `return_to_hand_count` (Gush), `sacrifice_filter` (a `matches_object_filter`-shaped dict, Flare of Denial, gaining a new `no…
- **Files:** `game/costs.py`, `game/engine/casting_mixin.py`, `game/condition_query.py`, `parser/oracle/spec.py`

### "Sacrifice an artifact or creature" additional-cost sentinel (Casting & Costs)

- **What:** New `additional_cost` sacrifice sentinel `"artifact_or_creature"`, plumbed through the whitelist and all three `_matches_*` copies.
- **Files:** `parser/oracle/spec.py`, `game/costs.py`

### Submerge's compound free-cast condition (Casting & Costs)

- **What:** New named boolean key `opponent_controls_forest_and_you_control_island` on `AbilitySpec.free_cast_condition` — a fixed compound condition, not a general "contro…
- **Files:** `game/condition_query.py`, `parser/oracle/spec.py`

### `grant_graveyard_cast_permission_this_turn` — Past in Flames (Casting & Costs)

- **What:** The primitive already existed (built for Backdraft Hellkite); Past in Flames just needed an oracle-text recognizer for "Each instant and sorcery card in your gr…
- **Files:** `parser/oracle/catalogue/handlers.py`

### Talon Gates of Madara: hand-zone "put onto the battlefield" activated ability (Casting & Costs)

- **What:** `PutSelfOntoBattlefieldFromHandEffect` + `ActivationCost.hand_zone` — `graveyard_zone`'s hand-zone sibling, auto-stamped onto a matching ability's cost by `effe…
- **Files:** `game/effects/core.py`, `game/costs.py`, `game/binding/core.py`

### MEC-20: RULE 601.2f "Expertise" free-cast-from-hand cycle (Casting & Costs)

- **What:** `FreeCastFromHandEffect` opens a `request_choose_objects` `"grant_free_cast"` action that only *arms* the picked hand card's `free_cast_instance_ids` entry rath…
- **Files:** `game/effects/core.py`, `game/rules_engine.py`, `parser/oracle/catalogue/handlers.py`
- **Why:** RULE 601.2f/718 technically require the free cast to happen as the Expertise spell resolves, but the engine has no "pause mid-resolution for a nested cast+targe…

### MEC-24: targeted flashback grant (Casting & Costs)

- **What:** `GameState.temp_flashback_grants` (`instance_id -> cost`), a per-graveyard-card marker (mirroring `temp_play_permissions`' shape); `GrantFlashbackToTargetEffect…
- **Files:** `game/effects/core.py`, `models/game_state.py`, `game/engine/lands_mixin.py`, `game/engine/casting_mixin.py`

### Alt-Cost Family Unconditional Gate (Bringer Cycle)

- **What:** The whole RULE 118.9 alt-cost family (`pitch`/`sac_filter`/`sac_type`/`ret_two`/`pay_if`/`pay_mana`) was pulled out of `allow_spell_effect`'s gate and made unco…
- **Files:** `parser/oracle/gate.py`.

### Snuff Out's Alt-Cost Siblings

- **What:** Alt-cast payment combinations — a board condition paired with a non-mana payment, mana-plus-return-to-hand (Borderpost cycle), and counted sacrifice beyond one…
- **Files:** `game/rules/casting_mixin.py`, `game/continuous.py`.

### Destroy/Exile-Then-Controller-Digs (Polymorph/Transmogrify)

- **What:** `DestroyExileThenControllerRevealCreatureEffect` destroys/exiles a target creature, then that creature's own controller (read before the RULE 400.7 zone change)…
- **Files:** `game/effects/core.py`, `game/rules_engine.py`.

### Cost Floor (Trinisphere)

- **What:** `continuous.cost_floor_for` + `StaticAbility.min_generic`, kept structurally apart from the existing additive cost-reduction/increase net (two floors take the m…
- **Files:** `game/continuous.py`, `game/effects/core.py`.

### Standing Exile-Cast Permission (Lukka's +1)

- **What:** `GameState.exile_cast_condition` + `GameEngine._has_conditional_exile_permission` — a standing, never-turn-swept exile-cast grant (unlike every existing `temp_p…
- **Files:** `models/game_state.py`, `game/engine/casting_mixin.py`, `game/static_conditions.py`.

### Reveal-Then-Free-Cast-If-Match (Powerbalance)

- **What:** `RevealTopThenFreeCastIfMVMatchEffect` reuses `request_choose_objects`'s existing `"cast_free"` action for the interactive "you may cast" half; the "you may rev…
- **Files:** `game/effects/core.py`.

### MEC-30 Pass 5: Three Cost-Shape Gaps (Penance, Seasoned Tactician, Bone Mask)

- **What:** `ActivationCost.put_hand_card_on_library` (Penance's "put a card from your hand on top of your library" cost, with chosen-or-auto-pick plumbing mirroring `_reso…
- **Files:** `game/costs.py`, `game/engine/activation_mixin.py`, `game/rules_engine.py`, `game/mana_potential.py`.

## Counters

### "Enters with N counters" replacement effect (RULE 614.1-style)

- **What:** "~ enters the battlefield with N/X `<counter-type>` counters on it." parses (`entry_counters_condition`/`entry_counters`, mirroring the tapped-entry split) and…
- **Files:** `parser/oracle/catalogue/counters.py`, `game/ability_catalogue.py`, `game/rules_engine.py`

### Bare "proliferate" recognition (RULE 701.30)

- **What:** `ProliferateEffect` already existed and was registered but had no oracle-text handler at all; one handler for bare "proliferate." closes it, including multi-sen…
- **Files:** `parser/oracle/catalogue/handlers.py`

### Kicked-conditional entry counters

- **What:** "if ~ was kicked, it enters with N counters on it" and its Multikicker-scaled "…for each time it was kicked" sibling reuse the existing entry-counters machinery…
- **Files:** `parser/oracle/catalogue/counters.py`, `game/rules_engine.py`

### Sunburst entry counters (PAR-42, PARSER_VERSION 238)

- **What:** RULE 702.43a — "~ enters with a +1/+1 counter on it **for each color of mana spent to cast it**." (Chamber Sentry / Crystalline Crawler / Woodland Wanderer / Sk…
- **Files:** `parser/oracle/catalogue/counters.py`, `game/rules/casting_mixin.py`, `parser/oracle/gate.py` (PARSER_VERSION 238)

### "Remove a Counter From ~" Activation Cost (RULE 701.19/602.1)

- **What:** The cost-parsing/payment machinery already existed; the gap was `segmenter.py`'s `_COST_LOOKS_REAL` sniff not recognizing "remove … counter" as a real cost when…
- **Files:** `parser/oracle/segmenter.py`, `game/costs.py`

### Variable-Count "Remove a Counter" Activation Cost

- **What:** `ActivationCost.remove_counters` gained `REMOVE_COUNTERS_X`/`REMOVE_COUNTERS_ANY` sentinels for "remove X counters" (32 real cards) and "remove any number of co…
- **Files:** `game/costs.py`, `game/game_engine.py`

### Activation-cost text grammar and unread-fragment refusal (ENG-49)

- **What:** `costs.parse_activation_cost` ran ~20 independent regex searches over a cost string and silently ignored every word none of them matched, so an ability could be claimed cheaper than printed: Fauna Shaman searched without discarding (`_DISCARD_RE` only knew "a card"), Grim Lavamancer pinged without exiling ("other" was mandatory), Rootha copied without bouncing, the Expeditions' "… and sacrifice it" never sacrificed, "Sacrifice two lands" charged nothing. The recognizers moved to one parser-side grammar, `parser/oracle/catalogue/cost_text.py`: `scan_cost_text` runs them in precedence order and returns each hit plus `leftover`, the words nothing read. `costs._parse_text` maps the hits onto `ActivationCost` fields and stores the leftover as `ActivationCost.unrecognized`.
- **Fail closed, twice:** the segmenter leaves an activated line with a leftover unclaimed (the card goes UNMODELED), and `bind_from_catalogue` refuses to bind an activated ability whose cost has one (logged — this catches hand-authored cost text). The grammar has to live on the parser side for the first check; importing `game/costs` from the parser would break the parser security-boundary test (`test_dependency_direction.py`). Same single-source idiom as `catalogue/lands.py`. The segmenter's old per-shape `_UNPAYABLE_VARIABLE_SACRIFICE_RE` guard became the general check, apart from a mana-ability-only "Sacrifice X" guard: `tap_for_mana` announces no X, so Springjack Pasture stays refused.
- **Grammar widened from the audit** (a corpus pass of every parser-claimed activated cost, 440 cards with a leftover at the start): "Sacrifice X/N `<type>s`" (`sacrifice_count`, with `SACRIFICE_COUNT_X` now also offered as `has_x`/`max_x` and bounded by the pool, which fixes Grim Hireling's never-announced X; colour/"nonland" adjectives, `tokens` suffix), "an artifact or creature" (`<a>_or_<b>`, split by both sacrifice-type matchers), "sacrifice it", "a Prism token", typed and random discards (`discard_filter`, `discard_random` → `rules.discard_random`, RULE 701.8d), "exile N [`<type>`] cards from your graveyard" charged on activation (`_activation_graveyard_exile_candidates`, excluding the source), "Exile this card from your graveyard" (`exile_self` + `graveyard_zone`, 47 Renew/Scavenge-shaped cards whose ability was unactivatable before), "Return ~ to its owner's hand" (`RETURN_SELF_TO_HAND`), counters removed "from ~", digit energy counts ("pay 8 {e}"), "Waterbend {N}" (`help_pay_kind`), "Unattach ~", "exile ~ from your hand", and ability-word prefixes ("Teleport — "). Typed filters are vetted against card types/supertypes + `SUBTYPES`, so "a historic card" stays unread rather than guessed.
- **Coverage effect:** 17,763 → 17,654 (−109; Commander-legal 17,069 → 16,967). +5 newly MODELED (Copper-Leaf Angel, Krav, Hero of Leina Tower, Wildborn Preserver, and Grim Hireling's parser verdict); 119 lost — every one had an activation cost part that was never charged. The remaining shapes are ENG-51. PARSER_VERSION 499. Tests: `tests/test_eng49_cost_leftovers.py`; `test_par120_counter_amounts_and_x.py`'s two refusal pins were flipped to "claimed".
- **Files:** `parser/oracle/catalogue/cost_text.py` (new), `game/costs.py`, `parser/oracle/segmenter.py`, `game/binding/core.py`, `game/engine/activation_mixin.py`, `game/engine/legal_actions_mixin.py`, `game/rules/misc_mixin.py` (`_matches_permanent_type`), `parser/oracle/gate.py`.
- **ENG-51 — charging the audit's residue (PARSER_VERSION 500):** the shapes ENG-49 had left refused, taken in order of how many cards each blocked.
  - **One permanent-phrase vocabulary.** `continuous.matches_permanent_word` reads the word `costs._permanent_word` builds from a cost phrase: `_` joins parts that must all hold ("another black creature" → `other_black_creature`, "a Goblin creature", "a noncreature artifact", "a creature with defender"), `_or_` joins alternatives. A part is a card type, colour, supertype, "token"/"non`<type>`", a tapped state, defender/flying, else a subtype. Sacrifice, counted sacrifice, tap-others, returning N permanents, the `pay_cost_then` path (`_matches_permanent_type`) and counter-removal scopes all go through it. The engine's own sacrifice matcher kept its explicit words and now falls through to it, which retired the Natural Order-only `<color>_creature` table. "other"/"another" always matches in the word; leaving the source out is the caller's job (`_names_other`), since only it knows the source.
  - **New components:** counters removed "from a creature you control" (one permanent carries them all) or "from among creatures you control" (spread), or of any kind (`REMOVE_COUNTERS_ANY_KIND`) — one `_counter_removal_plan` answers both "payable?" and "which", and bounds an announced X. "Exert ~" (`exert_permanent`, now shared with the attack declaration's exert), "Mill N cards", "Discard another card named ~", "Exile the top [`<type>`] card of your graveyard", "Exile a card from your hand", "Tap enchanted creature/land", "Sacrifice enchanted creature", "Return N lands you control to their owner's hand" (activation support for the alt-cast-only `return_to_hand_count`), "Pay half your life, rounded up" (`PAY_LIFE_HALF_UP`, sized at payment), "Put a -1/-1 counter on a creature you control" (= Blight 1, RULE 701.68), either-type graveyard exiles ("an instant or sorcery card"), "reveal ~ from your hand" (`hand_zone`). All auto-picked, the convention every non-interactive cost component already follows.
  - **Parser:** a cost the grammar reads *completely* is accepted even without a symbol `_COST_LOOKS_REAL` keys on (`_is_activation_cost` — "Tap enchanted creature: …"). "`<cost>` or `<cost>`: …" (the Shards) becomes two activated abilities sharing the effect, the Pemmin's Aura `extra_specs` idiom.
  - **Mana abilities:** `mana_abilities._parse_mana_ability_lines` reads the card's own name as "~" (so Black Tulip's "Exile Black Tulip" is charged) and drops a mana ability whose cost has a leftover — Soldevi Adnate, Jungle Patrol, a few Un-cards — except a planeswalker's loyalty line. Station "N+ |" tier lines (Evendo, Uthros, The Eternity Elevator) were being bound as unconditional mana abilities; they now carry `ManaAbility.min_charge`, checked with the Leveler gate. Mill, exile-from-hand, exert and counted-sacrifice mana costs stay out of auto-tap (`mana_potential._spends_more_than_a_tap`), like a sacrifice already did.
  - **Springjack Pasture:** "Sacrifice X Goats: Add X mana of any one color. You gain X life." — `ManaAbility.x_scaled`/`gain_life_x`, an `x` on `tap_for_mana` (and the session's `tap_for_mana` action), `has_x`/`max_x` on the offer (bounded by the Goats), and an X field on the board's mana buttons. The segmenter claims that one X-sized mana shape and still refuses any other.
  - **Coverage:** 17,654 → 17,748 (+94); Commander-legal 16,967 → 17,055. What still has an unread fragment is one-offs (PARSER_LONG_TAIL.md's "Known-open clusters"). Tests: `tests/test_eng51_cost_shapes.py`.

### "Remove All Counters" Effect

- **What:** `RemoveCountersEffect` (untargeted board-wide or `target_kind="permanent"`) strips every counter of every kind via `context.add_counters` with a negative amount…
- **Files:** `game/effects/core.py`

### "Proliferate Twice / N Times"

- **What:** `ProliferateEffect` gained a `times` param and parser recognition of the literal word "twice" or a digit-folded "N times" (normalize doesn't fold "twice" itself…
- **Files:** `game/effects/core.py`, `parser/oracle/catalogue/handlers.py`

### Kicked-Gated Entry Counters + Granted Keyword

- **What:** RULE 702.33b's "…and with `<keyword>`" compound entry-counter clause: both kicked entry-counter regexes gained an optional trailing keyword clause, and `RulesEn…
- **Files:** `parser/oracle/catalogue/counters.py`, `game/rules_engine.py`

### "Remove Up to N Counters from Target Permanent"

- **What:** `RemoveCountersEffect` gained a `max_count` param that opens an interactive amount-then-kind chooser (`request_remove_counters_choice`/`_continue_remove_counter…
- **Files:** `game/effects/core.py`, `game/rules_engine.py`

### Player-Counter Primitive

- **What:** `RulesEngine.add_player_counters`/`Player.add_counters` — the engine's first effect-driven way to add poison/energy/experience counters to a *player*, mirroring…
- **Files:** `game/rules_engine.py`, `models/player.py`

### RULE 122 Energy `{E}` Activated-Ability Cost Pips

- **What:** `ActivationCost.pay_energy` handles both repeated-pip ("Pay {E}{E}{E}{E}") and spelled-out-count ("Pay eight {E}") forms, charged via `add_player_counters(playe…
- **Files:** `game/costs.py`

### Energy Resolve-Time Optional Payment

- **What:** "You may pay {E}{E}.
- **Files:** `game/effects/core.py`, `game/rules_engine.py`

### Rad counters (RULE 728)

- **What:** A fourth source-less inherent trigger (alongside Monarch/Initiative) mills cards equal to the active player's live rad-counter count each main phase, loses life…
- **Files:** `game/rules_engine.py`, `game/effects/core.py` (`RadiationMillEffect`, `AddPlayerCountersEffect`), `parser/oracle/catalogue/handlers.py`
- **Why:** RULE 728.1 makes rad counters controlled by the active player regardless of who holds them (RULE 113.8 exception), so no designation/holder indirection was need…

### Rad counters — deferred-gap closure batch

- **What:** Closed all 11 previously-deferred rad-counter cards with real behaviour: new trigger-subject grammar (enchanted/equipped-creature verbs, tribal "self-or-group"…
- **Files:** `parser/oracle/segmenter.py`, `game/effects/core.py`, `game/rules_engine.py`, `game/continuous.py`
- **Why:** Per the project's "no half-implementations" rule — a second deferral of any of these had to be hand-authored this round rather than rolled forward a third time.

### Kicked X-scaled entry counters (PAR-7)

- **What:** "If this creature was kicked, it enters with X +1/+1 counters" — X being Kicker's own paid amount (`kicker_x_paid`), not a fixed count.
- **Files:** `parser/oracle/catalogue/counters.py`, `game/rules_engine.py`

### Named counter kinds — "spore" (PAR-12, RULE 122.1a)

- **What:** `AddCountersEffect.kind` was already a free string; only "put a counter on X" recognition was hard-restricted to `+1/+1`/`-1/-1`.
- **Files:** `parser/oracle/catalogue/handlers.py`

### Counter/Token-Creation Count-Amount Resolver Wiring (MEC-27)

- **What:** `AddCountersEffect` gained `amount_from_count_selector` (mirroring `DealDamageEffect`) with a new `add_counters_devotion` parser row for "put X counters on `<ta…
- **Files:** `game/effects/core.py`, `parser/oracle/catalogue/handlers.py`.

## Card Types & Structures

### Loyalty / planeswalker abilities (RULE 606)

- **What:** `ActivationCost.loyalty` parses signed `[±N]` costs; planeswalkers enter with printed starting loyalty; activation is gated to sorcery speed + once-per-turn; da…
- **Files:** `game/costs.py`, `game/game_engine.py`, `models/card.py`

### Aura / Equipment attachment resolution (RULE 303/301.5)

- **What:** An Aura attaches to its cast
- **What:** An Aura attaches to its cast-time target on resolution (fails to attach → straight to graveyard); Equip/Fortify/Reconfigure are sorcery-speed activated abilitie…
- **Files:** `game/rules_engine.py`, `game/targeting.py`, `game/continuous.py`

### Commander zone-replacement choice (RULE 903.9a/9b)

- **What:** Replaced an unconditional command-zone diversion with a real owner-chosen `pending_choice`, split by mechanism: 903.9a (graveyard/exile, a state-based action —…
- **Files:** `game/rules_engine.py`, `game/game_engine.py`
- **Why:** Previously `exile()` skipped the diversion entirely on an incorrect docstring claim that 903.9 was graveyard/death-only, and `return_to_hand()` offered no diver…

### Graveyard-Sourced "Return This Card Transformed"

- **What:** `ReturnFromGraveyardTransformedEffect`/`RulesEngine.return_from_graveyard`'s new `transformed` param flips a card onto its back face right after being placed fr…
- **Files:** `game/effects/core.py`, `game/rules/*_mixin.py`

### Token Lifecycle (RULE 704.5d)

- **What:** `GameObject.is_token` plus a new SBA, `RulesEngine._remove_stranded_tokens`, implements RULE 704.5d/111.7-8: a token that leaves the battlefield reaches its zon…
- **Files:** `game/rules/sba_mixin.py`, `models/game_object.py`

### Enters-Tapped Clause Recognition (RULE 614.1)

- **What:** Tap-condition recognition moved to a pure `parser/oracle/catalogue/lands.py` handler with `game/ability_catalogue.land_tap_condition` delegating to it, and gain…
- **Files:** `parser/oracle/catalogue/lands.py`, `game/ability_catalogue.py`

### Phasing (RULE 702.26)

- **What:** A new `GameObject.phased_out` flag, filtered out of `GameState.permanents()`/`permanents_controlled_by` (the sanctioned battlefield-reading choke point) so comb…
- **Files:** `game/rules_engine.py`, `game/game_engine.py`, `models/game_state.py`

### ENG-6/ENG-10: Copy-of-a-Copy (RULE 707.2)

- **What:** `become_copy` now sets `obj._front_card = obj.card` right after the copy mutation, so a later copy of an already-copied object reads its current form rather tha…
- **Files:** `game/copy_mechanics.py`

### ENG-7: Token's Own `enter_as_copy` Choice

- **What:** `create_token`'s build loop is now a recursive continuation (`_next(remaining)`) that pauses on a token's own `enter_as_copy_effects` (RULE 614.1c/614.12) befor…
- **Files:** `game/rules_engine.py`

### Battles (RULE 310)

- **What:** The whole card type from scratch: defense as counters rather than a separate stat (seeded on entry alongside planeswalker loyalty), a third `"battle"` defender…
- **Files:** `models/card.py`, `models/game_object.py`, `game/rules_engine.py`, `game/game_engine.py`
- **Why:** Defeat (RULE 310.11b) is noticed by the SBA pass rather than at any single counter-removal site, so every route to zero defense (combat, burn, anything) reaches…

### Saga chapter abilities (RULE 714.2d)

- **What:** Saga chapter lines ("I, II — effect") now resolve as ordinary triggered abilities (`EventType.SAGA_CHAPTER`) through the existing one-shot effect handler table,…
- **Files:** `parser/oracle/catalogue/saga.py`, `game/rules_engine.py`, `game/binding/core.py`
- **Why:** Chapters flow through the ordinary triggered-ability pipeline so targeting/"you may"/interactive ordering all work for free, instead of bespoke Saga-specific ma…

### Saga timing fixes + Read Ahead (RULE 714.3b/714.3c)

- **What:** Fixed the lore counter to be added at precombat main phase begin (not the draw step); narrowed the final-chapter sacrifice check to only wait on this Saga's own…
- **Files:** `game/rules_engine.py`, `game/game_engine.py`
- **Why:** RULE 702.155a means skipped chapters are gone for good, not delayed — an earlier draft firing chapters 1..N in sequence was wrong and corrected before shipping.

### Class (RULE 716) and Leveler (RULE 711)

- **What:** Multi-line block structures — Leveler's mutually-exclusive `LEVEL` tiers and Class's cumulative sequential levels — parsed via a new pure grammar module, with a…
- **Files:** `parser/oracle/catalogue/levels.py`, `game/costs.py`, `game/binding/core.py`
- **Why:** Needed the first genuinely general RULE 613.6 "as long as" conditional-static primitive (`min_level`/`max_level`/`level_counter`, gating on the ability's own so…

### Class trigger-wrapper recognition

- **What:** Recognized "When this Class becomes level N, `<effect>`." as a real one-shot trigger (fires once, doesn't re-fire on a higher level) and "When this Class enters…
- **Files:** `parser/oracle/catalogue/levels.py`, `parser/oracle/normalize.py`

### DFC transform + day/night (RULE 712.8, 731, 702.145)

- **What:** `RulesEngine.transform_permanent` actually flips a permanent's face and rebinds catalogue-derived abilities (`GameObject.transform()` alone never did); a new "t…
- **Files:** `game/rules_engine.py`, `services/game_session.py`, `services/replay.py`

### Adventure and Split/Fuse casting (RULE 715, 709)

- **What:** Both card types are now actually castable, generalizing the MDFC back-face casting machinery to a third `"fuse"` face value; Adventure's creature snapshot is st…
- **Files:** `models/card.py`, `game/game_engine.py`, `game/rules_engine.py`
- **Why:** `ManaCost.parse` already sums every `{N}` token regardless of source, and Scryfall's `cmc` is already the two halves' sum, so string concatenation alone *is* "p…

### Prepared cards (RULE 722)

- **What:** A permanent "becoming prepared" spawns a token copy of just its inset prepare-spell into exile, castable only while the source stays prepared and on the battlef…
- **Files:** `game/effects/core.py` (`BecomePreparedEffect`), `game/rules_engine.py` (`make_prepared`), `services/scryfall_client.py`
- **Why:** Reuses the existing RULE 704.5d "token disappears when stranded" SBA (scoped by checking the source is still prepared and on the battlefield) rather than a para…

### Token copies and "becomes a copy of" (RULE 707)

- **What:** `RulesEngine.copy_permanent` creates a token clone of a target's copiable card; "becomes a copy of target permanent" is a genuine layer-1 continuous effect (Ves…
- **Files:** `game/rules_engine.py`, `game/effects/core.py`

### Delver-shaped conditional transform + MDFC commander casting

- **What:** `RevealTopThenTransformEffect` implements "look at the top card; if it's a[n] `<type>`, transform ~." as a general, criteria-parameterized primitive (Delver of…
- **Files:** `game/effects/core.py`, `game/ability_catalogue.py`, `game/game_engine.py`

### Face-down permanents — morph, megamorph, disguise, manifest, cloak (RULE 708)

- **What:** Modeled as a face swap (`GameObject.turn_face_down` stashes the whole face-up bundle and swaps in a synthetic 2/2 with no text/abilities) so the layer engine, c…
- **Files:** `game/face_down.py`, `models/game_object.py`, `game/game_engine.py`, `game/rules_engine.py`
- **Why:** RULE 708.9's "reveal as it changes zones" lives at the single `GameState.remove_from_battlefield` chokepoint as a bare model transition rather than through `tur…

### Dungeons and venturing (RULE 309, RULE 701.49)

- **What:** A dungeon is plain data on `Player.dungeon` (not a `GameObject`, mirroring the Emblem reasoning), with its room graph parsed off the raw pre-normalize card text…
- **Files:** `models/dungeon.py`, `game/dungeons.py`, `services/dungeon_database.py`, `game/rules_engine.py`
- **Why:** Room abilities are collected the source-less way Monarch/Initiative's are, since there's no permanent for the per-object trigger scan to find — this also comple…

### Formats and casual variants — Planechase, Archenemy, Vanguard (RULE 8/9, 901, 904, 902)

- **What:** `models/game_format.py` replaces ad-hoc starting-life params with a named format record driving starting life/hand size/singleton and which RULE 9 variants are…
- **Files:** `models/game_format.py`, `game/variants.py`, `services/variant_card_database.py`
- **Why:** Team variants (RULE 809-811) are deliberately excluded — they change the turn structure itself rather than adding a card pool, tracked separately as PLR-14.

### Planar deck could return short decks

- **Files:** `game/variants.py`

### Dungeon room bindings, 29/30 rooms (PAR-13)

- **What:** The RULE 309 dungeon engine and room graphs were already complete; a room with no matching effect handler simply fails closed rather than breaking the graph.
- **Files:** `game/dungeons.py`, `parser/oracle/catalogue/handlers.py`

### Legendary named token creation (PAR-13)

- **What:** `CreateTokenEffect`/`synthesize_token_card` gained a `legendary` param (Cradle of the Death God's "The Atropal"), setting `Card.is_legendary` directly and foldi…
- **Files:** `game/effects/core.py`, `services/token_database.py`

### Format switch reaches the goldfish/multiplayer API (PLR-13)

- **What:** `GameEngine.new_game` already understood `game_format`/`archenemy_id`, but neither `api/game.py` nor `api/multiplayer.py` passed one through, so Planechase/Arch…
- **Files:** `services/game_session.py`, `api/game.py`, `api/multiplayer.py`, `models/game_format.py`

### Reveal-land cycle: interactive check-land (Hobbits batch)

- **What:** RULE 614.1's optional sibling to the deterministic check-land: `catalogue.lands`'s new `reveal_types` kind, resolved via a genuine interactive `land_tapped_reve…
- **Files:** `parser/oracle/catalogue/lands.py`, `game/rules_engine.py`

### "Create a token and attach ~ to it" (Hobbits batch)

- **What:** `AttachEffect`'s new `target_kind="created"`, reading `GameContext.created_objects` — a Living-Weapon-adjacent shape printed as ordinary text instead of the key…
- **Files:** `game/effects/core.py`, `parser/oracle/catalogue/handlers.py`

### Frodo, Sauron's Bane: two-stage transform state machine

- **What:** "{cost}: If Frodo is a Citizen, it becomes a Halfling Scout with base P/T 2/3 and lifelink." / a second ability escalating to Halfling Rogue.
- **Files:** `game/ability_catalogue.py`, `game/costs.py` (`activation_condition` settable directly from a hand-authored cost dict)

### Bare "create a token that's a copy of target X" recognizer

- **What:** `CopyPermanentEffect` existed but had no oracle-text recognizer (Ephemerate-adjacent cards were always hand-authored).
- **Files:** `parser/oracle/catalogue/handlers.py`

### Dynamic-magnitude token creation

- **What:** `CreateTokenEffect.count_from_trigger_event` ("create that many tokens", Lathril, Blade of the Elves) plus two dynamic-*count* oracle recognizers sharing a sele…
- **Files:** `game/effects/core.py`, `parser/oracle/catalogue/handlers.py`

### Bug: `_matches_permanent_type` missing planeswalker/battle branches (Card Types & Structures)

- **What:** All three near-duplicate copies of `_matches_permanent_type` (kept separate per the mixin-split architecture) had no `"planeswalker"`/`"battle"` branch, silentl…
- **Files:** `game/rules/misc_mixin.py`, `game/rules/damage_death_mixin.py`, `game/rules_engine.py`

### Bug: token synthesis dropped the Artifact type on "N/N artifact creature token" (Card Types & Structures)

- **What:** `synthesize_token_card` treated "Creature"/"Artifact" as strict either/or, and all three parser word-splitting loops recognized "artifact" as a supertype marker…
- **Files:** `services/token_database.py`, `parser/oracle/catalogue/handlers.py`, `game/effects/core.py`

### Copy-Except `not_legendary` / `add_types` / `add_subtypes`

- **What:** `Card.as_copy` gained `not_legendary` (strips `is_legendary` and the printed word, RULE 205.4a) alongside the pre-existing `add_types`/`add_subtypes`; `CopyPerm…
- **Files:** `models/card.py`, `game/effects/core.py`, `game/rules_engine.py`.

### `ReturnSelfFromGraveyardEffect.transformed` Wiring

- **What:** Threaded the existing `transformed` flag (RULE 400.7 + 712.8) through `ReturnSelfFromGraveyardEffect` for Ojer Axonil's death trigger.
- **Files:** `game/effects/core.py`.

## Keyword Catalogue

### PAR-69: Doctor's Companion (RULE 702.124m, PARSER_VERSION 383)

- **What:** Added `"Doctor's Companion"` as a plain FLAG row in `_TABLE` — the
- **Files:** `parser/oracle/catalogue/keywords.py`.

### M2 Ward (RULE 702.21)

- **What:** Ward pushes a real `StackItem` (a genuine ability the target's controller controls, RULE 603.3a) above the spell/ability that triggered it, so both players get…
- **Files:** `game/rules_engine.py`, `game/costs.py`, `parser/oracle/catalogue/keywords.py`
- **Why:** Built directly rather than through the generic trigger pipeline because a bind-once `effects` list can't carry per-firing data (which stack item, which caster).

### Regenerate (RULE 701.16)

- **What:** A new pre-emptive `EventType.DESTROY`, fired by `RulesEngine.destroy` and run through the existing replacement machinery, lets a regeneration shield (a `Replace…
- **Files:** `game/rules_engine.py`, `game/effects/core.py`, `models/events.py`

### Phasing (RULE 702.26)

- **What:** `GameObject.phased_out` built to unblock Robe of Stars, scoped initially to a single-permanent case.
- **Files:** `models/game_object.py`

### Granted protection (RULE 702.16)

- **What:** `GameObject.temp_protections`, read by `combat.is_protected_from`, granted via an interactive `grant_protection` effect and cleared at cleanup — Mother of Runes…
- **Files:** `models/game_object.py`, `game/combat.py`, `game/effects/core.py`

### Cycling suffix generalization and keyword-line recognition bug fixes

- **What:** Generalized `<type>cycling` (Islandcycling, Basic landcycling, …) the same way `<type>walk` already was, fixing "Basic landcycling" being silently skipped entir…
- **Files:** `parser/oracle/catalogue/keywords.py`, `parser/oracle/segmenter.py`

### Ward Cost `{X}` Resolution (RULE 702.21b)

- **What:** A ward ability's own `{X}` cost is now resolved fresh at the ward ability's *resolution* time (not when it triggers) via a new `ActivationCost.x_selector`, scop…
- **Files:** `game/costs.py`, `game/rules_engine.py`
- **Why:** Previously an unresolved `{X}` defaulted to amount 0, so a hypothetical board-count ward cost would have silently resolved as free — fixed pre-emptively even th…

### Living Weapon & Renown Real Behavior

- **What:** RULE 702.92/702.112 went from recognized-only to real behavior: a Living Weapon's ETB now creates and self-attaches a germ token (`LivingWeaponEffect`, one atom…
- **Files:** `game/binding/core.py`

### RULE 702.8b Flash Gates Cast Timing

- **What:** `GameEngine.can_cast`'s sorcery-speed timing check now actually consults the Flash keyword (`sorcery_speed = not (card.is_instant or combat.has(obj, "flash"))`)…
- **Files:** `game/game_engine.py`

### Channel / Cycling (RULE 702.29/702.28)

- **What:** A hand-zone, non-mana "Discard this card: `<effect>`" activated ability, distinct from the hand-exile mana-ability shortcut since Channel/Cycling use the stack.
- **Files:** `game/costs.py`, `game/rules_engine.py`, `game/game_engine.py`

### Monstrosity (RULE 701.37)

- **What:** `RulesEngine.monstrosity` is atomic (guard + counters + designation in one conditional).
- **Files:** `game/rules_engine.py`, `game/continuous.py`
- **Why:** Deliberately not unified with Adapt — monstrosity's gate is a sticky designation, adapt's is the creature's live counter count, so sharing an implementation wou…

### Adapt (RULE 701.46)

- **What:** A separate `RulesEngine.adapt`, gated purely on current +1/+1 counter count — no event, no designation.
- **Files:** `game/rules_engine.py`

### RULE 702.94b Soulbond Reaches Existing Primitive

- **What:** The `soulbond_pair` selector shipped with the cEDH cube batch had no card text able to invoke it; three new parser rows (quoted grant, anthem, bare keyword) let…
- **Files:** `parser/oracle/catalogue/`

### Dethrone (RULE 702.107)

- **What:** "Whenever this creature attacks the player with the most life (or tied), put a +1/+1 counter on it" — a per-firing procedural check (`RulesEngine.check_dethrone…
- **Files:** `game/rules_engine.py`, `game/combat.py`
- **Why:** Resolves the defending player off `attacker.combat_defender`, so a planeswalker/battle attack still checks that permanent's controller's life — a real ruling.

### Fading (RULE 702.32)

- **What:** Entry counters and the upkeep "remove one or sacrifice" behavior are both bound to the keyword itself (not to any specific card), reading counters off the parse…
- **Files:** `game/effects/core.py`, `game/rules_engine.py`

### Soulbond (RULE 702.94)

- **What:** Real pairing state (`GameObject.paired_with` on both objects) rather than a continuous effect, since RULE 702.94c breaks pairing on events; swept as an SBA so n…
- **Files:** `models/game_object.py`, `game/continuous.py`

### Mutate (RULE 702.140)

- **What:** An alternative cast cost that merges onto its target instead of entering the battlefield; the host stays the surviving `GameObject` per RULE 702.140c (counters/…
- **Files:** `game/rules_engine.py`, `models/game_object.py`

### Granted Escape (Underworld Breach)

- **What:** `continuous.granted_escape_for` lets a permanent grant Escape (RULE 702.138) rather than only a printed keyword, consulted by the same `_graveyard_cast_keyword`…
- **Files:** `game/continuous.py`

### Mutate under the pile (RULE 702.140b)

- **What:** `mutate_onto(..., under=True)` keeps the host's characteristics and merges the mutating card's abilities instead, chosen as the spell is cast; the host is valid…
- **Files:** `game/rules_engine.py`, `game/targeting.py`

### Ascend / the city's blessing (RULE 702.131)

- **What:** Previously a bare recognized keyword with zero bound behaviour.
- **Files:** `game/rules_engine.py`, `game/effects/core.py`, `game/continuous.py`

### Storied / the enduring story (RULE 702.195, PAR-51)

- **What:** The exact same idempotent-per-player-flag shape as Ascend above (`Player.has_enduring_story`, never cleared), granted at SBA cadence once its controller control…
- **Files:** `game/rules_engine.py`, `game/rules/sba_mixin.py`, `models/game/player.py`, `game/static_conditions.py`, `parser/oracle/catalogue/keywords.py`, `parser/oracle/catalogue/static_handlers.py`

### Party (RULE 700.8/702.129, PAR-53)

- **What:** `continuous.count_selector`'s `"creatures_in_your_party"` branch (a RULE 700.8 bipartite Cleric/Rogue/Warrior/Wizard matcher — a creature with several of those…
- **Files:** `parser/oracle/catalogue/static_handlers.py`. `tests/test_par53_party.py`.

### Ward `<cost>` static grants (RULE 702.21b, PAR-65)

- **What:** `continuous.py`'s `grant_keyword` loop already applied a granted `ward_cost` generically to *any* `affected_objects(state, ability)` result (Hexing Squelcher's…
- **Files:** `parser/oracle/catalogue/static_handlers.py`. `tests/test_par65_ward_grants.py`.

### Hexproof-from-quality keyword shape (PAR-5)

- **What:** `Hexproof` moved from a bare `FLAG` keyword shape to `QUALITY` (mirroring `Protection`), so "Hexproof from black" (Knight of Grace) keeps its colour instead of…
- **Files:** `parser/oracle/catalogue/keywords.py`

### Granting Cycling to hand cards (PAR-8)

- **What:** "Each `[<filter>]` card in your hand has cycling `<cost>`." (Jo Grant, Rhet-Tomb Mystic) — a layer-6 grant whose targets are hand cards rather than the battlefi…
- **Files:** `parser/oracle/catalogue/static_handlers.py`, `game/continuous.py`

### Generic Cycling execution for unregistered cards (PAR-9)

- **What:** A bare, unregistered "Cycling `<cost>`" keyword line was claimed for the coverage gate but bound to nothing.
- **Files:** `game/binding/core.py`

### "Choose a Background" keyword recognition (PAR-12, RULE 702.124)

- **What:** Registered as a bare FLAG keyword purely so a card whose only other lines are ordinary effects reaches `MODELED` instead of parking on this deckbuilding-only cl…
- **Files:** `parser/oracle/catalogue/keywords.py`

### Investigate mechanic (PAR-12, RULE 701.19a)

- **What:** A pure `create_token` alias ("Clue" was already a known token word) for bare "Investigate.", "Investigate twice.", and "Investigate `<n>` times." — 87+ cards, t…
- **Files:** `parser/oracle/catalogue/handlers.py`

### RULE 702.90/91 Infect and Wither: real behaviour

- **What:** Recognized as keywords with zero behaviour before this batch.
- **Files:** `game/rules_engine.py`, `game/combat.py`

### RULE 702.28c Cycling trigger, from nothing

- **What:** "When you cycle this card, `<effect>`." had no event to watch — the generic Cycling activated-ability binder gave no signal that a Cycling discard (vs.
- **Files:** `game/binding/core.py`, `game/rules_engine.py`, `models/game_state.py`

### Cumulative Upkeep (RULE 702.24) (MEC-16)

- **What:** `CumulativeUpkeepEffect` adds an age counter then reuses RULE 701.17's "sacrifice unless you pay" machinery, with the parsed cost repeated (scaled) once per age…
- **Files:** `game/effects/core.py`, `game/binding/core.py`

### Imprint (RULE 702.45-adjacent) (MEC-17)

- **What:** `RulesEngine.request_choose_objects` gained a `remember` flag that stamps a chosen exiled object's id onto `GameObject.linked_exile_id`; `ImprintEffect` is the…
- **Files:** `game/rules/misc_mixin.py`, `game/effects/core.py`, `game/mana_abilities.py`, `game/ability_catalogue.py`

### Slip Out the Back: `PhaseOutEffect` previous-clause pronoun (Keyword Catalogue)

- **What:** `PhaseOutEffect` (RULE 702.26) gained a `previous_subject` flag reading `GameContext.previous_targets`, matching `GrantUntilEffect`/`TapEffect`/`ReturnToHandEff…
- **Files:** `game/effects/core.py`, `parser/oracle/catalogue/handlers.py`

### Phasing out an opponent's permanent as a spell effect (RULE 702.26) (Keyword Catalogue)

- **What:** `PhaseOutEffect` already accepted an arbitrary `target_kind`; the gap was purely parser-side.
- **Files:** `game/effects/core.py`, `parser/oracle/catalogue/handlers.py`

### Delirium (RULE 702.137) (Keyword Catalogue)

- **What:** `normalize._strip_ability_words` strips "delirium" (a labeled ability word, RULE 207.2c, no rules meaning of its own), letting the bare "as long as…" clause fal…
- **Files:** `parser/oracle/normalize.py`, `game/static_conditions.py`

### Granted Ward With Its Own Cost (RULE 702.21b)

- **What:** `GameObject.granted_ward_cost` + `RulesEngine.check_ward`'s fallback, populated by `grant_keyword`'s new `ward_cost` param — a *granted* Ward with its own cost,…
- **Files:** `game/continuous.py`, `game/rules_engine.py`, `parser/oracle/catalogue/static_handlers.py`.

### RULE 702.64 Absorb — Real Behaviour

- **What:** Absorb went from a recognized-but-inert numbered keyword to real behaviour: bound structurally in `effect_binder.attach_to_object`'s keyword branch, straight of…
- **Files:** `game/binding/core.py`.

### RULE 702.164 Toxic — Real Behaviour

- **What:** Toxic N was already parser-recognized as a bare numbered keyword but had zero engine consumer — the poison-counter substitution in `deal_damage` only ever fired…
- **Files:** `game/combat.py`, `game/rules/damage_death_mixin.py`

### RULE 702.184a/721 Station (Edge of Eternities)

- **What:** A third "striated text box" card structure alongside Leveler/Class — a Spacecraft (or Planet land) whose text splits into a fixed Station reminder line (the rea…
- **Files:** `parser/oracle/catalogue/station.py` (new), `parser/oracle/gate.py`, `game/binding/core.py`, `game/engine/activation_mixin.py`, `game/engine/legal_actions_mixin.py`, `game/costs.py`, `game/continuous.py`, `game/combat.py`, `models/card.py` (`is_station`), `models/game_object.py` (`station_tapped_power`), `services/scryfall_client.py`

### MEC-48: Specialize (Alchemy Horizons: Baldur's Gate — digital keyword, PARSER_VERSION 223)

- **What:** "Specialize {cost}" — an Arena-only keyword with **no paper CR entry**.
- **Files:** `parser/oracle/catalogue/keywords.py`, `parser/oracle/segmenter.py`, `parser/oracle/gate.py`, `models/events.py`, `models/game_object.py`, `game/effects/core.py`, `game/binding/core.py`.

### Generic Flavor-/Ability-Word-Label Stripping (RULE 207.2c, PARSER_VERSION 99)

- **What:** `_ABILITY_WORD_RE`'s fixed 7-word evergreen whitelist (landfall/constellation/battalion/enrage/delirium/veil of time/avoidance) is what let a "Word — `<effect>`…
- **Files:** `parser/oracle/normalize.py`, `parser/oracle/gate.py`

### Keyword-line recognition: comma-containing keyword parameters (PAR-27, PARSER_VERSION 100)

- **What:** PAR-27's remaining scope was an audit — spot-check all 195 registered `catalogue/keywords.py` entries against real cache cards for `segmenter.is_keyword_line` f…
- **Files:** `parser/oracle/segmenter.py`, `parser/oracle/gate.py` (`PARSER_VERSION` 99 → 100 + `PARSER_VERSION.lock`)

### "Keyword — [ability]" families: Boast, Exhaust, Power-up, Forecast, Solved, Max Speed (PAR-28, PARSER_VERSION 101)

- **What:** Six RULE 702 keywords print a RULE 207.2c-style em-dash label in front of a *real* activated / triggered / static ability, with the keyword itself adding a fixe…
- **Files:** `parser/oracle/segmenter.py`, `parser/oracle/normalize.py`, `parser/oracle/catalogue/handlers.py`, `parser/oracle/gate.py` (`PARSER_VERSION` 100 → 101 + lock); `game/static_conditions.py`, `game/binding/core.py`, `game/costs.py`, `game/effects/core.py`, `game/engine/activation_mixin.py`, `game/engine/combat_mixin.py`, `game/engine/turn_loop_mixin.py`, `game/rules/misc_mixin.py`, `game/rules/sba_mixin.py`, `game/rules/triggers_mixin.py`; `models/game_object.py`, `models/player.py`, `models/events.py`

### Combat-evasion & targeting keywords: Shroud, Fear, Intimidate, Skulk, Shadow (PAR-22)

- **What:** Five RULE 509.1b / 702.18b keywords that the parser already
- **Files:** `game/combat.py`, `game/targeting.py`,

### Horsemanship (RULE 702.31) (MEC-87, 2026-09-15, PARSER_VERSION 386)

- **What:** The same PAR-22 shape one keyword later — already a real
- **Files:** `game/combat.py`, `parser/oracle/catalogue/handlers.py`,

### Banding (RULE 702.22 / 509–510) (MEC-88, 2026-09-15, PARSER_VERSION 386)

- **What:** `game/combat.py` had zero Banding logic before this (confirmed
- **Files:** `game/combat.py`, `game/engine/combat_mixin.py`,

### Triggered keyword abilities: Prowess, Exalted, Battle Cry, Mentor (PAR-24)

- **What:** Four RULE 702 keywords whose text *is* a triggered ability,
- **Files:** `game/binding/core.py`, `game/effects/core.py` (`PumpEffect.

### Death/graveyard keywords: Undying, Persist, Unearth, Embalm, Eternalize, Dredge (PAR-25)

- **What:** Six RULE 702 keywords parser-recognised but with zero engine
- **Files:** `game/rules/triggers_mixin.py`, `game/rules/draw_discard_mixin.py`,

### Cost keywords: Affinity, Convoke, Delve, Improvise (PAR-23)

- **What:** Four `KeywordShape.QUALITY`/`FLAG` cost keywords, all
- **Files:** `parser/oracle/catalogue/keywords.py` (`_resolve`),

### Cast-alternative/timing keywords: Backup, Dash, Madness, Miracle, Ninjutsu, Bestow (PAR-26)

- **What:** All six cast-alternative/timing keywords, all
- **Files:** `game/binding/core.py` (`_kw_backup` + the dash/madness/

## Designations & Standing Systems

### Goad (RULE 701.15)

- **What:** Goaded is modeled as a *set of goaders* per creature (not a flag), so multiple simultaneous goads and repeat-goading fall out naturally.
- **Files:** `game/rules_engine.py`, `game/game_engine.py`, `game/combat.py`
- **Why:** The requirement-audit check deliberately asks `_attack_conditions_ok`, not `_can_attack` — by audit time the creature is already declared/tapped, so `_can_attac…

### Monarch, Initiative and Emblems (RULE 725, 726, 114)

- **What:** Monarch/Initiative are plain player designations with source-less inherent triggered abilities (built fresh off live state per firing rather than found by the p…
- **Files:** `game/rules_engine.py` (`_collect_inherent_triggers`, `create_emblem`), `models/emblem.py`, `parser/oracle/catalogue/handlers.py`
- **Why:** Subject/selector shapes meaningful only relative to a source permanent ("self"/"attached_permanent") are rejected fail-closed at emblem parse time, since an emb…

### The Ring tempts you (RULE 701.51/701.52)

- **What:** `Player.ring_level` (0-4) is the designation itself (no quoted card text, unlike a RULE 114 emblem — the four abilities are fixed by the rules); `Player.ring_be…
- **Files:** `game/rules_engine.py`, `game/continuous.py`, `models/player.py`

### MEC-8 — an emblem's own activated ability

- **What:** RULE 114.4 permits an emblem to carry an activated ability.
- **Files:** `models/emblem.py`, `game/rules_engine.py`, `parser/oracle/catalogue/handlers.py`

### MEC-9 — Monarch/Initiative succession on player leave (RULE 725.4/726.4)

- **What:** `remove_player_from_game` now passes a departing Monarch/Initiative holder's designation to the active player before clearing their board; Initiative succession…
- **Files:** `game/rules_engine.py`

### "The Ring tempts you" + RING_TEMPTED trigger (PAR-12, RULE 701.51/701.52)

- **What:** The resolve-time alias (`the_ring_tempts_you`) already existed for one hand-authored card; general oracle recognition closed 36+ more.
- **Files:** `game/rules_engine.py`, `parser/oracle/catalogue/handlers.py`, `game/binding/core.py`

### Frodo, Adventurous Hobbit's compound Ring conditions (PAR-12)

- **What:** Closed the deck's own commander with three small resolve-time primitives: `GameState.life_gained_this_turn` (a new per-turn tracker, reset only on the incoming…
- **Files:** `game/effects/core.py`, `game/rules_engine.py`, `parser/oracle/spec.py`

### Emblem Replacement-Effect Plumbing

- **What:** Three-part fix so a granted `ReplacementEffect` on an emblem actually works: `models/emblem.py`'s `Emblem` gained a `replacement_effects` list; `RulesEngine._al…
- **Files:** `models/emblem.py`, `game/rules_engine.py`.

## Game Engine / Turn Loop & Actions

### Extra turns (RULE 500.7)

- **What:** `GameState.extra_turns` is a FIFO consumed by `GameEngine.begin_turn`; a `take_extra_turn` effect inserts a turn right after the current one (Final Fortune, pai…
- **Files:** `models/game_state.py`, `game/game_engine.py`, `game/effects/core.py`

### "Play/cast from the top of your library" permission

- **What:** A new self-contained `TopLibraryPermissionEffect` marker (look/play_lands/cast_spells/min_mana_value/requires_attached params) is read live off the battlefield…
- **Files:** `game/top_library.py`, `game/effects/core.py`, `game/game_engine.py`, `game/ability_catalogue.py`
- **Why:** RULE 701 has no native "play from the top" provision — every real card grants it as its own static ability, so this is a genuinely new mechanism rather than an…

### ENG-16: Shared `_chosen_targets` Helper

- **What:** Consolidated an identical RULE 115.1a "up to N targets off a possibly-shared list" resolution block, independently reimplemented by seven `GameEffect` subclasse…
- **Files:** `game/effects/core.py`

### ENG-18: Shared Combat-Damage-Marker Trigger Scaffold

- **What:** Only two of nine `_collect_*_triggers` methods turned out to be genuinely byte-for-byte identical outside their own effect construction (Ragavan's impulsive-dra…
- **Files:** `game/rules_engine.py`
- **Why:** Forcing one driver over all five candidates would have meant threading unrelated parameters through call sites that don't share logic — not real deduplication.

### ENG-19: Duplicate `_halvar_god_of_battle` Removed

- **What:** An incomplete early version of Halvar, God of Battle's catalogue entry (predating `extra_target_specs`) was still defined alongside the real, complete version f…
- **Files:** `game/ability_catalogue.py`

### ENG-21: `rules_engine.py` Split into Per-Responsibility Mixins

- **What:** The single 7,849-line, 236-method `RulesEngine` class now composes nine mixins under `game/rules/` (triggers, casting, draw/discard, damage/death, mana/counters…
- **Files:** `game/rules_engine.py`, `game/rules/*_mixin.py`
- **Why:** The 8-times-repeated `_finish(resolved)` closure pattern was investigated and deliberately *not* extracted — each has a genuinely different mechanic-specific bo…

### ENG-24: Table-Driven Keyword-Triggered-Ability Dispatch

- **What:** `_keyword_triggered_abilities` (soulbond/living_weapon/fading/renown/annihilator/afflict/bushido) became seven `_kw_<name>` builder functions in a `_KEYWORD_TRI…
- **Files:** `game/binding/core.py`

### Legal-actions validation

- **What:** `legal_actions(player)` returns the validated action set (play land, cast at correct timing/affordability, tap for mana, declare attacker, pass) plus per-action…
- **Files:** `game/game_engine.py`

### Goldfisch mode session (UC3)

- **What:** Single-player game against the real rules engine, exposed as a server-held session (`GameSession`/`GameSessionManager`) with Restart and Rewind (undo), both via…
- **Files:** `services/game_session.py`, `api/game.py`
- **Why:** `Card.__deepcopy__` shares immutable card defs so clones stay cheap, and the step cursor travels with each snapshot so a mid-turn undo doesn't jump turns.

### ENG-17: shared `_resolve_pool_cost` helper

- **What:** Consolidated `_resolve_tap_others` and `_resolve_discard_cost`'s duplicated RULE 602.1 "choose N from a pool" logic (auto-pick first N, or validate `chosen_ids`…
- **Files:** `game/game_engine.py`

### ENG-20: `game_engine.py` split into per-responsibility mixins

- **What:** The single ~4,700-line `GameEngine` class (~130 methods) was recomposed from eight mixins (`turn_loop_mixin.py`, `combat_mixin.py`, `casting_mixin.py`, `lands_m…
- **Files:** `game/engine/*_mixin.py`, `game/game_engine.py`
- **Why:** Mixins rather than delegation to sub-objects, because every method reads/writes the same `self.state`/`self.rules`, and ~100 test files plus services call metho…

### ENG-23: `GameSession._dispatch` table-driven dispatch

- **What:** The 264-line if/elif action-dispatch chain became a `_ACTION_HANDLERS` dict of `_dispatch_<kind>` methods (mirroring `EffectRegistry`'s registry-over-if/elif pa…
- **Files:** `services/game_session.py`

### Leyline's opening-hand battlefield permission (PLR-11, RULE 103.6a)

- **What:** "If this card is in your opening hand, you may begin the game with it on the battlefield." — a pregame setup permission, not a static/resolve-time effect, so it…
- **Files:** `parser/oracle/catalogue/opening_hand.py`, `services/game_session.py`, `game/rules/misc_mixin.py`

### Gemstone Caverns / Buried Ogre pregame-setup shapes (PLR-11 follow-up)

- **What:** Generalized the plain Leyline permission into `PregameSetupPermission` (`destination`, `condition`, `counter_type`/`counter_count`, `cost_kind`/`cost_amount`) c…
- **Files:** `parser/oracle/catalogue/opening_hand.py`, `services/game_session.py`, `game/rules/misc_mixin.py`

### Search criteria: colour-word qualifier + "equipment" subtype (Game Engine / Turn Loop & Actions)

- **What:** `SearchLibraryEffect`'s search grammar accepts a leading colour word ahead of a type list (consumed and dropped, not modeled as a filter) and "equipment" as a s…
- **Files:** `parser/oracle/catalogue/handlers.py`

### `card_query` power/toughness bounds (Game Engine / Turn Loop & Actions)

- **What:** `models/card_query.py` gained `max_power`/`min_power`/`max_toughness`/`min_toughness` criteria keys (fail-closed for a non-creature's `None` power), hand-wired…
- **Files:** `models/card_query.py`

### Wheel family: Timetwister / Wheel of Fortune / Windfall (Game Engine / Turn Loop & Actions)

- **What:** "Each player discards (or shuffles their hand and graveyard into their library), then draws N cards." Originally three hand-authored fused effect types (`wheel`…
- **Files:** `game/effects/core.py`, `game/effect_amounts.py`, `game/isa.py`, `game/ability_catalogue/entries_00{2,3,9}.py`, `entries_010.py`

### `DestroyEffect` "nonbasic" mass-wipe filter (Game Engine / Turn Loop & Actions)

- **What:** "Destroy all nonbasic lands." (Ruination) — a new `"nonbasic"` filter key paired with the existing `selector="all_lands"`.
- **Files:** `game/effects/core.py`, `game/ability_catalogue.py`

### `_substitute_x` walks `filter`/`criteria` dicts generically (Game Engine / Turn Loop & Actions)

- **What:** `RulesEngine._substitute_x`'s "x"/"-x" sentinel substitution now walks any effect's `filter`/`criteria` attribute, not just a plain `amount`/`count`/`power`/`to…
- **Files:** `game/rules_engine.py` (or its mixin)

### Mass "destroy each X" singular alternative + tutor colour/mana-value qualifiers (Game Engine / Turn Loop & Actions)

- **What:** `_MASS_DESTROY_NOUNS_SINGULAR` adds "destroy **each** X" alongside "destroy all Xs" (Meltdown).
- **Files:** `parser/oracle/catalogue/handlers.py`

### `ShuffleSelfIntoLibraryEffect` (RULE 701.20) (Game Engine / Turn Loop & Actions)

- **What:** "Shuffle ~ into its owner's library." (Green Sun's Zenith) overrides the default RULE 608.2m graveyard routing via the same `obj.zone != Zone.STACK` self-move o…
- **Files:** `game/effects/core.py`, `game/game_engine.py`

### Stonehewer Giant / Quest for the Holy Relic: search-then-attach (Game Engine / Turn Loop & Actions)

- **What:** `SearchLibraryEffect.attach_to_creature_you_control` applies right after `extra_counters`, auto-picking the first eligible creature (no RULE 115 target printed)…
- **Files:** `game/effects/core.py`, `parser/oracle/catalogue/handlers.py`

### Tainted Pact: repeated-dig-until-a-choice loop (Game Engine / Turn Loop & Actions)

- **What:** `ExileUntilDuplicateNameEffect`/`RulesEngine.exile_until_duplicate_name` opens a real "take vs.
- **Files:** `game/rules/search_mixin.py`

### Transmute Artifact: cost-comparison-gated placement (Game Engine / Turn Loop & Actions)

- **What:** `TransmuteArtifactEffect`/`RulesEngine.transmute_artifact` — a bespoke three-choice sequence (sacrifice → search → optional pay-the-difference) since the cost o…
- **Files:** `game/rules/misc_mixin.py`, `game/ability_catalogue.py`

### RULE 702.26b extra-combat-phase grants (Game Engine / Turn Loop & Actions)

- **What:** `GameEngine.insert_additional_combat_phase` splices a fresh combat (and, for "…an additional main phase," a fresh main) into the mutable per-turn `_turn_steps`…
- **Files:** `game/game_engine.py`, `game/effects/core.py`, `models/game_state.py`

### "Destroy target X. It can't be regenerated." (Game Engine / Turn Loop & Actions)

- **What:** The single most repeated removal-spell tail cache-wide.
- **Files:** `parser/oracle/segmenter.py`

### The "threaten" effect family (Game Engine / Turn Loop & Actions)

- **What:** "Gain control of target creature [with mana value N or less] until end of turn.
- **Files:** `parser/oracle/catalogue/handlers.py`, `parser/oracle/segmenter.py`, `parser/oracle/gate.py`, `game/effects/core.py`

### Combined "basic Island, Swamp, or Mountain card" search criteria (Game Engine / Turn Loop & Actions)

- **What:** `_SEARCH_CRITERIA`'s `basic`/`types` groups (previously mutually exclusive) widened to combine freely, closing the Panorama/Landscape/Monument tri-land fetch cy…
- **Files:** `parser/oracle/catalogue/handlers.py`

### "Each creature deals N damage to its controller" selector (Game Engine / Turn Loop & Actions)

- **What:** New `DealDamageEffect` selector `"each_creature_controller"` (Rakdos Charm's third mode) — recipient varies per creature (N independent hits) rather than one am…
- **Files:** `game/effects/core.py`

### Liliana, Dreadhorde General's −9: `count="all_but_one"` sacrifice sentinel (Game Engine / Turn Loop & Actions)

- **What:** "Each opponent chooses a permanent they control of each permanent type and sacrifices the rest" — six independent `sacrifice` calls (one per permanent type), se…
- **Files:** `game/rules_engine.py`, `game/ability_catalogue.py`
- **Why:** A multi-typed permanent kept by one type's cut can still be swept by another type's cut in this model — real rules let the same permanent count as the kept pick…

### `look_top_select` (Game Engine / Turn Loop & Actions)

- **What:** `RulesEngine.look_top_select`/`LookTopSelectEffect` — "Look at the top N cards.
- **Files:** `game/rules/search_mixin.py`, `parser/oracle/segmenter.py`

### `return_to_library` (RULE 701.3) + mass `ReturnToHandEffect` (Game Engine / Turn Loop & Actions)

- **What:** `RulesEngine.return_to_library`/`ReturnToLibraryEffect` — "put target creature on top/bottom of its owner's library" — closing 10 cards (Time Ebb, Griptide, Roi…
- **Files:** `game/rules_engine.py`, `game/effects/core.py`

### Intuition: two-player interactive search (Game Engine / Turn Loop & Actions)

- **What:** `IntuitionEffect`/`RulesEngine.request_intuition` — two chained `pending_choice`s: the caster picks three cards, then a real RULE 115 target (an opponent) choos…
- **Files:** `game/rules/search_mixin.py`, `game/ability_catalogue.py`

### Ral, Monsoon Mage: `CoinFlipEffect` (RULE 705.1) (Game Engine / Turn Loop & Actions)

- **What:** `CoinFlipEffect` branches into `win_effects`/`lose_effects` off `RulesEngine.coin_flip` — a reproducible RNG primitive that existed but had no consumer anywhere…
- **Files:** `game/effects/core.py`, `game/ability_catalogue.py`

### MEC-21: "exiled with ~" tracker (Game Engine / Turn Loop & Actions)

- **What:** `GameObject.exiled_with_ids` (an accumulating list, stamped by `ExileEffect(track_exiled_with=True)`) generalizes the single-slot `linked_exile_id` for a repeat…
- **Files:** `game/effects/core.py`, `models/game_object.py`

### MEC-23: resolve-time single-target ability-borrowing snapshot (Game Engine / Turn Loop & Actions)

- **What:** `GainActivatedAbilitiesOfTargetEffect` (Quicksilver Elemental) is the resolve-time, single-target sibling of MEC-21's standing layer-6 grant: at resolution it r…
- **Files:** `game/effects/core.py`, `models/game_object.py`

### Control of a Spell on the Stack (Commandeer)

- **What:** `GameContext.gain_control_of_spell`/`GainControlOfSpellEffect` — RULE 608.2m/111.5's owner/controller split applied to a still-stacked spell: only `StackItem.co…
- **Files:** `game/effects/core.py`.

## Multiplayer

### MEC-51: Control another player's turn / combat (RULE 720, PARSER_VERSION 224)

- **What:** "You control target opponent during that player's next turn." (Mindslaver, Sorin Markov's −7, Emrakul the Promised End's cast trigger, Worst Fears) and "…during…
- **Files:** `models/game_state.py` (`TurnControl`, `turn_controls`, `word_of_command`, `decider_for`/`driving_seat_for`/`active_turn_control_for`), `game/rules/triggers_mixin.py` (`_advance_turn_controls`), `game/effects/core.py` (`ControlPlayerEffect`, `SetLifeEffect`, `WordOfCommandEffect` + registry), `game/rules/misc_mixin.py` (`request_word_of_command`/`resolve_word_of_command_choice`), `game/engine/turn_loop_mixin.py` (`word_of_command` choice dispatch), `game/ability_catalogue/entries_016.py`, `parser/oracle/catalogue/handlers.py`, `parser/oracle/gate.py`, `services/game_session.py`, `frontend/src/js/gameBoardView.js`, `frontend/src/styles/main.css`.

### Multiplayer priority primitive → real RULE 117 loop

- **What:** `GameEngine.pass_priority(player)` originally added groundwork-only APNAP handling (record pass, hand to next player, resolve top of stack once all pass, RULE 1…
- **Files:** `game/game_engine.py`, `services/game_session.py`
- **Why:** Built as an opt-in flag rather than a rewrite so every solo/goldfish path keeps auto-draining unchanged (2,300+ existing tests passed through untouched).

### Lobby layer — rules-free people/tables model

- **What:** `services/lobby.py` models `LobbyPlayer` (id/name/presence) and `LobbyGame` (seats/status/observers) with zero imports from `game/`.
- **Files:** `services/lobby.py`

### Multiplayer session bridging

- **What:** `api/multiplayer.py` resolves each seat's saved deck the same way `api/game.py` resolves a goldfish deck (same `expand_entries`, same legality gate); `Lobby.sta…
- **Files:** `api/multiplayer.py`, `services/game_session.py`

### Per-seat mulligan setup

- **What:** `GameSession`'s single setup-complete flag became a per-seat pending set, and mulligan count became per-player, so every seat mulligans independently in paralle…
- **Files:** `services/game_session.py`

### Actor-attributed actions

- **What:** `apply_action(action, actor_id=...)` — the engine's existing per-player rules validation (RULE 601.3a timing, "the attacking player does not declare blockers")…
- **Files:** `game/game_engine.py`, `services/game_session.py`

### Hidden-zone redaction (RULE 400.2)

- **What:** `GameSession.view(perspective=...)` strips every other player's hand and every player's library from the payload (keeping only counts), routes a pending choice…
- **Files:** `services/game_session.py`

### Concede with deferred board cleanup (RULE 104.3a, 800.4a)

- **What:** Concede is legal at any time, bypassing timing gates; the RULE 800.4a board cleanup (removing the conceded player's objects) is deferred onto `GameState.pending…
- **Files:** `game/rules_engine.py`, `game/game_engine.py`

### Seat reclaimed by player name, not server id

- **What:** Lobby identity keyed off `normalize_name(name)` rather than the server-issued id, since name is the only handle that survives a page reload — reconnecting with…
- **Files:** `services/lobby.py`

### Disconnect grace period

- **What:** `Lobby.disconnect` marks a player absent and starts a grace period (default 90s) rather than dropping them; meanwhile `pass_for_absent_players` passes priority…
- **Files:** `services/lobby.py`, `api/multiplayer_ws.py`

### Idle priority-holder timeout

- **What:** A player holding priority who stays silent past a configurable idle timeout (default 120s) has their socket closed — not to police slow play, but because a tab…
- **Files:** `api/multiplayer_ws.py`

### `/ws/lobby` presence + per-participant push

- **What:** One socket per client doubles as the presence signal and the push channel; after any move it sends each participant their own redacted view rather than one shar…
- **Files:** `api/multiplayer_ws.py`

### Finished-table cleanup

- **What:** `Lobby.leave` now drops a FINISHED table the same way it already did a SETUP one, instead of leaving a played-out table sitting in every remaining player's lobb…
- **Files:** `services/lobby.py`

### Per-seat take-back (undo) budget

- **What:** A table-configured, host-set/capped undo convenience distinct from `rewind` — legal regardless of priority (same exemption as concede), scoped to the caller's o…
- **Files:** `services/game_session.py`
- **Why:** History entries now carry an actor id; slicing both `_history` and `move_log` by a tail-relative depth (not a front-based index) is required since `_history` tr…

### Tables of two to four seats (PLR-2)

- **What:** `services/lobby.py`'s `MAX_SEATS` raised from 2 to 4 (plus an explicit `MIN_SEATS=2`) — the whole backend change, since the engine had already been N-player thr…
- **Files:** `services/lobby.py`

### Random seating / random starting player (RULE 103.1/103.2)

- **What:** Two independent host-set table options (`randomize_seating`, `random_starting_player`) applied once by `LobbyGame.seating_order()` at game start.
- **Files:** `services/lobby.py`, `api/multiplayer.py`

### Seat banner colours

- **What:** `Seat.banner_color` lives in the lobby (not the `GameState`) since it must be visible in Setup before a game exists; normalized rather than validated (any WUBRG…
- **Files:** `services/lobby.py`, `api/multiplayer.py`

### Solo vs. Bots' seat banner colours

- **What:** Solo has no lobby to carry `Seat.banner_color`, so `gameBoardView.js`'s shared banner rendering (`bannerStyle`/`bannerGradients`) had nothing to read for it — e…
- **Files:** `api/solo.py`, `services/game_session.py`

### Face-down-in-exile redaction (PLR-3, RULE 400.2)

- **What:** A card exiled face down (RULE 701.20a, Beseech the Mirror-shaped) sits in an otherwise-public zone, so whole-zone redaction didn't cover it.
- **Files:** `services/game_session.py`

### In-progress UI selection survives a reconnect (PLR-6)

- **What:** A mid-cast targeting sequence or half-assembled block lived only in frontend state, so a reconnect had nothing to rebuild from.
- **Files:** `services/game_session.py`, `api/game.py`

### A `ping` counts as liveness too (PLR-5)

- **What:** The idle watchdog only reset a player's `last_action_at` from a real game action, so a player genuinely still at the table but just thinking got disconnected-an…
- **Files:** `api/multiplayer_ws.py`

### `move_actors` — a move/priority feed (VIS-5)

- **What:** `move_log` had labels but no actor, so a shared-board "Bob played X" feed had nothing to build from.
- **Files:** `services/game_session.py`

### Client-Token Identity Stub (PLR-4)

- **What:** A browser that has saved a Profil name gets a random `crypto.randomUUID()` client token (`mtg_client_token` cookie, sliding 90-day validity), letting two browse…
- **Files:** `frontend/src/js/settings.js`, `backend/mtg_analyzer/services/lobby.py`, `api/multiplayer_ws.py`, `api/schemas.py`.
- **Why:** `Lobby.connect`'s reclaim order becomes `player_id` -> `client_token` (if present) -> `name` (legacy, only when no token) — once a token is presented, name is n…

### Client-Token Expiry & Asset Purge (PLR-4)

- **What:** `Lobby.expired_token_players()`, swept once a second, forgets a client token unused for 90 days (`MTG_CLIENT_TOKEN_VALIDITY`) — never while connected or mid-gam…
- **Files:** `backend/mtg_analyzer/services/lobby.py`, `api/multiplayer_ws.py` (`sweep_once`).
- **Why:** The `name_in_use_by_other` guard exists because two browsers can now legitimately share a display name at once — without it, one stale browser expiring would de…

## Bots

### Bot plays through the client surface only

- **What:** A bot reads `GameSession.view(perspective=<its own id>)` — the same RULE 400.2-redacted payload a browser gets — and submits only entries from its own `legal_ac…
- **Files:** `services/bots.py`

### Bot base class — fixed decision order, policy hooks

- **What:** `Bot.decide()` fixes the order a seat must handle things in (pending choice, then setup/mulligan, then RULE 509.1a declare-blockers, then `play()` only if holdi…
- **Files:** `services/bots.py`

### Bots driven externally by `run_bots`

- **What:** `run_bots(session, bots)` applies one action at a time, called after any human action, right after `lobby.start()` (so a bot keeps its opening hand before human…
- **Files:** `services/bots.py`, `api/multiplayer.py`, `api/multiplayer_ws.py`

### Failed bot action doesn't wedge the table

- **What:** If a bot's chosen action raises `GameActionError`, the bot records that offer's signature to avoid re-picking it and passes priority instead (always legal) — ke…
- **Files:** `services/bots.py`

### GreedyBot policy

- **What:** Attacks with everything first, then in its own main phase plays a land, taps for its scarcest colour, casts/activates cheapest-first (never `{X}`=0), blocks by…
- **Files:** `services/bots.py`

### Bot seats in the lobby

- **What:** A bot is an ordinary `LobbyPlayer`/`Seat` (plus `Seat.bot_kind`, opaque to the lobby) so the rules engine never learns bots exist; a bot seat with a deck counts…
- **Files:** `services/lobby.py`, `api/multiplayer.py`

### Cast-action `mana_value` exposed

- **What:** `GameEngine._cast_action` now carries `mana_value` alongside `has_x`/`max_x`, so a client (or a bot ranking casts cheapest-first) can order offered casts by cos…
- **Files:** `game/game_engine.py`

### `ManaMaximizerBot`

- **What:** A diagnostic bot that plays a land every turn and taps every remaining mana source dry but never casts or attacks, added so the "mana produced" simulation metri…
- **Files:** `services/bots.py`

### GreedyBot: explicit main-phase development loop (PLR-7/PLR-8)

- **What:** `GreedyBot._develop_board` now tries a land, then `_cast_or_activate`, falling back to manual `tap_for_mana` only once neither offers anything, re-checking `leg…
- **Files:** `services/bots.py`

### GreedyBot: casting leans on mana-potential auto-tap (PLR-7/PLR-8)

- **What:** A cast/activate offer is only made once real pool or mana-potential can pay for it, and applying it auto-taps the exact needed sources — replacing the bot's old…
- **Files:** `services/bots.py`

### GreedyBot: Equip/Fortify/Reconfigure sort last (PLR-7/PLR-8)

- **What:** `ActivatedAbility` gained an `attach_kind` field (set by the keyword-activated-ability binder, surfaced on the `activate_ability` action) so the bot can push an…
- **Files:** `game/binding/core.py`, `game/engine/legal_actions_mixin.py`, `services/bots.py`

### `RulesEngine.predict_land_tapped` + land-untapped preference (PLR-7/PLR-8)

- **What:** A read-only preview of RULE 614.1's enter-tapped outcome for every deterministic check/fast/slow/Battlebond land shape, surfaced on the `play_land` offer as `en…
- **Files:** `game/rules_engine.py`, `game/engine/legal_actions_mixin.py`, `services/bots.py`

### GreedyBot: weakest-opponent targeting in a 3+ pod (PLR-7/PLR-8)

- **What:** `_attack` used to take the first player-kind defender in whatever order was returned — fine at 2 players, arbitrary at 3-4.
- **Files:** `services/bots.py`

## Replay/Puzzle Mode

### Replay / Puzzle mode

- **What:** Build an arbitrary 1-2 player board and play from it.
- **Files:** `services/game_session.py`, `services/replay.py`
- **Why:** Poison (new `Player.poison`, 10 → SBA loss) and generic player counters (energy/experience, `Player.counters`) were added here specifically to support Replay ed…

### Replay/Puzzle mode: 3-4 player pods

- **What:** `blank_replay` was capped at 2 players even though the turn engine and Multiplayer both already support up to 4 seats.
- **Files:** `services/replay.py`

## Instruction-Set Architecture (ISA) & Composition

### The composition axis (ENG-37, `14_` S3)

- **What:** `game/effects/composition.py` — `seq`, `if_else`, `optional`,
- **Files:** `game/effects/composition.py`, `game/effect_amounts.py`,

### The operand axis, and the first fusions retired (ENG-37, `14_` axis 4)

- **What:** `game/effect_operands.py` — an effect's operand may name a
- **Files:** `game/effect_operands.py`, `game/effects/core.py`

### Fusion retirement — parser-side batches (ENG-37, `14_` S3)

- **Files:** `parser/oracle/catalogue/handlers.py`, `game/effects/core.py`

### What ENG-37's exit criterion actually requires (measured)

### One structured condition vocabulary (ENG-36, `14_` S2)

- **What:** `game/effect_conditions.py` — `{kind, of, min/max}` predicates
- **Files:** `game/effect_conditions.py`, `game/static_conditions.py`,

### The general continuation primitive (ENG-35, `14_` S1)

- **What:** `game/continuations.py` — a registry of choice handlers, plus
- **Files:** `game/continuations.py`, `game/rules_engine.py`,

### Structure-aware suspension: the iteration frame (ENG-35, `14_` S1)

- **What:** `GameState.deferred_effects` entries carry a frame kind —
- **Files:** `game/rules/casting_mixin.py`, `game/effects/core.py`

### Spec validation reaches every nesting depth (ENG-37, partial)

- **What:** `AbilitySpec.validate()` walked only `self.effects`, so docs/09's
- **Files:** `parser/oracle/spec.py`,

### The atom inventory (ENG-34, `14_` S0)

- **What:** `game/isa.py` — a CR-derived instruction set (**106** operations:
- **Files:** `game/isa.py`, `scripts/isa_report.py`,

### The cheap-exit checkpoint passed (ENG-34, `14_` S0b)

- **What:** `scripts/isa_report.py --corpus` re-derives `13_` §5.6(b) from the
- **Files:** `scripts/isa_report.py`, `isa.TOP_CORPUS_OPERATIONS` (frozen, so

### The CR-versus-engine diff as a generated MEC backlog (ENG-34, `14_` §7)

- **What:** Diffing the CR-derived ISA against what the engine can actually
- **Files:** `docs/implementation-state/BACKLOG.md` (MEC section),

### MEC-75 — Rolling a die (RULE 706) [CLOSED, PARSER_VERSION 306]

- **What:** The first of the ENG-34 CR-versus-engine diff MEC tickets closed
- **Files:** `models/game/events.py` (`ROLL_DICE`, `DICE_ROLLED`),

### MEC-76 — Fateseal (RULE 701.29a) [CLOSED, PARSER_VERSION 307]

- **What:** The second ENG-34 CR-versus-engine diff MEC ticket closed —
- **Files:** `models/game/events.py` (`FATESEALED`),

### MEC-77 — Meld (RULE 701.42a) [CLOSED, PARSER_VERSION 308]

- **What:** The third ENG-34 CR-versus-engine diff MEC ticket closed — a
- **Files:** `models/game/events.py` (`MELDED`),

### MEC-78 — Heal (RULE 701.69a) [CLOSED, PARSER_VERSION 309]

- **What:** The fourth ENG-34 CR-versus-engine diff MEC ticket closed —
- **Files:** `game/rules/damage_death_mixin.py` (`heal`),

### MEC-79 — Harness (RULE 701.64) [CLOSED, PARSER_VERSION 310]

- **What:** The fifth ENG-34 CR-versus-engine diff MEC ticket closed —
- **Files:** `models/game/events.py` (`HARNESSED`),

### MEC-80 — Triple (RULE 701.11) [CLOSED — no code, already shipped]

- **What:** The sixth ENG-34 CR-versus-engine diff MEC ticket, and the one

### MEC-81 — group-scoped die-to-exile arm (RULE 616) [CLOSED, PARSER_VERSION 311]

- **What:** The die-to-exile rider ("If a creature dealt damage this way
- **Files:** `game/effects/core.py` (`GameContext.damaged_this_way` +

### MEC-82 — conditional magnitude replacement (RULE 614) [CLOSED, PARSER_VERSION 312]

- **What:** "Target creature gets -2/-2 until end of turn.
- **Files:** `game/effects/core.py` (`PumpEffect` params +

### MEC-83 — `effect_amounts` kinds for counters and basic land types [CLOSED, PARSER_VERSION 313]

- **What:** ENG-37's `bind` node (RULE 608.2 "…for each …") had no way to
- **Files:** `game/effect_amounts.py` (`AMOUNT_KINDS` + the two `_base`

### MEC-84 — controller-scoped permanent-left-battlefield history [CLOSED, PARSER_VERSION 314]

- **What:** The **Revolt** and **Disappear** ability words ("if a permanent
- **Files:** `models/game/game_state.py` (trackers + `remove_from_

## Oracle-Text Parser Front-End

### PAR-93 — Contraption-crank ticket retired after legality audit

- **What:** Retired the ticket rather than implementing an unsupported game
- **Why:** The ticket's assertion that Unfinity Contraptions were

### PAR-94: Per-unit activation-cost reductions — increment (PARSER_VERSION 441)

- **What:** Added the oracle-text route for a trailing "this ability costs
- **Files:** `parser/oracle/segmenter.py`, `game/continuous.py`,

### PAR-94: Conditional graveyard-mana-value discount — increment (PARSER_VERSION 442)

- **What:** `dynamic_reduction` now honours an optional live `active_if`
- **Files:** `game/static_conditions.py`, `game/engine/activation_mixin.py`,

### PAR-94: Conditional cost gates — increment (PARSER_VERSION 443)

- **What:** Added the legendary-creature and instant/sorcery-graveyard

### PAR-94: Specialize conditional discount — increment (PARSER_VERSION 444)

- **What:** Imoen's Specialize rider is parsed fail-closed into keyword

### PAR-95: Adamant per-mana-type riders (PARSER_VERSION 445)

- **What:** The casting payment now preserves exact WUBRG/colorless amounts,

### PAR-119 pilot: composed cast-trigger head (PARSER_VERSION 449)

- **What:** The first axis of the composed trigger-head grammar.

### ENG-47 (second slice): the per-turn history counters are derived from the event log

- **What:** 31 of the 38 `GameState.*_this_turn` counters (spells cast and their per-colour / per-type

### ENG-47 (final slice): `spell_watchers` retired, three more history phrases, and one amount operand per effect (PARSER_VERSION 459)

### PAR-119 (attack / block / player-event axes) and two wrong-but-modeled fixes (PARSER_VERSION 456)

### PAR-124's own residue: "copy that spell X times" and a delayed trigger's own group pronoun (PARSER_VERSION 460)

### PAR-124 closes completely: the mana-tap/life-gain player-event pair, X-token creation, a for-each pump variant, a targeted delayed DIES trigger, an optional targeted-antecedent composition, a hand-zone spell duplicate, and the controller-binding fix that makes the targeted variant generally safe (PARSER_VERSION 463)

### PAR-124's own residue, second batch: the "must be blocked this turn if able" cluster, the animate-land/flash/tap-selector family, and a group-subject copy (PARSER_VERSION 462)

### PAR-123 / PAR-124: two wrong-but-modeled families closed (PARSER_VERSION 455)

### PAR-121 (first step): one "unless you pay" row over the verb (PARSER_VERSION 454)

- **What:** `_SACRIFICE_/_DESTROY_/_TAP_/_EXILE_UNLESS_PAY_RE` were four registrations of "`<verb>` ~

### ENG-47 (first slice): turn-stamped events and `event_this_turn` (PARSER_VERSION 453)

- **What:** Every fired event now carries the turn it fired in (`GameEvent.turn`, set by

### PAR-120 (first slice): structured count selectors, count conditions and "where X is the number of …" (PARSER_VERSION 452)

- **What:** "How many X" is now one grammar instead of a phrase → selector table per

### PAR-120: referent state, cast provenance, and "that player" (PARSER_VERSION 465–466)

- **What:** Two more rows in `static_handlers._STATIC_CONDITION_RES` — the same generic

### PAR-120: retiring `_PT_CDA_SELECTORS` (PARSER_VERSION 467)

- **What:** RULE 604.3's characteristic-defining P/T family ("~'s power [and toughness] [is/are

### PAR-120: retiring `_GY_COST_COUNT_SELECTORS` (PARSER_VERSION 468)

- **What:** RULE 601.2f's "this spell costs `<N>` less to cast for each `<type>` card in your

### PAR-120: retiring `_CONTROL_COUNT_SELECTORS` (PARSER_VERSION 469)

- **What:** "You control `<n>` or more `<X>`"/"you control a/an `<X>`" (`static_condition`'s own

### PAR-120: shrinking `_ACTIVATION_COST_REDUCTION_SELECTORS` (PARSER_VERSION 470)

- **What:** `_activation_cost_reduction_selector` (RULE 601.2f's per-unit activation discount)

### PAR-120: shrinking `_FOR_EACH_AMOUNTS` (PARSER_VERSION 471)

- **What:** `_count_amount` (the `effect_amounts` reading of "for each `<phrase>`"/"the number of

### PAR-120: shrinking `_SELF_ANTHEM_FOR_EACH_SELECTORS` (PARSER_VERSION 472)

- **What:** RULE 613's per-unit standing anthem ("~ gets +P/+T for each `<X>`", `_SELF_ANTHEM_

### PAR-120: `group_selector_objects` structured selectors, and retiring `_FOR_EACH_SELECTORS` (PARSER_VERSION 473)

- **What:** `continuous.group_selector_objects` — the object-*returning* sibling of

### PAR-120: retiring `_GROUP_SELECTORS`, closing sub-item (a) (PARSER_VERSION 474)

- **What:** `_GROUP_SELECTORS` (12 entries) shrinks to 4, via `catalogue.handlers._group_selector`

### PAR-120 (sub-item (b)): "total power" as a standing condition, all four surfaces, plus the combat-scoped sibling (PARSER_VERSION 475–476)

- **What:** "Creatures you control have total power N or greater/less" (RULE 613.6/603.4) is now

### PAR-120: the mana-symbol sibling of Adamant's own condition (PARSER_VERSION 477)

- **What:** "If `<mana symbol[s]>` was spent to cast it/this spell" — the printed-symbol spelling of

### PAR-120: "you control your commander" (PARSER_VERSION 478)

- **What:** "You control your commander" (RULE 903.4) recognized as a standing condition — the

### PAR-120: "that player has N or fewer/no cards in hand" phase-trigger cluster (PARSER_VERSION 479)

- **What:** "At the beginning of each opponent's/each player's `<step>`, if that player has `<N>` or

### PAR-120: the `any` (OR) combinator, closing a real architectural gap (PARSER_VERSION 480)

- **What:** `static_conditions.py`'s own evaluator gains an `any` (OR) combinator, the sibling of its

### PAR-120: activation-condition fallback, closing the duplication for good (PARSER_VERSION 481)

- **What:** `catalogue.handlers._activation_condition_dict` — the separate, narrower "activate only

### PAR-120: P/T-CDA amount expressions (PARSER_VERSION 482)

- **What:** `count_phrase.parse_amount_phrase` and `continuous.count_selector` now evaluate sums, twice-counts, offsets, counters on the source, distinct card types/colors and maximum or total mana values for RULE 604.3 characteristic-defining power/toughness. The Lhurgoyf "that number plus 1" form shares the power selector. Positive "instant and sorcery" lists count either type; stacked "noncreature, nonland" exclusions require both. The full-cache measurement rose from 17,354 to 17,428 covered cards with no coverage regression.

### PAR-120: turn-history thresholds and payment facts (PARSER_VERSION 483)

- **What:** Shared conditions now read per-player life loss, draws, poison, source damage, last-turn life loss, graveyard exits and Treasure mana actually spent on a cast. The existing cost-reduction route also counts distinct creatures that attacked or died this turn. Conditional cast and activation reductions now remove matching colored pips as well as generic mana, covering Even the Score and Kami of Jealous Thirst. The recognized phrases reach the applicable trigger, activation or cost gates; v483 adds 34 covered cards with no coverage regression.

### PAR-120: resolution ordinals, one cost-per-count row, counter amounts, and four engine fixes they exposed (PARSER_VERSION 484)

- **Resolution count.** "if this is the Nth time this ability has resolved this turn" and its "if it's the second time" ladder are an effect-only gate, `ability_resolution_count` (`effect_conditions.CONTEXT_CONDITION_KINDS`, `min`/`max`, "first or second" is a range), read off `GameContext.ability_resolution_count`. `resolve_top_of_stack` sets that window from `GameObject.ability_resolutions` — per source object, keyed by the ability's printed text (`StackItem.ability_key`, stable across the undo deep copy where an `id()` isn't), stamped with the turn rather than swept each turn start, cleared by `reset_as_new_object`. The rulings (Ashling the Pilgrim, Omnath) fix the semantics: resolutions, not activations; the resolving one counts; only exactly the Nth; copies of the ability count (`copy_ability_item` carries the key). Kept out of `static_condition()` so an "as long as" static can never claim it.
- **Cost per count.** "This spell costs {N} less to cast for each `<X>`" is one row over `count_phrase` (Primeval Protector, Wall Off, Vanquish the Horde, Spectral Denial), replacing five per-phrase rows; `_SELF_COST_PER_PHRASES` keeps the named selectors those rows emitted (attacking, attacked/died this turn, party, basic land types), so no already-covered card's spec changed (spec-diffed against HEAD).
- **Counter amounts behind a leaving-counter gate.** "that many"/"that number of" and "where X is the number of counters it had on it" bind to `trigger_event_counter` (no `counter` = every kind); `add_counters` takes X (`COUNT_X`). Reyhan-/Yuna-/Felisa-shaped, plus the "where X is …" token cards.
- **"it" after create/manifest.** A bare "put counters on it" parsed as the ability's own source, so Additive Evolution, Recon Craft Theta, Fierce Invocation, Formless Nurturing, Big Play, Free from Flesh and Miraculous Recovery all put their counters on the spell/source (the 0/0 tokens died). Behind a clause that chose or created something, it is now `previous_subject` (`_stamp_counters_on_referent`, also inside a `bind`); `AddCountersEffect` falls back from `previous_targets` to `created_objects` like `PumpEffect`, and `ManifestEffect` reports what it manifested.
- **X per resolution.** `_substitute_x` overwrote an ability's X sentinel for good, so "{X}: You gain X life" activated for 3 then 5 gained 3 twice; `_restore_x_sentinels` snapshots the printed sentinels once and restores them before every substitution. A cast trigger's X is the cast spell's (`SPELL_CAST` carries `x_paid`, Zaxara's ruling).
- **Smaller:** "all creatures you control" group subject; "you control an X and a Y" (`all` over two control counts); devotion printed as "the number of green mana symbols in the mana costs of permanents you control"; "differently named" (`distinct: name`). Refused because the engine couldn't charge them yet: "Sacrifice X `<things>`" costs and "pay {X}. If you do, put X counters" (both lifted since, by ENG-49 and ENG-48; Springjack Pasture's mana-ability form stays refused). Probe: +37 cards, −1 (Springjack Pasture); `coverage_report.py`: 17,515 / 34,811.

### PAR-120: batch 6 — count-selector sweep and the last per-verb amount tables (PARSER_VERSION 485)

- **Wrong-but-MODELED counts.** Four emitters built `creatures_you_control_of_type_<word>` from whatever word was printed (`subgrammars.devotion_selector`'s single-word branch, "create … for each `<word>` you control", "loses life equal to the number of `<word>` you control", and Eriette's hand-authored drain, copied from that parse). The branch counts *creatures*, so Beacon of Creation (Forests), Avenger of Zendikar (lands), Nomads' Assembly (creatures), Basilisk Gate (Gates), Eriette (Auras), Myojin of Blooming Dawn (permanents) and Lys Alana Scarblade ("Elves" → `elve`) counted 0. They now call `subgrammars.subtype_count_selector` → `parse_count_phrase`, which reads a subtype on any permanent, a card type, an irregular plural, and refuses an unknown word; the Shrine/Bobblehead denylist went with it. 30 cards changed spec, all executed (`test_par120_count_selector_sweep.py`).
- **One X for a sentence.** "~ deals X damage to target creature and you gain X life, where X is …" was split at "and", so only the life gain saw the tail and the damage used the unpaid spell X (Tendrils/Consuming Corruption, Harsh Sustenance, Profane Prayers dealt 0). `_where_x_specs(several=True)` runs before the connector cascade and binds every effect's X — only when *every* effect holds it (Anim Pakal measures after its counter, so it keeps the sequenced reading). The single-effect path also stopped dropping a peeled condition inside the `bind` (Voldaren Ambusher's "if an opponent lost life this turn").
- **Tables retired.** `_PUMP_X_SELECTOR_PHRASES` and most of `_PUMP_X_AMOUNT_PHRASES` became one `bind` row over `parse_amount_phrase` ("the amount of life you gained this turn" joined `_NAMED_TERMS`; only "its power", "that creature's power", "the result" stay a table); `_BOLSTER_AMOUNT_SELECTORS` likewise; the self-anthem graveyard-subtype row reads `parse_count_phrase`; `_for_each_count_selector`'s four fallbacks (shadowed by the grammar except for an unknown word guessed as a creature type) and the "noncreature, nonland" table row (its grammar bug was already fixed) are gone.
- **Dead `count_selector` branches deleted** after a full-cache + catalogue scan of every emitted selector: 16 named branches (the eight the ticket listed minus `station_tapped_power`, which the binder sets, plus `artifacts_opponents_control`, `cards_in_your_hand`, `counters_on_permanents_you_control`, `distinct_named_artifact_tokens_you_control`, `elves_on_battlefield`, `noncreature_nonland_cards_in_your_graveyard`, the `*_cards_in_your_graveyard` substring scan) and three prefix parsers (`lands_opponents_control_of_type_`, `other_creatures_of_type_`, `other_creatures_you_control_of_type_`). `creatures_that_left_battlefield_this_turn` was kept and wired instead: MEC-84 built it for Kutzil's Flanker and no parse ever reached it (`_FOR_EACH_AMOUNTS`, and the "for each" group cap widened 45 → 70 characters).
- **Probe.** `parser_probe.py composition mods --axis <regex>` lists every repaired sentence of an axis, and `mods` now counts only sentences that fail on their own — a failing body's parseable sentences had inflated every axis (the "another/other" axis read 58 when 32 failed).

### PAR-128: controller scope, "another", and the player subject as target-grammar slots (PARSER_VERSION 485)

- **Scope slot.** `subgrammars.TARGET` accepts " an opponent controls / you don't control" after any row and "another/other" before it; `resolve_target_kind` composes them onto the row's kind — `NOT_YOU_TARGET_KINDS` (engine `SCOPE_NOT_YOU` frames; new `enchantment_/artifact_or_enchantment_/artifact_or_creature_you_dont_control`) and, for "another", the kind itself when its pool already excludes the source (`SOURCE_EXCLUDED_TARGET_KINDS`) or `OTHER_TARGET_KINDS`. `test_par128_target_scope.py` holds both tables to `targeting.TARGET_FRAMES`, since the parser can't import it.
- **Verb whitelists.** 37 per-verb `kind not in (...)` checks became `target_kind_allowed(kind, allowed)`, which walks `SCOPED_TARGET_BASE` (a scoped kind or type union narrows its base), so "destroy/return/tap/put a counter on target creature an opponent controls" work without each verb listing each scope. The pronoun-antecedent check in the segmenter reads the same way.
- **Union bug.** The N-way "target X, Y, or Z" row also matched "target artifact or enchantment", so Naturalize, Disenchant and ~100 others could target any permanent; the dedicated two-type rows now sit above it (`artifact_or_enchantment`, `artifact_or_creature` in either order). 124 already-covered cards changed kind accordingly.
- **One gate over "A, then B".** "If `<cond>`, A, then B" handed B to the connector split ungated: Canyon Crab, Wistfulness, Statute of Denial, Contaminant Grafter, Scion of Vitu-Ghazi and So Shiny did their second half regardless, and Airbender Ascension's "exile …, then return it" became "return the source". The existing one-gate rule now covers ", then" as well as "and".
- **Player subject.** "each player / each opponent `<verb>`" parses the verb as "target player `<verb>`" and iterates it with `for_each {"players": …}` (every effect must target exactly that player); "target opponent `<verb>`" narrows the target to `opponent`. The token rows' `who` slot takes "target player/opponent" (`creators: target`, the Hunted cycle).
- **Yield** (with batch 6): 17,515 → 17,641 (+126, 0 regressed); Commander-legal 53.3%. Open residue is PAR-128 in `BACKLOG.md`.

### PAR-120: count vocabulary, departing copy, token CDA, and "instead" overrides (PARSER_VERSION 486–498)

- `parse_count_phrase` composes disjoint exile/graveyard counts as one existing `terms` expression (Crackling Drake, Huskburster Swarm); the adjective in "untapped artifacts, creatures, and lands" applies to every member of Maraxus's type list. The distribution rule is limited to tap state so ambiguous adjective lists still fail closed.
- `chosen` is a structured selector scope, resolved through the source's existing `chosen_player_id`. Hand, graveyard and battlefield phrases now share it (Entropic Specter, Haunting Apparition, Lost Order of Jarkeld, Pallimud, Skyshroud War Beast). Without a recorded choice, the count is zero. The PAR-120 backlog retains only the other CDA forms and its remaining non-CDA work.
- A structured sum now counts colour-specific mana symbols in cards in a zone (Umbra Stalker); it reuses `ManaCost`'s hybrid-symbol colours. `Chroma —` is stripped as a RULE 207.2c ability word so the CDA body reaches the shared amount grammar.
- A counter-gated death trigger can copy its departed subject from the event's instance id (Chronozoa). This uses `CopyPermanentEffect`'s existing `trigger_event` referent and count; the live test resolves the death trigger after the original has reached the graveyard.
- Inline */* tokens whose quoted text defines their power and toughness carry that text on the synthesized token card. The normal token binder installs its own `pt_cda` at entry, so subsequent count changes update it (Kalonian Twingrove, Gutter Grime, Hallowed Haunting, Voice of Resurgence, Consuming Blob). The parser validates the quoted body through `static_effect_specs` before claiming it; the runtime test checks the token grows when another Spirit enters.
- The mass `add_counters` clause accepts "each creature you control that has a +1/+1 counter on it" (Slurrk), using its existing `creature_filter` at resolution. It leaves unmarked creatures untouched.
- A targetless "A. If `<condition>`, B instead" body becomes one `if_else` node, evaluating the gate before either branch. Rumor Gatherer now draws on the second resolution instead of also scrying.
- Targeted "instead" overrides (v496). When the replacement is the base with only its number changed, it becomes one `bind` measuring `{"kind": "if", …}`, so the base's target is announced once and the size is read at resolution (Galvanize, Rowan, Scholar of Sparks, Tezzeret's Simulacrum, Sulfurous Blast, Haunting Hymn). A targeted `count` is refused here because it fixes how many targets are announced (RULE 601.2c). Any other override is an `if_else`. `IfElseEffect.target_specs` now announces a requirement when both branches announce the *same* one, since the target is fixed whichever branch runs (Scythecat Cub, Colossal Growth — the MEC-82 keyword-grant gap, Tragic Banshee, Genemorph Imago, Doctor Jane Foster, Aerith). The parser resolves the replacement's "that creature/player/card" and leading "she/he/it" to the base's own target phrase, compares a target-shape signature (kind, count, mana-value cap, filters), and refuses a mismatch; Blood Beckoning and Bloodchief's Thirst stay unclaimed for that reason. "If `<cond>`, instead B" (leading "instead") is the same node. A leading intervening "if" on the base gates the whole override (Tallyman of Nurgle).
- An "Infusion —"/"Addendum —" paragraph on an instant or sorcery is joined onto the previous paragraph before normalizing, because it is the same spell ability's next instruction (RULE 608.2c). "That creature" and "instead" then see their antecedent (Efflorescence, Foolish Fate, Withering Curse).
- New conditions: `cast_during_your_main_phase` (a cast-time `GameObject` flag beside `cast_outside_sorcery_speed`, stack or not; all 14 SOLO Addendum cards), `treasure_mana_spent_to_activate` (stamped on the source at activation payment, the `counters_removed_as_cost` precedent; Jetmir's Fixer, Forsworn Paladin), and "you gained N or more life this turn" (the existing `gained_life_this_turn` `amount`; Aerith, Haliya, Sanguine Indulgence).
- "Otherwise, `<B>`" now absorbs a following "When you do, …" sentence into the else branch (Rose Room Treasurer). New effect `turn_face_up_chosen`: the controller picks one of their face-down permanents and turns it face up with no cost (RULE 708.8 by an effect; Zimone, Mystery Unraveler). `RulesEngine.turn_face_up` now reveals an instant or sorcery and leaves it face down, with no trigger (RULE 701.40g/701.58g).
- CDA residue (v496): an animate-with-quoted-CDA row grants the quoted `pt_cda` as an extra static on the animated object, targeted or self (Druid Class, Beorn's Hospitality, Chimeric Mass, Svogthos, The Goblin Sparring Grounds, whose count term is the player's experience counters). Angry Mob's turn-split CDA is a `pt_cda` gated `your_turn` plus a fixed `pt_set` gated `not_your_turn`, claimed as one static line.
- Retched Wretch's counter-gated death trigger now returns its own card and attaches a permanent layer-6 ability-removal static to the new object. A second death with the same counter no longer triggers it.
- Bogardan Phoenix branches once on the DIES event's last-known `death` counter: a marked source is exiled; an unmarked one returns with a death counter. The new effect-only `trigger_event_counters` condition is three-valued, so a missing event runs neither branch. The live test follows the first and second deaths.
- Ambitious Augmenter now creates its Fractal and transfers every counter kind from the dying source's event snapshot to the created token. `TransferEventCountersEffect` gained a `created` referent; a live death test checks both +1/+1 and shield counters.
- Rite of the Serpent measures its target's +1/+1 counters at resolution before destroying that target. A `bind` carries the captured value into an `amount_compare` branch that creates the Snake only for a marked creature; the bound sentinel is now valid in amount expressions. This leaves target selection on the outer `bind`, as required by RULE 115.1.
- A named legendary token with a quoted CDA (Bonny Pall's Beau) now takes the same token-card route as the unnamed */* tokens. The parser validates the quoted self-reference against the token's name, and the live test checks Beau's land-based P/T.
- Elephant Resurgence fuses its distributive token creation and subsequent quoted CDA into a single creation effect. Each token counts its own controller's creature cards, verified with different graveyard sizes for two players. Seize the Storm's token keeps trample while its CDA adds instant and sorcery cards in the graveyard to cards with printed flashback owned in exile.
- Closing batch (v498), which closed the ticket. **First-draw reveal:** "Reveal the first card you draw each turn. Whenever you reveal a `<type>` card this way, …" (Primitive Etchings, Rowen) is the existing first-draw `DRAW` trigger with each body effect gated on a new `first_drawn_this_turn` referent (the controller's first entry in `GameState.cards_drawn_this_turn_ids`); the reveal itself has no game effect. A new `is_basic` condition reads the basic supertype off the printed type line, since `Card` has no flag for it. Live tests also check a non-basic land and a second draw.
- **Turn-scoped spell cost reductions:** `GameState.turn_cost_reductions` holds player-owned RULE 601.2f discounts (`amount`, optional `spell_type`/`spell_colors`/`face_down`, `next_only`). They are read by `continuous.cost_reduction_for` after the permanent statics and cleared in `_step_cleanup`; a `next_only` entry is used up by the next matching cast in `RulesEngine.cast_spell`, free casts included. Effect `reduce_spell_costs_this_turn` adds an entry, and an X ("where X is … as this ability resolves") comes through `bind`, so it is measured once at resolution. This closes the whole family: Rowan and Will, Scion of …, Hardened Berserker, Peerless Samurai, Kaza, Maelstrom Muse, Spellbinding Soprano, Goblin Maskmaker. The new `life_lost_this_turn` count selector supplies Rowan's X.
- **Ochre Jelly's Split:** the dies trigger nests two `bind`s. The first pins the departed object's `instance_id`; the second measures half its `+1/+1` counters from the DIES snapshot (`divide: 2`, RULE 107.2 rounds down). The delayed end-step trigger (RULE 603.7) runs a `copy_permanent` with new `target_instance_id`/`enter_counters` params. The counters go on as the copy is made, so the 0/0 copy never meets a state-based-action check. "Split —" joined the RULE 207.2c ability-word list.
- **Cost-paid source (RULE 608.2h):** "for each `<kind>` counter on ~" now matches; `_FOR_EACH_SUFFIX_RE`'s group class lacked `~`, which also unlocked Culling Dais, Shrine of Loyal Legions, Otherworld Atlas and Private Research. A departed permanent keeps its counters until it becomes a new object, so these read last-known information unchanged. In an activated ability whose own cost exiles or sacrifices ~, "if it had N or more `<kind>` counters on it" is read as `source_counters` (Lost Isle Calling). **Fixed along the way:** `costs.py` had no battlefield "Exile ~" cost, so such an ability activated without exiling its source. New `ActivationCost.exile_self`, paid via `RulesEngine.exile`, with an affordability check that the source is on the battlefield.
- Yield of the closing batch: 17,739 → 17,763 (+24, 0 regressed), Commander-legal 53.6% (17,069). The full-cache tier's two red tests are the pre-existing ENG-50 pair.

### PAR-122: trigger doublers as a composed cause × subject (PARSER_VERSION 451)

- **What:** "If a triggered ability of `<subject>` triggers, that ability triggers an

### PAR-119: composed object-event head — enters/dies/attacks/blocks/leaves, sacrifice, discard, damage (PARSER_VERSION 450)

- **What:** The second axis of the composed trigger-head grammar, for the events

### PAR-98: Small verified residue batch #2 (PARSER_VERSION 448)

- **What:** Closed the fourteen-shape batch that PAR-79's close-out split off
- **Files:** `parser/oracle/segmenter.py`, `catalogue/handlers.py`,

### PAR-96: Total-mana cast-trigger riders (PARSER_VERSION 446)

- **What:** Added reusable parsing for “if N or more mana was spent to cast
- **Files:** `parser/oracle/segmenter.py`, `parser/oracle/gate.py`,

### PAR-97: Mill graveyard-entry batches (PARSER_VERSION 447)

- **What:** Added `CARDS_MILLED`, a last-known-information snapshot emitted
- **Files:** `models/game/events.py`, `game/rules/draw_discard_mixin.py`,

### PAR-92: Small verified residue batch (PARSER_VERSION 440)

- **What:** Modeled five small, independently verified parser shapes: the
- **Files:** `game/static_conditions.py`, `game/rules/damage_death_mixin.py`,

### PAR-91: Optional collect-evidence conditional riders (PARSER_VERSION 439)

- **What:** Added parser support for optional `collect evidence N` additional
- **Files:** `game/effects/choices_actions.py`, `parser/oracle/segmenter.py`,

### PAR-90: Suspected-state resolve-time referents (PARSER_VERSION 438)

- **What:** Added source, attached-host, and sacrificed-cost suspected-state
- **Files:** `game/effect_conditions.py`, `game/effects/counters_tokens.py`,

### PAR-89: Named-counter entry cycles (PARSER_VERSION 437)

- **What:** Tapped lands entering with charge/depletion counters now use both

### PAR-88: Graveyard land-play permission (PARSER_VERSION 435)

- **What:** "You may play lands from your graveyard" now binds a land-only

### PAR-87: Sacrifice-or-mana additional cost (PARSER_VERSION 434)

- **What:** The mandatory "sacrifice a creature or pay {M}" cast-cost form

### PAR-86: Targeted graveyard-card shuffle (PARSER_VERSION 433)

- **What:** "Target player shuffles up to N target cards from their graveyard

### PAR-85: Self-protective finite damage redirect (PARSER_VERSION 432)

- **What:** The en-Kor form "the next N damage that would be dealt to ~ this

### PAR-84: Tap and skip-next-untap family (PARSER_VERSION 431)

- **What:** The existing `TapEffect`/`SkipNextUntapEffect` pair now reaches

### PAR-83: Targeted graveyard card to library bottom (PARSER_VERSION 430)

- **What:** Parser recognition now reaches the existing `return_to_library`

### PAR-82: Quoted Static Grants — Residue After a Stale Premise (in progress, PARSER_VERSION 397)

- **What:** The ticket's own framing — "these two specific subject shapes

### PAR-81: "Switch Target Creature's Power and Toughness Until End of Turn" (PARSER_VERSION 396)

- **What:** `"pt_switch"` already existed as a `StaticAbility` layer 7e

### PAR-80: X-Spell "Target Creature Gets +X/+`<N>` Until End of Turn" (closed, PARSER_VERSION 413)

- **What:** The variable-power/fixed-toughness pump family (an X spell/

### PAR-78: "Prevent All Damage That Would Be Dealt To `<target>`" — Broad Recognition (PARSER_VERSION 393)

- **What:** The largest verified win in the 2026-09-15 Commander-legal tail

### PAR-77: Rebel/Mercenary Graveyard-Return Filter (PARSER_VERSION 391)

- **What:** PAR-70 built the "`<subtype>` permanent card" qualifier
- **Files:** `parser/oracle/catalogue/handlers.py`

### PAR-76: "Full Party" as a Conditional-Magnitude Override (PARSER_VERSION 390)

- **What:** RULE 700.8/702.129's Party mechanic (PAR-53/72) already had a
- **Files:** `game/effects/damage_draw.py` (`DealDamageEffect.amount_if_

### PAR-75: "Doctor's Companion" Referenced as a Card-Quality Filter (PARSER_VERSION 389)

- **What:** RULE 702.124m's "Doctor's companion" keyword (Doctor Who,
- **Files:** `parser/oracle/segmenter.py`

### PAR-74: "Spirit or Arcane spell" cast-trigger filter (Kamigawa, PARSER_VERSION 388)

- **What:** The ticket's own diagnosis was stale by the time it was worked:
- **Files:** `parser/oracle/segmenter.py` (`self_subject=True` on the typed

### PAR-70: Rebel/Mercenary Recruiter Tutor Chain (Mercadian Masques, PARSER_VERSION 383)

- **What:** Recognized `"<cost>: search your library for a rebel/mercenary
- **Files:** `parser/oracle/catalogue/handlers.py`

### PAR-71: "That Spell's Mana Value" Amount Referent (PARSER_VERSION 384)

- **What:** "That spell's mana value" as a resolve-time amount, in two
- **Files:** `parser/oracle/catalogue/handlers.py` (`_pump_mana_value`,

### PAR-72: Party Generalized Into a Resolve-Time Amount (PARSER_VERSION 385)

- **What:** Party (RULE 700.8/702.129) was previously wired only into two
- **Files:** `parser/oracle/catalogue/handlers.py` (the whole "PAR-72:

### PAR-49: Mistform chosen creature-type activation (PARSER_VERSION 373)

- **What:** Added the exact `{cost}: ~ becomes the creature type of your

### PAR-50: Combat-damage assignment statics (PARSER_VERSION 374)

- **What:** Parsed the unblocked-assignment and toughness-instead-of-power

### PAR-52: Spirit-or-Arcane cast triggers (PARSER_VERSION 376)

- **What:** Extended the existing spell-subtype cast-trigger grammar from a

### PAR-51: `start` investigated (no cluster) / Storied + comma-less title self-reference (PARSER_VERSION 380)

- **What:** BACKLOG's `PAR-51` bundled two unrelated leads from a stale v186
- **Files:** `parser/oracle/catalogue/keywords.py`,

### PAR-56: Teamwork (RULE 702.194) rider grammar + a dormant-bug fix (PARSER_VERSION 381)

- **What:** A prior batch (v377) had already wired the modal "choose N.
- **Files:** `game/static_conditions.py`, `game/effect_conditions.py`,

### PAR-58: Reflexive modal wrapper — stale backlog reconciliation

- **What:** Verified the existing gate-level `you may pay <cost>.

### PAR-59: Haunt payoff trigger wrappers (PARSER_VERSION 378)

- **What:** Added both printed Haunt payoff forms: combined ETB/haunted-

### PAR-45: Choose an opponent as this enters (PARSER_VERSION 372)

- **What:** Added the pre-entry `ChooseOpponentReplacement`, wired through

### PAR-46: Graveyard creature-card cost reduction — stale backlog reconciliation

- **What:** Closed as already delivered by the general `this spell costs

### PAR-44: Any-number deck-construction exception (PARSER_VERSION 371)

- **What:** RULE 100.2a's `A deck can have any number of cards named ~.` is

### PAR-64: Raid condition positional forms (PARSER_VERSION 369)

- **What:** Closed the positions that do not use PAR-62's ordinary leading

### PAR-61: grammar-restructure umbrella — porting the clause-tree-tier negative result

- **What:** PAR-61 is the umbrella over the ENG-34→37 / PAR-62 / PAR-63 chain;
- **Files:** `parser/oracle/catalogue/subgrammars.py`,

### PAR-63: cross-module sub-grammar reuse (`14_` S5)

- **What:** three shared-grammar items, all behaviour-neutral (the corpus
- **Files:** `parser/oracle/catalogue/subgrammars.py`, `handlers.py`,

### PAR-116: cross-module slot-grammar reuse audit (`14_` S5)

- **What:** Closed the successor audit without adding a false abstraction.
- **Files:** `docs/concepts/13_ORACLE_PARSER_GRAMMAR_REVIEW.md`,

### PAR-62: clause grammar surface complete (PARSER_VERSION 302–305)

- **Files:** `game_state.py`, `game/engine/combat_mixin.py`,
- **What:** the depth behind three connectives — the quantity half of

### PAR-62: section 5.2's connectives routed to nodes and gates (`14_` S4)

- **What:** the remaining `13_` section 5.2 connectives, at PARSER_VERSION 303:
- **Files:** `parser/oracle/segmenter.py`, `parser/oracle/gate.py` (v303),

### PAR-115: "its controller `<verb>`" is a referent, not a connective (`14_` S4, PARSER_VERSION 414)

- **What:** `13_ORACLE_PARSER_GRAMMAR_REVIEW.md` §3.1/§3.3 framed this
- **Files:** `parser/oracle/catalogue/handlers.py` (seven new

### PAR-62: the clause grammar's first connective (`14_` S4, PARSER_VERSION 302)

- **What:** RULE 601.2b's "you may `<effect>`" appearing **mid-body** now
- **Files:** `parser/oracle/segmenter.py`, `parser/oracle/gate.py` (v302),

### Parse-on-load memoization

- **What:** `parse_oracle` is called once per `GameObject` built, so a popular card was re-parsed from scratch on every copy/every game.
- **Files:** `parser/oracle/gate.py`

### Class level-header regex fix (RULE 716.3)

- **What:** `CLASS_LEVEL_RE` assumed "Level N: `<cost>`" but every real Class card prints the cost first ("{3}{W}: Level 2") — the regex had never matched a single real car…
- **Files:** `parser/oracle/catalogue/levels.py`

### Full-universe card-pool import and coverage ledger

- **What:** Bulk-loaded the full ~34k-card Scryfall Oracle universe into a persistent `RawCardStore`, with coverage measured/ranked by `scripts/coverage_report.py` against…
- **Files:** `scripts/import_bulk.py`, `services/raw_card_store.py`, `services/coverage_db.py`

### Self-reference fold ("this creature" normalization)

- **What:** `normalize._fold_self_reference` folds modern templating's "this creature"/"this permanent"/"this artifact"/etc.
- **Files:** `parser/oracle/normalize.py`

### Stickers (RULE 123) Declared Permanent Non-Goal

- **What:** The parser gate now recognizes any card mentioning "sticker" and fails closed with a new `NEVER_SUPPORTED` verdict distinct from `UNMODELED`, so it contributes…
- **Files:** `parser/oracle/gate.py`, `parser/oracle/processing_list.py`, `services/coverage_db.py`, `scripts/coverage_report.py`
- **Why:** No handler will ever claim Sticker text, so leaving it as ordinary `UNMODELED` would permanently pollute the "what to build next" ranking.

### Oracle-Text Parser Front-End — Phase 0/1 Bootstrap

- **What:** First two phases of the two-stage oracle-text compiler: a keyword catalogue mapping all RULE 702 keywords to their `AbilitySpec` shape, plus an effect-clause fr…
- **Files:** `parser/oracle/normalize.py`, `parser/oracle/segmenter.py`, `parser/oracle/catalogue/`, `parser/oracle/gate.py`, `game/ability_catalogue.py`
- **Why:** A card only ever gets parsed effects when fully `MODELED` — never half-resolved — which is what makes `gate.parse_oracle`'s coverage verdict the safety boundary…

### Battle oracle-text recognition

- **What:** `normalize._SELF_REFERENCE_RE` folding "this battle"/"this Siege" to `~` alone unlocked most of the 12/39 cached battles that reached MODELED; three shared-gram…
- **Files:** `parser/oracle/normalize.py`, `parser/oracle/catalogue/handlers.py`

### Inline "gets +1/-1 or -1/+1" split into two abilities (RULE 700.2)

- **What:** `segmenter._inline_pt_modal_bodies` rebuilds a compact "or"-joined full P/T clause pair into two complete activated abilities (Pemmin's Aura), only tried after…
- **Files:** `parser/oracle/segmenter.py`

### Alchemy `A-` self-name folding fix (PAR-4)

- **What:** `normalize._fold_self_name` now also folds an `A-`-stripped sibling of every name form it tries, so an Arena-rebalanced card's oracle text (which self-refers by…
- **Files:** `parser/oracle/normalize.py`

### `is_registered` DFC/split coverage-lookup fallback (Hobbits batch)

- **What:** `ability_catalogue.is_registered` didn't share `specs_for`'s own DFC/MDFC/split "//" front-face fallback, so a card registered under its front face alone report…
- **Files:** `game/ability_catalogue.py`

### `normalize`: leading "Until end of turn, `<body>`." fold

- **What:** Folds the less-common leading-duration phrasing (Triumph of the Hordes-shaped) into the far more common trailing "`<body>` until end of turn." every duration ha…
- **Files:** `parser/oracle/normalize.py`

### `_COST_LOOKS_REAL` exile-from-hand cost recognition

- **What:** "Exile this card from your hand: Add `<mana>`." (Simian/Elvish Spirit Guide) was unclaimed purely because the cost-shape sniff's recognized-cost-verb list never…
- **Files:** `parser/oracle/segmenter.py`

### Mana-ability coverage-classification fix for Bloom Tender (Oracle-Text Parser Front-End)

- **What:** Bloom Tender was already fully playable but scored `UNMODELED` because the segmenter's mana-ability claim check only recognized an effect line starting with "ad…
- **Files:** `parser/oracle/segmenter.py`

### General Count-Amount Resolver (MEC-27 origin)

- **What:** "X is the number of `<noun phrase>` you control" folded into the existing `subgrammars.DEVOTION` fragment (not a parallel constant), so every handler already em…
- **Files:** `parser/oracle/catalogue/subgrammars.py`, `game/continuous.py`.

### Qualifier Grammar & Draw/Life Verb Families for Count-Amount Resolver (MEC-27)

- **What:** `DEVOTION` gained "creatures you control with power N or less/greater" and generalized "tapped `<type>` you control"; `DrawCardEffect` gained `amount_from_count…
- **Files:** `parser/oracle/catalogue/subgrammars.py`, `game/continuous.py`, `game/effects/core.py`.

### Extra-Combat-Phase Regex Word-Order Widening

- **What:** `_EXTRA_COMBAT_PHASE_RE` widened to recognize the subject-first word order ("there is an additional combat phase after this phase") alongside the original ("aft…
- **Files:** `parser/oracle/catalogue/handlers.py`.

### Multi-Target Range Grammar & `PumpEffect.previous_subject` (ENG-30)

- **What:** The shared `_MULTI_TARGET_QUANTIFIER` gained a third alternative for "N or M" ranges, widening `tap`/`return_to_hand`/`return_from_graveyard`/`add_counters`/`pu…
- **Files:** `parser/oracle/catalogue/handlers.py`, `game/effects/core.py`.

### RULE 701.47/48 Amass — First Parser Handler

- **What:** "Amass `<Type>` N" ("amass Orcs 1"/"amass Zombies 2") had zero parser recognition even though the engine primitive (`AmassEffect`) already existed and was prove…
- **Files:** `parser/oracle/catalogue/handlers.py`

### PAR-21: RULE 701 keyword-action audit + Connive/Discover parser handlers

- **What:** PAR-21 asked for the audit its RULE 702 half (195-row keyword catalogue) had already had — a walk of the full RULE 701 keyword-action list (CR 701.2–701.70, `do…
- **Files:** `parser/oracle/catalogue/handlers.py`, `parser/oracle/gate.py` (PARSER_VERSION 104)

### RULE 604.3 characteristic-defining P/T — first oracle-text handler (PAR-20 follow-up, PARSER_VERSION 105)

- **What:** "`~`'s power and toughness are each equal to the number of `<X>`." (Maro / Molimo / Psychosis Crawler / Dakkon Blackblade / Ashaya-shaped) had no parser recogni…
- **Files:** `parser/oracle/catalogue/static_handlers.py`, `game/continuous.py` (`count_selector` — `cards_in_your_hand`), `parser/oracle/gate.py` (PARSER_VERSION 105)

### PAR-31 — "you get an emblem with '<ability>'" inner-body coverage

- **What:** The emblem *wrapper* has always parsed (`handlers._create_emblem` recursively parses the quoted body via `segment_line`); PAR-31's residue was inner-body famili…
- **Files:** `parser/oracle/catalogue/static_handlers.py`, `parser/oracle/catalogue/handlers.py`, `parser/oracle/segmenter.py`, `game/effects/core.py` (`CreateEmblemEffect.abilities`), `game/rules/misc_mixin.py` (`create_emblem` list branch), `game/ability_catalogue/entries_016.py`, `tests/test_par31_emblem_multi_type_grant.py`, `tests/test_par31_ob_nixilis_emblem.py`, `tests/test_mec54_max_life_and_you_compleat_me.py`

### PAR-33 — Aura/Equipment quoted-ability grants

- **What:** Closed the `enchanted/equipped <permanent> has "…"` family, including combined `gets +N/+N and has "…"` and attached-land forms.
- **Files:** `parser/oracle/catalogue/{handlers,static_handlers}.py`, `parser/oracle/segmenter.py`, `parser/oracle/gate.py` (PARSER_VERSION 236–362), `game/{binding/core,continuous,mana_abilities}.py`, `game/effects/{damage_draw,exile_control,registry}.py`, `models/game/game_object.py`, `tests/test_par33_regenerate_attached.py`.

### PAR-34 — generic group/state quoted-ability grants

- **What:** Closed group-scoped quoted grants and Threshold's conditional self grants without card-name or tribe-specific behaviour.
- **Files:** `parser/oracle/catalogue/{handlers,static_handlers}.py`, `parser/oracle/{segmenter,gate}.py` (PARSER_VERSION 363), `game/{binding/core,targeting}.py`, `game/effects/{choices_actions,exile_control,life_sacrifice,registry}.py`, `tests/test_par34_counter_lord_and_threshold.py`.

## Deck/Cube Playability Batches

### cEDH staples cube (Batches 13, 14, 25 and 26)

- **What:** Five subagent waves (2 generic-parser, 3 hand-authored) raised the 611-card "cEDH staples"/"cEDH staples 2" cube pool from 185 to 271 playable cards, combining…
- **Files:** `game/ability_catalogue.py`, `parser/oracle/catalogue/handlers.py`, `parser/oracle/catalogue/static_handlers.py`
- **Why:** Cards left unmodeled were each logged individually against a genuine engine gap (control-exchange, coin-flip, Soulbond/Mutate/Bargain) rather than half-modeled.
- **What:** Direct-authored continuation raising the cube pool from 271 to 285 playable, centered on a "destroy/counter target X; its controller creates a token" cluster.
- **What:** Made all 43 cards of the "cEDH staples cube" pool playable (2026-07-22), organized in six waves around shared primitives (state-tracking, mana, control/zones, n…

### ENG-38: Six stale cube-batch pins, and why an opt-in test tier goes stale

- **What:** The six `test_cube_batch_*` failures that surfaced once the
- **Files:** `game/effects/core.py`, `game/ability_catalogue/entries_002.py`,

### Deck Batch: Wyleth Equip (Boros Voltron)

- **What:** Hand-authored the ~50-card "Wyleth Equip" Boros voltron commander deck (2026-07-17), shipping a batch of generic reusable Equipment/Aura payoff primitives along…
- **Files:** `game/ability_catalogue.py`

### Enrage stragglers — hand-authored batch (11 cards)

- **What:** Closed the entire ~25-card Enrage population by hand-authoring the 11 cards still UNMODELED after the trigger fix, per explicit "do not defer" instruction — add…
- **Files:** `game/ability_catalogue.py`, `game/effects/core.py`, `game/targeting.py`

### "Hobbits"/"Wyleth Equip" saved decks made fully playable

- **What:** User-directed batch closing 50 of 51 unmodeled cards across two saved Commander decks (Hobbits 42, Wyleth Equip 9) — every card's full ability set bound to real…
- **Files:** `game/ability_catalogue.py`

### "Keywords Showcase" and "Eliferate" saved decks made fully playable

- **What:** User-directed batch: "Keywords Showcase" fully modeled (18/18); "Eliferate" reached 64/91 (remaining 27 genuinely bespoke — planeswalker loyalty bodies, trigger…
- **Files:** `game/ability_catalogue.py`, `parser/oracle/catalogue/handlers.py`

### "Eliferate"/"Imodane" saved decks made fully playable

- **What:** User-directed follow-up ("no deferrals"): closed Eliferate's remaining 27 cards and brought "Imodane" (69 unique cards, from-scratch) to full coverage.
- **Files:** `game/ability_catalogue.py`

### The seven "cEDH"-named saved decks/cubes (MEC-12)

- **What:** A 700+-unique-card pool across Ojer cEDH, cEDH Rocco, [cEDH] Glarb Bloomsday, cEDH staples, cEDH staples 2, cEDH M-K and cEDH Kinnan, worked across ten passes (…
- **What:** Made the highest-frequency shared staples across all seven cEDH-named saved decks/cubes (393 unique cards combined) playable, tracked as ordinary open work acro…
- **Files:** `game/ability_catalogue.py`, `parser/oracle/segmenter.py`
- **What:** Closed 436/764 unique cards across the seven cEDH-named saved decks/cubes (`MEC-12`), prioritizing highest deck-frequency cards.
- **What:** Closed 451/764 across the pool by working the unclaimed-clause list end to end rather than by frequency; landed several general primitives reused far past this…
- **What:** Closed six cards (Meltdown, Chord of Calling, Green Sun's Zenith, Finale of Devastation, Wishclaw Talisman, Ghostfire Slice), each landing a reusable primitive.
- **What:** Closed Mox Diamond, Mindbreak Trap, Eye of Ugin, Stonehewer Giant/Quest for the Holy Relic, Tainted Pact, and Transmute Artifact — all six previously-deferred g…
- **What:** Prioritized shapes generalizing well past the pool: the untap-cap family, Meekstone, RULE 115.4 change-target's first oracle-text handler, a power-qualified con…
- **What:** Closed Back to Basics, Auriok Salvagers, and Assassin's Trophy via three tightly-scoped, individually reusable primitives.
- **What:** Closed Slip Out the Back and Snapback/Pyrokinesis; investigated (but didn't build) Grafdigger's Cage/Weathered Runestone's zone-cast-restriction pair, finding i…
- **What:** Closed the fourth pass's own "broader gaps, needs real design" list in one sitting — devotion (RULE 700.6), phasing an opponent's permanent as a spell effect, R…

### Marchesa V4.2 (saved deck, fully playable) (Deck/Cube Playability Batches)

- **What:** Closed all 21 `UNMODELED` cards of the 96-card Marchesa V4.2 saved deck via seven general parser handlers plus seven hand-authored entries.
- **Files:** `parser/oracle/catalogue/handlers.py`, `game/ability_catalogue.py`, `game/effects/core.py`

### Vivi B4 (saved deck, fully playable) (Deck/Cube Playability Batches)

- **What:** Closed all 18 `UNMODELED` cards of the 99-card Vivi B4 storm-shell Commander deck (11 via general parser handlers, 7 hand-authored), several of the biggest sing…
- **Files:** `game/rules/search_mixin.py`, `parser/oracle/segmenter.py`, `game/effects/core.py`, `game/ability_catalogue.py`

### Blight Curse — Lorwyn Eclipsed (saved deck, fully playable) (Deck/Cube Playability Batches)

- **What:** Closed all 33 `UNMODELED` cards of the −1/−1-counters / wither / persist Commander deck (commander Auntie Ool, Cursewretch), 2026-09-07.
- **Files:** `game/ability_catalogue/entries_017.py` (per-card), `parser/oracle/catalogue/{handlers,subgrammars}.py`, `parser/oracle/segmenter.py`, `parser/oracle/spec.py`, `parser/oracle/gate.py`, `game/effects/core.py`, `game/continuous.py`, `game/targeting.py`, `game/binding/core.py`, `game/costs.py`, `game/static_conditions.py`, `game/engine/{activation,legal_actions,turn_loop}_mixin.py`, `game/rules/{triggers,damage_death,mana_counters,misc}_mixin.py`, `game/rules_engine.py`, `models/game_state.py`.

### Secrets of Strixhaven Commander decks (PAR-60, complete — 433/433) (Deck/Cube Playability Batches)

- **What:** Deck-first playability push for the five *Secrets of Strixhaven*
- **Files:** `game/ability_catalogue/entries_{018,019}.py`,

### Kinnan/M-K Batch: New General Primitives (MEC-12)

- **What:** Completed `cEDH Kinnan` (100/100) and `cEDH M-K` (97/97), 31 unique cards, entirely hand-authored.
- **Files:** `game/ability_catalogue.py` (per-card detail), various `game/` modules per primitive below.
- **What:** A cluster of smaller reusable additions from the same batch: `ReturnToLibraryThenDigSharedTypeEffect` (dig for a card sharing a bounced permanent's own printed…

### "Return it to the battlefield under its owner's/your control" — direct oracle-text route (PARSER_VERSION 184)

- **What:** `ReturnSelfToBattlefieldEffect` (built above for the delayed-trigger shape only — Nezahal's own "exile ~, return it tapped … at the beginning of the next end st…
- **Files:** `game/effects/core.py`, `parser/oracle/catalogue/handlers.py`. `tests/test_par30_return_self_to_battlefield.py`.

### Ojer cEDH Batch: New General Primitives (MEC-12)

- **What:** Closed 26/28 previously-unmodeled cards (49/77 -> 75/77) in `Ojer cEDH`, mostly via new general parser/engine primitives (each below) plus hand-authored singlet…
- **Files:** `game/ability_catalogue.py`.

### Rocco Batch: Cast-Intervening-If and Cast-Zone Prohibition (MEC-12)

- **What:** Closed 4 cards in `cEDH Rocco` (74/98 -> 78/98).
- **Files:** `game/rules_engine.py`, `models/game_object.py`, `game/effects/core.py`, `game/continuous.py`, `game/engine/casting_mixin.py`, `parser/oracle/segmenter.py`.

### Glarb Bloomsday Batch: New General Primitives (MEC-12)

- **What:** Closed 6 cards in `[cEDH] Glarb Bloomsday` (82/100 -> 88/100).
- **Files:** `game/ability_catalogue.py`, `game/effects/core.py`, `game/continuous.py`, `game/rules_engine.py` (lands module), `parser/oracle/catalogue/subgrammars.py`.

### "Enter as a copy, except …" family widened (MEC-12)

- **What:** `EnterAsCopyReplacement`/`Card.as_copy` gained four new "except" clause params, closing four `cEDH staples 2` cards at once: `only_types` (RULE 706.2's copiable…
- **Files:** `models/card.py`, `models/mana_cost.py`, `game/effects/core.py`, `game/copy_mechanics.py`, `game/continuous.py`, `game/binding/core.py`, `game/rules/casting_mixin.py`, `game/rules/sba_mixin.py`, `game/ability_catalogue.py`.

### Plain "exile, then return" blink template + trigger-level "up to one" fix (MEC-12)

- **What:** `BlinkEffect`/`RulesEngine.blink` (RULE 400.7, already shipped for Ephemerate/Restoration Angel) had no oracle-text recognizer for the *plain* template — no sub…
- **Files:** `game/effects/core.py`, `models/game_object.py`, `game/rules/triggers_mixin.py`, `parser/oracle/catalogue/handlers.py`, `parser/oracle/normalize.py`, `parser/oracle/gate.py` (PARSER_VERSION), `game/ability_catalogue.py`.

### Aven Mindcensor's search narrowing + a second "up to one" decline fix (MEC-12)

- **What:** RULE 701.19a-adjacent "If an opponent would search a library, that player searches the top N cards of that library instead." (Aven Mindcensor) — a *narrowing* s…
- **Files:** `game/effects/core.py`, `game/rules/search_mixin.py`, `game/ability_catalogue.py`.

### Pithing Needle / Phyrexian Revoker's free-text naming lock (MEC-12)

- **What:** RULE 601.2b's "as ~ enters, choose a card name" — but naming any Magic card rather than picking a creature type/colour/mode from an enumerable list, so it neede…
- **Files:** `game/effects/core.py` (`ChooseCardNameReplacement`, `_SELECTOR_KEYS`'s new `card_name_from_source` entry, the `"choose_card_name_on_enter"` factory), `game/continuous.py` (`group_selector_objects`'s new filter), `game/binding/core.py` (routes the new replacement onto `enter_choice_effects`), `game/rules/casting_mixin.py` (`_offer_enter_choices`/`resolve_enter_choice`'s new `choose_card_name` branch), `game/engine/turn_loop_mixin.py` (dispatch), `models/game_object.py` (`chosen_card_name`, RULE 400.7 reset), `game/ability_catalogue.py`.

### Defense Grid / Suppression Field / Tithe Taker's "costs {N} more" tax family (MEC-12)

- **What:** RULE 601.2f/602's cost-*increase* side of the existing `cost_reduction` static, on both a spell's cast cost and an activated ability's own activation cost.
- **Files:** `game/effects/core.py` (`cost_reduction` factory's three new params), `game/continuous.py` (`cost_reduction_for`'s new `active_if`/`except_caster_own_turn` checks, `activation_cost_reduction_for`'s widened scope/tax/carve-out), `game/engine/activation_mixin.py` (`_reduced_activation_mana`'s increase branch, `is_mana_ability` on `_can_pay_activation_cost`/`_pay_activation_cost`), `game/engine/mana_mixin.py` (`tap_for_mana` passing `is_mana_ability=True`), `game/engine/misc_mixin.py`, `game/engine/legal_actions_mixin.py` (both existence-only mana-ability probes), `game/ability_catalogue.py`.

### Solitude / Parallax Wave / Skyclave Apparition — the O-Ring/exile family's remaining shapes (MEC-12)

- **What:** Three more single-target/leaves-battlefield exile shapes, each needing one small, genuinely reusable addition to the existing O-Ring family (`ExileEffect(rememb…
- **Files:** `game/effects/core.py` (`GainLifeEffect.recipient`, `ReturnAllExiledWithEffect`, `CreateTokenForLinkedExileEffect`, `ExileEffect.max_mana_value`), `game/ability_catalogue.py`.

### Soul Partition's owner-held, opponent-taxed exile permission (MEC-12)

- **What:** "Exile target nonland permanent.
- **Files:** `game/effects/core.py` (`ExileEffect.grant_owner_play_permission`/`owner_play_permission_tax`, the `"cost_reduction"` factory's new `except_same_controller_as`), `game/continuous.py` (`self_cost_reduction_for`'s new `caster_id` param), `game/engine/casting_mixin.py` (`_adjust_cost` threading `player.id` through), `game/engine/legal_actions_mixin.py` (the `_has_conditional_exile_permission` fix), `game/ability_catalogue.py`.

### Abdel Adrian, Gorion's Ward's "exile any number you control" selection (MEC-12)

- **What:** "When Abdel Adrian enters, exile any number of other nonland permanents you control until Abdel Adrian leaves the battlefield.
- **Files:** `game/effects/core.py` (`ExileAnyNumberYouControlEffect`, `CreateTokenEffect.apply`'s `source` passthrough), `game/continuous.py` (`count_selector`'s new `exiled_with_count` kind), `game/rules/misc_mixin.py` (`request_choose_objects`'s new `track_exiled_with` param, threaded through its three helper methods), `game/ability_catalogue.py`.

### Dark Confidant's non-draw "reveal, take, lose life" upkeep trigger (MEC-12)

- **What:** "At the beginning of your upkeep, reveal the top card of your library and put that card into your hand.
- **Files:** `game/effects/core.py` (`RevealTopThenTakeAndLoseLifeEffect`), `game/ability_catalogue.py`.

### The land-animate family — Kamahl, Heart of Krosa and Ashaya, Soul of the Wild (MEC-12)

- **What:** Two cards making a permanent's card type cross the land/creature line in opposite directions — neither reachable by the oracle-text parser (both fully hand-auth…
- **Files:** `models/game_object.py` (`is_land` fix), `game/continuous.py` (`affected_objects`'s new `nontoken_creatures_you_control` scope), `game/ability_catalogue.py`.

### Yawgmoth's Will's graveyard-wide play permission and exile-redirect (MEC-12)

- **What:** "Until end of turn, you may play lands and cast spells from your graveyard.
- **Files:** `models/player.py` (`graveyard_play_permission_until_turn`, `graveyard_redirect_to_exile_until_turn`), `game/effects/core.py` (`GraveyardPlayPermissionThisTurnEffect`, `GraveyardRedirectToExileEffect`, their registry entries), `game/graveyard_cast.py` (`has_temporary_graveyard_play_permission`), `game/engine/lands_mixin.py` (`can_play_land`'s new branch, `_graveyard_cast_permission`'s widened check), `game/engine/legal_actions_mixin.py` (graveyard-zone land offer), `game/rules/damage_death_mixin.py` (`_move_to_graveyard`'s new player-scoped redirect check), `game/ability_catalogue.py`.

### Protean Hulk's total-mana-value-budgeted search (MEC-12)

- **What:** "When this creature dies, search your library for any number of creature cards with total mana value 6 or less, put them onto the battlefield, then shuffle." Ne…
- **Files:** `game/effects/core.py` (`SearchLibraryEffect.total_mana_value_budget`, its registry factory, `GameContext.request_search`'s widened proxy), `game/rules/search_mixin.py` (`request_search`/`_search_choice`/`resolve_search_choice`'s threaded budget), `game/ability_catalogue.py`.

### Helm of the Host, Twinflame and Heat Shimmer — the copy-a-creature family (MEC-12)

- **What:** Three "create a token that's a copy of [equipped/target] creature, except …" cards, closing the whole cluster BACKLOG.md had named but not individually diagnose…
- **Files:** `game/effects/core.py` (`CopyPermanentEffect.target_count`/`target_count_max`/`target_optional`, `ExileSpecificEffect`, its registry factory), `game/ability_catalogue.py`.

### Necrotic Ooze's "all graveyards" ability-borrowing source (MEC-12)

- **What:** "As long as this creature is on the battlefield, it has all activated abilities of all creature cards in all graveyards." The third `source_mode` for `grant_bor…
- **Files:** `game/continuous.py` (`_apply_borrowed_activated_abilities`'s new `"all_graveyards"` `source_mode` branch), `game/ability_catalogue.py`.

### MEC-32: the draw-replacement family's event granularity

- **What:** Alms Collector ("If an opponent would draw two or more cards, instead you and that player each draw a card."), Notion Thief and Chains of Mephistopheles (both "…
- **Files:** `models/events.py` (`EventType.DRAW_INSTRUCTION`), `models/game_state.py` (`GameState.first_draw_done_this_step`), `game/engine/turn_loop_mixin.py` (`_run_step`'s per-draw-step reset), `game/rules/draw_discard_mixin.py` (`draw`/`_single_draw` restructure), `game/effects/core.py` (`_split_multi_draw_replacement`, `_steal_non_first_draw_replacement`, `_discard_instead_of_non_first_draw_replacement`, their `ReplacementRegistry` entries), `game/ability_catalogue.py` (Alms Collector, Notion Thief, Chains of Mephistopheles).

### MEC-34: Animate Dead — RULE 303.4f's "Enchant creature card in a graveyard" reanimator Aura

- **What:** Animate Dead's own target isn't a permanent at all (RULE 303.4f's special case for the handful of Auras that enchant a graveyard *card*), so `RulesEngine._resol…
- **Files:** `models/game_object.py` (`GameObject.reanimate_target_id`), `game/rules/casting_mixin.py` (`_resolve_permanent_spell`'s graveyard-target bypass), `game/targeting.py` (`legal_targets`'s graveyard-quality "enchant" branch), `game/effects/core.py` (`ReturnFromGraveyardEffect`'s `target_kind="self_enchant_target"`, `SacrificeAttachedPermanentEffect`, its `EffectRegistry` entry), `game/ability_catalogue.py` (Animate Dead).

### MEC-36: Damping Sphere — mana-type override by amount + per-caster storm tax

- **What:** "If a land is tapped for two or more mana, it produces {C} instead of any other type and amount.
- **Files:** `game/continuous.py` (`mana_type_override_for`, `count_selector`'s `"spells_cast_this_turn"` key, `_NON_RULE_613_LAYERS`), `game/effects/core.py` (the `"mana_type_override"` `EffectRegistry` factory), `game/engine/mana_mixin.py` (`tap_for_mana`'s override consult), `models/game_state.py` (`spells_cast_this_turn`'s widened docstring), `game/engine/turn_loop_mixin.py` (`begin_turn`'s widened reset), `game/ability_catalogue.py` (Damping Sphere).

### MEC-37: Doomsday — no new search primitive, but two real engine bugs

- **What:** The original ticket framing ("exile up to five cards in a pile") described a mechanic Doomsday doesn't actually have — its real printed text is "Search your lib…
- **Files:** `game/effects/core.py` (`LoseLifeEffect.amount_from_half_own_life`, `_apply_effects_partitioned`'s `stack_item` param + `bool` return), `game/rules/casting_mixin.py` (`_apply_stack_item`/`_finish_spell_routing` split, `resume_deferred_effects`'s stack-item-aware resumption), `game/rules/search_mixin.py` (`exile_rest`'s chosen-card exclusion), `game/ability_catalogue.py` (Doomsday).

### MEC-38: Necropotence's three-clause engine

- **What:** "Skip your draw step.
- **Files:** `game/continuous.py` (`skipped_steps_for`, `_NON_RULE_613_LAYERS`), `game/effects/core.py` (`"skip_step"` `EffectRegistry` factory, `ExileEffect.target_kind="trigger_subject"`, `ExileTopOfLibraryEffect`, `CreateDelayedTriggerEffect`'s `exiled_object` capture, `"return_uncast_exiled"` `EffectRegistry` factory), `game/rules/misc_mixin.py` (`should_skip_step`'s new check), `models/events.py` (`EventType.DISCARD_CARD`), `game/rules/draw_discard_mixin.py` (`discard`/`discard_specific`'s new per-card firing), `game/rules/casting_mixin.py` (RULE 614.12's own discard site), `game/binding/core.py` (`_GROUP_CONTROLLER_EVENT_KEYS`'s `DISCARD_CARD` entry), `game/ability_catalogue.py` (Necropotence).

### MEC-39: Opposition Agent — search-result redirect, not a real control exchange

- **What:** "You control your opponents while they're searching their libraries.
- **Files:** `game/continuous.py` (`search_redirect_controller_for`, `_NON_RULE_613_LAYERS`), `game/effects/core.py` (`"search_redirect"` `EffectRegistry` factory), `game/rules/search_mixin.py` (`_finish_search`'s redirect consult + permission grant), `game/ability_catalogue.py` (Opposition Agent).

### MEC-35: Leonin Arbiter — a widened prohibition and a genuine RULE 116.2a special action

- **What:** "Players can't search libraries.
- **Files:** `game/effects/core.py` (`GrantSearchProhibitedEffect.scope`), `game/rules/search_mixin.py` (`is_search_prohibited_for`, `_has_search_exemption`, the widened prohibition guard), `game/engine/misc_mixin.py` (`pay_search_exemption`/`pay_search_exemption_actions`), `game/engine/legal_actions_mixin.py` (offering the new action), `models/game_state.py` (`search_exempt_until_turn`), `services/game_session.py` (the new action's dispatch entry), `game/ability_catalogue.py` (Leonin Arbiter).

### MEC-31: Spree (RULE 702.172a) and Escalate (RULE 702.120) — two "choose one or more" cost shapes, one selection primitive

- **What:** Neither keyword did anything before this ticket — both are variants of RULE 700.2's "choose one or more" modal shape (already fully built: `AbilitySpec.modes["a…
- **Files:** `parser/oracle/catalogue/modal.py` (`SPREE_HEADER_RE`/`SPREE_MODE_LINE_RE`/`split_spree_block`), `parser/oracle/gate.py` (`_process_spree_block`, dispatch loop, `PARSER_VERSION` 94), `parser/oracle/spec.py` (`mode_costs` validation + `to_dict`/`from_dict`), `game/binding/core.py` (`_build_mode_entries`'s `"cost"` key), `game/engine/casting_mixin.py` (`_escalate_cost`, `_modal_extra_cost`, `mode` threaded through `can_cast`/`effective_cast_cost`/`_auto_tap_for_cast_if_needed`/`_cast_current_face`), `game/engine/legal_actions_mixin.py` (`_cast_action`'s per-combination cost/lock, `_modal_cast_actions` docstring), `game/ability_catalogue.py` (Return the Favor).

### MEC-33: Omen Machine — an existing draw cap at zero, plus a genuine "each player's step, that player" tail

- **What:** "Players can't draw cards.
- **Files:** `game/effects/core.py` (`ExileTopOfLibraryEffect.player_selector`, `LandOrFreeCastEffect`, the `"exile_top_of_library"`/new `"land_or_free_cast"` `EffectRegistry` factories, `targeting` imports widened), `game/ability_catalogue.py` (Omen Machine).

### MEC-44: Necromancy — RULE 303.4f's non-Aura reanimator, and how much smaller its "real blocker" turned out to be

- **What:** "You may cast this spell as though it had flash.
- **Files:** `models/game_object.py` (`cast_outside_sorcery_speed`), `game/engine/casting_mixin.py` (the stamp in `_cast_current_face`), `parser/oracle/spec.py` (`ALLOWED_CAST_CONDITION_KEYS`'s `"unconditional"`, `_ALLOWED_CONDITION_KEYS`'s `"cast_outside_sorcery_speed"`), `game/condition_query.py` (`conditional_flash_holds`'s new branch), `game/effects/core.py` (`ConditionalEffect._condition_holds`'s new branch, `BecomeAuraEffect`, the `"become_aura"` `EffectRegistry` factory), `game/ability_catalogue.py` (Necromancy).

### MEC-40 batch 1: six small cards closed via three general primitives (`cEDH Rocco`/`cEDH staples`/`cEDH staples 2`)

- **What:** The first pass at `cEDH Rocco`'s own residue (MEC-40), sized against the live cache with `author_card.py`/`engine_bench.py` before writing anything — every one…
- **Files:** `parser/oracle/catalogue/handlers.py` (`_destroy_mv`'s widened kinds tuple, `_MASS_DESTROY_NOUNS`/`_MASS_DESTROY_NOUNS_SINGULAR`'s new "nonland permanent(s)" entries), `game/effects/core.py` (`GameContext.permanents_destroyed_this_way` + its `_apply_effects_partitioned`/`resume_deferred_effects` threading, `GameContext.destroy`'s bookkeeping, `AddManaEffect.any_color_choices`/`any_amount_from_context`, `ConditionalEffect`'s new `cards_in_graveyard_at_least` branch, `MarkCantBeCounteredEffect.target_kind`), `parser/oracle/spec.py` (`_ALLOWED_CONDITION_KEYS`'s new key), `game/targeting.py` (`"creature_source_is_blocking"` kind + its `ALLOWED_TARGET_KINDS`/label entries), `game/rules/casting_mixin.py` (`resume_deferred_effects`'s threading), `game/ability_catalogue.py` (Culling Ritual, Cabal Ritual, Ranger-Captain of Eos, Vexing Shusher, Tinder Wall — Abrupt Decay needed no catalogue entry, the parser fix alone closes it).

### MEC-40: `cEDH Rocco` done to completion — the remaining 18 gaps, no deferrals

- **What:** The second, no-deferral pass at MEC-40 — every one of `cEDH Rocco`'s remaining 18 gap cards (Academy Rector, Ajani Nacatl Pariah/Avenger, Allosaurus Shepherd, D…
- **Files:** `game/costs.py` (`exile_creature`, `saddle_power`, their `is_free`/`label()` entries, `_EXILE_CREATURE_RE`), `game/mana_abilities.py` (`_EXILED_CREATURE_MV_ADD_RE` dispatch), `parser/oracle/segmenter.py` (`_COST_LOOKS_REAL` widened), `parser/oracle/gate.py` (`PARSER_VERSION` → 95), `game/engine/mana_mixin.py` (`tap_for_mana`'s exile-creature amount override), `game/engine/activation_mixin.py` (`_exile_creature_candidate`, `saddle_power` cost payment, the `cost_restriction` checks in `_can_pay_activation_cost`), `game/engine/casting_mixin.py` (the `cost_restriction` check in `_can_pay_additional_cast_cost`), `game/engine/lands_mixin.py` (`_self_graveyard_or_exile_cast_permission`), `game/binding/core.py` (`_saddle_activated_ability`, `requires_saddled` trigger condition), `game/effects/core.py` (`SelfGraveyardOrExileCastPermissionEffect`, `BecomeSaddledEffect`, `SylvanLibraryEffect`, `TriggerDoublerEffect.cause_filter`/`cause_type_filter`, `GrantCantBeCounteredEffect.color`, `TopLibraryPermissionEffect.creature_only`/`subtypes`, `CopyPermanentEffect.set_power`/`set_toughness`/`extra_temp_keywords`, `MarkCantBeCounteredEffect`'s bug fix, the new `entering_object_unique_name`/`cost_exiled_creature_mv_plus_one`-adjacent condition branch, `cost_restriction` static registration), `game/continuous.py` (`cost_restricted`, `trigger_suppressed_for`, `trigger_doubler_bonus`'s `event` param, `has_standing_flash_permission`'s `type_filter`), `game/top_library.py` (`_grant_permits_cast`'s new filters), `game/engine/combat_mixin.py` (`contributor_power_gt_base` event field), `game/rules/draw_discard_mixin.py` (`cards_drawn_this_turn_ids`), `game/engine/turn_loop_mixin.py` (its reset, the new pending-choice dispatch), `game/rules/misc_mixin.py` (`request_pay_life_or_return_to_library`/`resolve_pay_life_or_return_choice`), `models/game_object.py` (`last_cost_exiled_object_mv`, `saddled_until_turn`), `models/game_state.py` (`cards_drawn_this_turn_ids`), `models/card.py` (`as_copy`'s `set_power`/`set_toughness`), `game/rules/copies_mixin.py` (`copy_permanent`'s new params), `parser/oracle/spec.py` (`entering_object_unique_name` in `_ALLOWED_CONDITION_KEYS`), `game/ability_catalogue.py` (all 18 cards).

### MEC-41: `[cEDH] Glarb Bloomsday` done to completion — the remaining 8 gaps, no deferrals

- **What:** All 8 of `[cEDH] Glarb Bloomsday`'s remaining gap cards (Ad
- **Files:** `models/game_object.py` (`colors_spent_to_cast`, `temp_cant_

### MEC-42: `cEDH staples` done to completion — all 12 named gaps

- **What:** Ashling, the Limitless; Dauthi Voidwalker; Derevi, Empyrial
- **Files:** `game/engine/casting_mixin.py` (`_evoke_cost`, the `evoke`/

### MEC-65: Exile-cost Evoke (RULE 702.74) — modern Incarnation cycle

- **What:** Solitude, Endurance, Fury, Subtlety, and Grief now parse their
- **Files:** `parser/oracle/catalogue/keywords.py`,

### MEC-43: `cEDH staples 2` — first batch, 9 near-free reuses

- **What:** Contamination, Leveler, Natural Order, Magda Brazen Outlaw,
- **Files:** `game/engine/activation_mixin.py` (`_matches_sacrifice_type`'s

### MEC-43: `cEDH staples 2` — second batch, two shared-primitive clusters (+ MEC-45)

- **What:** Gaddock Teeg, Sanctum Prelate, Chalice of the Void, Ethersworn
- **Files:** `game/continuous.py` (`cast_prohibited`'s `max_mana_value`/

### MEC-43: `cEDH staples 2` — third batch, 22 "near-free reuses"

### MEC-43: round 2, 17 more near-free reuses (`cEDH staples 2`/`K'rrik cEDH`)

### MEC-43: round 3, `SearchLibraryEffect` widenings (`cEDH staples 2`/`K'rrik cEDH`)

### MEC-43: round 3, "small, self-contained" (Vilis Broker of Blood, Volatile Stormdrake)

### MEC-43: round 4 — the last two decks closed (`cEDH staples 2`, `K'rrik cEDH`)

### MEC-40/41/42/43 coverage note

## Player Assets & Identity

### Favorite decks + multiplayer default settings (PLR-13)

- **What:** A third `player_assets.py` table, `favorite_decks` (same player-name-keyed shape as sleeves/token art, since decks aren't owned by a player in this app's one sh…
- **Files:** `services/player_assets.py`, `api/player_assets.py`

## Database Maintenance

### Ban-List Live Sync (DB-2)

- **What:** `scripts/update_ban_lists.py` re-derives the live "banned" set for a format from `RawCardStore.iter_raw()`'s already-cached Scryfall `legalities` data, diffs it…
- **Files:** `backend/mtg_analyzer/scripts/update_ban_lists.py`, `services/commander_legality.py`, `services/raw_card_store.py`.
- **Why:** Reads the source with `ast` rather than importing the module, so it has no dependency on the rest of `mtg_analyzer` being importable; `BANNED_COMMANDER_CARDS` s…

### Stale Pre-`mana_cost_string` Cache Audit (DB-1)

- **What:** Closed as structurally impossible rather than by a code change — `services/schema_version.py`'s `_clear_on_schema_change` wipes the entire card cache on any `mo…
- **Files:** `backend/mtg_analyzer/services/schema_version.py`, `models/card.py`.

### Commander-Legal Coverage Measurement

- **What:** Nothing previously scoped `coverage_report.py`'s coverage measurement to just the Commander-legal pool — it always ran over the whole ~35k-card cache, which inc…
- **Files:** `services/coverage_db.py`, `scripts/coverage_report.py`.

## Deck Analysis

### Dynamic (simulated) deck analysis (ANA-4)

- **What:** New `services/dynamic_analysis.py`: runs N solo goldfish matches headlessly against a `Bot`, aggregating turn-by-turn stats (lands drawn, mana potential, card a…
- **Files:** `services/dynamic_analysis.py`, `api/dynamic_analysis.py`

### Bot-driven goldfish match loop via `advance_to_decision` (ANA-4)

- **What:** `Bot` had only ever driven a multiplayer seat (interactive priority on); a goldfish session runs with that off, so the bot's "nothing to do" fallback (`pass_pri…
- **Files:** `services/dynamic_analysis.py`

### Infinite-mana guard for simulated matches (ANA-4)

- **What:** A `GreedyBot` against a real infinite-mana combo would tap forever without the turn ending.
- **Files:** `services/dynamic_analysis.py`

### Simulated matches keep no undo history (ENG-39)

- **What:** `GameSession` gained `keep_history=False`; `dynamic_analysis.
- **Files:** `services/game_session.py` (`_keep_history`, `_snapshot`),

### Bounded worker pool for background analysis jobs (ANA-4 follow-up)

- **What:** Each analysis job originally got its own bare `threading.Thread`, risking an unbounded burst of CPU-bound threads.
- **Files:** `services/dynamic_analysis.py`, `mtg_analyzer/config.py`

### Survivorship-bias fix in dynamic analysis (ANA-4 follow-up)

- **What:** The dummy opponent shared the real player's starting life, so a `GreedyBot` killed it within a handful of turns for any aggressive deck — later turns' means wer…
- **Files:** `services/dynamic_analysis.py`, `services/game_session.py`

## Auth & Persistence

### Deck persistence (save/load)

- **What:** `models/deck.py`'s `Deck` (server-generated UUID identity, name is just a label) and `services/deck_database.py`'s `DeckDatabase` (SQLite, same JSON-blob-per-ro…
- **Files:** `models/deck.py`, `services/deck_database.py`, `api/saved_decks.py`

### Cached color identity / commanders on a saved deck

- **What:** `color_identity`/`commanders` are computed once (needs resolved `Card` data, too costly per list render) and persisted, filled in lazily on first GET and reset…
- **Files:** `services/deck_validation.py` (`compute_deck_identity`), `api/saved_decks.py`

### `Deck.is_cube` flag

- **What:** Marks a saved decklist as a curated card pool rather than a legal Commander deck; parser and legality validation both gained an `is_cube` param that skips struc…
- **Files:** `parser/deckliste_parser.py`, `services/deck_validation.py`, `api/saved_decks.py`

### Repeatable modal modes (PAR-54, PARSER_VERSION 265)

- **What:** The Confluence header `Choose N.
- **Files:** `parser/oracle/catalogue/modal.py`, `parser/oracle/gate.py`, `parser/oracle/spec.py`, `game/binding/core.py`, `game/engine/legal_actions_mixin.py`, `game/engine/casting_mixin.py`, `game/rules/triggers_mixin.py`, `game/effects/core.py`, `tests/test_modal_choose_n.py`.

### Conditional modal headers (PAR-55 / MEC-66, PARSER_VERSION 266)

- **What:** `Choose N.
- **Files:** `parser/oracle/catalogue/modal.py`, `parser/oracle/gate.py`, `parser/oracle/spec.py`, `game/binding/core.py`, `game/effects/core.py`, `game/engine/casting_mixin.py`, `game/engine/legal_actions_mixin.py`, `game/rules/triggers_mixin.py`, `game/rules/misc_mixin.py`, `models/game_state.py`, `tests/test_modal_choose_n.py`.

### Compound tapped-entry colour choices (PAR-42, PARSER_VERSION 267)

- **What:** The "~ enters tapped.

### Compound non-creature removal filters (PARSER_VERSION 268)

- **What:** The existing Doom Blade / Go for the Throat parser row now

### Crib Swap (Dance of the Elements deck batch)

- **What:** Hand-authored the singleton removal spell rather than adding a

### Lamentation (Dance of the Elements deck batch)

- **What:** Hand-authored the singleton's ETB as one ordinary target choice

### Greenwarden of Murasa and Risen Reef (Dance of the Elements deck batch)

- **What:** Added two reusable resolution primitives.

### Muldrotha, the Gravetide (Dance of the Elements deck batch)

- **What:** Extended the standing graveyard-cast permission with Muldrotha's

### Distant Melody (Dance of the Elements deck batch)

- **What:** Reused the resolve-time creature-type choice and added the

### Bane of Progress, Yarok and Titan of Industry (Dance deck batch)

- **What:** Added the atomic artifact/enchantment wipe with an actual

### Foretell engine primitive

- **What:** Implemented RULE 702.143 end to end.

### MEC-71 — Dance: chosen-type graveyard return and Horde of Notions

- **What:** `ReturnChosenCreatureTypeFromGraveyardEffect` composes the

### MEC-72 — Dance: tribal reveal/dig and top-card ordering

- **What:** Two complementary library-manipulation primitives, both

### MEC-74 — Dance: tribal/count-sensitive ETB and landfall triggers

- **What:** Hand-authored the four remaining count-sensitive cards in the
- **Files:** `game/ability_catalogue/entries_016.py`, `game/effects/core.py`, and

### MEC-75 — Dance: temporary granted triggered abilities

- **What:** Hand-authored **Subterfuge**'s ETB as a pair of duration-bound
- **Files:** `game/ability_catalogue/entries_016.py` and

### MEC-64 — Suspend hand-zone special action

- **What:** Implemented RULE 702.62a's first Suspend ability as the

### MEC-68 / PAR-57 — Exhausted triggered modes per turn

- **What:** Added the `choose N that hasn't been chosen this turn` modal

### MEC-67 — Teamwork optional additional cost

- **What:** Added the RULE 702.194 Teamwork cast variant.

### ENG-37 B3 — Attached Aura-token fusion retired

- **What:** Retired `create_attached_aura_token` by composing `create_token`

### ENG-37 B3 — Attachment-copy fusion retired; B3 complete

- **What:** Retired Stangg's `copy_attachments_onto_last_created` fusion.

### ENG-37 — Optional Equipment attachment fusion retired

- **What:** Retired Nahiri's `create_token_may_attach_equipment`.

### ENG-37 — Counter-total token fusion retired

- **What:** Retired Ferrafor's token-count fusion.

### ENG-37 — Conditional copy reclassified

- **What:** Reclassified `conditional_copy` as the atomic layer-1

### PAR-82 / PAR-106 — redundant parser-ticket audit (PARSER_VERSION 429)

- **What:** Retired two tickets whose stated shared parser work was already
