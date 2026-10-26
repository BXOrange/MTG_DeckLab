# Code map: where to look first

Task → entry point. Load when you do not know where a behaviour lives.

| Task | Start in |
| --- | --- |
| Playing a card during a resolving effect (RULE 608.2g) | `effects.GameContext.offer_play_during_resolution`, `GameEngine.play_resolution_card` / `resolution_play_actions`, and the matching `services/game_session.py` action/choice path; preserves targets, modes, announced optional life payments, paid/free graveyard casts and land-play limits without a turn-long grant |
| Combat / keywords | `game/combat.py`, `game/game_engine.py` (`_step_combat_damage`) |
| Static abilities / P/T / anthems | `game/continuous.py`, `models/game/game_object.py` |
| "As long as …" conditions on a static (RULE 613.6) | `game/static_conditions.py` — the project's **single state-predicate vocabulary**, read by statics' `active_if`, trigger intervening-ifs, `binding/core.py`'s replacement gate and (via `game/effect_conditions.py`) resolving effects; includes `opponent_was_dealt_damage_this_turn` (damage per opponent, distinct from life loss); plus `parser/oracle/catalogue/static_handlers.py` (`_STATIC_CONDITION_RES`, `_conditional_static_specs`) |
| "Until …" durations on a continuous effect (RULE 611) | `game/durations.py`, `GameState.floating_statics`, `effects.GrantUntilEffect` — note "until end of turn" stays on the `temp_*` path |
| How many targets a spell/ability wants (RULE 115.1/601.2c) | `game/targeting.py` (`TargetSpec.count`/`count_max`/`count_selector`, `effective_count`, `resolved_count`, `expand_counts`/`collapse_groups`) |
| "Another target land" / "another target land you control" | `game/targeting.py` (`other_land` / `other_land_you_control` exclude the source; ordinary land kinds include it), `parser/oracle/catalogue/subgrammars.py` (`OTHER_TARGET_KINDS`) |
| A clause naming what a previous clause targeted, created, or revealed | `effects.GameContext.previous_targets` / `created_objects` / `revealed_card` (all maintained by `_apply_effects_partitioned`; `revealed_card` is the `of: "revealed"` referent, set by `reveal_top`) |
| "It" / "that creature" under a group trigger ("whenever a creature you control enters …", RULE 603.1) | `game/effects/composition.py`'s `TriggerSubjectReferentEffect` (`trigger_subject_referent`: seeds `previous_targets`, runs a body *against* the firing object, `acting="controller"` for "its controller …", `event_key="remembered"` inside a payment's "if you do"); the parser reaches it from `parser/oracle/catalogue/handlers.py`'s `match_clause` (group fallbacks, tried only after every row written for the group subject), `parser/oracle/catalogue/referent_condition.py` (conditions on "it") and `segmenter._referent_characteristic_specs` / `_hoist_referent_seed`; a bare `it` read as the *source* under a group trigger is wrong-but-MODELED — see the PAR-123 lesson in `PARSER_LONG_TAIL.md` |
| Activated abilities / costs | `game/costs.py`, `game/game_engine.py` (`activate_ability`) |
| Card abilities / fetch lands / enters-tapped | `game/card_catalogue/` (one file per card), `game/card_registry/` (the `register`/`specs_for` mechanism), `binding/core.py `bind_from_catalogue`` |
| Hand-authoring a specific card's effects | `hand-author-card` skill, [docs/Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md](docs/Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md) |
| Effects / triggers | `game/effects/` (registry in `effects/registry.py`), `game/binding/core.py` |
| Which trigger conditions the parser recognizes | `parser/oracle/segmenter.py` (`_TRIGGER_VERBS` object subjects, `_PHASE_STEP_WORDS`, `_PLAYER_TRIGGER_CONDITIONS` "whenever **you** scry/surveil", `_VARIANT_TRIGGER_CONDITIONS`) |
| Face-down permanents (morph/disguise/manifest/cloak) | `game/face_down.py`, `models/game/game_object.py` (`turn_face_down`/`turn_face_up`), `game/game_engine.py` (`turn_face_up`, `face="face_down"`) |
| Dungeons + venturing | `models/game/dungeon.py`, `game/dungeons.py`, `services/dungeon_database.py`, `rules_engine.venture_into_the_dungeon` |
| Formats & casual variants (Planechase/Archenemy/Vanguard) | `models/game/game_format.py`, `game/variants.py`, `services/variant_card_database.py`, `game_engine.new_game(game_format=…)` |
| "Play/cast from top of library" permission | `game/top_library.py`, `game/game_engine.py` (`can_play_land`/`can_cast`/`legal_actions`), `gameBoardView.js` (`libraryTopHtml`) |
| Who an effect acts on / how much it measures (an operand naming a referent) | `backend/mtg_analyzer/game/effect_operands.py` (`{"of": …, "as": "controller"}`), `game/effect_amounts.py`; both resolve referents through `effect_conditions.subject_of` |
| Combining effects: branching, "you may", "for each", "…equal to" | `backend/mtg_analyzer/game/effects/composition.py` (`seq`/`if_else`/`optional`/`for_each`/`bind`), `game/effect_amounts.py` (what `bind` measures) |
| An "if `<predicate>`, `<effect>`" gate on a resolving effect (RULE 603.4/702.33b) | `backend/mtg_analyzer/game/effect_conditions.py` (referents + the `GameContext` predicates + the flat-key translator), `game/static_conditions.py` (every state predicate, shared with statics/triggers/replacements), `parser/oracle/segmenter.py`'s `_CONDITION_PREFIXES` |
| A player choice: opening one, answering one, adding a new kind | `backend/mtg_analyzer/game/continuations.py` (the handler registry), `RulesEngine.open_choice`/`resolve_choice` |
| What an effect type/engine method *is* (instruction/fusion/alias/…) | `backend/mtg_analyzer/game/isa.py`, `scripts/isa_report.py --registry` |
| Which operations the corpus actually uses, and their argument frames | `scripts/isa_report.py --corpus` (re-derives `13_` §5.6b from the ledger) |
| What a `TargetSpec.kind` decomposes into (types × scope × filters) | `game/targeting.py`'s `TARGET_FRAMES` |
| Mana abilities with “Activate only if …” (Mox Opal / Metalcraft) | `game/mana_abilities.py` parses the shared activation condition and gates production options; `engine/activation_mixin.py` rechecks it during cost validation, including mana abilities and auto-tap |
| On-disk paths / env-var config | `backend/mtg_analyzer/config.py` |
| Goldfish UI | `frontend/src/js/goldfishView.js` |
| UI styles | `frontend/src/styles/main.css` (ordered imports); area styles in the same directory, including `game-layout.css`, `battlefield.css`, `game-choices.css`, `replay.css`, `multiplayer.css` |
| UI translations | `frontend/src/js/locales/en.js` / `de.js` (catalog entry points); matching area catalogs under `locales/en/` and `locales/de/` |
| Engine integration tests | `backend/tests/game/engine/test_engine_*.py` (casting, attachments, commander, combat, ward, costs, state/effects, turns/mana); shared factories and setup in `engine_test_helpers.py` |
| Solo vs. bots (Multiplayer engine, no lobby) | `backend/mtg_analyzer/api/solo.py`, `frontend/src/js/soloView.js`; shared picker/mulligan/banner markup in `frontend/src/js/gameSetup.js` (also used by goldfish/multiplayer) |
| Multiplayer (lobby, seats, shared board) | `backend/mtg_analyzer/services/lobby.py`, `api/multiplayer.py`, `api/multiplayer_ws.py`, `frontend/src/js/multiplayerView.js`, `lobbySocket.js`, `bannerColors.js` (seat banner colours) |
| Bots filling a multiplayer seat (UC5) | `backend/mtg_analyzer/services/bots.py` (registry/driver, compatible class exports; individual policies in `services/bot_policies/`, deck planning in `services/bot_strategy.py`), `services/lobby.py` (`Seat.bot_kind`, `add_bot`), `frontend/src/js/multiplayerView.js` (`addBotHtml`/`seatRowHtml`) |
| Replay/Puzzle mode (build+save/load a board) | `backend/mtg_analyzer/services/replay.py`, `game_session.py` (`edit_*` actions), `frontend/src/js/replayView.js` |
| Archidekt deck import proxy | `backend/mtg_analyzer/services/archidekt_client.py`, `api/import_external.py` (Moxfield was tried and reverted twice — Cloudflare-blocked; don't re-add it without checking that's changed) |
| Refreshing the full Oracle card pool (new set) | `backend/scripts/update_card_pool.py` — re-downloads the Scryfall `oracle_cards` bulk dump, merges it into `RawCardStore`, reseeds the app cache, and prints a ban-list drift heads-up (`scripts/import_bulk.py` is first-load only; its default reuses an on-disk dump) |
| Commander Spellbook combo snapshot, lazy matching, and Bracket signals | `backend/mtg_analyzer/services/commander_spellbook_database.py`, `api/combos.py`, `frontend/src/js/analyzeView.js`, `deckAnalysis.js`; full data contract, DB lifecycle, matching limits, and the narrow infinite-combo heuristic in [docs/Reference/COMMANDER_SPELLBOOK.md](docs/Reference/COMMANDER_SPELLBOOK.md) |
| Applying a ban-list update | `backend/scripts/update_ban_lists.py` — rewrites a hand-maintained ban-list constant (`BAN_LIST_TARGETS`, just `services/commander_legality.py`'s `BANNED_COMMANDER_CARDS` today) straight from the raw store's live `legalities` data; no network of its own, run `update_card_pool.py` first. `--format <key>`/`--dry-run` |
| Player-uploaded token art / card-back sleeves | `backend/mtg_analyzer/services/player_assets.py`, `api/player_assets.py`, `frontend/src/js/profileView.js` (upload UI + player name), `gameBoardView.js` (`resolveImageUrl`/`setAssets`) |
| Default art for a vanilla ("1/1 white Soldier") token | `backend/mtg_analyzer/services/token_database.py` (`TokenArtLibrary`, keyed by exact name/power/toughness/colors — a token name is reprinted at multiple stat lines across sets), `data/token_art.json`, `scripts/build_token_art_library.py` (rebuild from a fresh Scryfall bulk dump); consumed by `synthesize_token_card` and `services/replay.py`'s `_token_card` |
| Engine coverage doc (user-facing) | `frontend/src/js/implementationStatusView.js` |
| Resuming a ticket someone (or a crashed session) was building | [docs/implementation-state/workingOn.md](docs/implementation-state/workingOn.md) — its block's *Next step*; update it as you go, delete the block on close |
| What's still open (any area) | [docs/implementation-state/BACKLOG.md](docs/implementation-state/BACKLOG.md) — tickets by category; parked/low-priority + non-goals in [DEFERRED.md](docs/implementation-state/DEFERRED.md) |
| Why shipped work looks the way it does | [Done_Backend.md](docs/implementation-state/Done_Backend.md) / [Done_Frontend.md](docs/implementation-state/Done_Frontend.md) |
| Parser-tail strategy, lessons, worked samples | [docs/implementation-state/PARSER_LONG_TAIL.md](docs/implementation-state/PARSER_LONG_TAIL.md) |
| Looking up a `RULE <n>` in the CR text | `docs/Reference/rules_wiki/` (rule#/term → source line; see its `README.md`) |
| Full docs/ map (requirements/concepts/Reference/implementation-state) | [docs/README.md](docs/README.md) |
| How to *use* the app (not build it) | [user-docs/](user-docs/) (English + German) |
