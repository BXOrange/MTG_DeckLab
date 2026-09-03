# Backend — Done

**Catalogue** (organized by game mechanic/feature, not by date): what has
shipped and *why it was built that way*, grouped under the same subsystem
names used throughout `CLAUDE.md` and `game/`'s own module layout. Open work
lives in [BACKLOG.md](BACKLOG.md); parser-tail strategy and worked examples
in [PARSER_LONG_TAIL.md](PARSER_LONG_TAIL.md). Remaining plan:
[10_COMPLETION_ROADMAP.md](10_COMPLETION_ROADMAP.md).

Entry headings are stable — a `Done_Backend.md "<entry or ticket>"` reference
from the code lands here (Ctrl+F/grep the exact phrase; a citation predating
this reorganization may point at a *topic* that now spans several entries in
the matching section below, rather than one paragraph — the ticket id or
deck/card name it names is still the thing to search for). Within each
section, closely-related tickets/passes that built the same feature over
time are kept as one entry with sub-bullets rather than scattered
chronologically, since the point of this file is "what exists and why,"
not "in what order it arrived" — `git log`/`git blame` remain authoritative
for history. A saved-deck/cube playability push that closed cards by
combining several *already-described* primitives gets one short entry in
"Deck/Cube Playability Batches" naming what closed and pointing at those
primitives, rather than repeating their detail.

Two categories intentionally hold very little: `HTTP API` and
`Configuration & Persistence` are the thin plumbing layers; the real depth
is in the rules-engine categories below them.

## Configuration & Persistence

### Configuration: centralized on-disk paths and runtime constants

- **What:** Consolidated previously hard-coded module constants (cache/data dirs, DB paths, Scryfall User-Agent/rate limit) into `mtg_analyzer/config.py`, overridable via `MTG_CACHE_DIR`/`MTG_DATA_DIR`/`MTG_USER_AGENT`/`MTG_SCRYFALL_MIN_REQUEST_INTERVAL` env vars, so a one-off script or test run can avoid colliding with a real dev server's cache/saved-decks.
- **Files:** `mtg_analyzer/config.py`, `api/dependencies.py`, `card_database.py`, `deck_database.py`, `player_assets.py`
- **Why:** Service modules keep their old constant names as backward-compatible aliases onto the new `config.py` values, so nothing importing them broke.

### Configuration: JSON config file + worker/concurrency knobs + log level

- **What:** Every `config.py` value now resolves `MTG_* env var > backend/mtg_analyzer/config.json > built-in default` (the file is `json.load`-ed once at import; missing/malformed → ignored with a `RuntimeWarning`, server still starts; `MTG_CONFIG_FILE` relocates it; `_`-prefixed keys are doc-only `_comment`s). The committed `config.json` ships with every knob written out. Added three concurrency knobs, each also a `setup/start.py` flag that passes the env var into the (single) uvicorn subprocess: `SERVER_THREAD_WORKERS` / `--server-threads` (default 40) resizes the AnyIO request-thread pool from `api/app.py`'s lifespan (`_apply_server_thread_workers`) — the ceiling on how many sync-`def` gameplay endpoints, i.e. games mid-step, run at once; `DYNAMIC_ANALYSIS_WORKERS` / `--analysis-jobs` (existing knob, now file-backed) caps concurrent analysis jobs; `DYNAMIC_ANALYSIS_MATCH_WORKERS` / `--analysis-match-workers` (default 0 = `os.cpu_count()`, 1 = off) makes `run_dynamic_analysis` fan one job's independent match simulations across a `ProcessPoolExecutor` for real GIL-bypassing speed-up (~3x on a 10-core box for an 8-match run), with a `_MIN_MATCHES_FOR_PROCESS_POOL` in-process fast path for small jobs and a fall-back to in-process if the pool can't start or every worker dies. Also added `LOG_LEVEL` / `MTG_LOG_LEVEL` / `logging.level` / `./start.sh --log <level>`: nothing configured logging before, so `mtg_analyzer.*` records fell through to `logging.lastResort` (WARNING+ only, never at the asked-for level). `create_app()` → `_configure_logging()` sets the `mtg_analyzer` parent logger to this level (default **WARNING** — engine/parser are chatty at INFO), leaving root at WARNING so app-DEBUG doesn't unmute third-party libs; `start.py` also hands the level to uvicorn as `--log-level` (whose own `info` default this project overrides to `warning`).
- **Files:** `mtg_analyzer/config.py`, `mtg_analyzer/config.json`, `api/app.py`, `services/dynamic_analysis.py`, `setup/start.py`, `tests/test_config_and_workers.py`
- **Why:** One uvicorn process is deliberate — the game-session manager, lobby and analysis job registry are in-memory process-wide singletons (`api/dependencies.py`), so `uvicorn --workers N` would break session affinity. Match simulations are self-contained and CPU-bound, so processes (not threads) are what actually parallelises an analysis; the shuffles happen up front off the process-global RNG so a pooled and an in-process run see the same set of games. `start.sh`/`start.bat` are pure arg-forwarders, so `--log` (and the worker flags) land there for free.

### Configuration: offline-safe startup

- **What:** Made `./start.sh` guaranteed connectionless: `setup/install.py` installs `pip --no-index [--find-links wheelhouse]` first (fast + offline-safe) and only falls back to an index-using run (gated on a 2s TCP probe rather than pip's own stall) when that fails; `--download-wheels` caches a full wheelhouse for a brand-new venv with no network.
- **Files:** `setup/install.py`, `setup/start.py`, `setup/wheels/`
- **Why:** An audit found the only network dependency in the whole startup path was an unconditional `pip install --upgrade pip` in the setup script, not the app itself (frontend/cache/data are all local).

### Data Layer: DecklisteParser

- **What:** Server-side decklist text parser ported line-for-line from the frontend's own parser (multiple qty formats, tag/set suffix stripping, structural Commander validation); also strips foil/star markers (`★`/`☆`) that otherwise break name resolution.
- **Files:** `mtg_analyzer/parser/deckliste_parser.py`, `frontend/src/js/parser.js`

### Validator: Commander legality checker

- **What:** Real Commander legality — color identity (union of all commanders' identity vs. every other card), a hand-maintained banned-card list, RULE 903.3 legendary-commander eligibility, and the full co-commander pairing family: plain Partner (pairs with any Partner card), "Partner with X" (pairs only with that named card via `partner_with`), Friends forever (RULE 702.123i-adjacent — pairs with any other Friends-forever card, same shape as plain Partner), and RULE 903.3d "Choose a Background" (pairs only with an actual Background enchantment, matched by type line since Background is a subtype rather than a keyword ability). Returns a `CommanderLegalityResult` (not a bare list) exposing `bannedCardNames`/`colorIdentityViolationNames` so the frontend can flag exact offending cards.
- **Files:** `mtg_analyzer/services/commander_legality.py`, `services/lazy_card_loader.py`, `services/card_database.py`
- **Why:** `color_identity` is read straight from Scryfall's precomputed field, so hybrid/Phyrexian/MDFC identity is correct for free. The legendary check (DB-3) reads `"legendary" in type_line` rather than trusting the separately-stored `Card.is_legendary` flag alone — real production `Card`s (`scryfall_client`/`token_database`) always keep the two in sync, but this repo's own hand-built test fixtures across ~40 files frequently don't bother setting the flag even when their `type_line` says "Legendary"; trusting the flag alone surfaced as a real regression (a multiplayer test fixture's "Test Commander" card hanging a websocket test) before this fallback was added, exactly the class of false negative `is_planeswalker`/`is_artifact`'s own type-line-derived pattern already avoids. A Background enchantment used alone or paired with anything other than a "Choose a Background" creature is still flagged non-legendary, since its RULE 903.3 eligibility only exists as half of that specific pair.
- **Bug fixed:** DFC/split-card decklist entries (front-face-only or full "Front // Back" name) failed to resolve because Scryfall's collection endpoint only matches a face name; `LazyCardLoader.load_cards`/`CardDatabase.get_card` now always query by front face and map the result back to whatever name was requested.

### Data Layer: GameState / Player / ManaPool models

- **What:** Core Phase-1 game models: `GameState` (battlefield/stack, turn/phase/step/priority pointers, an event bus `fire_event`/`subscribe`), `Player` (life, per-player zones, `ManaPool`, per-turn land counter, player-level effects), `ManaPool` (per-color tally + backtracking payment solver), `GameObject` (one instance of a `Card` in a zone with mutable state), and `GameEvent`/`EventType`.
- **Files:** `models/game_state.py`, `models/player.py`, `models/mana_pool.py`, `models/game_object.py`, `models/events.py`

### Data Layer: CardDatabase + Scryfall integration + LazyCardLoader

- **What:** SQLite card cache storing each card's `to_dict()` JSON so the schema stays in sync with `Card`; `ScryfallIntegration` batches lookups via Scryfall's `/cards/collection`; `LazyCardLoader` checks the DB first and only hits Scryfall on a miss, persisting what it fetches. Card images are a separate on-disk cache keyed by Scryfall id.
- **Files:** `services/card_database.py`, `services/scryfall_client.py`, `services/lazy_card_loader.py`, `services/image_cache.py`

### Data model / cache schema versioning

- **What:** Detects when a database's on-disk row format has drifted from the current model code: a SHA-256 over the source files defining each DB's stored format is stamped into a `schema_meta` table and compared on open. The disposable card cache clears itself on mismatch (re-fetchable from Scryfall); the irreplaceable deck store never wipes, just records the new hash and warns.
- **Files:** `services/schema_version.py`
- **Why:** Both SQLite DBs store `to_dict()` JSON blobs, so a model change silently strands old rows — the "Sol Ring cast for free" bug was exactly this class of problem.

## HTTP API

### HTTP API foundation: server framework

- **What:** Picked and set up FastAPI + uvicorn (`mtg_analyzer/api/app.py`) with CORS open to any localhost port for the static frontend dev server.
- **Files:** `mtg_analyzer/api/app.py`

### Decklist validation endpoint (POST /api/decks)

- **What:** Server-side decklist parse + structural validation mirroring the frontend's own parser request/response shape, with real Commander legality (color identity, ban list, Partner rules) appended via the `Validator` service; an unresolvable commander name skips the real checks and adds a warning instead of running against incomplete color identity.
- **Files:** `mtg_analyzer/api/decks.py`, `services/commander_legality.py`, `parser/deckliste_parser.py`

### Card lookup & image API

- **What:** `GET /api/cards` (list cached cards), `GET /api/cards/search?name=` (exact-name resolve via `LazyCardLoader`), `POST /api/cards/resolve` (bulk name resolution in one round trip for a whole decklist), and `GET /api/cards/{card_id}/image?size=` (serves/downloads card art into `backend/cache/images/`) so the frontend never calls Scryfall directly.
- **Files:** `mtg_analyzer/api/cards.py`, `api/images.py`, `services/image_cache.py`

### Deck persistence: save/load/delete/validate saved decks

- **What:** `POST /api/decks/save`, `GET /api/decks`, `GET /api/decks/{id}`, `DELETE /api/decks/{id}` persist a decklist distinct from the parse-only `POST /api/decks`; `GET /api/decks/{id}/validation` shares its Commander-legality logic via `services/deck_validation.py` (`validate_deck_sections`/`apply_legality`) so the three call sites can't drift, and `POST /api/game/goldfish` refuses (422) to start an illegal deck.
- **Files:** `mtg_analyzer/api/saved_decks.py`, `services/deck_database.py`, `services/deck_validation.py`

### WebSocket game session channel

- **What:** `WebSocket /ws/game/{game_id}` groups connections by game id and runs each client's `player_action` through the same `GameSession`/`GameSessionManager` the REST API uses, broadcasting `GameSession.view()` to every connection on that game id; an unknown id or illegal action replies only to the sender.
- **Files:** `mtg_analyzer/api/game_ws.py`, `api/dependencies.py`
- **Why:** Built as the future channel for pushing an opponent's moves in interactive multiplayer; solo goldfish play still uses REST directly and the channel wasn't wired to any frontend view yet at this point.

### Archidekt deck import proxy (Import — follow-up from the frontend)

- **What:** `GET /api/import/archidekt/{deckId}` fetches Archidekt's unauthenticated public deck JSON endpoint (confirmed not Cloudflare-blocked, unlike Moxfield which was tried and reverted twice) and converts it into decklist text sections (commander/mainboard/sideboard) matching what the save-deck endpoints expect.
- **Files:** `services/archidekt_client.py`, `api/import_external.py`

## Mana System

### Mana cost model: Hybrid and Phyrexian mana

- **What:** A real per-symbol mana cost model (`ManaCost.parse` → `ManaSymbol`s tagged generic/variable/color/colorless/hybrid/mono-hybrid/Phyrexian, exposing `payment_options()`) built on a new `Card.mana_cost_string` raw-cost field, since the existing `Card.mana_cost` dict only tracked a lossy per-symbol pip count. `ManaPool.can_pay`/`pay` solve payment including hybrid choice and Phyrexian life payment.
- **Files:** `models/mana_cost.py`, `models/mana_pool.py`, `services/scryfall_client.py`
- **Bug fixed:** `pay()` correctly computed the life cost of a Phyrexian pip but `RulesEngine.cast_spell` discarded the return value, so `{W/P}` never actually drained life (RULE 119.4). Fixed via a new shared `RulesEngine.lose_life(player, amount, cause=...)` choke point that every life-loss path (damage, cost, effect) now routes through.

### Mana cost model: self-healing stale cache rows

- **What:** `Card.has_mana_cost_data` flags a non-land row with a blank `mana_cost_string` as pre-dating that field (Scryfall always gives a real, even if `"{0}"`, cost string); `LazyCardLoader.load_cards` treats such a hit as a miss and refetches from Scryfall to heal the row in place, falling back to the stale copy (never "not found") if the refetch fails.
- **Files:** `models/card.py`, `services/lazy_card_loader.py`
- **Why:** Prevents a "Sol Ring cast for free" class of bug where a stale cached row missing `mana_cost_string` was read as free.

### Mana cost model: X-spell casting

- **What:** RULE 601.2b — `{X}` parses to a `VARIABLE` symbol worth 0 until announced; `ManaCost.has_variable`/`.with_x(x)` resolve every `{X}` in a cost, `GameEngine.can_cast`/`cast_spell` take an `x` argument, and `legal_actions` surfaces `has_x`/`max_x` (scanned down from the pool's total) so the UI prompts for a value.
- **Files:** `models/mana_cost.py`, `game/game_engine.py`, `game/rules_engine.py`

### Mana abilities on tap (RULE 605) — dual-land production choice

- **What:** A permanent's tap ability is modeled as a list of mutually-exclusive production options; `GameEngine.tap_for_mana` takes an `option_index` so a dual land makes one chosen color, not both, and `legal_actions` exposes the options per source.
- **Files:** `game/mana_abilities.py`, `game/game_engine.py`

### Mana-ability costs redone properly (RULE 605.1a/602.1)

- **What:** `tap_for_mana` previously only ever taxed the source's own tap; now charges a mana ability's full printed cost (mana pips, {T}/{Q}, life, sacrifice, `tap_others`, `add_counters_cost`) through a shared `_pay_activation_cost`. `mana_abilities.py` rewritten to parse each `<cost>: Add …` line independently rather than one whole-text regex, correctly excluding target-bearing lines (RULE 605.1a) and quoted grants onto other objects. Added variable ("for each") amounts, a mana ability's own side effect (`self_damage`, painlands), and a genuinely new effect shape for "untap this creature" with no RULE 115 target.
- **Files:** `game/mana_abilities.py`, `game/game_engine.py`, `game/costs.py`
- **Why:** `tap_others` deliberately became a real player choice rather than an engine auto-pick, since the printed cost has no "other" qualifier and Birchlore Rangers can legally tap itself as one of its own two Elves.

### "Add 1 mana of any color" resolve-time color choice

- **What:** A spell/ability's bare "Add 1 mana of any color." now opens a genuine `add_mana_any_color` `pending_choice` (W/U/B/R/G) at resolution instead of guessing a color, distinct from a permanent's own pre-declared mana-ability options. Defaults to White on a missing/invalid answer.
- **Files:** `game/effects.py`, `game/rules_engine.py`, `parser/oracle/catalogue/handlers.py`
- **Why:** Built as shared infrastructure for Deathrite Shaman rather than a coverage play — zero real cards were unlocked by this alone at ship time.

### Leveler-gated mana abilities (RULE 711.4c)

- **What:** A Leveler's own mana ability, printed inside a `LEVEL n-m` tier, now only applies while the object's level counter is in that tier's range — `ManaAbility` gained `min_level`/`max_level`, parsed by splitting a Leveler's raw oracle text into per-tier blocks before running the existing line parser.
- **Files:** `game/mana_abilities.py`

### Mana spend restrictions (RULE 605.3a)

- **What:** `ManaPool` gained a `restricted` lot structure alongside its flat pool, tagged with a caller-opaque restriction dict and consumed via an `allows_restriction` predicate supplied by the payer — restricted mana is drained before unrestricted mana of the same type. `ManaAbility.restriction` recognizes the real-card vocabulary (creature/legendary/instant-or-sorcery/named-type spells, commander-only, any-{X}-cost). Wired at every payment call site (tap-for-mana, cast, activation).
- **Files:** `models/mana_pool.py`, `game/mana_abilities.py`, `game/game_engine.py`
- **Why:** `ManaPool` stays ignorant of what a restriction *means* (models/ must not import game/) — it only calls a caller-supplied predicate, preserving the module boundary.

### "Any combination of colors" mana (RULE 605.1a)

- **What:** "Add N mana in any combination of colors" (Selvala, Flamebraider) — the payer splits the resolved total across colors instead of picking one repeated color. `ManaAbility.any_combination` plus `GameEngine.tap_for_mana`'s new `color_split` parameter (validated by `validate_color_split`); `None` preserves the prior single-colour behaviour for existing callers.
- **Files:** `game/mana_abilities.py`, `game/game_engine.py`

### Hand-zone mana abilities (RULE 605.1a)

- **What:** "Exile this card from your hand: Add …" (Elvish/Simian Spirit Guide) — a mana ability activated straight from the hand, with no battlefield permanent or {T} at all. New `hand_mana_abilities_for`/`GameEngine.activate_hand_mana_ability` mirror the battlefield tap path but pay via `RulesEngine.exile(source)` instead of the battlefield-only cost helpers.
- **Files:** `game/mana_abilities.py`, `game/game_engine.py`
- **Why:** No prior "from hand" activation surface existed to extend (cycling/unearth aren't modeled either), so this was a genuinely new activation path.

### "Tapped for mana" event primitive (RULE 605.1)

- **What:** `tap_for_mana` fires a new `EventType.TAPPED_FOR_MANA` after mana lands in the pool, off a genuine mana-ability tap only — carrying `instance_id`, `object_types`, `controller_id`, and the produced mana. Unlocks Price of Glory by composing this with a new `not_controllers_turn` trigger predicate and the reflexive "destroy that land" primitive.
- **Files:** `models/events.py`, `game/game_engine.py`, `game/effect_binder.py`

### Two RULE 605.3a Mana-Spend-Restriction Kinds

- **What:** `chosen_type_spell` (Cavern of Souls/Unclaimed Territory, resolved per-instance off the tapped land's own RULE 601.2b `chosen_type`) and `mana_value_or_x_spell` (Helga, Skittish Seer/Troyan/Gutsy Explorer).
- **Files:** `game/mana_abilities.py`, `game/game_engine.py`
- **Bug fixed:** "X mana of any one color, where X is `<name>`'s power" (as opposed to the already-supported "equal to `<name>`'s power") wasn't recognized as a variable-amount selector at all.

### Throne of Eldraine Fully Modeled

- **What:** Chosen-colour mana production (`ManaAbility.color_selector="chosen_color"`), a `chosen_color_monocolored_spell` spend restriction, and a colour-locked activation cost (`ActivationCost.spend_only_chosen_color`, re-expressing the whole activation cost as chosen-color pips).
- **Files:** `game/mana_abilities.py`, `game/game_engine.py`, `game/costs.py`

### Quoted Mana-Ability Grants

- **What:** "Elves you control have '{T}: Add {B}.'" (Tyvar Kell) — recognized directly by `static_handlers._granted_mana_options` since a plain top-level mana ability is claimed-without-a-spec by the segmenter (mana production is read off text directly, not through the effect registry), so the nested-parse recursion other quoted grants use has nothing to re-emit. `{T}`-only cost.
- **Files:** `parser/oracle/catalogue/static_handlers.py`

### Mana-spent-to-cast tracking

- **What:** `GameObject.mana_spent_to_cast` plus a `SPELL_CAST` event `mana_spent` key distinguish "cast for an alternative/reduced cost of {0}" (still a paid cast) from the pre-existing `free` flag — needed for Lavinia/Boromir's "counter that spell" reflexive triggers.
- **Files:** `game/game_engine.py`, `models/events.py`

### Triggered mana ability (RULE 605.1b/605.4)

- **What:** `TriggeredAbility.mana_ability` resolves off-stack the instant it fires, so mana from an ability triggered off another mana ability is spendable within the same payment window that triggered it — the reason Wild Growth and Kinnan, Bonder's Pupil are playable.
- **Files:** `game/effects.py`, `game/rules_engine.py`

### Mirrored/matching mana effects (Kinnan, Mana Web)

- **What:** `MirrorProducedManaEffect` adds only the mana a triggering permanent actually produced (narrower than a plain "any colour" add); `TapMatchingLandsEffect` locks down every land that could produce a colour a tapped land actually made.
- **Files:** `game/effects.py`

### Open mana-potential display aggregate

- **What:** A per-colour (WUBRGC) display computation via six independent greedy maximizations, each seeded from an empty virtual pool (not the real pool) so open+used equals the turn's total accessed capacity; prefers a net-positive converter (e.g. Selvala) over a plain zero-cost producer when it helps the colour being maximized.
- **Files:** `game/mana_potential.py`

### Mana-Potenzial: auto-tap execution (`find_tap_plan`, `GameEngine.auto_tap_for`)

- **What:** A DFS-based planner seeded from the real current pool, with a bounded fixed-point retry (so a converter needing another source's output still resolves) and a node cap; deliberately never spends a sacrifice/hand-exile-cost source (Treasure, Spirit Guide) automatically. `auto_tap_for` executes a found plan purely through existing `tap_for_mana`/`activate_hand_mana_ability` calls.
- **Files:** `game/mana_potential.py`, `game/engine/mana_mixin.py`

### Automatic silent auto-tap on cast/activate

- **What:** A new `assume_mana_available` param on `can_cast`/`can_activate` skips only the mana-pool check so the engine can probe "is mana the only thing blocking this play" before silently tapping sources for an otherwise-fully-legal cast/activation; the same probe widens `legal_actions` offers to include a play that's legal except for mana and payable via potential, since the UI never posts an action it wasn't offered.
- **Files:** `game/game_engine.py`, `game/engine/mana_mixin.py`, `services/game_session.py`

### Distinct-colour mana spend restriction (PAR-7, RULE 605.3a-shaped)

- **What:** "Spend only colored mana on X. No more than one mana of each color may be spent this way." (Emblazoned Golem's Kicker). New `ManaPool.can_pay_distinct_colors(n)`/`pay_distinct_colors(n)`, paid as a separate step after the printed/fixed cost portion so the two payment checks can't wrongly double-count the same mana.
- **Files:** `models/mana_pool.py`, `game/engine/casting_mixin.py`, `game/ability_catalogue.py`

### Auto-tap offer bounded by mana potential for X/Kicker (MEC-13)

- **What:** `auto_tap_for` itself already handled a chosen X/Kicker value, but `max_affordable_x`/`max_affordable_kicker`/`max_affordable_kicker_x` (which drive the frontend's X input caps) bounded their search by the real mana pool alone, so a value only reachable by tapping untapped lands was never even offered. Fixed by bounding the search with `mana_potential.max_potential_total` and checking each candidate via `is_castable_via_potential`.
- **Files:** `game/mana_potential.py`, `game/engine/legal_actions_mixin.py`
- **Bug fixed:** `_cast_current_face` never threaded `kicker_x` through to `_auto_tap_for_cast_if_needed` at all, so a variable-Kicker spell always auto-tapped as if `kicker_x=0`, silently under-tapping and then failing its own correctly-costed `can_cast`.

### Face-down (morph) cast offer and auto-tap ordering fix (MEC-13)

- **What:** The face-down cast offer used a real-pool-only `can_cast` check instead of the potential-aware one, so the offer itself never appeared unless mana was already floating.
- **Files:** `game/game_engine.py`, `game/engine/legal_actions_mixin.py`
- **Bug fixed:** `cast_spell`'s `face_down` branch ran its legality gate *before* any auto-tap attempt (unlike the ordinary front-face path), so even after the offer appeared, clicking it still failed whenever the flat {3} required tapping untapped lands — fixed by making `_auto_tap_for_cast_if_needed` face-aware and calling it before the gate.

### Auto-tap dynamic colour-preference recompute (MEC-13)

- **What:** `_choose_option`'s colour preference was a static set computed once from the cost, so two different flexible dual lands searching for a two-colour cost would both greedily pick the same colour and never find an obviously-available plan. Fixed with `mana_potential._still_short_colors`, recomputed fresh before every tap attempt in `find_tap_plan`'s round loop.
- **Files:** `game/mana_potential.py`

### Bloom Tender / Carpet of Flowers mana primitives (ENG-27)

- **What:** New `ManaAbility.color_selector` kind `"colors_among_permanents_you_control"` — Bloom Tender's real cached text is a deterministic aggregate ("one mana of every color among permanents you control"), not a menu. Separately, `AddManaEffect.amount_from_target_count_selector`/new `amount` param on `add_mana_any_color` plus `GameObject.added_mana_with_ability_this_turn` model Carpet of Flowers as a genuine once-per-turn *targeted, triggered* mana ability (RULE 605.5a disqualifies a targeting ability from ever being a true mana ability, so it goes on the stack).
- **Files:** `game/mana_abilities.py`, `game/effects.py`, `models/game_object.py`, `game/ability_catalogue.py`
- **Why:** Sizing first found the ticket's own framing wrong for both cards — Bloom Tender has no player choice, and Carpet of Flowers can't be a mana ability at all per RULE 605.5a.

### User-reported bug: qualified "any color" mana clauses ignored board state (Mana System)

- **What:** `game/mana_abilities.py`'s `_parse_clause` matched the bare substring "any color" before checking any qualifying condition after it, so every *qualified* clause (Mox Amber's "…among legendary creatures and planeswalkers you control," Exotic Orchard/Fellwar Stone's "…that a land an opponent controls could produce") fell through to an unconditional 5-colour branch. Fixed with two new standalone-dispatched regexes and two new `color_selector` pairs, each a genuine live-board menu — `_colors_a_land_could_produce` reads a candidate land's own *live* mana abilities, guarded against infinite mutual reflection between two reflecting lands.
- **Files:** `game/mana_abilities.py`
- **Bug fixed:** Mox Amber, Exotic Orchard, Fellwar Stone, Quirion/Sylvok Explorer, and Harvester Druid all behaved like unconditional 5-colour Command Towers regardless of board state — found by a user playing a real goldfish game.

### MEC-25: `grant_mana_ability` upgrade shape (Mana System)

- **What:** Goldspan Dragon's "Treasures you control have '{T}, Sacrifice this artifact: Add two mana of any one color.'" needed a non-`{T}`-only cost and *replacement* of a matching printed ability rather than stacking a second one. New `grant_mana_ability` `cost` param + `GameObject.granted_mana_ability_upgrades`; `mana_abilities_for` drops any printed ability whose cost has the same shape as an upgrade's before adding the upgraded one.
- **Files:** `game/continuous.py`, `game/mana_abilities.py`, `game/ability_catalogue.py`

### MEC-21: `grant_any_color_for_activation` wildcard permission (Mana System)

- **What:** A standing RULE 605.1a wildcard permission over *activation*-cost mana (not a characteristic grant), consulted by all three activation-cost payment sites via `ManaPool`'s existing `wildcard` param — distinct from RULE 605.3a spend restrictions, which restrict what a lot can pay for rather than what colour it counts as. Scoped by `creature_abilities_only`.
- **Files:** `game/continuous.py`, `game/engine/activation_mixin.py`

### MEC-23: self-scoped, single-colour mana wildcard (Mana System)

- **What:** `any_color_for_activation` gained `self_only` (this permanent's abilities only) and `from_color` (only one specific WUBRG letter substitutes, not all five); `ManaPool._solve` gained a matching branch narrowing a colored pip's candidates to `[real_color, wildcard_color]` instead of all five.
- **Files:** `game/continuous.py`, `models/mana_pool.py`

### Hybrid-Mana Devotion Counting

- **What:** `devotion_to_hybrid` (Blended Twistling) counts any hybrid mana symbol once regardless of which two colours it spans (unlike ordinary devotion, which counts a hybrid pip toward both colours); a mono-hybrid pip doesn't count. Also added a standing (non-EOT) self-anthem row scaled by devotion.
- **Files:** `game/continuous.py` (`count_selector`), `parser/oracle/catalogue/subgrammars.py`, `parser/oracle/catalogue/static_handlers.py`.

### Devotion-Coupled Mana Choice (Nykthos)

- **What:** New `ManaAbility.color_selector` `"devotion_to_chosen_color"` — the one mana ability where the colour choice and produced amount are coupled: `resolve_options` builds a live 5-colour menu where each option's amount is that colour's current devotion, omitting 0-devotion colours.
- **Files:** `game/mana_abilities.py`, `parser/oracle/segmenter.py`.

### Mana Production Multiplier (Nyxbloom Ancient)

- **What:** New `mana_multiplier` static + `continuous.mana_production_multiplier_for`, consulted directly by `GameEngine.tap_for_mana` — deliberately excludes triggered/hand-zone/ritual mana per RULE 605's scoping.
- **Files:** `game/continuous.py`, `game/engine/mana_mixin.py`.

## Rules Engine Core Loop

### Effect system foundation

- **What:** Core effect hierarchy — `GameEffect`, `StaticEffect`, `TriggeredAbility`, `ReplacementEffect`, `ActivatedAbility`, `WinConditionEffect` — plus a `GameContext` facade that effects act through so their consequences route back through the engine's own primitives.
- **Files:** `game/effects.py`

### EffectRegistry and core one-shot effects

- **What:** A name-keyed `EffectRegistry` (hybrid class+registry design) with the first core one-shot effects: `DealDamageEffect`, `DrawCardEffect`, `DiscardEffect`, `DestroyEffect`.
- **Files:** `game/effects.py`

### Turn phases and steps as sequences (RULE 500)

- **What:** `TurnSequence`/`GamePhase`/`GameStep` model the turn structure as data the engine walks, consulting skip effects per step instead of hardcoding phase logic.
- **Files:** `game/phases.py`

### Casting/Stack/Mana/Priority/Triggers/SBA core loop

- **What:** Foundational implementation of Casting (RULE 601), Stack (RULE 608 LIFO), Mana (RULE 504), Priority (RULE 117), Triggered Abilities (RULE 603/607), and State-Based Actions (RULE 704: life≤0, empty-library draw loss, 0-toughness, lethal damage, legend rule). Trigger ordering defaults to APNAP-by-controller.
- **Files:** `game/rules_engine.py`

### Interactive stack (RULE 608)

- **What:** Casting leaves the spell on the stack instead of auto-resolving; `GameEngine.pass_priority` resolves the top object one at a time so instants can be cast in response. The turn loop still auto-resolves the stack when advancing a step; `resolve_until_stable` stops on a pending choice.
- **Files:** `game/game_engine.py`

### Library search and the general pending-choice mechanism (RULE 701.19)

- **What:** `SearchLibraryEffect` (type-restricted) plus `RulesEngine.request_search`/`resolve_search_choice` established the general `state.pending_choice` pattern: a JSON-able choice that travels with rewind snapshots, pauses resolution, and is answered by a `choose`/`decline` session action — reused by nearly every later interactive feature.
- **Files:** `game/effects.py`, `game/rules_engine.py`

### GainLifeEffect and CounterSpellEffect

- **What:** `GainLifeEffect` and `CounterSpellEffect` (removes a spell from the stack to its owner's graveyard, RULE 701.5) registered alongside damage/draw/discard/destroy/search.
- **Files:** `game/effects.py`

### "X loses N life" effect family and gain/lose-life controller fallback

- **What:** Added `lose_life`/`lose_life_selector` handlers and registered `LoseLifeEffect` (previously only reachable internally by Afflict) with the same mass-selector shape `DealDamageEffect` has.
- **Files:** `game/effects.py`, `parser/oracle/catalogue/handlers.py`
- **Bug fixed:** `GainLifeEffect`/`LoseLifeEffect`'s "no explicit player" fallback read `targets[0]` from the ability's shared target list, crashing when combined with an unrelated targeted effect in the same clause (Deathrite Shaman's "Exile target creature card... You gain 2 life."). Fixed to use the effect's own controller instead.

### Surveil (RULE 701.31)

- **What:** Mirrors the existing Scry implementation exactly: new `EventType.SURVEIL`, `RulesEngine.surveil` (always resolves the "keep everything on top" outcome non-interactively, firing the event for observers), `SurveilEffect`, and a parser handler for "surveil {NUMBER}".
- **Files:** `game/effects.py`, `game/rules_engine.py`, `parser/oracle/catalogue/handlers.py`

### Explore (RULE 701.44) (PAR-29, PARSER_VERSION 106)

- **What:** A new engine primitive for the Ixalan keyword action, the biggest single item in the PAR-29 RULE 701 residue. `RulesEngine.explore(permanent, player=None)` (in `search_mixin.py`, beside scry/surveil): reveal the top card of the exploring permanent's controller's library; a **land** goes to that player's hand (no counter); a **nonland** puts a +1/+1 counter on the permanent (through `add_counters`, so Doubling Season &c. still apply) and opens `explore_bin` — a genuine yes/no "may put the revealed card into your graveyard" (`resolve_explore_bin_choice`; declining leaves it on top). New `EventType.EXPLORED` fires once the whole process is complete (RULE 701.44b — inline for the land/empty-library paths, from the choice resolver otherwise), carrying `instance_id` / `controller_id` / `found_land` for a future "whenever ~/a creature you control explores" trigger. `effects.ExploreEffect` resolves *which* permanent(s) explore — the same three subject shapes as `GoadEffect`: bare self (`target_kind=None` — "when ~ enters, it explores", the 15-card bulk), `previous_subject` ("that creature explores", the creature an earlier clause chose), and a `TargetSpec` ("target creature you control explores").
- **Files:** `game/rules/search_mixin.py`, `game/effects.py` (+ `EffectRegistry`), `models/events.py`, `game/engine/turn_loop_mixin.py` (`resolve_pending_choice` dispatch), `parser/oracle/catalogue/handlers.py` (`explore_self_named` / `explore_self_pronoun` / `explore_previous` / `explore_target`), `frontend/src/js/gameBoardView.js` (`explore_bin` icon).
- **Deliberately unclaimed:** "explores, then it explores again" (Defossilize — a repeat wrapper); mass "each Merfolk creature you control explores" (an untargeted selector, `ExploreEffect` has no `selector` param); "whenever a creature you control explores, `<effect>`" (the `EXPLORED` event fires, but no trigger-condition parser row reads it yet). RULE 701.44d's APNAP ordering for simultaneous multi-permanent explores is not modeled (no single card creates that situation).
- **Yield:** +22 real cache cards (`parser_probe.py` diff, full cache, 0 regressed) — Merfolk Branchwalker, Seekers' Squire, Siren Lookout, Cenote Scout, Emperor's Vanguard, Tishana's Wayfinder, and more.
- **Tests:** `tests/test_par29_explore.py`

### Populate (RULE 701.36) (PAR-29, PARSER_VERSION 107)

- **What:** The next item off the PAR-29 RULE 701 residue, a small primitive on top of existing machinery. `RulesEngine.populate(player)` (in `copies_mixin.py`, beside `copy_permanent`): put a token onto the battlefield that's a copy of a creature token `player` controls (701.36a), nothing if they control none (701.36b). Degenerate cases resolve without asking (the `request_manifest_dread` idiom) — zero creature tokens → no-op; exactly one → copy it straight through `copy_permanent`; two or more → a new `populate` `pending_choice` (`resolve_populate_choice`, mandatory, a missing answer defaults to the first offered token). `effects.PopulateEffect` is the whole binding: "populate" never takes a target or a pronoun subject, so unlike `ExploreEffect`/`GoadEffect` there is only the one shape — `_controller_of(self.source, context)` and call the primitive.
- **Files:** `game/rules/copies_mixin.py` (`populate` / `resolve_populate_choice`), `game/effects.py` (`PopulateEffect` + `EffectRegistry`), `game/engine/turn_loop_mixin.py` (`resolve_pending_choice` dispatch), `parser/oracle/catalogue/handlers.py` (`populate` handler — a bare-word fullmatch), `frontend/src/js/gameBoardView.js` (`populate` icon).
- **Deliberately unclaimed:** ~9 cards whose "populate" clause is now real but that carry a *second* still-unmodeled clause (Determined Iteration's "the token created this way gains haste. sacrifice it …", Ghired, Conclave Exile's "the token enters tapped and attacking", Ghired's Belligerence's divided-damage trigger) stay UNMODELED.
- **Yield:** +14 real cache cards net (`parser_probe.py`, full cache, 0 regressed — a bare-word fullmatch handler cannot over-match) — Wake the Reflections, Rootborn Defenses, Trostani's Judgment, Sundering Growth, Growing Ranks, Song of the Worldsoul, Wayfaring Temple, Vitu-Ghazi Guildmage, and more.
- **Tests:** `tests/test_par29_populate.py`
- **Follow-up (PARSER_VERSION 114):** "populate X times" (Full Flowering) closed — `PopulateEffect.count` now takes the plain `"x"` sentinel `RulesEngine._substitute_x` already resolves generically on any effect's own `count`/`amount` attribute (the same idiom `MonstrosityEffect`/`AdaptEffect` already used), with 2+ repeats sequenced one at a time via `GameState.deferred_effects` (the RULE 608.2 idiom `ConniveEffect`/`SacrificeEffect` use) since each repeat's own "which token?" choice is independently interactive. See "PAR-29: Parser-shaped only residue" below.

### Bolster (RULE 701.39) + Support (RULE 701.41) (PAR-29, PARSER_VERSION 108)

- **What:** The +1/+1 keyword-action pair, off the PAR-29 RULE 701 residue. **Bolster N** is a new primitive: `RulesEngine.bolster(player, amount, source=None)` (in `mana_counters_mixin.py`, beside `add_counters`) finds the least toughness among creatures `player` controls and puts N +1/+1 counters on the one creature at that toughness — through `add_counters`, so RULE 616.1 doublers (Doubling Season) and RULE 122.5 "whenever a +1/+1 counter is put on ~" triggers apply. RULE 701.39a's tie clause is a `bolster` `pending_choice` (`resolve_bolster_choice`), opened only on a genuine tie; a single least-toughness creature or none resolves without asking (the `RulesEngine.populate` idiom). `effects.BolsterEffect` is a bare "you"-subject effect like `PopulateEffect` (no target, no pronoun). **Support N** needs no effect of its own — "support N" is a parser alias emitting the exact `add_counters` spec `_add_counters_multi_target` already produces for "put a +1/+1 counter on each of up to N target creatures" (`target_kind="creature"`, `target_count=N`, `optional=True`). RULE 701.41c's "a creature's support can't put a counter on itself" falls out for free: `targeting`'s plain `"creature"` kind already excludes the ability's own source (line ~923, `o is not source`).
- **Files:** `game/rules/mana_counters_mixin.py` (`bolster` / `resolve_bolster_choice`), `game/effects.py` (`BolsterEffect` + `EffectRegistry`), `game/engine/turn_loop_mixin.py` (`resolve_pending_choice` dispatch), `parser/oracle/catalogue/handlers.py` (`bolster` / `support` handlers), `frontend/src/js/gameBoardView.js` (`bolster` icon). The `when ~ enters, <kw> N` and `<cost>: <kw> N` wrappers come free from the existing trigger/activated-ability grammar.
- **Deliberately unclaimed:** "bolster 1, then put a +1/+1 counter on each creature you control with a +1/+1 counter on it" (Scale Blessing — a second clause); "you may pay `{3}{W}`. If you do, support 2" (Jubilant Mascot — a `pay_cost_then` wrapper, a different card from the one PARSER_VERSION 114 closed below).
- **Yield:** +25 real cache cards combined (`parser_probe.py`, full cache, 0 regressed — both handlers `fullmatch` a bare "`<kw>` `<digits>`" clause that was UNMODELED, nothing to over-match) — Aven Tactician, Elite Scaleguard, Sandsteppe Mastodon, Cached Defenses, Aerie Auxiliary, Relief Captain, Gladehart Cavalry, Lead by Example, Shoulder to Shoulder, and more.
- **Tests:** `tests/test_par29_bolster_support.py`
- **Follow-up (PARSER_VERSION 114):** "bolster X, where X is `<board count>`" closed — `BolsterEffect.amount_from_count_selector` reads `continuous.count_selector` live at resolution (the same idiom `PumpEffect.amount_from_count_selector` uses), for three real phrases (`tapped_creatures_you_control`; `cards_in_your_hand`; a new `distinct_named_artifact_tokens_you_control` selector, Sandsteppe War Riders' own "differently named artifact tokens" count). "support X" closed too — `AddCountersEffect` gained a `count_selector` param threaded onto its own `TargetSpec` (`"source_x_paid"`, the same sentinel March of Swirling Mist/Change of Plans already use for "up to X target creatures"). Found and fixed a real dormant bug on the way: `AddCountersEffect.apply`'s multi-target branch checked `TargetSpec.effective_count != 1` to decide whether to enter the multi-target path at all — a static field with no live board access, so a `count_selector`-sized spec always read back as `effective_count == 1` and silently dropped every target past the first (`GoadEffect.apply` already had the correct `count_selector or effective_count != 1` guard; `AddCountersEffect` never got the same fix when `count_selector` was newly wired to it here). Caught by an execute-level test, not the parse-level ones. See "PAR-29: Parser-shaped only residue" below.

### Suspect (RULE 701.60) (PAR-29, PARSER_VERSION 109) + one-off shapes residue closed (PAR-30, PARSER_VERSION 210)

- **What:** The Murders at Karlov Manor designation, off the PAR-29 residue. A new `GameObject.is_suspected` flag in the `is_monstrous`/`goaded_by` family — `RulesEngine.suspect(obj)` sets it (no-op on a non-creature; fires `EventType.SUSPECTED` either way, like `goad`), `RulesEngine.remove_suspected(objs)` clears it, `reset_as_new_object` clears it (RULE 400.7 — a new object isn't suspected). RULE 701.60b's two consequences are read off the flag **at combat time**, never via the layer engine: `combat.is_suspected` is the new predicate, `combat.has_menace` returns True for a suspected creature (so `min_blockers` requires 2+), and `combat_mixin.can_block` refuses a suspected blocker. `effects.SuspectEffect` resolves *which* creature — the same subject shapes as `GoadEffect` plus an `attached` one: bare self ("when ~ enters, suspect it"), `previous_subject` ("return target creature card … suspect it"), `attached` ("suspect enchanted creature" — this Aura's host), and a `TargetSpec` ("suspect [up to N] target creature[ an opponent controls]"). `effects.RemoveSuspectedEffect` is Absolving Lammasu's "all suspected creatures are no longer suspected".
- **Files:** `models/game_object.py` (`is_suspected` + `reset_as_new_object` + `to_dict`), `models/events.py` (`SUSPECTED`), `game/rules/misc_mixin.py` (`suspect` / `remove_suspected`), `game/combat.py` (`is_suspected` / `has_menace`), `game/engine/combat_mixin.py` (`can_block`), `game/effects.py` (`SuspectEffect` / `RemoveSuspectedEffect` + `EffectRegistry`), `parser/oracle/catalogue/handlers.py` (`suspect_self` / `suspect_previous` / `suspect_attached` / `suspect_target` / `remove_suspected_all`).
- **Deliberately unclaimed (at v109; most closed at v210 below):** conditional "if it's suspected, `<effect>`" clauses; two-colour token bodies alongside a suspect clause (Person of Interest — a `create_token` colour gap, unrelated). The "can't become suspected" static, the "if it's suspected, it's no longer suspected" tail and the "suspected creatures you control" group trigger filter all shipped in the PAR-30 one-off-shapes batch. The mechanic itself is complete — a future card with none of those extra clauses lands MODELED with no new work.
- **Yield:** +8 real cache cards (`parser_probe.py` diff vs v108, full cache, 0 regressed) — Barbed Servitor, Convenient Target, Incriminating Impetus, Caught Red-Handed, Absolving Lammasu, Reasonable Doubt, Rune-Brand Juggler, It Doesn't Add Up.
- **Tests:** `tests/test_par29_suspect.py`
- **Follow-up (PARSER_VERSION 114):** "target suspected creature you control" (Deadly Complication) closed at the filter level — a new `is_suspected` key on `combat.matches_object_filter`/`TargetSpec.creature_filter`, the same boolean-flag shape `attacking`/`is_commander`/`nontoken` already use. The rest of this entry's own "deliberately unclaimed" list was filed as four explicit new-primitive tickets under the PAR-30 Suspect bullet and closed together below.
- **One-off shapes residue closed (PAR-30, v210):** the four primitive-blocked singletons.
  - **`EffectSpec.condition` key `previous_target_is_suspected`** (Agrus Kos, Spirit of Justice — "choose up to one target creature. If it's suspected, exile it. Otherwise, suspect it."). The BACKLOG's "genuine if/else effect primitive" is expressed the same way `clash_won` / `ring_tempted_at_most` already are: two mutually complementary condition-gated specs. The condition reads *this* effect's own resolved `targets[0]` first (the exile branch carries the RULE 115 `target_spec`, so `previous_targets` isn't set yet), then `GameContext.previous_targets` for the "otherwise" branch. Exile leaves `is_suspected` set on the old object reference (RULE 400.7), so the complementary branch still evaluates `True` and stays skipped — no snapshot needed. `segmenter._CHOOSE_TARGET_IF_SUSPECTED_RE` matches the exact printed template only (a card that swapped the branch bodies is a new shape).
  - **`RemoveSuspectedEffect` gained `previous_subject` / `attached` / `optional` subject shapes** (it was mass-`scope="all"`-only). Deadly Complication's "You may have it become no longer suspected." routes the "may" through `request_choose_objects` (new `CHOOSE_OBJECT_ACTIONS` member `"remove_suspected"`, `_apply_chosen_object` branch) so declining is a real board choice — a suspected creature has menace, which its controller may want to keep. `handlers._remove_suspected_may_previous` (`previous_subject_only`) emits it; the modal block's second mode is now fully claimed.
  - **"suspect up to one *other* target creature you control"** — `subgrammars._TARGET_ROWS`' "another target creature you control" row widened to `(?:another|other)` (`UP_TO_ONE` consumes the "up to one " prefix, leaving "other target …"). Clandestine Meddler's ETB.
  - **"whenever one or more *suspected* creatures you control attack, …"** — `segmenter._batch_attack_group_filter` returns `{"is_suspected": True}` for the `suspected` qualifier (it previously failed the whole trigger closed), and `effect_binder._any_attacking_matches` honours that key against the live RULE 508.3a attacking group. Clandestine Meddler's surveil trigger.
  - **Airtight Alibi hand-authored** (`ability_catalogue/entries_016.py`) — Flash / Enchant creature parse off the printed text; the ETB is three host-scoped shared primitives (`tap` untap `attached_permanent`, `pump` hexproof-until-EOT, `remove_suspected` `attached` — RULE 701.60a's reverse already no-ops on a non-suspected creature, so no explicit gate); the static is a +2/+2 anthem plus a `grant_keyword` slug `"cant_become_suspected"` the layer engine stamps and `RulesEngine.suspect` checks (the only card printing that prohibition, so a bespoke slug rather than a new static kind).
  - **Yield:** +4 (Agrus Kos Spirit of Justice, Clandestine Meddler, Deadly Complication parser-MODELED; Airtight Alibi hand-authored), 0 regressed. `tests/test_par30_suspect_one_off_shapes.py`. Whole ticket = engine primitives + oracle handlers + `PARSER_VERSION` bump, one batch.

### Detain (RULE 701.35) (PAR-29, PARSER_VERSION 110)

- **What:** The Return to Ravnica designation, off the PAR-29 residue — the same shape as Suspect/goad. `GameObject.detained_by` is a per-detainer set (in practice one entry), swept "until your next turn" by the *same* `GameEngine.begin_turn` loop that expires `goaded_by` (RULE 701.35b — "until the next turn of the controller of the spell or ability"). `RulesEngine.detain(obj, detainer_id)` adds the entry and fires `EventType.DETAINED`; `reset_as_new_object` clears it (RULE 400.7). RULE 701.35b's three consequences are enforced at the point of use via `combat.is_detained`: `_can_attack` and `can_block` refuse a detained permanent, and `can_activate` refuses to activate its abilities (mana abilities go through `tap_for_mana` not `can_activate`, so a detained permanent's mana ability staying usable is a documented minor deviation — no cached detain target has one). `effects.DetainEffect` is targeted-only (no self/pronoun on any real card); `count`/`optional` cover the "up to two/three target …" cycle. Needed one shared-grammar addition: a `target nonland permanent an opponent controls` / `… you don't control` row in `subgrammars._TARGET_ROWS` (onto the existing `nonland_permanent_you_dont_control` targeting kind), for Lyev Skyknight / New Prahv Guildmage.
- **Files:** `models/game_object.py` (`detained_by` + `reset_as_new_object` + `to_dict`), `models/events.py` (`DETAINED`), `game/rules/misc_mixin.py` (`detain`), `game/engine/turn_loop_mixin.py` (`begin_turn` sweep), `game/combat.py` (`is_detained`), `game/engine/combat_mixin.py` (`_can_attack` / `can_block`), `game/engine/activation_mixin.py` (`can_activate`), `game/effects.py` (`DetainEffect` + `EffectRegistry`), `parser/oracle/catalogue/subgrammars.py` (TARGET row), `parser/oracle/catalogue/handlers.py` (`detain` / `detain_multi`).
- **Deliberately unclaimed:** "detain each nonland permanent your opponents control with mana value N or less" (Lavinia of the Tenth — a mass selector with a mana-value filter); "detain target creature with backup or vehicle an opponent controls" (Azorius Traffic Enforcement — a keyword filter).
- **Yield:** +10 real cache cards (`parser_probe.py` diff vs v109, full cache, 0 regressed) — Azorius Arrester, Azorius Justiciar, Inaction Injunction, Isperia's Skywatch, Lyev Decree, Lyev Skyknight, Martial Law, New Prahv Guildmage, Soulsworn Spirit, Archon of the Triumvirate.
- **Tests:** `tests/test_par29_detain.py`
- **Follow-up (PARSER_VERSION 111):** the `target nonland permanent an opponent controls` TARGET row this added pointed at `nonland_permanent_you_dont_control`, which `targeting.legal_targets` had always handled but `ALLOWED_TARGET_KINDS` never whitelisted — `tests/test_oracle_pipeline.py::test_target_rows_all_resolve_to_allowed_kinds` caught it. Added `nonland_permanent_you_control`/`nonland_permanent_you_dont_control` to the whitelist.

### Blight N — standalone form (PAR-29, PARSER_VERSION 111)

- **What:** "Blight N" (Bloomburrow — reminder text "put N -1/-1 counters on a creature you control"), the negative sibling of Bolster. `RulesEngine.blight(player, amount)` (in `mana_counters_mixin.py`, beside `bolster`) puts the counters on a creature `player` picks — any creature they control, not least-toughness — so it opens a `blight` `pending_choice` (`resolve_blight_choice`) whenever they control 2+; zero → nothing (an unpayable cost), one → straight on. Counters go on through `add_counters(kind="-1/-1")`, so RULE 122.5 triggers and the RULE 704.5q annihilation SBA apply. `effects.BlightEffect` is a bare "you"-subject effect like `PopulateEffect`/`BolsterEffect`. Handler `blight (?P<n>\d+)`.
- **Files:** `game/rules/mana_counters_mixin.py`, `game/effects.py` (+ `EffectRegistry`), `game/engine/turn_loop_mixin.py` (`resolve_pending_choice`), `parser/oracle/catalogue/handlers.py`.
- **Deliberately unclaimed (a separate, bigger build):** the **cost forms** — "{cost}, Blight N: `<effect>`" (Sting-Slinger, Gristle Glutton) and "as an additional cost to cast this spell, blight N" (Pyrrhic Strike) — and the "you may blight N. If you do, `<effect>`" pay-cost-then wrapper (Warren Torchmaster, Sourbread Auntie). These need an `ActivationCost`/cast-cost field + payment path, not an effect. **Known pre-existing bug found here, not introduced:** the segmenter/cost-parser currently accepts `{1}{R}, {T}, Blight 1` as a cost and *silently drops the "Blight 1"* (`costs.parse_activation_cost` ignores the unrecognized token), so Sting-Slinger et al. are **wrongly MODELED** — activatable without the drawback. Filed under PAR (BACKLOG) as part of the Blight-cost build; the honest fix (fail-closed on "blight" in a cost) will *reduce* the count by ~5 until the real payment path lands. "blight X" (Soul Immolation, a dynamic amount) also stays UNMODELED, fail-closed.
- **Yield:** +1 real cache card net (`parser_probe.py` diff vs v110, full cache, 0 regressed) — Sinister Gnarlbark. Most Blight cards are cost-form or carry a second unmodeled clause (Shadow Urchin's counter-death trigger).
- **Tests:** `tests/test_par29_blight.py`

### Endure N (RULE 701.63) (PAR-29, PARSER_VERSION 112)

- **What:** The Bloomburrow keyword action — the permanent's controller **either** puts N +1/+1 counters on it **or** creates an N/N white Spirit creature token. A genuine modal choice: `RulesEngine.endure(permanent, amount)` (in `misc_mixin.py`, beside `monstrosity`/`adapt`) opens an `endure` `pending_choice` (`resolve_endure_choice`, `to_token` yes/no; a missing answer defaults to the counters branch) — but *only* when the counters branch is possible (the permanent is still a creature on the battlefield). If "it" has left, RULE 608.2b leaves only the token, so it resolves without asking. `_endure_make_token` builds the token via `synthesize_token_card(name="Spirit", power=N, toughness=N, colors=["W"])` → `create_token`; counters go through `add_counters` so RULE 122.5 triggers and doublers apply. `effects.EndureEffect` resolves *which* permanent endures — the same subject shapes as `ExploreEffect`: bare self ("when ~ enters, it endures 3", the bulk), `previous_subject`, and a `TargetSpec`.
- **Files:** `game/rules/misc_mixin.py` (`endure` / `_endure_make_token` / `resolve_endure_choice`), `game/effects.py` (`EndureEffect` + `EffectRegistry`), `game/engine/turn_loop_mixin.py` (`resolve_pending_choice`), `parser/oracle/catalogue/handlers.py` (`endure_self_named` / `endure_self_pronoun` / `endure_previous` / `endure_target`), `frontend/src/js/gameBoardView.js` (`endure` + the previously-missing `blight` icon).
- **Yield:** +7 real cache cards (`parser_probe.py` diff vs v111, full cache, 0 regressed) — Anafenza, Unyielding Lineage, Dusyut Earthcarver, Fortress Kin-Guard, Inspirited Vanguard, Kin-Tree Nurturer, Sandskitter Outrider, Sinkhole Surveyor.
- **Tests:** `tests/test_par29_endure.py`
- **Follow-up (PARSER_VERSION 114):** both remaining gaps closed. "Endures X" (Krumar Initiate) — `EndureEffect.amount` now takes the plain `"x"` sentinel `RulesEngine._substitute_x` already resolves generically (int conversion deferred to `apply()` rather than attempted at construction, since `int("x")` would raise). "You may pay `<cost>`. If you do, it endures N." (Descendant of Storms) rides the existing `pay_cost_then_general` wrapper (MEC-18) — its recursive follow-up parse (`parse_effect_body`) is now called with `self_subject=True`, unlocking `self_subject_only` rows like "it endures N" for the follow-up text; safe because a *targeted* follow-up is already rejected by the same handler (the only pronoun shape left is the ability's own source), and RULE 603.5's "if you do" always continues the same triggered ability's subject. See "PAR-29: Parser-shaped only residue" below.

### Recruit (RULE 701.70) (PAR-29, PARSER_VERSION 113)

- **What:** The Tales of Middle-earth keyword action — "draw a card, then discard a card. If you discarded a nonland card, create a 1/1 white Human Soldier creature token." **Connive's sibling** (`ConniveEffect` — the same draw-then-conditional-discard shape) but its own primitive, `RulesEngine.recruit(player)` (in `misc_mixin.py`): the payoff is a token, not a +1/+1 counter on a source, and threading a second flag through `request_choose_objects`'s 8 `connive` touch-points would have been more surface than the mechanic needs. `recruit` draws, then opens a `recruit` "which card to discard" `pending_choice` (`resolve_recruit_choice`, mandatory — a missing answer defaults to the first card) when the hand has 2+; `_recruit_discard` reads `is_land` *before* the move (same order as the connive branch) and calls `synthesize_token_card(name="Soldier", …, colors=["W"], subtypes=["Human","Soldier"])` → `create_token`. `effects.RecruitEffect` is a bare "you"-subject effect. Handler `recruit` (bare word — every card prints it as an ETB/attack trigger's whole body).
- **Files:** `game/rules/misc_mixin.py` (`recruit` / `_recruit_discard` / `resolve_recruit_choice`), `game/effects.py` (`RecruitEffect` + `EffectRegistry`), `game/engine/turn_loop_mixin.py` (`resolve_pending_choice`), `parser/oracle/catalogue/handlers.py`, `frontend/src/js/gameBoardView.js` (`recruit` icon).
- **Yield:** +5 real cache cards (`parser_probe.py` diff vs v112, full cache, 0 regressed) — Great Gilded Boat, Lake-town Lookout, Long Lake Nuisance, Patient Instructor, The Mountain-king's Return.
- **Tests:** `tests/test_par29_recruit.py`

### PAR-29: Parser-shaped only residue (PARSER_VERSION 114)

- **What:** The whole "Parser-shaped only (engine already fine)" bullet BACKLOG.md's PAR-29 entry had left after Explore/Populate/Bolster+Support/Suspect/Detain/Blight/Endure/Recruit shipped, closed in one batch — the Bolster/Support/Suspect/Endure/Populate halves are folded into their own entries above; this entry covers the three genuinely new pieces.

  **Connive** (RULE 701.47/701.50) widened from the two hand-authored self-only shapes (Ledger Shredder, PAR-21) to the full family: `ConniveEffect` gained a `TargetSpec` subject ("target creature [you control] connives"), a `previous_subject` pronoun ("that creature connives"), and RULE 701.50d's dynamic "connives X, where X is `<count-selector-or-trigger-event-field>`" (`times_from_count_selector` reading `continuous.count_selector` — `attacking_creatures`, a new `creatures_died_this_turn` DEVOTION branch; `times_from_trigger_event` reading `GameContext.trigger_event["amount"]`, Mask of the Schemer's own "the amount of damage it dealt"). Getting RULE 701.50d *right* mattered: "connives N" draws N cards and discards N cards as **one** N-card choice, not N separate 1-and-1 cycles — the original single-cycle implementation would have quietly modeled this wrong had an execute-level test not caught it before shipping. 2+ subjects (Change of Plans' "each of X target creatures you control connive", `TargetSpec.count_selector="source_x_paid"` — the same sentinel March of Swirling Mist's "up to X target creatures phase out" already uses) are sequenced one at a time via `GameState.deferred_effects`, the RULE 608.2 idiom `SacrificeEffect._sacrifice_each_in_order` established — looping every subject's interactive discard synchronously would silently overwrite an earlier subject's still-unanswered prompt. +5 cards (Mob Lookout, Mechanical Mobster, Raffine Scheming Seer, Spymaster's Vault, Unstable Experiment); a further ~10 real cards still block on unrelated gaps (a `whenever a creature you control connives` `EventType.CONNIVED`-shaped trigger condition, a "when it connives this way" delayed sub-trigger, a convoke-group selector, a quoted-ability self-subject edge case) not attempted here.

  **Standalone "double"/"triple `<X>`'s power and toughness"** (RULE 701.10/11) — `PumpEffect.self_multiplier` (2 doubles, 3 triples) is a genuinely new *per-recipient* dynamic amount, unlike every existing `amount_from_*` field (one shared magnitude for the whole group): each recipient's own *current* power/toughness (post-layer-engine, so a same-resolution anthem is already reflected) sets its own delta, computed inside `_pump_one` rather than `apply()`-wide so the same one line of logic covers the self/previous-subject/target/group-selector shapes for free. Three printed surface forms, each its own oracle-text row: "double the power and toughness of `<TARGET>`/each creature you control", the possessive "double `<TARGET>`'s/~'s power and toughness", and the bare pronoun "double its power and toughness" (both `self_subject_only` and `previous_subject_only`, since Grunn's self-reference and World War Hulk's earlier-target reference are genuinely different referents behind identical text). +7 cards (Dragonclaw Strike, Epic Fight, Grunn the Lonely King, Nylea's Colossus, Reckless Amplimancer, Roar of Endless Song, Unnatural Growth); Choose Your Weapon/Tifa's Limit Break's own modal "• `<Mode Name>` — double target creature's power and toughness…" bodies and Maular/Okaun's own trigger-condition prefixes stay unclaimed on unrelated segmenter gaps (a labeled-mode bullet prefix the segmenter doesn't strip; "whenever a player wins a coin flip"/"whenever a creature you control with mana value N or greater attacks" trigger-condition rows that don't exist yet) — not this handler's job.

  **RULE 701.10's "exchange control of `<X>` and `<Y>`" / "exchange life totals"** generalized from three hand-authored singletons (Gilded Drake's self+"up to one" form, Oko's two-explicit-different-kinds form, Soul Conduit's two-target life form) to the general oracle-text templates: `ExchangeControlEffect` gained a real `optional` param (defaulting `False` — Gilded Drake's own call site now passes `optional=True` explicitly rather than relying on a hardcoded default) for the mandatory self+target form (Avarice Totem/Eyes Everywhere/Phyrexian Infiltrator), and a `count=2` same-kind mode (`TargetSpec(count=2, distinct_controllers=…)`, reusing the identical `apply()` code path the two-explicit-kind mode already had — `targets[0]`/`targets[1]` read the same regardless of whether they came from one spec or two) for "exchange control of 2 target `<kind>`[ controlled by different players]" (Shifting Borders/Switcheroo/Modify Memory); `ExchangeLifeTotalsEffect` gained the same self+target mode (Magus of the Mirror/Mirror Universe/Axis of Mortality). A new `land_you_dont_control` target kind (mirroring `nonland_permanent_you_dont_control`) closed Political Trickery/Vedalken Plotter's own "target land an opponent controls" — and, as a free side effect of widening the shared `land_you_control` TARGET row, also closed Trade Routes' unrelated `return_to_hand` clause. +11 cards. "Controlled by different players" is enforced by `ExchangeControlEffect.apply`'s own runtime `mine.controller_id != theirs.controller_id` check (a same-controller pick just no-ops) rather than at targeting time — RULE 115's `distinct_controllers` field only works *within* one spec's own multi-round gathering, not across two independently-typed specs, and building that cross-spec constraint for this batch's own 2-card yield wasn't attempted. A large residue stays open, mostly one shared shape — a cross-target "shares a card/permanent type with it" legality predicate RULE 115 has no mechanism for at all (Confusion in the Ranks, Daring Thief, Gauntlets of Chaos, Legerdemain, Role Reversal, Shifting Loyalties, The Trickster-God's Heist), plus several one-off gaps (a numeric cross-target comparison, a "you neither own nor control" kind, a "nonlegendary" filter, "the creature with the greatest mana value" dynamic selection, exchanging a spell instead of a permanent, teams, a delayed triple exchange) — filed in full under PAR-29 in `BACKLOG.md` rather than repeated here. **(Update — PAR-30, PARSER_VERSION 211–212: the whole residue is now closed** — the cross-target predicate and numeric comparison as resolve-time checks (v211: Daring Thief / Legerdemain / Role Reversal / Shifting Loyalties / Puca's Mischief / Spawnbroker), the remaining twelve as bespoke hand-authored primitives (v212). See the "Two-way control exchange" entry.)

- **Files:** `game/effects.py` (`ConniveEffect`, `PumpEffect._pump_one`/`self_multiplier`, `ExchangeControlEffect`, `ExchangeLifeTotalsEffect`, `AddCountersEffect.apply`'s bug fix, `PopulateEffect`/`EndureEffect`'s `"x"`-sentinel widening, `BolsterEffect.amount_from_count_selector`), `game/targeting.py` (`land_you_dont_control`), `game/continuous.py` (`creatures_died_this_turn` DEVOTION branch, `distinct_named_artifact_tokens_you_control`), `game/combat.py` (`matches_object_filter`'s `is_suspected` key), `game/ability_catalogue/entries_005.py` (Gilded Drake's explicit `optional=True`), `parser/oracle/catalogue/handlers.py` (every new row named above), `parser/oracle/catalogue/subgrammars.py` (`land_you_control`/`land_you_dont_control` TARGET rows, `DEVOTION`'s `creatures_died_this_turn` branch), `parser/oracle/catalogue/handlers.py`'s `_pay_cost_then_general` (`self_subject=True` on its recursive follow-up parse).
- **Yield:** +28 real cache cards combined (`parser_probe.py`/`scripts/coverage_report.py`, full cache, 0 regressed at every step) — see each family's own count above.
- **Tests:** `tests/test_connive_target_and_dynamic_amount.py`, `tests/test_exchange_control_and_life_totals_family.py`, extended `tests/test_par21_keyword_actions.py`, `tests/test_par29_populate.py`, `tests/test_par29_bolster_support.py`, `tests/test_par29_suspect.py`, `tests/test_par29_endure.py`, `tests/test_effect_families.py` (the new `PumpEffect.self_multiplier` cases).

### Clash (RULE 701.30) (PAR-29, PARSER_VERSION 115) + win-branch residue batch 1 (PAR-30, PARSER_VERSION 147)

- **What:** The Lorwyn/Shadowmoor keyword action, and the biggest single item left in the PAR-29 "needs an engine primitive first" list by cache count. `RulesEngine.clash(player, with_opponent=True)` (in `misc_mixin.py`, beside `suspect`/`detain`): `player` reveals the top card of their library and — for "clash with an opponent" (RULE 701.30b) — every opponent reveals theirs too; returns whether `player` **won** (RULE 701.30d — their revealed card's mana value strictly greater than every *other* card revealed). With no opponent (a 1-player Goldfisch/Replay board) or every opponent's library empty, nothing else is revealed and `player` wins on their own reveal alone — a deliberate reading of 701.30b's "choose an opponent" when there is none, keeping clash cards functional in solo play; an empty own library can't win. **Documented simplification:** RULE 701.30a's optional "then put that card on the bottom" is always declined (revealed cards stay on top) — an APNAP pair of interactive yes/no pauses for ~33 cache cards, and it never changes *this* resolution's win/lose outcome. `effects.ClashEffect` (a bare "you"-subject effect, no target/pronoun, registered as `clash`) stashes the outcome on `GameContext.clash_won`.
- **The "if you win …/otherwise …" branch** is *not* params on the clash spec — it's sibling `ConditionalEffect`s in printed order, gated on a new `EffectSpec.condition` key `"clash_won"` (bool). `ConditionalEffect._condition_holds` reads `GameContext.clash_won`, falling back to the firing `CLASHED` event's own `won` for the "whenever you clash, … if you won, …" shape (Entangling Trap — the clash there is the *trigger*, not a body clause). `None` from both fails *both* branches, so a stray "otherwise" with no clash in scope resolves to nothing. `_apply_effects_partitioned` resets/restores `clash_won` per resolution, the same idiom as `previous_targets`.
- **Events:** `EventType.CLASHED` (always, `player_id`/`won`) and `EventType.WON_CLASH` (only on a win) — the `CLASHED`/`WON_CLASH` split mirrors `LIFE_GAIN`/`LIFE_GAINED` so "whenever you win a clash" (Marvo, Deep Operative) needs no event `filter`. Both added to `effect_binder._GROUP_CONTROLLER_EVENT_KEYS` (`player_id`) and `segmenter._PLAYER_TRIGGER_CONDITIONS` ("you clash" → `CLASHED`, "you win a clash" → `WON_CLASH`).
- **Parser:** handler `clash` (`clash with (an opponent|defending player)`); `segmenter._IF_YOU_WIN_CLASH_RE` / `_OTHERWISE_CLASH_RE` are condition-wrappers in `parse_effect_body` (the `_KICKED_CONDITION_RE` idiom) that recursively parse the branch body and attach `condition={"clash_won": …}`. The `_CONNECTORS` period-split hands "clash with an opponent" / "if you win, …" / "otherwise, …" to `parse_effect_body` separately, so no combined multi-sentence handler is needed and the compound cards ("... . clash with an opponent. if you win, ...") are covered by the same three pieces.
- **Files:** `models/events.py`, `game/rules/misc_mixin.py` (`clash`), `game/effects.py` (`ClashEffect` + `EffectRegistry`, `GameContext.clash_won`, `_apply_effects_partitioned` save/restore, `ConditionalEffect._condition_holds`'s `clash_won` key), `game/effect_binder.py` (`_GROUP_CONTROLLER_EVENT_KEYS`), `parser/oracle/spec.py` (`_ALLOWED_CONDITION_KEYS` + bool check), `parser/oracle/segmenter.py` (`_IF_YOU_WIN_CLASH_RE` / `_OTHERWISE_CLASH_RE` + `_PLAYER_TRIGGER_CONDITIONS`), `parser/oracle/catalogue/handlers.py` (`_clash`), `parser/oracle/gate.py` (PARSER_VERSION 115).
- **Yield:** +9 real cache cards (`parser_probe.py` diff vs v114 / `scripts/coverage_report.py --no-db`, full cache, 0 regressed) — Adder-Staff Boggart, Bog Hoodlums, Nath's Elite, Oaken Brawler, Paperfin Rascal, Springjack Knight, Release the Ants, Research the Deep, Revive the Fallen. ~24 more cache clash cards stay UNMODELED on ordinary effect-grammar residue in their win branch ("return ~ to its owner's hand", "those creatures gain `<keyword>`", "that player `<verb>s`", "repeat this process", a "protection from the color of your choice" first clause) — none of it clash-specific; tracked in `BACKLOG.md`.
- **Win-branch residue batch 1 (PAR-30, v147):** five small parser widenings, no engine change. (1) "Whenever you **clash and win**, …" joins "you win a clash" as a `WON_CLASH` trigger phrasing (`segmenter._PLAYER_TRIGGER_CONDITIONS`) — Sylvan Echoes. (2) `_FREE_CAST_FROM_HAND_RE` accepts "…spell **from your hand** with mana value N or less…" word order (an `n_after` group read alongside `n` by `_free_cast_from_hand`) — Marvo, Deep Operative's own second ability. (3) `return_self_to_hand`'s regex accepts "return **this card** to its owner's hand" (Ringskipper — a "when ~ dies" clash-win body, so the source is in the graveyard; `RulesEngine.return_to_hand` moves it from whatever zone it's in), scoped to that handler rather than widening the shared `_SELF_SUBJECT` macro. (4) the connector-split loop treats a sub-part that is purely a bare `clash` spec as a **referent-transparent interstitial** — it neither targets nor creates, so a card like Gilt-Leaf Ambush ("Create two tokens. Clash with an opponent. If you win, **those creatures** gain deathtouch …") carries its `previous_targets`/`created_objects` pronoun chain across the clash sentence instead of having it cleared. (5) `_PUMP_PREV_SINGULAR_PT_RE` accepts "gets **an additional** +N/+N" (Fistful of Force). **+5** (Sylvan Echoes, Marvo, Ringskipper, Gilt-Leaf Ambush, Fistful of Force), 0 regressed. `tests/test_par30_clash_win_branch.py`.
- **Win-branch residue batch 2 (PAR-30, v148):** two parser widenings. (1) A **"{X}-scaled damage" handler** — `_damage_x` (`"~ deals x damage to <target>"`, digit-free so no overlap with the `NUMBER`-based `damage` row) emits `EffectSpec("damage", {"amount": "x"})`, the `"x"` sentinel `RulesEngine._substitute_x` already rewrites off the spell/ability's announced {X}. This is squarely general effect-grammar — no handler for X-damage existed at all — so it closes **+20 classic X-burn spells/abilities** (Blaze, Devil's Play, Fanning the Flames, Volcanic Geyser, Cinder Elemental, Heat Ray, Pain Kami, Goblin Dynamo, Knollspine Invocation, Latulla, Flameblast Dragon, …) alongside **Titan's Revenge** (the clash card, blocked on its pre-clash "~ deals X damage to any target" clause). Verified end-to-end: `_substitute_x` sets `amount=4`, a 3/3 dies; a player target loses 5 at X=5. (2) `_DESTROY_ALL_RE` gained an optional " your opponents control" scope → new `opponents_enchantments`/`opponents_artifacts` selectors in `_mass_selector_objects` (`_MASS_DESTROY_SELECTORS`; a scope on any other noun fails closed) — **Spring Cleaning**'s clash win-branch. **+21 total**, 0 regressed. `tests/test_par30_damage_x.py`, `tests/test_par30_clash_win_branch.py`.
- **Win-branch residue batch 3 (PAR-30, v149) — the "doesn't untap during its controller's next untap step" family:** another general effect-grammar family (~95 SOLO) that a clash card (Entangling Trap) sits inside. New `effects.SkipNextUntapEffect` (registered `skip_next_untap`) sets `GameObject.skip_next_untap` — **RULE 702.19b's own one-time flag**, already consumed and cleared in `GameEngine._step_untap` (built for exert), so no engine plumbing beyond the effect. A pure rider (taps nothing), so "Tap X. It doesn't untap …" is the ordinary two-clause `[tap, skip_next_untap{previous_subject}]` sequence, "it" resolved off `GameContext.previous_targets`. Three subject shapes — `target <perm>` / `it`·`that <perm>` (prev-subject) / `~` (self). **Also a standalone `_tap` fix:** its allowed target kinds never included the controller-scoped creature kinds (`_TAP_TARGET_KINDS`), so "tap target creature **an opponent controls**" (Chillbringer, Berg Strider — half the tempo family) didn't parse at all. **+51** — the whole tap-and-freeze family (Frost Lynx, Frost Titan, Frost Trickster, Dungeon Geists, Nebelgast Herald, Niblis of Frost, Kor Hookmaster, Kor Entanglers, Barl's Cage, Chandra's Revolution, Hands of Binding, Blustersquall, Ojutai's Breath, …) plus **Entangling Trap**. 0 regressed; verified end-to-end (flag survives to the untap step, which skips the creature and clears it). A stale negative test (`test_mec19_becomes_target_family.py` — Frost Titan asserted UNMODELED) flipped to positive. `tests/test_par30_skip_next_untap.py`.
- **Win-branch residue batch 4 (PAR-30, v150) — "gains protection from the color of your choice until end of turn":** RULE 702.16, ~27 SOLO, a clash card (**Redeem the Lost**) among them. The engine primitive is Mother of Runes' `effects.GrantProtectionEffect` / `RulesEngine.grant_protection_choice` (an interactive `grant_protection_color` pick landing in `GameObject.temp_protections`, cleared at cleanup) — only the parser recognition of this exact phrasing was missing. `GrantProtectionEffect` gained a self mode (`target_kind=None` — "~ gains …", Jareth/Cartel Aristocrat) and a `previous_subject` mode ("put a +1/+1 counter on target creature you control. **it** gains …", Feat of Resistance); its `apply` now loops recipients rather than reading only `targets[0]`. Three parser rows (`{TARGET}` whitelisted to creature/creature_you_control/permanent_you_control · `self_subject_only` · `previous_subject_only`). **+17** (the Sejiri Shelter/Sejiri Steppe/Shelter/Stave Off cycle, Center Soul, Emerge Unscathed, Blessed Breath, Gods Willing, Moonlit Strider, Thornscape/Stormscape Master, Midvast Protector, Armored Guardian, Benevolent Bodyguard, Aven Liberator), 0 regressed; verified end-to-end. `tests/test_par30_grant_protection_choice.py`.
- **Win-branch residue batch 5 (PAR-30, v151) — "reveal cards from the top of your library until you reveal a `<type>` card. put that card `<onto the battlefield / into your hand>` and the rest `<bottom / graveyard / shuffle>`":** ~64 SOLO, **Recross the Paths** a clash card among them. The engine primitive is `RulesEngine.dig_until` / `effects.DigUntilEffect` (the generalized cascade dig — predicate + `hit_destination` + `rest_destination` all parameterized) — only the "reveal until a *type* predicate" parser recognition was missing. `_REVEAL_UNTIL_TYPE_RE` + a `_DIG_UNTIL_REST_RES` `re.search` over the leftover tail (so the many "put all other cards revealed this way …" / ", then shuffle …" connector spellings don't each need a row). Predicates: a land / basic land / creature / artifact / enchantment / nonland / nonartifact-nonland card. **Fails closed** on "onto the battlefield **tapped**" (Clifftop Lookout — `_place_dig_hit` has no tapped-entry mode). **Documented simplification**: "in any order" is modeled as `dig_until`'s only bottoming mode, a random order. **+9** (Recross the Paths, Atla Palani, Foster, Evolutionary Leap, Madcap Experiment, Audacious Reshapers, Spinner of Souls, The Regalia, Vivien Nature's Avenger, Yuna's Whistle), 0 regressed; verified end-to-end. `tests/test_par30_reveal_until_type.py`.
- **Win-branch residue batch 6 (PAR-30, v152) — "you gain life equal to `<its / that creature's>` `<power / toughness>`":** ~36 SOLO, **Weed Strangle** a clash card among them. The creature isn't a RULE 115 target of the gain-life effect itself, so a new `GainLifeEffect.amount_from_subject` string param (`"<who>_<char>"`) names the object + characteristic, resolved in `_resolve_amount_override`'s existing chain. Three gated parser rows: "its" on a bare-`~` trigger → `self_*` (`self_subject_only` — Bottle Golems' "When ~ dies, …its power"); "its" on a group trigger → `trigger_subject_*` (`group_subject_only` — Angelic Chorus' "Whenever a creature you control enters, …its toughness", reads the firing event's `instance_id`); "that creature's" after another clause → `previous_subject_*` (`previous_subject_only`, RULE 608.2h last-known info — the creature is usually gone). The ungated bare form fails closed. **+14** (Bottle Golems, Boulderbranch Golem, Angelic Chorus, Brightmare, Weed Strangle, Tribute to Hunger, Consuming Vapors, Conclave Mentor, Cleric Class, Sheltering Word, Sunscourge Champion, Heal the Scars, South Wind Avatar, Wolverine Riders), 0 regressed; verified end-to-end (self power → +3; a destroyed creature's last-known toughness → +5). `tests/test_par30_gain_life_eq_characteristic.py`.
- **Win-branch residue batch 7 (PAR-30, v153) — "~ [also] deals N damage to that creature's controller":** ~22 SOLO, **Lash Out** a clash card among them. New `DealDamageEffect.recipient_subject` string param (`"<who>_controller"`) — derives the recipient *player* from `GameContext.previous_targets` (RULE 608.2h last-known controller — "Destroy target creature. ~ deals 2 damage to that creature's controller." — Consign to the Pit / Blur of Blades) or the firing event's own `instance_id` / `controller_id` payload ("Whenever a creature blocks/dies, …" — Battle Strain / Dingus Staff / Gimli). No RULE 115 target of this effect's own, so `target_spec` is `None` (its `__init__` `if` now guards `recipient_subject is None` too) and `apply` short-circuits to a direct `context.deal_damage(player, amount, source)`. Two gated parser rows (`previous_subject_only` / `group_subject_only`), the `_DAMAGE_TO_SUBJECT_CONTROLLER_RE` regex also accepting "~ **also** deals" (Blooming Blast). **+10** (Consign to the Pit, Blur of Blades, Grotag Siege-Runner, Battle Strain, Dingus Staff, Lash Out, Cindervines, Destructive Revelry, Heat of Battle, Structural Distortion), 0 regressed; verified end-to-end (both subject modes hit the right opponent for the right amount). `tests/test_par30_damage_to_subject_controller.py`.
- **Win-branch residue batch 8 (PAR-30, v154) — two small bodies; the general-family seam is worked out:** "untap all `<basic land subtype>` you control" (Woodland Guidance) → a new `continuous.group_selector_objects` `lands_you_control_of_type_<x>` branch (the land sibling of the existing `creatures_you_control_of_type_<x>`) + a one-line `_is_valid_tap_selector` whitelist widen; "~ deals N damage to each creature blocking it" (Fire Juggler, 4 cards) → a new `DealDamageEffect.each_creature_blocking_source` selector (every battlefield creature whose `GameObject.blocking` names this ability's own source, read live). **+2**, 0 regressed; verified end-to-end. `tests/test_par30_clash_batch8.py`. The last six clash win-branch cards are genuine singletons — closed by **MEC-50** below, as engine primitives rather than hand-authoring.
- **MEC-50 — Clash win/otherwise-branch residue closed (PARSER_VERSION 209).** Six primitive-blocked singletons, one batch (engine primitives + oracle handlers + version bump). The shared piece is **`GameContext.clashed_opponent`** — `RulesEngine.clash` records the opponent it clashed with (`_last_clash_opponent_id`, first living opponent — a documented simplification, same as `GainControlBySourceEffect`), `ClashEffect` stashes it on the context, and `_apply_effects_partitioned` gives it the same save/reset/restore as `clash_won`. Then:
  - **Hoarder's Greed** — new `RepeatProcessEffect(effects, repeat_while="clash_won")`: runs the serialized process (`[lose_life, draw, clash]`, built fresh each pass via `build_effects` — the `CreateDelayedTriggerEffect` idiom), looping while `context.clash_won` holds, capped at `_MAX_CLASH_REPEAT_ITERATIONS` (20 — a chain of clash wins is unbounded in principle). Segmenter `_CLASH_REPEAT_PROCESS_RE` (a whole-body match, since the win branch loops the *process*, not a fresh clause).
  - **Broken Ambitions** — `MillEffect.selector="previous_subject_controller"`: "that spell's controller mills four" reads `context.previous_targets[0]` (the countered spell, now in a graveyard with no controller — RULE 608.2h) and mills its `owner_id`. Handler `mill_prev_spell_controller`. The counter-unless-pays-`{X}` and clash already parsed; this was the only unclaimed clause.
  - **Whirlpool Whelm** — `ReturnToHandEffect.to_library_top_if_clash_won`: the clash resolves before the bounce (printed order), so `context.clash_won` is set when the bounce applies — on a win the single target goes to the top of its owner's *library* instead of hand (via `RulesEngine.return_to_library`). One effect, so no stale RULE 400.7 reference to "that creature" after a zone change; the "you may" is auto-taken (beneficial-*may* convention). Segmenter `_CLASH_BOUNCE_OR_LIBRARY_RE`.
  - **Captivating Glance** — new `GainControlAttachedEffect(recipient)`: an indefinite control change of this Aura's host to the ability's controller (`"controller"`, win branch) or `GameContext.clashed_opponent` (`"clashed_opponent"`, otherwise) — a direct `controller_id` mutation + recompute, the same MVP simplification `GainControlBySourceEffect` makes. Handler `gain_control_attached` (recognises "gain control of enchanted creature" / "that player gains control of enchanted creature").
  - **Pulling Teeth** — `DiscardEffect.previous_subject`: "that player" in the otherwise branch is the `Player` the win branch RULE 115-targeted (`context.previous_targets[0]`, set even when the win-branch `ConditionalEffect` gate fails, since targets are chosen at cast time). Handler `that_player_discards`. **Bonus:** `previous_subject` falls back — when no target was chosen this resolution — to the firing trigger's own event player (a DAMAGE event's recipient, a SPELL_CAST's caster, a per-player phase step), which unlocks **+28 "whenever ~ deals damage to a player, that player discards a card" cards** (Abyssal Specter, Blazing Specter, Headhunter, Oppression, Necrogen Mists, Larceny, Okiba-Gang Shinobi, Helm of the Ghastlord's granted trigger, …) the parser could never claim before.
  - **Pollen Lullaby** — `SkipNextUntapEffect.subject="clashed_opponent"`: flags `skip_next_untap` on every creature that player currently controls, no RULE 115 target. Handler `clashed_opp_creatures_no_untap`. (The "prevent all combat damage this turn" first clause already parsed.)
  - **Yield:** +34, 0 regressed. **Files:** `game/rules_engine.py` (`_last_clash_opponent_id`), `game/rules/misc_mixin.py` (`clash`), `game/effects.py` (`GameContext.clashed_opponent`, `_apply_effects_partitioned` save/restore, `ClashEffect`, `RepeatProcessEffect` + `_MAX_CLASH_REPEAT_ITERATIONS`, `MillEffect.selector`, `ReturnToHandEffect.to_library_top_if_clash_won`, `GainControlAttachedEffect`, `DiscardEffect.previous_subject`, `SkipNextUntapEffect.subject`), `parser/oracle/segmenter.py` (`_CLASH_REPEAT_PROCESS_RE`, `_CLASH_BOUNCE_OR_LIBRARY_RE`), `parser/oracle/catalogue/handlers.py` (`mill_prev_spell_controller`, `that_player_discards`, `gain_control_attached`, `clashed_opp_creatures_no_untap`), `parser/oracle/gate.py` (PARSER_VERSION 209). **Tests:** `tests/test_mec50_clash_win_branches.py` (all six end-to-end — the repeat loop counts and caps, the countered spell's owner is milled, the bounce goes to hand on a loss and library-top on a win, control follows the winner, the otherwise-discard hits the right player, the clashed opponent's creatures don't untap; + the "that player discards" trigger-event fallback).
- **Tests:** `tests/test_par29_clash.py` (parse + branch-condition attachment + `RulesEngine.clash` win/loss/no-opponent/empty-library + no-bottoming + end-to-end ETB trigger granting a counter on win / not on loss).

### Firebending — printed-keyword behaviour (RULE ~702.189) (PAR-29)

- **What:** "Firebending N" (Doctor Who) was parser-*recognized* (`keywords.py` `_N` shape) but inert. `effect_binder._kw_firebending` now synthesizes its RULE 702-text ability — "Whenever this creature attacks, add {R}×N. This mana lasts until end of combat." — as a self-only `ATTACKS` `TriggeredAbility` with `mana_ability=True` (RULE 605.4, resolves off-stack so the {R} is spendable that combat) wrapping `AddManaEffect(colors=["R"]*n)`. Same `_KEYWORD_TRIGGERED_BUILDERS` dispatch (keyed on `spec.keyword["name"]`/`["n"]`) as Annihilator/Afflict/Bushido. **Documented simplification:** the "lasts until end of combat" note isn't modeled — the mana empties at the ordinary step boundary rather than carrying a combat-scoped lifetime.
- **Files:** `game/effect_binder.py` (`_kw_firebending`, `_KEYWORD_TRIGGERED_BUILDERS`, `AddManaEffect` import).
- **Tests:** covered by the existing keyword-binder suite plus an inline check that a printed-Firebending creature binds an `ATTACKS` `AddManaEffect` mana ability.

#### The grant path — parametric keyword *grants* (ENG-31, PARSER_VERSION 128)

- **What:** every real Firebending card *grants* the keyword — "target creature you control gains firebending N until end of turn" (Fire Nation Palace), "creatures you control gain firebending N …" (Sozin's Comet), a token "with firebending N" (Fire Nation Attacks) — and a keyword carrying a *number* couldn't ride the flat `keywords: [str]` list that `pump`/`grant_keyword`/`create_token` all carry. Now a `parametric_keywords: [{"name", "n"}]` param sits alongside that flat list on all three.
- **Stamping (`continuous._apply_layer_6_ability`):** a `grant_keyword` static's `parametric_keywords` entries stamp `GameObject._granted_parametric_keywords[name] = n` (re-derived every recompute, cleared by `reset_derived` — the parametric sibling of `_granted_keywords`); `PumpEffect` writes an until-EOT grant into the new `GameObject.temp_parametric_keywords` dict (cleared at cleanup RULE 514.2 next to `temp_keywords`), folded in the same pass. `GameObject.parametric_keyword_value(name)` reads a granted value ahead of the printed `parametric_keywords[name]["n"]`.
- **Behaviour (`effect_binder.parametric_keyword_triggered_abilities`):** the printed-keyword path runs `_KEYWORD_TRIGGERED_BUILDERS` at bind-on-load; a grant has no bind step, so `_apply_layer_6_ability` calls this helper every recompute to re-synthesize the keyword's RULE 702-text triggered ability (firebending's self-only `ATTACKS` add-{R}×N mana ability) off the *granted* N, onto `_granted_triggered_abilities`, cached in `GameState._granted_ability_cache` keyed on `(id(ability), instance_id, "parametric", name, n)` (the `n` in the key so a changed amount mints a fresh ability and prunes the stale one). Only the four keywords whose RULE 702 text *is* a triggered ability — firebending / annihilator / afflict / bushido (`_GRANTABLE_PARAMETRIC_KEYWORDS`) — are grantable; every other NUMBER-shape keyword (renown, toxic) stays fail-closed for a grant. A token created "with firebending N" docks the keyword onto its own `parametric_keywords` + synthesizes its `triggered_abilities` right after it enters (a printed part of its definition, not a layer-6 grant).
- **Parser:** `_split_keywords_with_parametric` (a `_token_keywords` sibling) splits a "flying, firebending 2" list into `(flag_slugs, [{name, n}])` and fail-closes on anything that's neither a FLAG keyword nor a grantable parametric one. Reached from `_pump_keywords` and `_inline_create_token_params`; the `pump_keyword` and `create_token` handler regexes gained `0-9` in their keyword capture. `spec._clamp_params` also clamps each nested `n` (a synthesized `["R"] * n` mustn't be handed an unbounded amount).
- **Files:** `models/game_object.py` (`_granted_parametric_keywords`, `temp_parametric_keywords`, `parametric_keyword_value`, resets), `game/continuous.py` (`_apply_layer_6_ability`), `game/effect_binder.py` (`parametric_keyword_triggered_abilities`), `game/effects.py` (`PumpEffect`/`CreateTokenEffect`/`grant_keyword` registry), `game/engine/turn_loop_mixin.py` (cleanup), `game/combat.py` (`toxic_value` via the helper), `parser/oracle/catalogue/handlers.py`, `parser/oracle/spec.py`, `parser/oracle/gate.py` (v128).
- **Yield:** 3 real cache cards newly MODELED (0 regressed) — Fire Nation Palace, Fire Nation Attacks, Sozin's Comet.
- **Tests:** `tests/test_eng31_parametric_keyword_grants.py` (clause parse incl. the non-grantable fail-closed case; real-card `parse_oracle`; execute: static grant synthesizes the `{R}{R}` ATTACKS mana ability live and drops when the source leaves; until-EOT grant clears at cleanup; a token created with firebending N; Fire Nation Palace end-to-end through `bind_from_catalogue`).
- **Residue closed (PAR-30, PARSER_VERSION 135):**
  - **Iroh, Dragon of the West** — "each creature you control **with a counter on it** gains firebending N …" needed a new group selector: `_GROUP` + `_GROUP_SELECTORS` gained the phrase, `continuous.group_selector_objects` a `creatures_you_control_with_a_counter` branch (any counter kind, any positive count). ENG-31's `pump` `parametric_keywords` path already handles the grant over a `selector` group.
  - **Fire Nation Occupation** — "whenever you cast a spell **during an opponent's turn**, …" needed only an optional turn qualifier on `_CAST_SPELL_TRIGGER_PLAIN_RE` mapping to the trigger's already-existing `not_controllers_turn` gate (RULE 603.4, `effect_binder` — `SPELL_CAST`'s `player_id` is in `_GROUP_CONTROLLER_EVENT_KEYS`). "during your turn" has no matching engine gate, so it's left fail-closed. This also closed the **"flash matters" cluster** — Brineborn Cutthroat, Dream Spoilers, Glen Elendra Pranksters, Nightmare Sower, Unwelcome Sprite, Voracious Tome-Skimmer, Baxter (+7). Total v135 yield: **+11**, 0 regressed.
  - **v157 — the self grant.** **Fire Nation Cadets** ("~ has firebending N as long as there's a lesson card in your graveyard") — the fourth parametric-grant form, alongside pump/group/token. `static_handlers._SELF_GRANT_RE`'s keyword capture now accepts a trailing digit (a `0-9` added to the char class) and routes through `_split_keywords_with_parametric` — **only when `_flag_keywords` returns `None` first**, so the ordinary landwalk/flag self-grant path is byte-identical — emitting `grant_keyword {affects: "self", parametric_keywords: […]}`, which `continuous._apply_layer_6_ability`'s existing ENG-31 branch applies over `affected_objects` = `[source]`. The `as long as` half is the v156 `subtype_in_graveyard` gate wrapping it. +1, 0 regressed. `tests/test_eng31_parametric_keyword_grants.py`.

#### The "whenever you waterbend, earthbend, firebend, or airbend" trigger (PAR-30, PARSER_VERSION 214) — bending residue closed

- **What:** the last open sub-bullet of PAR-29's parser trail — Avatar Aang's "Whenever you waterbend, earthbend, firebend, or airbend, draw a card. Then if you've done all four this turn, transform Avatar Aang." A strict singleton (`parser_probe.py blocked` = 1 SOLO, 0 also-blocked), so hand-authored; the reusable half is a general **bending event**.
- **`EventType.BENT` + `RulesEngine.record_bend(player, kind, amount=0)`** (in `misc_mixin.py`, beside `collect_evidence`/`forage`/`behold`): stamps `GameState.bends_this_turn` (`{player_id: {kind…}}`, cleared wholesale each `GameEngine.begin_turn` next to `creatures_died_this_turn`) and fires `BENT` carrying `player_id`/`controller_id`/`kind`/`amount`. `kind` ∈ `RulesEngine.BEND_KINDS` (`waterbend`/`earthbend`/`firebend`/`airbend`); an unknown kind is a no-op. `_GROUP_CONTROLLER_EVENT_KEYS["BENT"] = "player_id"`, so a hand-authored `{"subject": "you"}` trigger works exactly like "whenever **you** scry/surveil".
- **All four primitives fire it:**
  - `RulesEngine.earthbend` — at the end of the animation + counters (its `source`'s controller).
  - the **waterbend** additional-cast-cost payment — `GameEngine.cast_spell` fires it right after `obj.additional_cost_paid` is set, when `additional_cast_cost.help_pay_kind == "waterbend"` (RULE 701.67c — "triggers whenever that player pays a waterbend cost"; the cost is folded into the mana total, so there is no earlier discrete moment).
  - **airbend** — `ExileEffect` gained a `bend_kind` param; `handlers._airbend`/`_airbend_trigger_subject` now emit `"bend_kind": "airbend"`, and `ExileEffect._record_bend_if_set` fires `BENT` once per resolution that exiled ≥1 object (the *only* parser-visible change this batch).
  - **firebend** — `effect_binder._kw_firebending` now returns a *second*, ordinary `ATTACKS` trigger carrying `effects.RecordBendEffect(kind="firebend")` alongside the existing mana ability; kept separate so the latter stays a pure RULE 605.4 mana effect and the marker still fires when N is 0 (Firebending X). Attacking with a Firebending creature is how the Avatar set "firebends".
- **The reflexive clause:** `EffectSpec.condition` gained `did_all_bends_this_turn` (`ConditionalEffect._condition_holds`) — the ability controller's `bends_this_turn` set must cover every entry of `BEND_KINDS`. Avatar Aang is `_avatar_aang` in `ability_catalogue/entries_008.py`: one `triggered` spec on `BENT`/`{"subject":"you"}` → `[draw 1, transform (condition: did_all_bends_this_turn)]`. `transform` with no target flips the source DFC (RULE 712.8); the back face "Aang, Master of Elements" rebinds through the ordinary parser fallback (unregistered name), so nothing here authors it.
- **Files:** `models/events.py` (`BENT`), `models/game_state.py` (`bends_this_turn`), `game/rules/misc_mixin.py` (`record_bend`, `BEND_KINDS`), `game/rules/mana_counters_mixin.py` (`earthbend` fire point), `game/engine/casting_mixin.py` (waterbend fire point), `game/engine/turn_loop_mixin.py` (`begin_turn` clear), `game/effects.py` (`ExileEffect.bend_kind`/`_record_bend_if_set`, `RecordBendEffect` + registry, `ConditionalEffect` `did_all_bends_this_turn`), `game/effect_binder.py` (`_kw_firebending` second trigger, `_GROUP_CONTROLLER_EVENT_KEYS["BENT"]`, `RecordBendEffect` import), `game/ability_catalogue/entries_008.py` (`_avatar_aang`), `parser/oracle/catalogue/handlers.py` (`_airbend`/`_airbend_trigger_subject` `bend_kind`), `parser/oracle/spec.py` (`did_all_bends_this_turn` in `_ALLOWED_CONDITION_KEYS`), `parser/oracle/gate.py` (v214).
- **Yield:** +1 (Avatar Aang, via hand-authoring — no card's parser verdict changes). 0 regressed.
- **Tests:** `tests/test_par30_firebending_bending_trail.py` (`record_bend` fires + stamps + rejects unknown kind; `bends_this_turn` cleared on `begin_turn`; each of earthbend / airbend-via-`ExileEffect` / firebending-attack fires `BENT`; a plain exile does *not*; Avatar Aang draws on any one bend, transforms only after all four distinct bends this turn, no transform when one bend is repeated ×4, an opponent's bend doesn't trigger it; hand-authored specs carry the `BENT` trigger). `tests/test_par29_airbend.py` updated for the `bend_kind` param.

- **Also v135 (unrelated to Firebending):** "those creatures" / "each of those creatures" now parse as the RULE 115 previous-target-group pronoun alongside "they" (`_PREV_GROUP_SUBJECT` in the `_PUMP_PREVIOUS_TARGETS_*` / `_PUMP_PREVIOUS_SELECTOR` rows) — Cauldron Haze, Cauldron of Souls. `tests/test_par30_group_and_cast_trigger.py`.
- **Also v136 (PAR-30, the threaten / "it gains haste" restatement tail):** the *singular*-pronoun sibling of the `_PUMP_PREVIOUS_TARGETS_*` family — `_PUMP_PREV_SINGULAR_PT_RE` / `_PUMP_PREV_SINGULAR_KW_RE` (`previous_subject_only`, reusing the same `_pump_previous_targets_*` builders) claim "it / that creature / that permanent / that artifact / that token [also] gets +N/+N [and gains `<kw>`] / gains `<kw>` until end of turn". Two supporting changes make them reachable: (1) `segmenter`'s connector-split loop now **propagates** the previous-subject referent through a split clause that itself consumed the pronoun (`any(s.params.get("previous_subject") …)`) — so "gain control of target creature … . untap that creature. it gets +2/+0 …" keeps the chain onto the third sentence — and only *extends* a chain, never starts one; (2) `_GAIN_CONTROL_HASTE_TAIL_RE` also matches "untap **that permanent**" and a "`, and`" join between the untap and haste clauses. **+50** cache cards, 0 regressed — mostly the broad "put a +1/+1 counter on / deal N damage to / untap target creature. it gains `<kw>` until end of turn" shape (Snakeskin Veil, Gerrard's Command, Rile, Eutropia the Twice-Favored, Malevolent Whispers) and clash "if you win, that creature gets +2/+2 …" payoffs (Fistful of Force). A redundant `tap`(untap)/`pump`(haste) alongside the `gain_control_until_eot` effect on a threaten card is harmless — both use `previous_subject`, no fresh RULE 115 target, and the creature is already untapped / already has haste. The narrower "it gains **haste** until end of turn" threaten tail proper (~63 SOLO) mostly still blocks on antecedent widening (`_gain_control_eot` rejecting a qualified target, an "if you do," wrapper, "create a Blood token" not parsing) — PAR-30. `tests/test_par30_pump_prev_singular.py`.
- **Also v137 (PAR-30, the delayed sac/exile tail — the single biggest RULE 701-trail sub-cluster, ~100 SOLO by substring):** "[Then] sacrifice / exile `<it / that creature / that token / them / those tokens>` at the beginning of [the/your] next end step." One **ungated** `_DELAYED_SAC_EXILE_TAIL_RE` handler → `create_delayed_trigger` (RULE 603.7, `step="end"`, `scope="any"`, inner `sacrifice_specific` / `exile_specific` — the `.objects`-carrying primitives Kiki-Jiki/Twinflame already use). The one new piece is `CreateDelayedTriggerEffect`'s `capture="previous_or_self"`: at arm time it bakes into the inner effect's `.objects` whatever this same resolution's earlier clause chose (`context.previous_targets`, a RULE 115 target) → created (`context.created_objects`, RULE 608.2 — a just-made token or reanimated card) → `[self.source]` (a bare self-subject "sacrifice it" with nothing before it — Brackwater Elemental, Deathknell Kami, Chimeric Coils, Dark Maze). Ungated rather than `previous_subject_only` because the capture no-ops cleanly on an empty chain (the exile→copy connector's own safety) and a create-token antecedent never sets the segmenter's `previous_subject` flag — gating would miss most of the cluster. Composes with the existing kicked-conditional wrapper (In Thrall to the Pit's "if this spell was kicked, sacrifice that creature …" keeps its `condition={"kicked": True}`). **+21** (Tidal Wave, Akoum Stonewaker, Dawn of the Dead, Footsteps of the Goryo, Feral Lightning, Thatcher Revolt, Macabre Mockery, …), 0 regressed — the rest of the ~100 stay blocked on their own *other* clauses (populate/conjure variants, "tapped and attacking", kicked P/T riders). `tests/test_par30_delayed_sac_exile_tail.py`.
- **Also v146 (PAR-30, the "Create a token …. It gains haste until end of turn." tail):** three small pieces. (1) `segmenter._announces_creature_target` now returns True for a `create_token`/`copy_permanent`/`become_copy` spec — the created object is the next clause's "it" — and `PumpEffect.previous_subject` falls back to `GameContext.created_objects` when `previous_targets` is empty (a create clause has no RULE 115 target). (2) The connector-split loop seeds its pronoun chain (`referent`/`referent_selector`) from the caller's `previous_subject`/`previous_selector` instead of always restarting at `False`: a two-sentence wrapper (`_EXILE_THEN_COPY_SENTENCE_RE`, `_with_after_tail`) passes `previous_subject=True` for an "after" span it already knows opens with a referent, and the *first* sub-part must inherit that — this also closed God-Pharaoh's Gift and Séance, whose "…except it's a 4/4 black Zombie. It gains haste…" tail hits exactly this path. (3) `_DELAYED_SAC_EXILE_TAIL_RE` gained a `destroy` verb → a new `destroy_specific` effect (`DestroySpecificEffect`, the destroy sibling of `sacrifice_specific`/`exile_specific`; goes through `RulesEngine.destroy` so a regen shield / indestructible can still save it, unlike sacrifice) — Old Hob, Alleycat Blues' "Destroy it at the beginning of the next end step". **+9** (Harried Dronesmith, God-Pharaoh's Gift, Séance, Mordor on the March, Mardu Charm, Mardu Monument, Mogg Cannon, Rebellion of the Flamekin, Salt Road Skirmish), 0 regressed; verified end-to-end (Harried Dronesmith's ETB Thopter gains haste via `created_objects`). Residue not on "it gains haste": Molten Duplication (needs `{TARGET}` "artifact or creature **you control**" scoping — a shared macro), Old Hob's *other* ability ("target attacking creature **token**" filter), Artistic Process (a modal `choose 1 —` option body). `tests/test_par30_created_token_pronoun.py`.

### Time Travel (RULE 701.56) (PAR-29, PARSER_VERSION 127)

- **What:** The Doctor Who keyword action. `RulesEngine.time_travel(player, times=1)` (in `misc_mixin.py`, beside `behold`): "For each suspended card you own and each permanent you control with a time counter on it, you may add or remove a time counter." **Documented simplification** (no per-object interactive add/remove pick): a **suspended card** the player owns loses one time counter — the acceleration reason to time travel your own suspended spells; if that empties it, `RulesEngine.grant_free_cast_window_from_exile` opens the RULE 702.62a window (and arms `granted_suspend_haste` for a creature) exactly as `SuspendUpkeepEffect` would — and a **Vanishing/Fading**-style permanent (a time counter on a battlefield permanent) the player controls gains one, prolonging it. Both are the beneficial-to-you direction; a time counter on anything else is left alone. `times` repeats the whole pass ("time travel, then time travel" — The Parting of the Ways, from `parse_effect_body`'s `, then` split into two `time_travel` specs).
- **`effects.TimeTravelEffect`** is a bare "you"-subject effect; handler is `_c(r"(?:you )?time travel")` → `EffectSpec("time_travel", {})`.
- **Files:** `game/rules/misc_mixin.py` (`time_travel`), `game/effects.py` (`TimeTravelEffect` + `EffectRegistry`), `parser/oracle/catalogue/handlers.py` (inline `EffectHandler`), `parser/oracle/gate.py` (PARSER_VERSION 127).
- **Yield:** 3 real cache cards newly MODELED (0 regressed) — All of History All at Once, Time Beetle, Wibbly-wobbly Timey-wimey. The 6 ALSO-BLOCKED cards (Coward // Killer, Rotating Fireplace, The Girl in the Fireplace, The Parting of the Ways, …) stay UNMODELED on *other* clauses (an activated-cost restriction, a "becomes a `<subtype>` in addition" body, a modal-chapter block), not on time travel — tracked in PAR-30.
- **Tests:** `tests/test_par29_time_travel.py` (clause parse; real-card `parse_oracle`; execute: accelerates a suspended card and opens the free-cast window at zero; prolongs a Vanishing permanent).

### Face a Villainous Choice (RULE 701.55) (PAR-29, PARSER_VERSION 126)

- **What:** The Doctor Who forced-modal-on-an-opponent action. `RulesEngine.request_villainous_choice(source, controller_id, facing_ids, option_a, option_b, labels)` is the `VoteEffect` APNAP sweep **minus the tally**: each facing player (already resolved and APNAP-ordered by the effect) gets a `villainous_choice` `pending_choice` (`_advance_villainous_choice` opens the next; `resolve_villainous_choice` applies that player's chosen option and re-advances). `GameState._pending_villainous` holds the two serialized option effect-lists. The key move: each option is applied with `_apply_effect_specs(specs, source, targets=[facing])`, so an option's `sacrifice`/`discard`/`lose_life` spec (no selector) lands **on the facing player**, while a "you …" spec (no target) stays on `controller_id`.
- **`effects.FaceVillainousChoiceEffect`** resolves the facing players from `subject`: `"each_opponent"` (APNAP), `"target"` (`targets[0]`), `"trigger_target_player"` (the triggering event's `player_id` — "Whenever ~ deals combat damage to a player, that player faces …"). Registered as `face_villainous_choice`; dispatched from `turn_loop_mixin` as `kind == "villainous_choice"`.
- **Parser (`_face_villainous_choice`, `_VILLAINOUS_HEADER_RE`):** splits "`<subj>` faces a villainous choice — `<A>`, or `<B>`." on `, or ` (tries each occurrence, accepts the partition where *both* halves are modelable). `_villainous_option_specs` mini-parses each option: a "they/that player `<verb>`" clause is retried as "target player `<verb>`s" (3rd-person-singular) so it binds to `targets=[facing]` rather than a stale `selector="event_player"`; a bare edict ("they sacrifice a creature of their choice") maps straight to a player-less `sacrifice` spec (no `SacrificeEffect` change — its `apply` already reads `targets[0]` when no selector is set). **Documented simplification:** RULE 701.55b's "if one option is impossible, they must choose the other" is not enforced — both options are always offered.
- **Bug fixed on the way:** "**you** create a … token **with `<kw>`**" was mis-tagged `creators="each_player"` in `_inline_create_token_params` — the `who` regex group captured "you" and the branch only excluded nothing. Now gated on `"each" in who`. (Any "you create … with keyword" card was making *every* player create the token.)
- **Not done (some closed by ENG-33 below):** cards whose option body still isn't modelable — "you create a token that's a copy of that card" (The Master, Gallifrey's End), "exile cards … until you exile a nonland card, then cast it" (Ensnared by the Mara), "that creature becomes a 1/1 and loses all abilities" (Hunted by The Family), plus the conditional/previous subjects (Davros' "each opponent who lost 3+ life this turn", The Master's "choose an opponent with the most life"). Each blocks on a distinct engine primitive — filed in **MEC-52** (was PAR-30, whose parser trail closed at PARSER_VERSION 216).
- **Files:** `game/rules_engine.py` (`_pending_villainous`), `game/rules/misc_mixin.py` (`request_villainous_choice`/`_advance_villainous_choice`/`resolve_villainous_choice`), `game/engine/turn_loop_mixin.py` (dispatch), `game/effects.py` (`FaceVillainousChoiceEffect` + `EffectRegistry`), `parser/oracle/catalogue/handlers.py` (`_VILLAINOUS_HEADER_RE`/`_villainous_option_specs`/`_face_villainous_choice` + `EffectHandler`; `_inline_create_token_params` `who` fix), `parser/oracle/gate.py` (PARSER_VERSION 126).
- **Yield:** 2 real cache cards newly MODELED (0 regressed) — Damocles Base, Sword of Kang; The Dalek Emperor.
- **Tests:** `tests/test_par29_villainous_choice.py` (edict-vs-lose-life parse; unmodelable-option fail-closed; real-card `parse_oracle`; execute: 3-player `each_opponent` sweep where each opponent applies their own pick via `resolve_pending_choice`, a "you gain life" option landing on the controller not the facing player).

#### Option-body primitives (ENG-33, PARSER_VERSION 129 / 130 / 132)

- **What:** the shipped `face_villainous_choice` / `vote` parsers only claim a card when *every* option/outcome body is modelable. Three general handlers close the recurring gaps — and each unlocks a much larger family of ordinary spells, not just the villainous cards:
  - **targeted-player edict** — `_TARGET_PLAYER_EDICT_RE` → `sacrifice` with the new `SacrificeEffect.target_kind="player"` (a real RULE 115 player target, the single-target sibling of `_SACRIFICE_EDICT_RE`'s `each_player`/`each_opponent` mass form; `apply` already reads `targets[0]` when a `target_spec` is present). "target player/opponent sacrifices [N] [nontoken] creature/artifact/land/permanent [of their choice]" — Diabolic / Chainer's / Sudden Edict, ~13 SOLO.
  - **uncapped / noncreature free-cast** — `FreeCastFromHandEffect` gained `noncreature_only` and made its mana-value cap *optional* (the MEC-20 "Expertise" capped form is unchanged; an uncapped effect offers every nonland hand card). `_FREE_CAST_FROM_HAND_RE` widened for "you may cast a[ noncreature] spell from your hand without paying its mana cost" — Great Intelligence's Plan, Maelstrom Archangel, Yue the Moon Spirit.
  - **put a `<type>` card from hand onto the battlefield** — `_PUT_FROM_HAND_RE` → the existing `PutFromHandOntoBattlefieldEffect`; type words validated against `_PUT_FROM_HAND_TYPE_WORDS` (permanent types + a handful of artifact subtypes), fail-closed on anything else. Dr. Eggman, plus the whole Elvish Piper / Quicksilver Amulet / Master Transmuter / Stoneforge Mystic / Growth Spiral / Sakura-Tribe Scout / Walking Atlas / Krosan Wayfarer family (+26).
- **The 4th named primitive**, "create a token that's a copy of that card", is PAR-18's existing `CopyPermanentEffect(referent="previous")` — nothing new to build in the effect itself. Two parser pieces feed it:
  - **the copy-modifier tail** (PARSER_VERSION 130): "except it's [a] `<P/T>` `<colour>` `<subtype>` [creature] [in addition to its other types]" — `_copy_except_modifier`'s new `_COPY_EXCEPT_PT_RE` branch. `set_power`/`set_toughness`/`add_subtypes` already existed on `CopyPermanentEffect`; colour needed adding — `Card.as_copy(set_colors=...)` (replace the copied card's colour identity outright), threaded through `RulesEngine.copy_permanent` / `GameContext.copy_permanent` / `CopyPermanentEffect.set_colors` / its `EffectRegistry` entry. **Documented simplification:** without "in addition to its other types" the printed clause replaces the copied creature's subtypes rather than adding to them — this always appends (RULE-inexact for tribal synergies only). +1 (Ember Island Production's modal shape).
  - **the two-sentence connector** (PARSER_VERSION 132): "Exile [up to N] target `<X>` card from [a/your] graveyard. [If you do / If you exiled a card this way,] create a token that's a copy of **that card**[, except …]." — the reanimator-token cycle (Ardyn, Anikthea, Séance, God-Pharaoh's Gift, Sauron the Necromancer, Sin, Soul Separator). `segmenter._EXILE_THEN_COPY_SENTENCE_RE` matches the whole span at `parse_effect_body` level (before the connector-split loop shatters it into a bare "if you do, create …" half no handler claims), parsing the exile and the copy independently and requiring the exile to genuinely pick a graveyard card (`_announces_creature_target`, which already recognises the `graveyard_*` target-kind prefix) — the RULE 608.2 pronoun `_apply_effects_partitioned` writes into `GameContext.previous_targets`. The reflexive connector needs **no `pending_choice`**: `CopyPermanentEffect(referent="previous")` already no-ops on an empty `previous_targets`, which is exactly the state the connector gates on; the branch fails closed unless `after` is a copy-of-that-card. "You may exile …" optionality is peeled and re-folded as `optional=True`; `handlers._EXILE_FROM_GRAVEYARD_RE` was widened to accept the untargeted "exile **a** creature card from your graveyard" determiner, not just "target". +1 (Ardyn, the Usurper). The "non-aura enchantment card" filter + "exile X target … for each card exiled this way, …" cluster shipped later at PARSER_VERSION 216 (see "Reanimator-token residue" just below); "create a tapped [and attacking] token", "…and pay its mana cost:" activation cost, and "you create a token that's a copy of that card" as a *villainous option body* (The Master, Gallifrey's End — needs `previous_targets` threaded through `_apply_effect_specs` in the APNAP sweep) remain, as **MEC-52**.
- **Files:** `game/effects.py` (`SacrificeEffect.target_kind`, `FreeCastFromHandEffect.noncreature_only` + optional cap, both `EffectRegistry` entries; `CopyPermanentEffect.set_colors`), `models/card.py` / `game/rules/copies_mixin.py` (`as_copy(set_colors=…)` / `copy_permanent(set_colors=…)`), `parser/oracle/catalogue/handlers.py` (`_TARGET_PLAYER_EDICT_RE`, `_FREE_CAST_FROM_HAND_RE`, `_PUT_FROM_HAND_RE` + `_PUT_FROM_HAND_TYPE_WORDS`, `_copy_except_modifier`/`_COPY_EXCEPT_PT_RE`, `_EXILE_FROM_GRAVEYARD_RE` widened), `parser/oracle/segmenter.py` (`_EXILE_THEN_COPY_SENTENCE_RE` + its `parse_effect_body` branch), `parser/oracle/gate.py` (v129 / v130 / v132).
- **Yield:** +45 (v129, put-`<type>`-from-hand + edict families dominate) / +1 (v130, Ember Island Production) / +1 (v132, Ardyn) cache cards — `parser_probe.py` diff, full cache, 0 regressed each pass.
- **Tests:** `tests/test_eng33_villainous_vote_bodies.py` (v129 bodies + fail-closed cases), `tests/test_copy_except_family.py` (the modifier tail), `tests/test_eng33_exile_then_copy.py` (v132 — the connector: parse of the "if you exiled a card this way" and "you may exile … if you do" forms + the two fail-closed cases (no graveyard antecedent; a non-copy follow-up), real-card `parse_oracle(Ardyn)`, and an end-to-end `_apply_effects_partitioned` execute making a 5/5 black Demon token copy of an exiled graveyard creature).

### Reanimator-token residue — the graveyard-exile-copy cluster (PAR-30 close-out, PARSER_VERSION 216)

- **What:** three cards the ENG-33 connector (above) left `UNMODELED`, each on a small gap around a `CopyPermanentEffect` primitive that already existed. Closes the **parser** side of PAR-30 (PAR-29's trail); what's left of that ticket's residue is engine primitives, tracked as **MEC-52**.
  - **Anikthea, Hand of Erebos** — "exile up to one target **non-Aura enchantment** card from your graveyard. Create a token that's a copy of that card, except it's a 3/3 black Zombie **creature** in addition to its other types." Two pieces: (1) a `non_aura_enchantment` entry in `targeting._GRAVEYARD_TYPE_FILTERS` (`is_enchantment` and no "Aura" subtype on the printed type line) + its `_GRAVEYARD_TYPE_WORD` / `_graveyard_target_kind` wiring in `catalogue/handlers.py` + the German label in `_GRAVEYARD_TYPE_LABELS`; (2) `_COPY_EXCEPT_PT_RE` now captures the "… creature" word and emits `add_types=["Creature"]` when present — without it `Card.as_copy` set `power`/`toughness` on a non-creature original (an enchantment card) and tripped `Card.__init__`'s RULE 208.1 invariant (`as_copy` already flips `is_creature` for a `"creature"` in `add_types`; harmless/idempotent when the original is already a creature, e.g. God-Pharaoh's Gift). The exile→copy segmenter connector + `copy_permanent_previous` handler did the rest. The "enters or attacks" trigger already parsed.
  - **Hour of Eternity** — "Exile X target creature cards from your graveyard. For each card exiled this way, create a token that's a copy of that card, except it's a 4/4 black Zombie." — new `segmenter._EXILE_X_GY_FOR_EACH_CREATE_RE` span (the X-count sibling of `_EXILE_THEN_COPY_SENTENCE_RE`): the exile is `count_selector="source_x_paid"` (the Foggy Swamp Visions idiom), the follow-up `copy_permanent` with `referent="previous_each"` — one copy of *each* exiled card (already an engine primitive).
  - **Midnight Ritual** — same exile, "…create a 2/2 black Zombie creature token." per exiled card. `CreateTokenEffect` gained `count_from_context` — a **closed whitelist** (`_TOKEN_COUNT_CONTEXT_ACCUMULATORS = {"objects_exiled_this_way"}`) so parser-derived text can never name an arbitrary `GameContext` attribute — mirroring the intent of `_resolve_extra_counter_amount`'s own `count_from_context` key (Sunfall's Incubate). The new segmenter span routes an inline-token follow-up onto it.
- **Files:** `game/targeting.py` (`_GRAVEYARD_TYPE_FILTERS["non_aura_enchantment"]`, `_GRAVEYARD_TYPE_LABELS`), `game/effects.py` (`CreateTokenEffect.count_from_context` + `_TOKEN_COUNT_CONTEXT_ACCUMULATORS` + its `EffectRegistry` entry), `parser/oracle/catalogue/handlers.py` (`_GRAVEYARD_TYPE_WORD`, `_graveyard_target_kind`, `_COPY_EXCEPT_PT_RE` + `_copy_except_modifier`), `parser/oracle/segmenter.py` (`_EXILE_X_GY_FOR_EACH_CREATE_RE` + its `parse_effect_body` branch), `parser/oracle/gate.py` (PARSER_VERSION 216).
- **Yield:** +3 (Anikthea, Hand of Erebos; Hour of Eternity; Midnight Ritual) — `parser_probe.py` diff, full cache, 0 regressed. Overall coverage 13,558 / 34,811 (38.9%); Commander-legal 12,976 / 31,830 (40.8%).
- **Tests:** `tests/test_par30_reanimator_token_residue.py` — parse (all three, spec-shape assertions), fail-closed ("non-Aura permanent" stays UNMODELED; a "for each … exiled this way" follow-up the two known shapes don't cover stays UNMODELED), and execute (`_apply_effects_partitioned`: Anikthea makes a 3/3 Zombie *creature* copy of an exiled enchantment card; Hour scales copies with `x_paid`; Midnight makes one 2/2 Zombie per exiled card).

- **MEC-52 (first sub-item) — Sauron, the Necromancer + a RULE 603.4 intervening-if on delayed triggers (PARSER_VERSION 217).** "Whenever Sauron attacks, exile target creature card from your graveyard. Create a **tapped and attacking** token that's a copy of that card, except it's a 3/3 black **Wraith with menace**. At the beginning of the next end step, exile that token **unless Sauron is your Ring-bearer**." Four small pieces:
  - **`CreateDelayedTriggerEffect` / `DelayedTrigger` gained a `condition` dict** — a whitelisted `EffectSpec.condition`-shaped map (`_ALLOWED_CONDITION_KEYS`, unknown keys dropped at construction) re-checked by `GameEngine._fire_delayed_triggers` via a throwaway `ConditionalEffect._condition_holds` against the ability's own source (the first baked effect's `source`) when the delayed ability *would* go on the stack. If it doesn't hold, the ability simply doesn't trigger (RULE 603.4) — the one-shot `DelayedTrigger` is still consumed. This gates the *whole* delayed ability, which is what an "…unless `<X>`" rider on the delayed instruction wants — distinct from a `condition` on an *inner* spec (`build_effects` → `ConditionalEffect`, checked at resolution, and which the `capture` branches would have to reach through).
  - **`_delayed_sac_exile_when_first`** — a when-first sibling of `_DELAYED_SAC_EXILE_TAIL_RE` ("At the beginning of `<the/your>` next end step, sacrifice/exile `<it>`[ unless ~ is your Ring-bearer]"). The verb-first tail form is unchanged; the when-first phrasing was previously intercepted as a triggered-ability line and never reached an effect handler, so it works via the `parse_effect_body` connector-split loop (fine for a `<cost>: <clause>. at the beginning…` body / the exile→copy connector's `after` span). An optional "unless ~ is your Ring-bearer" rider → `create_delayed_trigger`'s new `condition={"is_ring_bearer": False}`. **`capture` choice by subject:** "that token"/"those tokens"/"the token(s)" → `capture="created_objects"` (an earlier clause's *created* thing, never a RULE 115 target it also chose — Sauron exiles a graveyard *card* as its target, so `previous_or_self` would have baked that already-exiled card); "it"/"that creature"/"that permanent" keep `previous_or_self`.
  - **`_COPY_PERMANENT_PREVIOUS_RE` + `segmenter._EXILE_THEN_COPY_SENTENCE_RE`'s `after` anchor** accept a `tapped and attacking |tapped |attacking ` prefix — `CopyPermanentEffect` already took `tapped`/`attacking` (RULE 508.4), only the pronoun-copy recognisers hadn't.
  - **`_COPY_EXCEPT_PT_RE`** accepts a trailing "with `<keyword>`" ("a 3/3 black Wraith **with menace**") → `extra_temp_keywords` (validated through `_token_keywords`, fail-closed on an unknown word), instead of mis-splitting "with menace" into subtypes.
- **Files:** `game/effects.py` (`CreateDelayedTriggerEffect.condition` + registry), `models/game_state.py` (`DelayedTrigger.condition`), `game/engine/turn_loop_mixin.py` (`_delayed_trigger_condition_holds`, `_fire_delayed_triggers` filter), `parser/oracle/catalogue/handlers.py` (`_COPY_PERMANENT_PREVIOUS_RE`, `_COPY_EXCEPT_PT_RE`, `_DELAYED_SAC_EXILE_WHEN_FIRST_RE`/`_delayed_sac_exile_when_first` + `EffectHandler`), `parser/oracle/segmenter.py` (`_EXILE_THEN_COPY_SENTENCE_RE`), `parser/oracle/gate.py` (v217).
- **Yield:** +1 (Sauron, the Necromancer). The when-first delayed handler is a genuine reusable addition but currently solo-unblocks no other card — the rest of that phrasing's cache cluster (Apprentice Necromancer, Momo's Heist, Skirk Alarmist, The Beamtown Bullies, …) is also-blocked on unrelated clauses (turn-face-up-on-target, gain-control chains, reanimate-under-their-control). Overall coverage 13,559 / 34,811 (39.0%); Commander-legal 12,977 / 31,830 (40.8%).
- **Tests:** `tests/test_mec52_delayed_trigger_condition.py` — parser (Sauron spec shape; the when-first handler in a connector chain; the "unless" rider; fail-closed on an unrelated end-step clause), engine (`condition=None` fires; `{"is_ring_bearer": False}` does *not* fire while the source is the Ring-bearer but the trigger is still consumed; fires when it isn't), and execute (Sauron's whole trigger — tapped/attacking 3/3 Wraith copy with menace, delayed exile armed with the condition, token exiled at the end step).

- **MEC-52 (Davros, Dalek Creator) — `GameState.life_lost_this_turn` (PARSER_VERSION 218).** "At the beginning of your end step, create a 3/3 black Dalek artifact creature token with menace **if an opponent lost 3 or more life this turn**. Then **each opponent who lost 3 or more life this turn** faces a villainous choice — you draw a card, or that player discards a card." The whole card needed one new piece of state and two thin hooks onto it:
  - **`GameState.life_lost_this_turn`** — the exact mirror of `life_gained_this_turn`: a `{player_id: int}` map bumped in `RulesEngine.lose_life` (which its own docstring already calls "the single choke point for life loss, whatever causes it — damage, a life-paid cost, a direct 'loses N life' effect"), so this one site covers every path. Reset for *every* player each `GameEngine.begin_turn` (not just the incoming active one, unlike `life_gained_this_turn` whose consumers are all own-turn attack triggers) — Davros's end-step trigger reads each *opponent's* value.
  - **`ConditionalEffect._condition_holds` key `opponent_lost_life_this_turn_at_least`** (`_ALLOWED_CONDITION_KEYS`) — true if *any* opponent of the ability's controller is at/past the threshold. Reached via a new segmenter **suffix** rule `_OPPONENT_LOST_LIFE_SUFFIX_RE` ("`<effect>` if an opponent lost N or more life this turn"), checked at the *top* of `parse_effect_body` — before `match_clause` / the connector split — so the base `create_token` handler can't claim the clause *without* the gate (a wrong-but-modeled unconditional token). Fail-closed: a bare later ". then `<Y>`" clause split off by the period connector does not inherit the condition.
  - **`FaceVillainousChoiceEffect.subject_min_life_lost`** — narrows an `"each_opponent"` sweep to opponents at/past the threshold. `_VILLAINOUS_HEADER_RE`'s `subj` group grew an optional "each opponent **who lost N or more life this turn**" branch (`mll`), mapped to `subject="each_opponent"` + `subject_min_life_lost=N`. The option bodies ("you draw a card" / "that player discards a card") already parsed.
- **Files:** `models/game_state.py` (`life_lost_this_turn`), `game/rules/damage_death_mixin.py` (`lose_life` bump), `game/engine/turn_loop_mixin.py` (`begin_turn` reset), `game/effects.py` (`ConditionalEffect` key; `FaceVillainousChoiceEffect.subject_min_life_lost` + registry), `parser/oracle/spec.py` (`_ALLOWED_CONDITION_KEYS`), `parser/oracle/segmenter.py` (`_OPPONENT_LOST_LIFE_SUFFIX_RE`), `parser/oracle/catalogue/handlers.py` (`_VILLAINOUS_HEADER_RE` / `_face_villainous_choice`), `parser/oracle/gate.py` (v218).
- **Yield:** +1 (Davros, Dalek Creator). Overall coverage 13,560 / 34,811 (39.0%); Commander-legal 12,978 / 31,830 (40.8%). `GameState.life_lost_this_turn` is broadly reusable (many "an opponent/a player lost life this turn" cards) — grep for it before adding another life-loss tracker.
- **Tests:** `tests/test_mec52_davros_life_lost.py` — the counter (bumps on `lose_life` and damage, resets every player at `begin_turn`), parser (Davros spec shape; the suffix condition doesn't leak onto a later ". then" clause), and execute (conditional token only when an opponent is past the threshold; the villainous sweep skips opponents who didn't lose enough and is empty when nobody qualifies; Davros's whole end-step trigger end-to-end).

- **MEC-52 (The Master, Gallifrey's End) — hand-authored, + two general villainous-choice primitives (no `PARSER_VERSION` bump).** "Make Them Pay — Whenever a nontoken artifact creature you control dies, you may exile it. If you do, choose an opponent with the most life among your opponents. That player faces a villainous choice — They lose 4 life, or you create a token that's a copy of that card." The DIES group trigger with a nontoken+artifact filter and the "you may exile **it**" reflexive on the dying creature are past the parser's villainous grammar, so it's a `game/ability_catalogue.py` entry (`entries_016.py`), `optional=True` for the "if you do" gate, `EffectSpec("exile", {"target_kind": "trigger_subject"})` for the dying creature. Three reusable engine pieces it drove:
  - **`ExileEffect`'s trigger-subject branch now seeds `context.previous_targets`** with the exiled object — RULE 608.2's "it"/"that card" referent for a following clause, the same thing the RULE 115 targeted branch leaves behind via `_apply_effects_partitioned`.
  - **`FaceVillainousChoiceEffect.subject == "opponent_with_most_life"`** — RULE 701.55's pre-selection (ties → first in APNAP order, a documented simplification of the printed "your choice").
  - **`FaceVillainousChoiceEffect.capture_previous`** — the villainous choice resolves *after* it's answered (a fresh `_apply_effect_specs`, this resolution's context long gone), so option B's `copy_permanent` `referent="previous"` would have nothing to read. With the flag, `apply` snapshots `context.previous_targets` (the just-exiled card) into `request_villainous_choice(captured_previous=…)`; `resolve_villainous_choice` re-seeds `self.context.previous_targets` around that option's `_apply_effect_specs` call. Also fixed on the way: `CopyPermanentEffect` in a referent/self mode (`target_spec is None`) was grabbing a stray `targets[0]` — here the *facing player* the villainous option is applied against — instead of its referent; it now ignores `targets` in that mode (the same gotcha `ExileEffect`'s self mode already documents, Mizzix's Mastery).
- **Files:** `game/effects.py` (`ExileEffect` trigger-subject `previous_targets`; `FaceVillainousChoiceEffect.subject`/`capture_previous` + registry; `CopyPermanentEffect` stray-`targets` fix), `game/rules/misc_mixin.py` (`request_villainous_choice`/`resolve_villainous_choice` thread `captured_previous`), `game/ability_catalogue/entries_016.py` (the entry).
- **Yield:** +1 (The Master, Gallifrey's End). Overall coverage 13,561 / 34,811 (39.0%); Commander-legal 12,979 / 31,830 (40.8%). `subject="opponent_with_most_life"` and `capture_previous` are reusable for the rest of the villainous residue.
- **Tests:** `tests/test_mec52_the_master_gallifreys_end.py` — registration/bind, the DIES trigger picks the highest-life opponent and option A drains 4, option B makes a copy of the exiled artifact creature under the controller, and a *token* artifact creature dying does not trigger (the nontoken filter).

- **PAR-30 close-out — RULE 701 keyword-action trail is verified complete.** Every keyword action has parser recognition *and* an engine primitive (audited action-by-action while closing PAR-29/PAR-30): Attach, Counter, Create, Destroy, Discard, Exile, Fight, Goad, Investigate, Mill, Regenerate, Scry, Search, Shuffle, Surveil, Tap/Untap, Transform/Convert, Proliferate, Monstrosity, Adapt, Amass, Manifest/Cloak, Manifest Dread, Venture, The Ring Tempts You, Connive, Discover, Explore, Populate, Bolster, Support, Suspect, Detain, Endure, Recruit, Collect Evidence, Forage, Behold, Learn, Incubate, Clash, Blight, Earthbend, Airbend, Vote, Face a Villainous Choice, Time Travel, Exchange Control, Exchange Life Totals — plus engine-action verbs with no oracle grammar (Activate/Cast/Play) and variant-subsystem ones (Planeswalk/Set in Motion/Abandon, Meld). Harness (701.64) / Heal (701.69) have ~0–3 cache cards and no dedicated handler — trivially small if one ever prints. Assemble (701.45) is out of the CR; Open an Attraction / Roll to Visit (701.51/52) are the Attractions non-goal; Teams / Get a Life (RULE 810) is a permanent non-goal. The card-by-card *effect-body grammar around* the keyword actions is ordinary long-tail work now (PAR-31…PAR-53 clusters); the six cards that still block on a distinct engine primitive are **MEC-52**.

### Vote (RULE 701.38) (PAR-29, PARSER_VERSION 124) + outcome bodies that needed new primitives (MEC-46, PARSER_VERSION 173)

- **What:** The Conspiracy / "Will of the Council" / "Council's Dilemma" voting subsystem. `RulesEngine.request_vote(source, controller_id, options, majority_specs?, tie_index?, per_vote_specs?)` runs an APNAP sweep — every living player, from the active player in turn order, gets a `vote` `pending_choice` (`_advance_vote` opens the next; `resolve_vote_choice` records the pick and re-advances) — the same chain-of-single-player-choices shape `request_all_players_decline_or` uses, over the same `_apply_effect_specs` tail. `GameState._pending_vote` holds the remaining voters, the running per-option tally, and the serialized outcome. Once everyone has voted, `_tally_and_apply_vote` resolves one of two outcome shapes:
  - **majority** (`majority_specs` — one serialized effect list per option): the strict vote leader's list is applied; `tie_index`'s branch wins if no option leads alone (RULE 701.38d, "or the vote is tied").
  - **per-vote scaling** (`per_vote_specs` — `[{option, effects, scale}]`): each entry's effects apply once with every `count`/`amount` param multiplied by `scale` × that option's vote total.
  `effects.VoteEffect` binds it (a bare "you"-subject effect; the outcome is applied with the caster as target). Dispatched from `turn_loop_mixin` as `kind == "vote"`.
- **Parser:** `_vote_majority` and `_vote_per_vote` (both on `_VOTE_HEADER_RE`, "starting with you, each player votes for `<opts>`. `<rest>`"). `_split_vote_options` handles "A or B" / "A, B, or C". Each outcome body is recursively `parse_effect_body`'d and rejected if it declares a RULE 115 target (can't resolve off-stack, same guard as `_pay_cost_then_general`) — narrowed in v164 to spare a `players`-scoped (untargeted, Living Death) branch. **v165:** `_vote_per_vote` now *carries* a leading "each player / each opponent" subject off segment 0 onto a subject-less later segment split from it by a bare "and" (Capital Punishment — "each opponent sacrifices … for each death vote **and** discards a card for each taxes vote", the discards clause still each opponent's); "you" stays fine as its own segment subject, and a later segment naming a *different* scoped subject still fails closed. **v166:** a plain "take an extra turn after this one" body handler wired to the pre-existing `take_extra_turn` effect type (nothing emitted it before) — closes Plea for Power's modelable vote half plus a broad Time Walk / Temporal Manipulation spill (see the Extra turns entry); `_vote_per_vote` fail-closes on a `take_extra_turn` body (no count param to scale by tally — Expropriate). **v167:** two no-param effect types `planeswalk` (RULE 901.10, `effects.PlaneswalkEffect` → `RulesEngine.planeswalk`) and `chaos_ensues` (RULE 901.13, `ChaosEnsuesEffect` → the new `RulesEngine.trigger_chaos`, factored out of `roll_planar_die` and now a genuine no-op with no active plane) — `_vote_majority`'s body parse claims Path of the Animist / Path of the Enigma; a bare "planeswalk" body is also a standalone handler. Fullmatch-only: "planeswalk to `<plane>`" / "you may planeswalk" stay UNMODELED.
- **MEC-46 (PARSER_VERSION 173):** the four remaining outcome shapes, each an engine primitive + oracle handler on the shared `_VOTE_HEADER_RE`:
  - **Per-winning-option** (`request_vote(winner_specs=...)`): like `majority_specs` but `_tally_and_apply_vote` applies **every** option tied for most votes, not only a sole leader. Council Guardian's "gains protection from each color with the most votes" grant is an **indefinite RULE 611 continuous effect keyed to the source, no duration** — `GrantUntilEffect` gained a `self_subject` mode (scope `affects="objects"` / `object_ids=[source]` with no RULE 115 target) and the parser emits, per leading colour, `grant_until` → `grant_protection_static` with `duration="rest_of_game"`. `_vote_winner_protection`. Closes **Council Guardian**.
  - **Targeted-tally** (`RulesEngine.request_object_vote` + `_pending_object_vote` + `vote_object` `pending_choice` + `_tally_and_apply_object_vote`): each voter picks one of a candidate *object* set (options carry `instance_id` + `card_id`), then `outcome` (`"exile"`/`"return_to_hand"`) is applied to every object tied for most votes (RULE 701.38d). `effects.ObjectVoteEffect` (`pool="nonland_permanents_opponents"` — board scan not controlled by you; or `pool="graveyard_cards"` + `card_types` — your graveyard filtered by type word). `_vote_object`. Closes **Council's Judgment**, **Custodi Squire**.
  - **Forced vote** (`GameState.forced_vote_controller_id`, `effects.SetForcedVoterEffect`): while set for the turn, `_advance_vote` / `_advance_object_vote` redirect every ballot's `pending_choice["player_id"]` to that player (real voter's name in the prompt via `_vote_decider`); cleared at cleanup (RULE 514.2) like every other "this turn" flag. Parser: `_forced_vote` on `"you choose how each player votes this turn"`. Closes **Illusion of Choice**; narrows Grudge Keeper / Erestor.
  - **Expropriate** (`_vote_expropriate`): time body → `take_extra_turn` gained a `count` param (`_tally_and_apply_vote`'s per-vote loop already scales `count` by tally → N extra turns). Money body → a new `per_vote_specs` entry shape `{"option": i, "per_voter_gain_control": true}`: `_advance_expropriate_gain_control` chains one `request_choose_objects(action="gain_control")` pick per money **ballot** (recorded in `_pending_vote["ballots"]`), the remaining queue carried in the choice's `then_specs` (`effects.ExpropriateGainControlEffect`) so it survives `clone()`. `gain_control` is a new `CHOOSE_OBJECT_ACTIONS` verb — an indefinite `controller_id` reassignment (RULE 701.38 outcome body, no duration), the `GainControlBySourceEffect` shape. Plus the trailing `exile ~` self-exile. Closes **Expropriate**.
  - **Galadriel, Elven-Queen** (parser residue): `_add_counters_ring_bearer` ("put a +1/+1 counter on your Ring-bearer" → `AddCountersEffect.ring_bearer`, resolved against `continuous.ring_bearer_of`); `the_ring_tempts_you` bare body already parsed. The real blocker was the RULE 603.4 intervening-if "if another Elf entered the battlefield under your control this turn" — `segmenter._ANOTHER_SUBTYPE_ENTERED_IF_RE` peels it off a phase-trigger body into `trigger["active_if"]` = `static_conditions`' new `another_subtype_entered_this_turn` kind (a live battlefield scan for a non-source permanent you control that entered this turn, `obj.turn_entered == state.turn_number` — no new per-turn tracker). Closes **Galadriel, Elven-Queen**.
- **Bots:** `Bot.answer_choice` picks a `vote` / `vote_object` option at random (`self._vote_rng`, seeded off the bot's id so a bot-vs-bot table replays identically) — a vote has no least-change default the way a "you may" prompt does. All three bot kinds inherit it.
- **Frontend:** `gameBoardView.js` — `vote` / `vote_object` / `villainous_choice` `CHOICE_ICONS` entries (🗳️ / 😈); `vote_object` routed to the scry/surveil face-thumbnail renderer (`lookTopChoiceHtml`) since its options carry `card_id`. The `vote` modal already rendered generically.
- **Yield:** +6 real cache cards MODELED (Council Guardian, Council's Judgment, Custodi Squire, Illusion of Choice, Expropriate, Galadriel, Elven-Queen); 0 regressed.
- **Tests:** `tests/test_mec46_vote_outcomes_family.py` — parse (all 6 real cards MODELED; `winner_specs` / `vote_object` / Expropriate `per_vote_specs` spec shapes; Galadriel `active_if` + dominion branch); execute (winner-specs grants indefinite protection from every leader and survives cleanup; object-vote exiles / returns the most-voted; forced voter answers every ballot then clears at cleanup; Expropriate queues N extra turns / opens a per-money-ballot gain-control; `another_subtype_entered_this_turn` condition; ring-bearer counter; bot random-vote spread + reproducibility; winner-specs no-op with `None` entries).
- **Files:** `models/game_state.py` (`_pending_vote`/`_pending_object_vote` — actually on `RulesEngine.__init__`, `game/rules_engine.py`; `forced_vote_controller_id`), `game/rules/misc_mixin.py` (`request_vote`/`_advance_vote`/`_vote_decider`/`resolve_vote_choice`/`_tally_and_apply_vote`/`_advance_expropriate_gain_control`/`request_object_vote`/`_advance_object_vote`/`resolve_object_vote_choice`/`_tally_and_apply_object_vote`; `CHOOSE_OBJECT_ACTIONS` + `_apply_chosen_object` `gain_control`), `game/engine/turn_loop_mixin.py` (`vote`/`vote_object` dispatch; `_step_cleanup` clears `forced_vote_controller_id`), `game/effects.py` (`VoteEffect.winner_specs`, `ObjectVoteEffect`, `SetForcedVoterEffect`, `ExpropriateGainControlEffect`, `TakeExtraTurnEffect.count`, `GrantUntilEffect.self_subject`, `AddCountersEffect.ring_bearer` + `EffectRegistry`), `game/static_conditions.py` (`another_subtype_entered_this_turn`), `parser/oracle/catalogue/handlers.py` (`_vote_winner_protection`/`_vote_object`/`_vote_expropriate`/`_forced_vote`/`_add_counters_ring_bearer` + `EffectHandler`s), `parser/oracle/segmenter.py` (`_ANOTHER_SUBTYPE_ENTERED_IF_RE` in the phase-trigger branch), `parser/oracle/gate.py` (PARSER_VERSION 124 → 173), `services/bots.py` (`Bot.answer_choice` random vote), `frontend/src/js/gameBoardView.js` (`CHOICE_ICONS`, `vote_object` thumbnails).
- **Yield:** 5 real cache cards newly MODELED (`parser_probe.py` diff / `coverage_report.py --no-db`, full cache, 0 regressed) — Bite of the Black Rose, Coercive Portal, Tyrant's Choice (majority), Lieutenants of the Guard, Orchard Elemental (per-vote).
- **Tests:** `tests/test_par29_vote.py` (majority + per-vote parse; adversarial 3-option / permanent-vote / carried-subject rejects; real-card `parse_oracle`; execute: 2-player APNAP sweep via `resolve_pending_choice`, majority leader branch, tie → `tie_index`, per-vote count/amount scaled by tally).

### Airbend (RULE 701.65) (PAR-29, PARSER_VERSION 123) + qualifier widening & trigger-subject form (PAR-30, PARSER_VERSION 144) + airbend-a-spell — PAR-30 Airbend residue cluster closed (PARSER_VERSION 145)

- **What:** The second Avatar: The Last Airbender bending action. "Airbend [up to N] target `<X>`" = "Exile it. While it's exiled, its owner may cast it for {2} rather than its mana cost." Built almost entirely on existing infra: `ExileEffect`'s `grant_owner_play_permission` already stamps `GameState.exile_cast_condition` (owner may cast from exile, gated by `GameEngine._has_conditional_exile_permission`). The one new piece is the **fixed alternative cost**: `ExileEffect.owner_play_permission_cost` (a mana string) stamps a new `GameState.exile_cast_cost_override` (`instance_id → "{2}"`), which `GameEngine.effective_cast_cost` substitutes for the printed cost while the card is in the exile zone — the same substitution point (and reduction/tax-still-apply-on-top behaviour) Flashback/Escape's graveyard alt cost already uses. Like `exile_cast_condition`, keyed by `instance_id` and never swept (a cast card is a new object per RULE 400.7, so the stale entry is inert).
- **Parser (v123):** `_airbend` (`_AIRBEND_RE`) matches `airbend [up to N] target (nonland permanent|creature[s])` → `EffectSpec("exile", {target_kind, count?, optional?, grant_owner_play_permission: True, owner_play_permission_cost: "{2}"})`. The `exile` registry factory gained the `owner_play_permission_cost` passthrough.
- **Qualifier widening & trigger-subject form (PAR-30, v144):** `_AIRBEND_RE` widened to "[up to N / exactly N / any number of] [other / another] target `<X>` [you control]" → the right source-scoping/-excluding `ExileEffect` `target_kind` (`creature_you_control` / `other_creature_you_control` / `nonland_permanent_you_control`; "any number of" → `count=10, optional=True`). New `_AIRBEND_TRIGGER_SUBJECT_RE` ("airbend that creature / that permanent / it") → `EffectSpec("exile", {target_kind:"trigger_subject", …})` (MEC-38 — reads the firing event's own `instance_id`), for **Monk Gyatso**'s "you may airbend that creature" on a group `BECOMES_TARGET` trigger (the "you may" is peeled by the BECOMES_TARGET dispatch's own `_peel_optional`). **Engine gap fixed:** `ExileEffect`'s `trigger_subject` branch did the exile but skipped every post-exile rider — the owner-play-permission stamp, the free-cast window, the import tax — so an airbend-that-creature would have exiled with no recast permission. Extracted the rider block into a shared `_post_exile(context, target)` helper both the RULE 115 targeted branch and the trigger-subject branch call.
- **Airbend a spell (PAR-30, v145) — cluster closed:** "airbend up to one other target creature **or spell**" (Aang, Swift Savior). `_AIRBEND_RE` gained an `or spell` tail → `target_kind="spell_or_creature"` (the MEC-43 Unsubstantiate targeting union; a `nonland permanent … or spell` shape fails closed, no real card prints it) + a new `ExileEffect.spell_or_permanent` flag: a chosen target that is a live spell on the stack is pulled off it via `RulesEngine.move_spell_off_stack(item, "exile")` (RULE 400.1 — it never resolves) instead of `context.exile`, then the same `_post_exile` recast-permission riders apply. Mirrors `ReturnToHandEffect`'s own `spell_or_permanent` (Unsubstantiate). **The PAR-30 Airbend residue cluster is now closed.**
- **Bending-verb trigger (Avatar Aang) — closed PARSER_VERSION 214:** `EventType.BENT` now fires from every bending primitive (airbend included, via `ExileEffect.bend_kind`). See the Firebending section's "whenever you … bend trigger" entry.
- **Files:** `models/game_state.py` (`exile_cast_cost_override`), `game/effects.py` (`ExileEffect.owner_play_permission_cost` + registry passthrough; v144 `_post_exile` helper shared by the trigger-subject branch; v145 `ExileEffect.spell_or_permanent` + stack-spell branch + registry passthrough), `game/engine/casting_mixin.py` (`effective_cast_cost`), `parser/oracle/catalogue/handlers.py` (`_AIRBEND_RE`/`_airbend`, v144 widening + v145 `or spell` tail; `_AIRBEND_TRIGGER_SUBJECT_RE`/`_airbend_trigger_subject` + `EffectHandler`s), `parser/oracle/gate.py` (PARSER_VERSION 123 / 144 / 145).
- **Yield:** v123 — 3 real cache cards (Airbending Lesson, Glider Staff, Whirlwind Technique). v144 — +2 SOLO (Monk Gyatso, Airbender's Reversal); the airbend clause also stops blocking Aang Airbending Master / Aang the Last Airbender / Appa Loyal Sky Bison / Appa Steadfast Guardian (each still UNMODELED on its own other clauses). v145 — +1 (Aang, Swift Savior). 0 regressed each pass.
- **Tests:** `tests/test_par29_airbend.py` (v123 — clause forms incl. the "creature or spell" adversarial reject + real-card `parse_oracle` + execute: exile → owner-only cast-from-exile permission at a fixed {2}, not the printed {4}{G}{G}; v144 — every qualifier form parses to the right `target_kind`, "airbend that creature"/"airbend it" → `trigger_subject`, Monk Gyatso + Airbender's Reversal MODELED, and execute: a `BECOMES_TARGET` trigger firing with the ally's `instance_id` exiles the ally and stamps its `{2}` recast override; v145 — the "creature or spell" form parses to `spell_or_creature`/`spell_or_permanent`, and execute end-to-end: a Lightning Bolt on the stack is pulled off it into exile with a `{2}` recast override, and the same effect still exiles a battlefield creature).

### Waterbend (RULE 701.67) (ENG-32, PARSER_VERSION 131) + optional-additional-cost-paid tracker (PAR-30, PARSER_VERSION 155)

- **What:** the last of the "bending quartet". The activated `waterbend {N}:` cost was never the blocker — the segmenter's `_COST_LOOKS_REAL` sniff already accepts the `{N}` brace, so "Waterbend {3}: `<body>`" bound as a plain `{3}` activated ability all along (the word "Waterbend" is noise, and RULE 701.67's Convoke-style "tap your artifacts and creatures to help" helper is a **documented simplification**, dropped — `ActivationCost.help_pay_kind="waterbend"` records it, nothing consumes it). What the cards were actually blocked on was their **effect bodies**, all built here as general primitives:
  - **base P/T set with a duration** — `_BASE_PT_UNTIL_EOT_RE` ("~ / creatures you control ha[s|ve] base power and toughness N/M until end of turn", literal or `{X}`) → `grant_until` parking a resolve-time layer-7b `pt_set` `StaticAbility` in `GameState.floating_statics`. `GrantUntilEffect.apply` resolves an `"x"` sentinel in the nested `static.params` against `GameObject.x_paid` (`RulesEngine._substitute_x` only walks a one-shot effect's own magnitude fields, not a grant's payload). Flexible Waterbender, Katara Water Tribe's Hope, Biomass Mutation.
  - **bare "can't be blocked this turn"** — `_CANT_BE_BLOCKED_TURN_RE` ("~ / target creature can't be blocked this turn", no P/T delta — that's `_PUMP_UNBLOCKABLE_RE`) → `UnblockableEffect`, given a new `target_kind=None` self mode for Giant Koi's own activated ability. Unlocked a large non-Waterbend family too (Slip Through Space, Infiltrate, Ashiok's Skulker, Key to the City, Suspicious Bookcase, …).
  - **"enchanted creature's owner shuffles it into their library"** — `_SHUFFLE_ENCHANTED_INTO_LIBRARY_RE` → `ShuffleSelfIntoLibraryEffect` gained a `subject="attached_permanent"` mode (re-reads the Aura's `attached_to` at resolution, calls `RulesEngine.shuffle_into_library` on the host). Watery Grasp.
  - **mandatory "as an additional cost to cast this spell, waterbend {N}"** — `AbilitySpec.additional_cost` gained a `{"waterbend": N}` key (`_ADDITIONAL_COST_WATERBEND_RE`, `spec.py` validation); `parse_activation_cost` turns it into `ActivationCost(mana={N}, help_pay_kind="waterbend")`; `casting_mixin.effective_cast_cost` folds the `{N}` generic into the spell's total (so `can_cast`'s pool check and `_auto_tap_for_cast_if_needed` both see it, and `_pay_additional_cast_cost` — which has no mana branch — doesn't double-charge). Water Whip, Benevolent River Spirit.
- **v155 — the Kicker-shaped optional-additional-cost-paid tracker (PAR-30).** RULE 601.2b's "as an additional cost to cast this spell, **you may** `<waterbend {N}/blight N/behold X/sacrifice …>`." — the general optional-additional-cost primitive the "Not done" note below had flagged as unbuilt for four Waterbend cards, and which ~12 cache cards across four keyword families want.
  - **Parser.** `segmenter._ADDITIONAL_COST_OPTIONAL_PREFIX_RE` strips a leading "you may " off the `_ADDITIONAL_COST_LINE_RE` cost run and sets a new `AbilitySpec.additional_cost_optional` bool alongside the existing `additional_cost` dict (kind-agnostic — the whole `_additional_cost_dict` vocabulary, not just waterbend). `_ADDITIONAL_COST_PAID_CONDITION_RE` ("if this spell's/its/her/… additional cost was paid, `<rest>`") recurses the rest through `parse_effect_body` and tags each spec `condition={"additional_cost_paid": True}` — mirroring `_KICKED_CONDITION_RE`'s "wrap the rest, tag the condition" idiom exactly; the "…, `<effect>` **instead**" amount-override shape fails `match_clause` on `rest` and stays unclaimed, same as "if kicked … instead".
  - **Effect.** `EffectSpec.condition`'s new `"additional_cost_paid"` key (whitelist + bool validation in `spec.py`); `ConditionalEffect._condition_holds` reads `GameObject.additional_cost_paid`, the generic sibling of the `"bargained"` branch (`False` = the "unless … paid" negative).
  - **Casting.** `GameObject.additional_cost_paid` (a per-cast record, cleared in `reset_for_new_object` next to `buyback_paid`), set at cast time by `casting_mixin.cast_spell` — `True` for a mandatory additional cost always, for an *optional* one only when the caller chose the new `pay_additional=True` cast variant. `pay_additional` is threaded through `can_cast` / `effective_cast_cost` (which folds the optional cost's mana into the total only when it's set) / `cast_spell` / `_cast_current_face` / `_auto_tap_for_cast_if_needed` / `_pay_additional_cast_cost` (early-returns for a declined optional cost so a sacrifice/discard portion doesn't fire either) / `GameSession._dispatch_cast_spell`. `effect_binder.attach_to_object` copies `spec.additional_cost_optional` onto `GameObject.additional_cast_cost_optional`.
  - **Offer.** `legal_actions_mixin._offer_cast` appends a second `_cast_action(pay_additional=True)` entry alongside the plain one whenever the spell has an optional additional cost and `can_cast(pay_additional=True)` — the same "alongside, never in place of" shape as evoke/help_pay. The plain (decline) offer is never locked by an optional additional cost.
  - **Yield:** +1 (Requiting Hex — "you may blight 1" + "if this spell's additional cost was paid, you gain 2 life"), 0 regressed. The four Waterbend cards this was filed for each still need their own effect body (see below).
- **v158 — Katara, Seeking Revenge closed.** Both its remaining clauses rode primitives from v155–156. "**~ gets +P/+T for each `<subtype>` card in your graveyard**" (`static_handlers._SELF_ANTHEM_FOR_EACH_GY_SUBTYPE_RE`) → a self `anthem` scaled by `continuous.count_selector`'s new `<subtype>_cards_in_your_graveyard` prefix branch — a live type-line scan, the sibling of v156's `subtype_in_graveyard` gate; the explicit `creature_cards_in_your_graveyard` row above it keeps its own `Card.is_creature` check. "**`<effect>` unless `<its>` additional cost was paid**" (`segmenter._ADDITIONAL_COST_NOT_PAID_SUFFIX_RE`) → the negative, *suffix* form of v155's `additional_cost_paid` `EffectSpec.condition`, checked *after* the connector split so it binds only to its own clause. +7 — Katara plus every "+X/+X for each `<type>` card in your graveyard" beater the count-selector unlocked (Knight of the Reliquary, Fiend Artisan, Liliana's Elite, Salvage Slasher, Wight of the Reliquary, Madame Hydra Reanimated). `tests/test_par30_for_each_graveyard_subtype.py`.
- **v215 — Waterbend residue, first pass (PAR-30).** Three cluster wins the residue cards (and many others) were blocked on:
  - **"Whenever you / an opponent draws their second card each turn, …"** — `segmenter._DRAW_CARD_TRIGGER_NTH_RE` (the draw-side sibling of `_CAST_SPELL_TRIGGER_NTH_RE`, reusing its closed ordinal→int map) emits `{"event": "DRAW", "condition": {"subject": …}, "is_nth_draw_this_turn": N}`. The engine predicate (`effect_binder`, `GameState.cards_drawn_this_turn`, RULE 120.3) already existed (Faerie Mastermind's hand-authored shape); this is purely the recognizer. **~+35**, closes **The Unagi of Kyoshi Island** (its Ward—Waterbend {4} already resolved to a plain `{4}` ward via the keyword text-cost fallback — the waterbend helper is the same documented-simplification drop as every other waterbend cost).
  - **"[another/other] target permanent you control"** → the real `permanent_you_control` target kind (`_TARGET_ROWS` row, above the bare "another target permanent" row; `_TAP_TARGET_KINDS` gained it). Closes **North Pole Patrol**'s "{T}: Untap another target permanent you control".
  - **"up to one other target nonland permanent"** → a new `_TARGET_ROWS` row (`(?:another|other) target nonland permanent` → `nonland_permanent`, RULE 109.5 adds no distinct kind). Closes **Invasion Submersible**'s ETB.
  - **waterbend {X}** mandatory additional cost — `_ADDITIONAL_COST_WATERBEND_RE` now matches `{X}` → `{"waterbend": "x"}`, and `legal_actions_mixin` surfaces `has_x`/`max_x` off a *mandatory* variable additional cost (`effective_cast_cost` already folds `additional_cast_cost.mana.with_x(x)`; `cast_spell` stamps `x_paid`, which the body reads). Verified end-to-end: a spell whose only {X} is `waterbend {X}` announces X, pays `{X}` on top of the printed cost, and its "Draw X cards" body draws X. This is the announcement plumbing **Crashing Wave / Foggy Swamp Visions / Waterbender's Restoration** need — their *bodies* are still bespoke (see BACKLOG).
  - **Files:** `parser/oracle/segmenter.py` (`_DRAW_CARD_TRIGGER_NTH_RE` + dispatch, `_ADDITIONAL_COST_WATERBEND_RE` `{X}`), `parser/oracle/catalogue/subgrammars.py` (`permanent_you_control` + `other target nonland permanent` rows), `parser/oracle/catalogue/handlers.py` (`_TAP_TARGET_KINDS`), `game/engine/legal_actions_mixin.py` (`has_x` off a mandatory variable additional cost), `parser/oracle/gate.py` (v215).
  - **Yield:** +45 cache cards, 0 regressed. `tests/test_par30_waterbend_residue.py`; `tests/test_eng32_waterbend.py` updated (the `{X}` form is now claimed).
- **v216 (no PARSER_VERSION bump — engine primitives + hand-authored) — Waterbend residue bodies, batch.** Eight of the nine residue cards, hand-authored (`ability_catalogue/entries_016.py`) over new/widened engine primitives:
  - **`TemporaryPlayerTrigger` gained a duration + a scope axis.** `duration="this_turn"` (armed `"active"` immediately, dropped at the next `EventType.TURN_BEGIN` — the existing `active_since_turn > install_turn` check *is* "until end of this turn") and `event_player_scope="any"` (fire on every matching `event_type`, not only when it names `player_id`). `InstallTemporaryPlayerTriggerEffect` gained `recipient="controller"`. Together: **Ruinous Waterbending** — "All creatures get -2/-2" (parses on its own) + `EffectSpec("install_temporary_player_trigger", …, condition={"additional_cost_paid": True})` = an event-based, this-turn, any-death, you-gain-1-life floating trigger.
  - **`no_max_hand_size_rest_of_game`** — a new effect setting `GameState.no_max_hand_size_player_ids` (a player-id set, never cleared, RULE 400.7-safe), consulted by `continuous.has_no_maximum_hand_size` (the resolve-time-granted sibling of the Reliquary Tower battlefield static). **Spirit Water Revival**: `draw 2` gated `additional_cost_paid=False`; `[shuffle_graveyard_into_library, draw 7, no_max_hand_size_rest_of_game]` gated `True` (RULE 118.3 "instead" = mutually-exclusive complements); `exile` self tail.
  - **`ExileEffect`/`TapEffect` gained `count_selector`** → `TargetSpec.count_selector="source_x_paid"` (resolved at *announce* time off `x_paid`, so `has_legal_targets` sees a real int, not the `"x"` sentinel); their `apply` trusts a `count_selector`-sized `targets` list wholesale (the `AddCountersEffect` guard). **Waterbender's Restoration**: `exile` X `creature_you_control` with `track_exiled_with` + a `create_delayed_trigger` (`step="end"`, `scope="any"` — "**the** next end step") running `return_all_exiled_with`. Even the single-target "exile then return at next end step" (Otherworldly Journey) had no primitive before this.
  - **`CopyPermanentEffect.referent="previous_each"`** — one token copy of *each* object an earlier clause exiled (`GameContext.previous_targets`), not just `prev[0]`. **Foggy Swamp Visions**: `exile` X `any_graveyard_creature` → `copy_permanent previous_each` → `create_delayed_trigger` (`scope="controller"` — "**your** next end step", `capture="created_objects"`) sacrificing the tokens.
  - **`AddCountersEffect` `previous_subject` + `divided`** — a counter pool auto-split across every `previous_targets` object; `creature_filter` now forwarded from the registry. **Crashing Wave**: `tap` up to X (`count_selector`) → distribute 3 `stun` across the just-tapped creatures. **Documented simplification:** "any number of tapped creatures **your opponents control**" is dropped (a caster taps opponents' creatures to stun them) and the split is auto-even, not an interactive "any number of" choice.
  - **`look_top_select` gained `select_optional` + `select_filter`** (a `combat.matches_object_filter` dict — "you **may** reveal a **creature card with power 3 or less**"). The "select" phase offers only eligible cards + a decline option; a filter with no eligible card skips the pick. **Water Tribe Rallier**: `waterbend {5}` (= a plain `{5}` activated cost) → `look_top_select {count: 4, select_optional, select_filter: {card_type: creature, max_power: 3}, rest_order: "random"}`.
  - **Invasion Submersible** — the ETB parses on its own (v215); the Exhaust body is hand-authored: `grant_until` rest-of-game `type_change` (+artifact +creature, 0/0 base) + `add_counters` ×3 + `activate_only_once_marker` (→ `once_per_game`). A stand-in for the 165-SOLO "becomes a creature" animation cluster (still its own PAR ticket).
  - **Waterbending Lesson** — `draw 3` + `pay_cost_then {cost: "{2}", else_effects: [discard 1]}` (RULE 118.3 "discard unless you pay").
  - **Files:** `models/game_state.py` (`TemporaryPlayerTrigger` duration/scope, `no_max_hand_size_player_ids`), `game/rules/triggers_mixin.py` (`_collect_temporary_player_triggers` scope), `game/rules/search_mixin.py` (`look_top_select` filter/optional), `game/continuous.py` (`has_no_maximum_hand_size`), `game/effects.py` (`InstallTemporaryPlayerTriggerEffect`, `NoMaxHandSizeRestOfGameEffect`, `CopyPermanentEffect.previous_each`, `ExileEffect`/`TapEffect` `count_selector`, `AddCountersEffect` `previous_subject`+`divided` & `creature_filter` registry, `GameContext.look_top_select`, `tap` registry no longer `int()`s `count`), `game/ability_catalogue/entries_016.py` (8 factories).
  - **Yield:** +7 cache cards (all hand-authored), 0 regressed. Full suite green. `tests/test_par30_waterbend_residue_bodies.py`.
- **The Waterbend (RULE 701.67) residue bullet is now closed.** The one card it couldn't reach — **Secret of Bloodbending** ("you control target opponent during their next combat phase / turn") — is deferred to **MEC-51 · Control another player's turn (or a part of it)**, the general Mindslaver / Sorin Markov `−7` / Emrakul-family primitive (a `GameState` control map + state machine + priority/action/choice/turn-based-action routing hooks). Not a loose parser end — a real standalone engine feature. See `BACKLOG.md`.
- **Files:** `game/costs.py` (`ActivationCost.help_pay_kind`, `parse_activation_cost` waterbend branch), `game/effects.py` (`GrantUntilEffect` X-substitution, `UnblockableEffect`/`ShuffleSelfIntoLibraryEffect` new modes + registries; v155: `ConditionalEffect._condition_holds` `additional_cost_paid` branch), `game/engine/casting_mixin.py` (`effective_cast_cost` additional-cost mana fold; v155: `pay_additional` threaded through `can_cast`/`effective_cast_cost`/`cast_spell`/`_cast_current_face`/`_auto_tap_for_cast_if_needed`/`_pay_additional_cast_cost`, `GameObject.additional_cost_paid` recording), `game/engine/legal_actions_mixin.py` (v155: `_offer_cast` optional-additional-cost variant, `_cast_action` `pay_additional`), `game/effect_binder.py` (v155: `attach_to_object` copies `additional_cost_optional`), `models/game_object.py` (v155: `additional_cost_paid` field + reset), `services/game_session.py` (v155: `_dispatch_cast_spell` round-trip), `parser/oracle/catalogue/handlers.py` (`_BASE_PT_UNTIL_EOT_RE`, `_CANT_BE_BLOCKED_TURN_RE`, `_SHUFFLE_ENCHANTED_INTO_LIBRARY_RE`), `parser/oracle/segmenter.py` (`_ADDITIONAL_COST_WATERBEND_RE`; v155: `_ADDITIONAL_COST_OPTIONAL_PREFIX_RE`, `_ADDITIONAL_COST_PAID_CONDITION_RE`), `parser/oracle/spec.py` (`additional_cost` `waterbend` key; v155: `AbilitySpec.additional_cost_optional`, `"additional_cost_paid"` condition key), `parser/oracle/gate.py` (v131, v155).
- **Yield:** +52 cache cards at v131 (10/28 `waterbend` cards MODELED; the bulk is the can't-be-blocked and base-P/T families); +1 at v155 (Requiting Hex). `parser_probe` diff, full cache, 0 regressed each time.
- **Tests:** `tests/test_eng32_waterbend.py` (real-card `parse_oracle` incl. the still-UNMODELED `{X}` form; v155: `segment_line` optional-vs-mandatory flag, `parse_effect_body` `additional_cost_paid` condition incl. the "instead" adversarial, Requiting Hex end-to-end, `_offer_cast` two cast variants gated by affordability, declining leaves the flag `False` and pool untouched, paying folds the mana and sets the flag, `ConditionalEffect` gates on the flag; execute: base-P/T set lasting until cleanup, group `{X}` resolving off `x_paid`, self "can't be blocked", Water Whip's `{1}{U}`+`{5}` total gating `can_cast` and draining the pool).

### Earthbend (RULE 701.66) (PAR-29, PARSER_VERSION 122) + dynamic X & pronoun tail (PAR-30, PARSER_VERSION 134) + "When you do" collapse (PAR-30, PARSER_VERSION 142) + dying-subject power X (PAR-30, PARSER_VERSION 143) + Earthshape hand-authored — PAR-30 Earthbend residue cluster closed

- **What:** The Avatar: The Last Airbender keyword action — the first of the "bending quartet" built. "Earthbend N" = "Target land you control becomes a 0/0 creature with haste that's still a land. Put N +1/+1 counters on it." `RulesEngine.earthbend(land, amount, source)` (in `mana_counters_mixin.py`, beside `bolster`/`blight`) does the animation as **two `rest_of_game` floating statics** scoped to the one land's `instance_id` (`GameState.floating_statics`, `affects="objects"`): a layer-4 `type_change` (`add_types=["creature"]`, `power=0`, `toughness=0` — the layer engine's own layer-7b animation P/T) and a layer-6 `grant_keyword` (`keywords=["haste"]`). Then `add_counters(land, N, "+1/+1")`. A genuine RULE 611 continuous effect, so RULE 611.2c ends it on its own if the land leaves — the layer engine only visits battlefield permanents, and a returned land is a new object the `object_ids` list no longer names.
- **`effects.EarthbendEffect`** targets `land_you_control` (the reminder text's "target land you control"), or reads a `previous_subject` land (`GameContext.previous_targets`) for "earthbend N, then `<verb>` that land". `amount` accepts the `"x"` sentinel (int conversion deferred to `apply`, as `EndureEffect` does — an unresolved sentinel resolves to 0). Registered as `earthbend`; handler `_earthbend` matches the literal `earthbend N`.
- **Documented simplification:** the reminder text's third sentence — "When it dies or is exiled, return it to the battlefield tapped." — is not modeled (an edge case for solo practice; the land goes to graveyard/exile like any permanent).
- **Dynamic X (PAR-30, v134):** "earthbend X, where X is [twice] the number of `<count>`" — `_earthbend_x`/`_EARTHBEND_X_RE`. `EarthbendEffect` gained `amount_from_count_selector` (a live `continuous.count_selector` read at resolution, clamped to `MAX_EFFECT_MAGNITUDE`, the same idiom `BolsterEffect` uses) and `amount_multiplier` (folds a "**twice** the number of …" prefix — Bumi's Feast Lecture). A land/artifact **subtype** count ("forests", "Foods") isn't in `subgrammars.DEVOTION`'s creature-scoped vocabulary, so `_EARTHBEND_X_SUBTYPE_SELECTORS` maps those onto `continuous.count_selector`'s existing `lands_you_control_of_type_<x>` / `foods_you_control`; "creatures you control with power N or greater" is built inline. Rockalanche, The Boulder Ready to Rumble, Bumi's Feast Lecture. Still UNMODELED: "…where X is **that creature's power**" (a dying creature's own last-known power — Beifong's Bounty Hunters).
- **"then untap that land" pronoun tail (PAR-30, v134):** `segmenter._announces_creature_target` now recognises an `earthbend` spec as picking a land by type (its `TargetSpec` is built inside `EarthbendEffect.__init__`, not surfaced as a param), and a new `previous_subject`-only handler `_TAP_PREVIOUS_SUBJECT_RE` claims "[then] tap/untap that land|permanent|artifact|creature" — the singular sibling of `_UNTAP_PREVIOUS_GROUP_RE` ("those creatures"), distinct from `_TAP_GROUP_SUBJECT_RE` ("that creature", `group_subject_only`) and `_tap_self` ("it"/"this ~"). Avatar Kyoshi, and — a bonus — ~8 unrelated "pump/attach/+1+1-counter target creature. Untap that creature." cards (Savage Surge, Stony Strength, Galadhrim Bow, Stun Sniper, Super Suit, Veteran's Reflexes, Seedcradle Witch, Stabbing Pain).
- **"Earthbend N. When you do, `<effect>`." collapse (PAR-30, v142):** `_EARTHBEND_THEN_WHEN_YOU_DO_RE` in `segmenter`, dispatched in `parse_effect_body` right after `_SACRIFICE_THEN_WHEN_YOU_DO_RE`. "earthbend N" is a mandatory keyword action (no "may"), so RULE 603.3's "when you do" sub-trigger is a certainty — the two sentences reduce to one plain `[earthbend N, <effect>]` sequence with no `pending_choice`, the identical certain-antecedent rationale the self-sacrifice collapse uses. Narrow: the before-clause regex is exactly `earthbend \d+`, and the dispatch fails closed (`None`) unless the recursively-parsed before-specs contain an `earthbend` spec — so it can never claim the genuine optional "you may `<action>`. When you do, …" family (which begins "you may " and never matches). The `<effect>` half already parsed via the connector-split loop; only the literal "When you do," was blocking. Closes **Earth Rumble**.
- **Dying-subject power X (PAR-30, v143):** "Whenever a **nonland** creature you control dies, earthbend X, where X is **that creature's power**." (Beifong's Bounty Hunters). Two additive pieces. (1) `segmenter._GROUP_SUBJECT_RE` gained an optional `nonland` qualifier → `condition["nonland"]` → `effect_binder._build_group_ok`'s new `want_nonland`, a negated main-type check against the DIES event's snapshotted `object_types` (RULE 400.7 — the object has left the battlefield by the time the trigger check runs), the same event-payload shape `nontoken` already uses. (2) `_EARTHBEND_THAT_CREATURES_POWER_RE` → `EarthbendEffect.amount_from_trigger_event="power"`, reading the DIES event's RULE 400.7 last-known-power snapshot — which `damage_death_mixin` now stamps on the DIES `GameEvent` (`power=obj.power`), mirroring the identical stamp `LEAVES_BATTLEFIELD` already carried for `LoseLifeEffect.amount_from_trigger_event`. Deliberately anchored on the literal "that creature's power" so only the dying-subject read is claimed ("its power" / "that creature's toughness" stay UNMODELED). Closes **Beifong's Bounty Hunters**.
- **Earthshape (hand-authored, no PARSER_VERSION bump) — Earthbend residue cluster closed:** the cluster's last card. "Earthbend 3. Then each creature you control with power less than or equal to **that land's power** gains hexproof and indestructible until end of turn. You gain hexproof until end of turn." — a `spell_effect` `AbilitySpec` in `ability_catalogue/entries_016.py`: `[earthbend 3, pump{selector:"creatures_you_control", creature_filter:{max_power:3}, keywords:["hexproof","indestructible"]}]`. The one small engine change: `PumpEffect`'s `selector`-group branch now also narrows by `creature_filter` (via `combat.matches_object_filter`, the same predicate `TargetSpec.creature_filter` uses) — it previously only applied `creature_filter` to the *targeted* branch, a latent gap. **Two documented simplifications:** (a) "that land's power" is modeled as the literal earthbend amount (3) — RULE 701.66 makes the target land a 0/0 that then gets N +1/+1 counters, i.e. exactly N/N, so "that land's power" is 3 absent any other P/T modifier; the animated land is itself a 3/3 creature you control and so is (correctly) among the protected creatures. (b) "You gain hexproof until end of turn" is dropped — player-level hexproof is deliberately unmodeled in this engine (same call as Veil of Summer's player-level hexproof in the Kinnan/M-K batch). **The PAR-30 Earthbend residue cluster is now fully closed** — its BACKLOG bullet is deleted.
- **Files:** `game/rules/mana_counters_mixin.py` (`earthbend`), `game/rules/damage_death_mixin.py` (`power=obj.power` on the DIES `GameEvent`, v143), `game/effects.py` (`EarthbendEffect` + `EffectRegistry`; `PumpEffect`'s `selector`-group branch now honours `creature_filter`, Earthshape), `game/effect_binder.py` (`_build_group_ok`'s `want_nonland`, v143), `game/continuous.py` (`creature_cards_in_your_graveyard` was v133), `game/ability_catalogue/entries_016.py` (`_earthshape`), `parser/oracle/segmenter.py` (`_announces_creature_target` earthbend recognition; `_EARTHBEND_THEN_WHEN_YOU_DO_RE` + its `parse_effect_body` dispatch, v142; `_GROUP_SUBJECT_RE`'s `nonland` qualifier, v143), `parser/oracle/catalogue/handlers.py` (`_earthbend`, `_earthbend_x`/`_EARTHBEND_X_RE`, `_EARTHBEND_THAT_CREATURES_POWER_RE`/`_earthbend_that_creatures_power`, `_TAP_PREVIOUS_SUBJECT_RE`/`_tap_previous_subject` + `EffectHandler`s), `parser/oracle/gate.py` (PARSER_VERSION 122 / 134 / 142 / 143).
- **Yield:** v122 — 9 real cache cards (Ba Sing Se, Cracked Earth Technique, Earth Village Ruffians, Earthbending Lesson, Earthbending Student, Haru Hidden Talent, Rebellious Captives, Sandbenders' Storm, Solid Ground). v134 — +12 (Rockalanche, The Boulder, Bumi's Feast Lecture, Avatar Kyoshi + the 8 "Untap that creature" cards). v142 — +1 (Earth Rumble). v143 — +1 (Beifong's Bounty Hunters). Earthshape hand-authored — +1, no bump. 0 regressed each pass. **The PAR-30 Earthbend residue cluster is now closed.**
- **Tests:** `tests/test_par29_earthbend.py` (v122 — clause parse + real-card `parse_oracle` + animate-and-count + `rest_of_game` persistence + no-op + bind-and-apply; v143 — "that creature's power" now claimed, a genuinely un-modeled dynamic form still rejected); `tests/test_par30_earthbend_dynamic.py` (v134 — each X phrasing parses to the right selector, real cards MODELED, and execute: a live Forest count and a "twice the number of Foods" count reach the target land's `+1/+1` counters, plus "earthbend 5, then untap that land" end-to-end; v143 — "that creature's power" parses to `amount_from_trigger_event`, "its power"/"toughness" stay UNMODELED, Beifong's MODELED, and execute end-to-end: a 5/5 dying earthbends the land by 5, a plain land dying doesn't fire the trigger); `tests/test_par30_earthbend_when_you_do.py` (v142 — the collapse produces `[earthbend, fight]`, "you may earthbend …"/"scry 2. when you do …" both fail closed, real Earth Rumble MODELED, and execute: the sequence's earthbend half animates the land + adds counters); `tests/test_par30_earthshape.py` (Earthshape registered with the right specs, and execute end-to-end: the animated land + a 2/2 gain hexproof/indestructible, a 6/6 doesn't).

### Blight (RULE 701.68) — cost forms (PAR-29, PARSER_VERSION 121)

- **What:** The Bloomburrow keyword action's *cost* integration (the standalone-verb effect form — `effects.BlightEffect` / `RulesEngine.blight` opening a `blight` `pending_choice` — shipped at PARSER_VERSION 111; see "Blight N — standalone form"). RULE 701.68 "blight N" = put N -1/-1 counters on a creature you control. New `ActivationCost.blight: int` covers all three cost shapes: an activated-ability cost (`{1}{R}, {T}, Blight 1:` — Sting-Slinger), a never-blocking additional cast cost (`blight N or pay {M}` — Bogslither's Embrace, Wild Unraveling), and a `pay_cost_then` half.
- **Synchronous auto-pick.** `RulesEngine.blight` gained `interactive: bool = True`; `interactive=False` (every cost site) auto-picks the creature with the highest toughness then power — the least-self-harm pick, the same "auto-pick to minimise loss" documented simplification `collect_evidence` uses — since cost payment can't pause for a `pending_choice`. `blight_possible(player)` (controls ≥1 creature) is the shared affordability check.
- **Wired parallel to Forage/Behold:** `costs.py`'s `_BLIGHT_RE` in `_parse_text` + `is_free`/`label`/`to_dict`/`from_dict`; `activation_mixin._can/_pay_activation_cost`; `misc_mixin._can/_pay_player_cost` (for `pay_cost_then`); `casting_mixin._pay_additional_cast_cost` (alongside `behold`, same non-blocking "or pay {M}"-dropped treatment). `spec.py`'s `_validate_additional_cost` gained the `blight` key; `segmenter._ADDITIONAL_COST_BLIGHT_RE` recognises the additional-cost line (and both it and `_ADDITIONAL_COST_BEHOLD_RE` were widened to accept a multi-pip "or pay {…}").
- **`_PAY_COST_THEN_OR_ELSE_RE` — the "If you don't" else-branch.** `PayCostThenEffect.else_effects` already existed (Wandering Archaic); the parser only ever emitted "If/when you do". A new handler `_pay_cost_then_or_else` ("you may `<cost>`. If you don't, `<effect>`." → `pay_cost_then` with `else_effects`, empty `effects`) closes Chaos Spewer ("you may pay {2}. If you don't, blight 2" — needs no blight-cost work, just the else-branch), Gutsplitter Gang, Scuzzback Scrounger. Registered right after `pay_cost_then_general`, same `MAY_COST_THEN_CLAUSE` vocabulary (now including `blight \d+`), same targeted-follow-up rejection.
- **Bug fixed:** the cost parser silently dropped "Blight N" from a cost string — the standalone-verb effect handler only ever matched "blight N" mid-sentence, never `{cost}, Blight N: <effect>`. So Sting-Slinger (already MODELED, because the activated-ability handler claimed the line with a `{1}{R}, {T}` cost) charged *no blight at all*. Now correct; no coverage change (the card was already counted), behaviour fixed. The BACKLOG note predicting a ~5-card coverage *drop* from this fix was wrong — nothing was mis-counted as MODELED off the dropped token, only mis-executed.
- **Not done:** Gristle Glutton (`{T}, Blight 1: discard a card. If you do, draw a card.` — a `pay_cost_then`-shaped *body* inside an activation) and Spiral into Solitude (`{1}{W}, Blight 1, Sacrifice ~: exile enchanted creature.` — a three-part cost + Aura-body the activated-ability handler doesn't claim) stay UNMODELED on their bodies, not the blight cost; Warren Torchmaster's *targeted* "when you do, target creature gains haste" payoff can't resolve off-stack. Filed under PAR-29 in `BACKLOG.md`.
- **Files:** `game/costs.py` (`blight` field, `_BLIGHT_RE`), `game/rules/mana_counters_mixin.py` (`blight` `interactive` param, `blight_possible`), `game/rules/misc_mixin.py` (`_can/_pay_player_cost`), `game/engine/activation_mixin.py` (`_can/_pay_activation_cost`), `game/engine/casting_mixin.py` (`_pay_additional_cast_cost`), `parser/oracle/spec.py` (`_validate_additional_cost`), `parser/oracle/segmenter.py` (`_ADDITIONAL_COST_BLIGHT_RE`, `_additional_cost_dict`), `parser/oracle/catalogue/handlers.py` (`_MAY_COST_THEN_CLAUSE`, `_PAY_COST_THEN_OR_ELSE_RE`, `_pay_cost_then_or_else`), `parser/oracle/gate.py` (PARSER_VERSION 121).
- **Yield:** 8 real cache cards newly MODELED (`parser_probe.py` diff / `coverage_report.py --no-db`, full cache, 0 regressed) — Blighted Blackthorn, Bogslither's Embrace, Chaos Spewer, Dream Seizer, Gutsplitter Gang, Scuzzback Scrounger, Sourbread Auntie, Wild Unraveling.
- **Tests:** `tests/test_par29_blight_cost.py` (additional-cost dict forms + cost-string parse/round-trip + "if you do"/"if you don't" clause forms + real-card `parse_oracle` + `interactive=False` highest-toughness auto-pick + `blight_possible` gate + non-blocking additional cast cost + `_can/_pay_player_cost`).

### Behold (RULE 701.4) (PAR-29, PARSER_VERSION 120)

- **What:** The Tarkir: Dragonstorm keyword action, reached in the current card pool only as an *additional cast cost* — "As an additional cost to cast this spell, behold a `<type>` or pay {N}." RULE 701.4a "behold a quality" = reveal a permanent you control with that quality, or a card with that quality from your hand. New `ActivationCost.behold: Optional[str]` holds the type word (a creature type — dragon/elf/kithkin/merfolk — for every real card). `RulesEngine.behold(player, quality, source=None)` (in `misc_mixin.py`, beside `forage`) scans the battlefield then the hand for a match via `continuous.has_subtype`; on a hit it fires `EventType.BEHELD` (`player_id`/`controller_id`/`instance_id`/`quality`) and returns `True`, else `False`.
- **Non-blocking additional cost.** `_can_pay_additional_cast_cost` always returns `True` for a `behold` cost, and `_pay_additional_cast_cost` calls `behold` best-effort (a `False` just means nothing was revealed). **Documented simplification:** the "or pay {N}" mana alternative isn't modeled — same precedent and reasoning as `segmenter._ADDITIONAL_COST_PAY_LIFE_OR_MANA_RE` ("pay N life or pay {cost}", where only the life half is kept). The consequence is a rare under-cost: a player holding no matching permanent/card casts the spell without paying the {N} they'd owe at a real table. Beholding itself has no game-state effect in this engine (it's a reveal), and nothing in the pool triggers on it yet — the `EventType.BEHELD` row + the `_PLAYER_TRIGGER_CONDITIONS`/`_GROUP_CONTROLLER_EVENT_KEYS` entries keep the keyword-action family's "fire an event so a future trigger can see it" convention.
- **Ungated the additional-cost wrapper.** `segmenter`'s "as an additional cost to cast this spell," recognition was previously gated behind `allow_spell_effect` (instants/sorceries only). RULE 601.2b additional costs apply to *any* spell, and real creature spells print them (Demon of Catastrophes, Arbiter of Woe, Lesser Masticore, Mardu Outrider, plus the three Behold creatures Kinsbaile Aspirant / Lys Alana Dignitary / Silvergill Mentor). The wrapper is unambiguous and the spec it emits carries no bare imperative for the gate to guard against, so the `_ADDITIONAL_COST_LINE_RE` branch now runs regardless of card type; the closed cost vocabulary is unchanged, so an out-of-vocab additional cost on a permanent still fails closed. `test_additional_costs.py`'s `test_permanent_never_claims_additional_cost_line` (written on the false premise that no permanent prints this) was replaced by `test_permanent_claims_recognized_additional_cost_line` + `test_permanent_still_fails_closed_on_unrecognized_additional_cost`.
- **Not done:** Molten Exhale ("cast as though it had flash if you behold a dragon as an additional cost") — a conditional-flash fused with the additional cost; Elven Passage ("you may behold an elf. If you do, untap that land.") — an activated-ability body needing a behold `pay_cost_then` half plus a "that land" pronoun; the Champion cycle ("behold a `<type>` **and exile it**" + a leaves-the-battlefield return); Celestial Reunion ("behold 2 creatures of a chosen type"). Filed under PAR-29 in `BACKLOG.md`.
- **Files:** `models/events.py` (`BEHELD`), `game/costs.py` (`behold` field + `is_free`/`label`/`to_dict`/`parse_activation_cost`), `game/rules/misc_mixin.py` (`behold`), `game/engine/casting_mixin.py` (`_can/_pay_additional_cast_cost`), `game/effect_binder.py` (`_GROUP_CONTROLLER_EVENT_KEYS`), `parser/oracle/spec.py` (`_validate_additional_cost` `behold` key), `parser/oracle/segmenter.py` (`_ADDITIONAL_COST_BEHOLD_RE`, `_additional_cost_dict`, `_PLAYER_TRIGGER_CONDITIONS`, ungated `_ADDITIONAL_COST_LINE_RE`), `parser/oracle/gate.py` (PARSER_VERSION 120).
- **Yield:** 9 real cache cards newly MODELED (`parser_probe.py` diff / `coverage_report.py --no-db`, full cache, 0 regressed) — Caustic Exhale, Kinsbaile Aspirant, Lys Alana Dignitary, Silvergill Mentor (Behold), plus Arbiter of Woe, Demon of Catastrophes, Grafted Identity, Lesser Masticore, Mardu Outrider (creature/other-permanent spells whose sacrifice/discard additional cost was the only blocker).
- **Tests:** `tests/test_par29_behold.py` (dict-form parse + adversarial no-match + creature-spell claim + real-card `parse_oracle` + cost round-trip + `behold` primitive permanent-then-hand + non-blocking additional cost + creature spell binds and stays castable with no match).

### Forage (RULE 701.61) (PAR-29, PARSER_VERSION 119)

- **What:** The Bloomburrow cost mechanic, and the direct sibling of Collect Evidence's build one version earlier. RULE 701.61a "forage" = "exile three cards from your graveyard **or** sacrifice a Food". New `ActivationCost.forage: bool` (the "N" is fixed at three, so a bool, not an int). `RulesEngine.forage(player)` (in `misc_mixin.py`, beside `collect_evidence`) auto-picks between the two halves — a Food is sacrificed (`put_into_graveyard`, RULE 701.17, fires `SACRIFICE`) whenever `player` controls one, keeping the three graveyard cards (the strictly more valuable line); otherwise the three oldest graveyard cards are exiled — then fires `EventType.FORAGED` (RULE 701.61b — process-complete, fired even when neither was possible). Documented simplification: no interactive choice between the halves (the same auto-pick idiom `collect_evidence`/`_pay_escape_graveyard_cost` use). `forage_possible(player)` is the shared affordability check.
- **Wired everywhere a cost is paid**, exactly parallel to Collect Evidence: `costs.py`'s `_FORAGE_RE` in `_parse_text` (+ `is_free`/`describe`/`to_dict`/`from_dict`); `activation_mixin._can/_pay_activation_cost` (for `{cost}, forage: <effect>` — Camellia, the Seedmiser, though it stays UNMODELED on its own body); `misc_mixin._can/_pay_player_cost` (for `pay_cost_then`). `EventType.FORAGED` + `segmenter._PLAYER_TRIGGER_CONDITIONS` ("you forage" → the event) + `effect_binder._GROUP_CONTROLLER_EVENT_KEYS` (`player_id`) back "whenever you forage, …".
- **Parser handlers:** `forage_bare` (`you may forage` whole clause → `pay_cost_then` with empty effects); `forage` (bare `forage`, the segmenter-peeled triggered-ability body → `effects.ForageEffect`).
- **Not done:** Curious Forager's *targeted* "when you do, return target permanent card from your graveyard to your hand" payoff (`PayCostThenEffect` branch effects resolve off-stack, no target step) and Feed the Cycle's "forage or pay {B}" as an *alternative additional cast cost*. Filed under PAR-29 in `BACKLOG.md`.
- **Files:** `models/events.py`, `game/costs.py`, `game/rules/misc_mixin.py` (`forage` / `forage_possible`, `_can/_pay_player_cost`), `game/engine/activation_mixin.py`, `game/effects.py` (`ForageEffect` + `EffectRegistry`), `game/effect_binder.py`, `parser/oracle/segmenter.py`, `parser/oracle/catalogue/handlers.py` (`_MAY_COST_THEN_CLAUSE`, `_forage_bare`, `_forage`), `parser/oracle/gate.py` (PARSER_VERSION 119).
- **Yield:** 3 real cache cards newly MODELED (0 regressed) — Bushy Bodyguard, Corpseberry Cultivator, Treetop Sentries.
- **Tests:** `tests/test_par29_forage.py` (cost parse + round-trip + clause forms + `forage_possible` + graveyard-exile path + Food-sacrifice-preferred path + impossible-still-fires-event + ETB-via-binder with an "if you do" draw rider).

### Collect Evidence (RULE 701.59) (PAR-29, PARSER_VERSION 118)

- **What:** The Murders at Karlov Manor cost mechanic. RULE 701.59a "collect evidence N" = "exile any number of cards with total mana value N or greater from your graveyard". New `ActivationCost.collect_evidence: int` field — a **total-mana-value threshold**, the MV-sum sibling of Escape's `exile_from_graveyard` flat card count. `RulesEngine.collect_evidence(player, N)` (in `misc_mixin.py`, beside `learn`) does the exile — auto-picking **highest mana value first** so the fewest cards leave (documented simplification, the same "auto-pick, no chooser in this MVP" idiom `_pay_escape_graveyard_cost`/`discard` use) — then fires `EventType.COLLECTED_EVIDENCE` (RULE 701.59b — process-complete, fired even when the threshold wasn't reached). `collect_evidence_possible(player, N)` is the shared affordability check.
- **Wired everywhere a cost is paid:** `costs.py`'s `_COLLECT_EVIDENCE_RE` recognizes it in a cost string (`parse_activation_cost` → `to_dict`/`from_dict` round-trip); `activation_mixin._can/_pay_activation_cost` charge it for `{cost}, collect evidence N:` abilities; `misc_mixin._can/_pay_player_cost` charge it for `pay_cost_then` ("you may collect evidence N. if you do, …" — `handlers._MAY_COST_THEN_CLAUSE` gained the alternative). `EventType.COLLECTED_EVIDENCE` + `segmenter._PLAYER_TRIGGER_CONDITIONS` ("you collect evidence" → the event) + `effect_binder._GROUP_CONTROLLER_EVENT_KEYS` (`player_id`) back "whenever you collect evidence, …".
- **Parser handlers:** `collect_evidence_bare` (`you may collect evidence N` whole clause → `pay_cost_then` with empty effects — an optional cost whose only payoff is the separate trigger); `collect_evidence` (bare `collect evidence N`, what's left after the segmenter peels a triggered ability's outer "you may " → `effects.CollectEvidenceEffect`, a mandatory resolving-effect form, the peeled "you may" carrying the optionality).
- **Files:** `models/events.py`, `game/costs.py` (`collect_evidence` field, `_COLLECT_EVIDENCE_RE`, `is_free`/`describe`/`to_dict`/`from_dict`), `game/rules/misc_mixin.py` (`collect_evidence` / `collect_evidence_possible`, `_can/_pay_player_cost`), `game/engine/activation_mixin.py` (`_can/_pay_activation_cost`), `game/effects.py` (`CollectEvidenceEffect` + `EffectRegistry`), `game/effect_binder.py` (`_GROUP_CONTROLLER_EVENT_KEYS`), `parser/oracle/segmenter.py` (`_PLAYER_TRIGGER_CONDITIONS`), `parser/oracle/catalogue/handlers.py` (`_MAY_COST_THEN_CLAUSE`, `_collect_evidence_bare`, `_collect_evidence`), `parser/oracle/gate.py` (PARSER_VERSION 118).
- **Yield:** 3 real cache cards newly MODELED (`parser_probe.py` diff / `coverage_report.py --no-db`, full cache, 0 regressed) — Evidence Examiner, Izoni Center of the Web, Surveillance Monitor.
- **Tests:** `tests/test_par29_collect_evidence.py` (cost-text parse + round-trip + clause forms + `collect_evidence_possible` + highest-MV-first exile + short-graveyard still fires the event + a real `{cost}, collect evidence N:` activated ability paying it).

#### Reflexive "When you do, `<targeted payoff>`" residue (PAR-30, PARSER_VERSION 206) + exotic activated bodies (PAR-30, PARSER_VERSION 207)

- **v206 — reflexive trigger primitive.** A *targeted* "you may `<cost>`. **When you do**, `<effect>`." is RULE 603.11's reflexive triggered ability: `_pay_cost_then_general` stops rejecting a targeted follow-up and emits `pay_cost_then` with a new ``then_trigger``; on payment, `RulesEngine._enqueue_pay_cost_then_trigger` builds a fresh `TriggeredAbility` and queues it on `pending_triggers`, so the ordinary placement path gathers its RULE 115 target and stacks it (`effects` resolve off-stack and never could). Carries the outer trigger's `GameEvent` on `StackItem.trigger_event`. Cost whitelist = mana / typed-sacrifice / discard / pay-life / collect-evidence / forage / blight, so it closes the whole "you may pay {cost}. If you do, `<targeted effect>`" family — Surgespanner, Teneb, Bearer of Silence, Sample Collector, Curious Forager, Warren Torchmaster. **+43**, 0 regressed. Files: `game/effects.py` (`PayCostThenEffect.then_trigger_specs`), `game/rules/misc_mixin.py` (`request_pay_cost_then`/`resolve_pay_cost_then_choice`/`_enqueue_pay_cost_then_trigger`), `parser/oracle/catalogue/handlers.py`. Tests: `tests/test_reflexive_when_you_do_trigger.py`.
- **v207 — the `{cost}, collect evidence N: <body>` activated abilities.** `segmenter._COST_LOOKS_REAL` never listed `collect evidence \d+` / `forage` / `blight \d+`, so those lines failed the cost sniff and never reached the activated handler; adding them unblocked the bodies:
  - **`exile enchanted creature`** — `ExileEffect`'s new ``attached_permanent`` self-mode (reads `GameObject.attached_to`, no RULE 115 target — the sibling of that mode on `TapEffect`/`PumpEffect`) + handler `exile_attached`. Spiral into Solitude, and a whole Aura family the parser could never finish before: Dreadful Apathy, Cooped Up, Choking Restraints, Caught in the Brights, Redemption Arc, …
  - **`discard a card. If you do, <effect>`** — `segmenter._DISCARD_THEN_IF_YOU_DO_RE` collapses a bare mandatory discard + its reflexive tail to a plain `[discard, <effect>]` sequence (same rationale as the sacrifice/earthbend "when you do" collapses; empty-hand failure is a documented simplification). Gristle Glutton's loot.
  - **`each opponent loses N life unless they discard a card or sacrifice a creature`** — `_EACH_PLAYER_LOSE_LIFE_UNLESS_RE` widened to "each opponent" (`each_player_pay_or` `scope="each_opponent"`) and the OR cost form (`EachPlayerPayOrEffect.sacrifice_or_discard`, since the plain cost parser AND-combines its fragments). Polygraph Orb.
  - **+13**, 0 regressed. **Hedge Whisperer hand-authored** (`ability_catalogue/entries_016.py`): the manland body is a targeted `grant_until` on `land_you_control` with a layer-4 `type_change` (Plant Boar 5/5, still a land) *plus* a layer-6 `grant_keyword` haste — one target, two statics, via the new `GrantUntilEffect.extra_statics` list — bounded by `condition={"kind": "source_tapped"}` (RULE 611.2b, ends when Hedge Whisperer untaps); `sorcery_speed_only` carries "Activate only as a sorcery".
  - Files: `parser/oracle/segmenter.py` (`_COST_LOOKS_REAL`, `_DISCARD_THEN_IF_YOU_DO_RE`), `parser/oracle/catalogue/handlers.py` (`exile_attached`, `_EACH_PLAYER_LOSE_LIFE_UNLESS_RE`), `game/effects.py` (`ExileEffect._attached_mode`, `EachPlayerPayOrEffect.sacrifice_or_discard`, `GrantUntilEffect.extra_statics`/`_park_static` refactor), `game/ability_catalogue/entries_016.py` (`_hedge_whisperer`), `parser/oracle/gate.py` (PARSER_VERSION 206/207). Tests: `tests/test_collect_evidence_blight_bodies.py`.
- **v208 — Feed the Cycle's forage additional cost.** "As an additional cost to cast this spell, forage [or pay {M}]." → `_ADDITIONAL_COST_FORAGE_RE` → `additional_cost={"forage": True}` (`ActivationCost.forage`, already charged by `_can`/`_pay_activation_cost`); the "or pay {M}" alternative is the same documented drop `behold`/`blight` additional costs already make. +1, 0 regressed. Files: `parser/oracle/segmenter.py` (`_ADDITIONAL_COST_FORAGE_RE`, `_additional_cost_dict`), `parser/oracle/spec.py` (`_validate_additional_cost` `forage` key), `parser/oracle/gate.py` (PARSER_VERSION 208). Test in `tests/test_collect_evidence_blight_bodies.py`.
- **v213 — the residue, closed.** Every remaining per-card primitive from the BACKLOG bullet, one batch. Parser (+26 cache cards, 0 regressed):
  - **The Lorwyn "Champion" cycle reflavoured.** `ActivationCost.behold_exile` (`segmenter._ADDITIONAL_COST_BEHOLD_EXILE_RE` → `additional_cost={"behold_exile": "<type>"}`) — a *mandatory* additional cast cost (no "or pay {N}", so it *blocks* casting, unlike PAR-29's `behold`): `GameEngine._pay_additional_cast_cost` beholds a matching permanent/hand card, exiles it and stamps `GameObject.linked_exile_id`; `_can_pay_additional_cast_cost` refuses the cast when nothing matches (`_behold_exile_candidate`). The paired "return the exiled card to its owner's **hand**" LTB is `handlers._RETURN_EXILED_CARD_RE`'s widened "to its owner's hand" branch → `ReturnLinkedExileEffect(destination="hand")`. → **Champion of the Clachan** and **Champions of the Perfect** MODELED (the latter's hand-authored stopgap — which modelled the behold-exile as a plain `sacrifice` and dropped the LTB — is **retired**, `specs_for` now falls through to the parser).
  - **`subject_damages_each_opponent_equal_to_power`** — a triggered-ability body where the damage source *and* its amount are one object read off `GameContext.trigger_event` (`instance_id`, a `group_subject_only`/`self_subject_only` handler row), so "it deals damage equal to its power to each opponent" sources from the *entering/turned-face-up* creature, not `self.source` the plain `damage_equal_to_power` selector rows would use. → **Champion of the Path** + a 6-card SOLO cluster.
  - **`tap_and_stun`** — "tap [up to one] target creature[ an opponent controls] and put a stun counter on it" as one clause → `[tap, add_counters {kind:"stun", previous_subject}]` (new `AddCountersEffect.previous_subject`). Enforced engine-side: **RULE 122.1c** stun-counter skip-untap is now a replacement in `RulesEngine.set_tapped` (the single untap choke point — covers the untap step, `{Q}`, `TapEffect(untap=True)`). → **Champions of the Shoal** + a ~15-card cluster (Alchemax Slayer-Bots, Constrictor Sage, Cryogenic Stasis, Stunning Shot, …).
  - **`_CONDITIONAL_FLASH_IF_BEHOLD_RE`** → `conditional_flash={"controller_beholds_subtype": "<type>"}` (`condition_query`, `ALLOWED_CAST_CONDITION_KEYS`) — "you may cast this spell as though it had flash if you behold a Dragon". **Documented simplification:** the reveal / additional-cost payment isn't separately modelled — the flash timing is gated on the caster *being able* to behold (a matching permanent/hand card), the same "or pay {N}" drop PAR-29 set. → **Molten Exhale**.
  - **`additional_cost={"behold_two_shared_type": True}`** (optional) — `GameEngine._behold_two_shared_type` picks a creature type the caster has ≥2 of across battlefield + hand, stamps it on `GameObject.chosen_type`, sets `additional_cost_paid`. → **Celestial Reunion** (see its hand-authored body below).
  - **`type_change` gained a ``legendary`` param** (`continuous.recompute` layer 4 → `GameObject._granted_legendary`, the same flag The Ring's "your Ring-bearer is legendary" sets) and a new **`source_has_subtype`** `EffectSpec.condition` key (RULE 603.4 intervening-if on the ability's own source's *derived* subtypes).
- **v213 — hand-authored / engine (`ability_catalogue/entries_008.py`, `game/effects.py`):**
  - **Champion of the Weird** — `BlightEffect(target_kind="opponent")`: "target opponent **blights** N" — the RULE 115 target is the *player*, the -1/-1 counters go on a creature *they* control. `Pay 1 life, Blight 2` is a real compound `ActivationCost` (`pay_life` + `blight`); `sorcery_speed_only` carries "Activate only as a sorcery".
  - **Tenth District Hero** — two `{cost}, collect evidence N:` levelers. L1: a `rest_of_game` `grant_until` — layer-4 `type_change` (`set_subtypes=["Human","Detective"]`, base 4/4) + layer-6 vigilance. L2: gated on `condition={"source_has_subtype": "Detective"}` — `type_change` `legendary=True` base 5/5 + a layer-6 anthem grant (`grant_keyword` `affects="other_creatures_you_control"`, indestructible). **Documented simplification:** the literal rename to "Mileva, the Stalwart" isn't modelled — `GameObject.name` has no override mechanism and no card in the pool references the name.
  - **Elven Passage** — `MayBeholdThenUntapLinkedEffect`: the `search` effect's `remember=True` stamps the fetched basic land's id on the (sacrificed) source's `linked_exile_id`; this reads it back, beholds an Elf if able, and untaps the land. "You may" auto-taken when able (pure upside).
  - **Incinerator of the Guilty** — `CollectEvidenceXThenBoardDamageEffect`: a `DAMAGE`/`combat`/`is_player` self-trigger; "that player" is `event["target_id"]`; **X = the maximum available evidence** (every graveyard card exiled — documented, since larger X is strictly better and costs nothing more); the reflexive "when you do" is folded in (untargeted mass selector, no RULE 115 target).
  - **Memory Vampire** — `MemoryVampireCombatEffect`: mill "that many" (`event["amount"]`) from **every opponent** (a self-mill line isn't auto-taken); then collect evidence 9 and **free-cast the highest-MV nonland card from the defending player's graveyard** (`RulesEngine.cast_without_paying`, auto-pick). **Bug fixed:** `cast_without_paying` never set `obj.controller_id`, so a card cast from another player's graveyard entered under *their* control — now the caster controls it (RULE 108.4).
  - **Conspiracy Unraveler** — a `granted_alt_cast_cost` `StaticAbility` + `continuous.granted_alt_cast_cost_for`: the engine's `alt_cost=True` cast path (`can_cast` / `cast_spell` / legal-actions `_offer_cast` / `_castable_now_or_via_potential` / `_cast_action`) now falls back to a **battlefield-scanned** alt cost when the spell has no `AbilitySpec.alt_cost` of its own. `_can_pay_alt_cast_cost` / `_pay_alt_cast_cost` gained a `collect_evidence` component. Controller-scoped.
  - **Celestial Reunion** — `CelestialReunionSearchEffect`: search a creature card with mana value ≤ the spell's `x_paid`; `request_search`'s `destination_if` puts it onto the battlefield (rather than hand) when `additional_cost_paid` and it matches `chosen_type`.
- **Tests:** `tests/test_par30_champion_behold_exile.py`, `tests/test_par30_collect_evidence_residue.py`.

### Learn (RULE 701.48) (PAR-29, PARSER_VERSION 117)

- **What:** The Strixhaven keyword action. RULE 701.48a is "choose one — reveal a Lesson card you own from **outside the game** and put it into your hand; **or** discard a card, then if you discarded a card this way, draw a card." **Documented simplification:** the Lesson branch is dropped — this engine has no sideboard / outside-the-game zone with a Commander-legal use (the same call `ability_catalogue/entries_010.py` already makes for Karn, the Great Creator's -2). Learn collapses to its other, fully-modelable half: `RulesEngine.learn(player)` (in `misc_mixin.py`, beside `recruit`) drives an **optional** discard-a-card-then-draw straight through the existing `request_choose_objects` chooser — `optional=True` gives the decline option, `then_specs=[{draw 1}]` fires only on a real discard. An empty hand is a no-op (nothing to discard, Lesson branch gone). No new `pending_choice` kind, no `resolve_*` method — the chooser's own resolver handles it. `effects.LearnEffect` is a bare "you"-subject effect like `RecruitEffect`; handler `learn` matches the bare word (every real card's whole clause).
- **Files:** `game/rules/misc_mixin.py` (`learn`), `game/effects.py` (`LearnEffect` + `EffectRegistry`), `parser/oracle/catalogue/handlers.py` (`_learn` + `EffectHandler`), `parser/oracle/gate.py` (PARSER_VERSION 117).
- **Yield:** 15 real cache cards newly MODELED (`parser_probe.py` diff / `coverage_report.py --no-db`, full cache, 0 regressed) — Arcane Subtraction, Cram Session, Enthusiastic Study, Eyetwitch, Field Trip, Gnarled Professor, Guiding Voice, Igneous Inspiration, Overgrown Arch, Poet's Quill, Pop Quiz, Professor of Symbology, Rise of Extus, Sparring Regimen, Study Break. Retriever Phoenix stays UNMODELED — its "if you would learn, you may instead return this card" is a replacement on the learn action (a `WOULD_LEARN` event shape), a separate build.
- **Tests:** `tests/test_par29_learn.py` (parse + real-card end-to-end + discard→draw + decline is a no-op + empty-hand no-op + ETB-via-binder).

### Incubate (RULE 701.53) — literal `incubate N` (PAR-29, PARSER_VERSION 116) + dynamic X (PAR-30, PARSER_VERSION 133 / 160 / 162) + residue closed (PAR-30, PARSER_VERSION 205)

- **What:** "Incubate N" — create an Incubator token (a power/toughness-less colourless artifact token) with N +1/+1 counters on it. **No new engine primitive:** the Incubator DFC token already existed end-to-end — `create_token`'s `extra_counters` places the counters, and the `Incubator` catalogue entry (`ability_catalogue/entries_008.py`, `_incubator_token`) binds "{2}: Transform this token" (→ a 0/0 Phyrexian artifact creature, whose counters then make it N/N) onto every token so named via `bind_from_catalogue`'s name-keyed lookup. Glissa, Herald of Predation's hand-authored entry already emitted exactly this `create_token` spec; this batch is just the oracle-text recognizer — handler `incubate`, `_c(r"(?:you )?incubate (?P<n>\d+)")` (the "you incubate N" form covers the "when you do" continuation, e.g. Assimilate Essence).
- **Dynamic X (PAR-30, v133):** "Incubate X, where X is `<count>`" — `_incubate_x`/`_INCUBATE_X_RE`. `CreateTokenEffect.extra_counters` gained two resolve-time amount keys alongside the literal `count` (`_resolve_extra_counter_amount`, clamped to `MAX_EFFECT_MAGNITUDE`): `count_from_count_selector` (a live `continuous.count_selector` read — "the number of lands you control", and a new `creature_cards_in_your_graveyard` selector for "creature cards in your graveyard") and `count_from_trigger_event` (the firing event's own field — "that spell's mana value" off a `SPELL_CAST` `mana_value`, the same field `CreateTokenEffect.pt_from_trigger_event` already read for Shark Typhoon). "incubate X **twice**" is just `create_token`'s own `count=2` (one Incubator per repetition).
- **"…where X is its power" (PAR-30, v160):** a "when ~ dies" trigger — Bloated Processor, Furnace Gremlin. No engine change: `damage_death_mixin` already stamps the dying object's last-known `power` onto the DIES event (RULE 400.7, added for `EarthbendEffect.amount_from_trigger_event`'s "earthbend X, where X is that creature's power" at v143), so `_incubate_x` just routes "its power" to `extra_counters`' existing `count_from_trigger_event="power"` key — the same firing-event idiom.
- **"Its controller incubates X, where X is its mana value" + "…exiled this way" (PAR-30, v162):** the two remaining *dynamic-amount* residue shapes.
  - **Excise the Imperfect** — `CreateTokenEffect.creators` gained `"previous_target_controller"` (the token's creator is whoever last controlled the just-exiled `GameContext.previous_targets[0]` — RULE 608.2h, it is already gone), and `extra_counters` gained `count_from_subject` reading a `"<who>_<char>"` string via a new shared module helper `_characteristic_of_subject` (factored out of `GainLifeEffect._from_subject`; `char` now also covers `mana_value`, read off the printed card). The plain `_exile` handler also learned the real `nonland_permanent` target kind it never reached before — bonus coverage for **Anguished Unmaking**, **Utter End**.
  - **Sunfall** — new `GameContext.objects_exiled_this_way` int accumulator, the exact sibling of `permanents_destroyed_this_way`: bumped by `context.exile` for every object that genuinely moved *into* exile this resolution, threaded through `_apply_effects_partitioned`'s save/reset/restore + the RULE 608.2 deferred-resume, read by `extra_counters`' new `count_from_context` key.
- **Files:** `parser/oracle/catalogue/handlers.py` (`_incubate`, `_incubate_x`/`_INCUBATE_X_RE`, `_exile` kind list, `_counter` reflexive tail, `_IF_PREV_CREATURE_CANT_BLOCK_RE`), `parser/oracle/catalogue/subgrammars.py` (`_SPELL_TYPE_WORD` + `"battle"`), `parser/oracle/segmenter.py` (`_CAST_SPELL_TARGETS_PERMANENT_TRIGGER_RE`), `parser/oracle/spec.py` (`previous_target_is_creature`), `game/effects.py` (`GameContext.objects_exiled_this_way` + `exile`, `_characteristic_of_subject`, `_apply_effects_partitioned`, `CreateTokenEffect._resolve_extra_counter_amount` + `creators`, `CounterSpellEffect.on_pay_effect_specs`, `CantBlockEffect.previous_subject`, `RevealHandChooseDiscardEffect.optional`/`else_specs`, `SearchLibraryEffect.track_exiled_with`, `GameContext.choose_objects`/`request_search` passthroughs), `game/rules/casting_mixin.py` (deferred-resume threading, `_targets_a_permanent`), `game/rules/misc_mixin.py` (`counter_unless_pays` on-pay specs, `request_choose_objects`/`_choose_objects_choice`/`resolve_choose_objects_choice` `else_specs`), `game/rules/search_mixin.py` (`track_exiled_with` through `request_search`/`_search_choice`/`_finish_search`), `game/effect_binder.py` (`requires_spell_targets_permanent` predicate), `game/continuous.py` (`creature_cards_in_your_graveyard`, `source_x_paid` selectors), `game/targeting.py` (`_spell_matches_filter` `"battle"`, `incubator_token_you_control` kind), `game/ability_catalogue/entries_016.py` (`_traumatic_revelation`, `_phyrexian_incubator`, `_progenitor_exarch`), `parser/oracle/gate.py` (PARSER_VERSION 116 / 133 / 160 / 162 / 205).
- **Yield:** v116 — 13 real cache cards (Compleated Huntmaster, Converter Beast, Essence of Orthodoxy, Eyes of Gitaxias, Gift of Compleation, Ichor Drinker, Infected Defector, Injector Crocodile, Marauding Dreadship, Merciless Repurposing, Phyrexian Awakening, Sculpted Perfection, Tangled Skyline). v133 — +3 (Glistening Dawn, Blight Titan, Chrome Host Seedshark), 0 regressed. v160 — +2 (Bloated Processor, Furnace Gremlin), 0 regressed. v162 — +4 (Excise the Imperfect, Sunfall, Anguished Unmaking, Utter End), 0 regressed. v205 — +4 parser (Assimilate Essence, Don't Make a Sound, Searing Barb, Tiller of Flesh), 0 regressed, + 3 hand-authored (Phyrexian Incubator, Progenitor Exarch, Traumatic Revelation).
- **Residue closed (PAR-30, v205)** — the last cache singletons, each blocked on grammar *around* the incubate, not on incubate itself. Three general parser rows (+4 cache cards, 0 regressed):
  - **`_counter` reflexive tail** — "…unless its controller pays {N}. **If they do**, `<effect>`." A serialized sub-body parsed recursively (fail-closed) into `CounterSpellEffect.on_pay_effect_specs`, threaded through `RulesEngine.counter_unless_pays` → stashed as `_pending_counter_on_pay_specs` → applied by `resolve_counter_unless_pays_choice` **only** on the `answer == "pay"` branch (inert on every branch that ends in a `counter_spell`). `_SPELL_TYPE_WORD` / `targeting._spell_matches_filter` also gained `"battle"` ("counter target creature or battle spell"). **Assimilate Essence**; bonus **Don't Make a Sound** ("… If they do, surveil 2.").
  - **`_IF_PREV_CREATURE_CANT_BLOCK_RE`** — "if it's a creature, it can't block this turn", a damage-rider tail: the preceding "deals N damage to **any target**" clause can land on a player/planeswalker/battle, so the restriction is gated on `GameContext.previous_targets[0]` being a creature (`CantBlockEffect.previous_subject`, sets `temp_cant_block`; `ConditionalEffect` gate `previous_target_is_creature` in `spec._ALLOWED_CONDITION_KEYS`). **Searing Barb**.
  - **`_CAST_SPELL_TARGETS_PERMANENT_TRIGGER_RE`** — "whenever you cast a spell that targets one or more permanents" (RULE 608.2b). `casting_mixin` stamps a `targets_a_permanent` bool onto the `SPELL_CAST` event (any chosen target that's a battlefield `GameObject`); `effect_binder._trigger_condition` adds a `requires_spell_targets_permanent` predicate reading it. **Tiller of Flesh**.
- **Residue hand-authored (PAR-30, v205)** — three genuine singletons in `ability_catalogue/entries_016.py` (parser verdict stays UNMODELED; `specs_for` claims them by name), each needing one small general engine primitive:
  - **Traumatic Revelation** — "you **may** choose … If you don't, incubate 3." `RevealHandChooseDiscardEffect` gained `optional` + `else_specs`, threaded through `request_choose_objects`' new `else_specs` (the mirror of `then_specs`: fires only when the choice ends with nothing picked, *including* an empty candidate pool). `"battle"` joined the effect's `card_types` filter. The else body is a plain incubate-3 `create_token`.
  - **Phyrexian Incubator** — "incubate 2 **that many times**" (count = cards the search exiled, across the search's RULE 608.2 `pending_choice` suspension). `SearchLibraryEffect(track_exiled_with=True)` → `_finish_search` appends every card sent to `"exile"` onto the source's own `GameObject.exiled_with_ids` (the same accumulator `ExileEffect.track_exiled_with` writes) — it lives on the permanent, so it survives suspend/resume; the following `create_token` reads it back with the pre-existing `count_selector="exiled_with_count"`. "Then shuffle" is `_finish_search`'s default. *Documented simplification:* "or cards with phyrexian back faces" is dropped (`card_query` type-line substring match claims the Phyrexian subtype, not a DFC whose back-only face is Phyrexian).
  - **Progenitor Exarch** — "incubate 3 **X times**" off the source's own announced {X} (new `continuous.count_selector` key `"source_x_paid"` reading `GameObject.x_paid`, still present when the ETB trigger resolves). The "{T}: Transform target Incubator token you control" ability reuses the `Incubator` token's own `grant_until`/`type_change`/`rest_of_game` animation with a RULE 115 target — new `incubator_token_you_control` target kind (a token named "Incubator" the ability's controller controls).
- **Tests:** `tests/test_par29_incubate.py` (parse + real-card end-to-end + token created with counters + transforms into an N/N creature + ETB-via-binder); `tests/test_par30_incubate_dynamic.py` (each X phrasing parses to the right `extra_counters` key; execute: a live creature-card graveyard count, an "incubate X twice" land count; v160 — Bloated Processor's DIES trigger reads a grown creature's last-known power through a real `destroy` + `resolve_until_stable`, X=0 still makes the Incubator; v162 — Excise creates the Incubator under the *victim's* controller sized to its mana value, Sunfall sizes to the number of creatures it exiled, and the accumulator doesn't leak between two back-to-back resolutions); `tests/test_incubate_parser_residue.py` (v205 parser rows — parse each clause + adversarial non-match, execute: Searing Barb's rider bites a creature target and no-ops on a player one, Assimilate Essence incubates on the pay branch only); `tests/test_incubate_residue_authored.py` (v205 hand-authored — parser still UNMODELED but registered; Traumatic Revelation's else-branch fires when the hand has no creature/battle card and doesn't when a card is discarded; Phyrexian Incubator makes one Incubator per exiled card end-to-end through the search suspension and none when nothing's found; Progenitor Exarch makes X Incubators off `x_paid` and its {T} ability transforms only your own Incubator token).

### Reproducible random numbers (RULE 705/706)

- **What:** `RulesEngine.random_int`/`random_choice`/`coin_flip` draw off `GameState`'s own `(rng_seed, rng_counter)` pair, so randomness survives clone/undo/rewind deterministically.
- **Files:** `game/rules_engine.py`, `models/game_state.py`

### RULE 400.7 "new object" identity reset (blink / return from graveyard)

- **What:** New `GameObject.reset_as_new_object()` is the single shared fix point clearing counters, attachment linkage, control/copy state, cast-time flags, combat state, every "until end of turn" grant, and transform state — called by both `blink()` and `return_from_graveyard()`, which also now reset `controller_id` to the owner (RULE 108.4). Deliberately does not change `instance_id`, since trigger closures snapshot it at bind time.
- **Files:** `models/game_object.py`, `game/rules_engine.py`
- **Bug fixed:** `blink()` reused the same `GameObject` without resetting temporary power/toughness/keywords (an until-EOT pump survived a flicker), and `return_from_graveyard()` never cleared counters at all (a creature that died with +1/+1 counters could come back with them via Reanimate/Regrowth).

### Targeted "target player gains/loses N life"

- **What:** `GainLifeEffect` gained an opt-in `target_kind`, mirroring `LoseLifeEffect`'s existing one, so a targeted life-total clause isn't misread against a shared multi-effect target list.
- **Files:** `game/effects.py`, `parser/oracle/catalogue/handlers.py`
- **Bug fixed:** `_lose_life`'s regex already matched "target player loses N life" but the builder never inspected which alternative matched, so a genuinely targeted life-loss clause was silently bound as an untargeted "you lose N life" for every prior card using that template.

### Exile Target Player's Graveyard

- **What:** `ExileTargetGraveyardEffect` targets one player and empties their whole graveyard (Bojuka Bog), distinct from single-card graveyard exile and the untargeted "exile all graveyards" effect; the same parser handler also claims Tormod's Crypt's "exile all cards from target player's graveyard" phrasing.
- **Files:** `game/effects.py`, `parser/oracle/catalogue/handlers.py`

### Counter-Family Parser Additions (Spells)

- **What:** Spell target filters (noncreature/card-type list/mana-value on `TargetSpec.spell_filter`), "unless its controller pays `{…}`" via a `counter_unless_pays` interactive choice (auto-counters when unpayable), and "this spell can't be countered" as a `CantBeCounteredEffect` marker `RulesEngine.counter_spell` refuses.
- **Files:** `parser/oracle/catalogue/handlers.py`, `game/effects.py`

### New One-Shot Effect Families (Bounce/Recursion/Tutor/Mass Damage/Self-Attach)

- **What:** One parser-expansion wave added return-to-hand (bounce), graveyard recursion (new `graveyard_creature`/`creature_you_control`/`land_you_control` target kinds), tutor-to-hand plus basic-land fetch, `add_mana` (Dark Ritual), mass damage ("deals N damage to each creature/player/opponent" via a closed `selector` on `DealDamageEffect`), and ETB self-attach for Equipment.
- **Files:** `parser/oracle/catalogue/handlers.py`, `game/effects.py`

### Generalized "Search Your Library for X" Grammar (RULE 701.19)

- **What:** `SearchLibraryEffect`/`RulesEngine.request_search` was already generic (criteria, destination, count); parser recognition was widened to combine criteria phrases, an optional "reveal" clause, five destination phrasings and five pronoun variants — unlocking 13 real popular tutors. A follow-up pass added `zones=["library","graveyard"]` (Doomsday/Finale-shaped combined search), per-found-card `destinations` overrides (Cultivate's split destination), and `exile_rest` (Doomsday's "exile the rest, no shuffle").
- **Files:** `game/effects.py`, `game/rules/search_mixin.py`, `parser/oracle/catalogue/handlers.py`

### Mass "Destroy/Exile All X" Board Wipes

- **What:** `DestroyEffect`/`ExileEffect` gained a `selector` (`all_creatures`/`all_artifacts`/`all_enchantments`/`all_permanents`/`all_planeswalkers`) plus an optional filter (`min_toughness`/`min_mana_value`/`max_mana_value`), and `DestroyEffect.can_be_regenerated=False` for "can't be regenerated" wipes (skips the replacement pass entirely). Wired into Austere Command/Farewell's modal modes and a combined `each_creature_and_player` selector for Volcanic Fallout.
- **Self-excluding wipe (PAR-30, v163):** `all_other_creatures` (RULE 400's "other" — every creature but this effect's own source, whoever controls it) and `other_creatures_you_control` (that, narrowed to the source's controller — Desolation Giant) selectors. Parser `_DESTROY_ALL_OTHER_RE` claims "destroy all other creatures[ you control]" / "…all creatures other than ~" / "…except [for] ~", with an optional "they/those creatures can't be regenerated" tail matched in the same whole-body pass. +1 (Novablast Wurm); also closes the "destroy all creatures other than ~" gap in Magister of Worth's condemnation vote branch (card still blocked on its grace branch's mass graveyard-reanimation).
- **Files:** `game/effects.py` (`_MASS_DESTROY_SELECTORS`, `_mass_selector_objects`), `parser/oracle/catalogue/handlers.py`
- **Tests:** `tests/test_par30_destroy_all_other.py` (each phrasing → the right selector; the regen tail; plain "destroy all creatures" still includes the source; execute: `all_other_creatures` spares only the source, `other_creatures_you_control` also spares opponents' creatures).

### New One-Shot Effect Batch (Wyleth Equip)

- **What:** A cluster of one-off effect classes each backing one clause shape: `ExileGainLifeToControllerEffect` (Swords to Plowshares), `TargetPlayerDrawLoseLifeEffect` (Sign in Blood), `CounterAndFirstStrikeEffect` (The Wandering Emperor +1), `ProliferateEffect`, `UnblockableEffect` (a new `temp_unblockable` flag), and several exile/graveyard/token effects — deliberately atomic per verb pair to avoid the "two targeting effects sharing one target" double-prompt bug.
- **Files:** `game/effects.py`

### Impulsive-Look Effect

- **What:** "Look at the top N cards, take one matching a filter, put the rest into Y" (Grisly Salvage/Commune with the Gods-shaped) — a new `ImpulsiveLookEffect`/`RulesEngine.request_impulsive_look`, a distinct shape from both cascade (peels exactly N, not "until a match") and search (not the whole library).
- **Files:** `game/effects.py`, `game/rules_engine.py`

### Impulsive Draw (Exile + Temporary Play Permission)

- **What:** "Exile, you may play until the end of your next turn" (Light Up the Stage-shaped): `GameState.temp_play_permissions` (instance_id → turn granted) since the card sits in exile rather than on a standing permanent; swept at cleanup once expired.
- **Files:** `game/rules_engine.py`, `game/game_engine.py`

### Impulsive Draw's Dual-Player Extension + Mana-Wildcard Permission

- **What:** `GameState.temp_play_permission_player` extends impulsive draw to a permission granted to a *different* player than the exiling one (Ragavan's per-firing combat-damage trigger, Mnemonic Betrayal's whole-graveyard exile). Mnemonic Betrayal also needed RULE 605.1a's broadest mana wildcard ("any type can be spent") via a new `ManaPool.can_pay`/`pay` `wildcard` param.
- **Files:** `game/rules_engine.py`, `game/game_engine.py`, `models/mana_pool.py`
- **Bug fixed:** `resolve_top_of_stack` unconditionally routed a resolved instant/sorcery to the graveyard even when one of its own effects had already exiled it; and `_remove_from_current_zone` only searched the acting player's own zones, missing a card sitting in a different player's exile.

### ENG-1: Re-Validate Attachment Legality Every SBA Pass

- **What:** RULE 704.5m/n (an illegally-attached Aura/Equipment) had only ever been checked when a host *left* the battlefield. `RulesEngine._revalidate_attachments`, a new SBA check, now re-runs the same `_attachment_legal` an initial attach uses for every still-battlefield-resident attached permanent each SBA pass; `_attachment_legal` also gained a protection check it never had before.
- **Files:** `game/rules/sba_mixin.py`, `game/combat.py`
- **Bug fixed:** Two pre-existing paths (a hand-authored "return as a new Aura" effect, two test fixtures) had attached permanents whose `parametric_keywords`/oracle text never went through the normal attach route, so their now-legitimately-attached state would have been silently stripped on the very next SBA pass — fixed at the source rather than exempted.

### ENG-2: Interactive Sacrifice Choice for `SacrificeEffect`

- **What:** RULE 701.17's "player sacrifices N permanents matching `<type>`" (Annihilator) now funnels through `request_choose_objects` instead of auto-picking the first match, reusing the same RULE 601.2c-style chooser Tevesh Szat's own ability already used — reached from the other direction.
- **Files:** `game/rules_engine.py`, `game/effects.py`
- **Why:** `greatest_power` (Professor Onyx) deliberately keeps its own recompute-after-each-removal `max()` auto-pick rather than routing through the chooser, since no shipped card sacrifices more than one this way and the chooser's single up-front pool doesn't model a moving "greatest" set.

### Turn/phase/step loop, event system

- **What:** `run_turn` walks the `TurnSequence`, runs each step body (untap, first-turn draw-skip, combat damage, cleanup discard-to-7), opens priority windows, and empties mana between steps (RULE 500.4).
- **Files:** `game/game_engine.py`

### Mulligan/setup phase gating

- **What:** `GameSession(require_setup=True)` starts a goldfish game with only `mulligan`/`keep_hand` legal until every card is kept; `mulligan` reshuffles and draws a fresh 7, `keep_hand` requires bottoming exactly `mulligan_count` cards (London style).
- **Files:** `services/game_session.py`

### Display-only round number

- **What:** `GameState.round_number` is a display-only companion to the rules-correct `turn_number` (RULE 500.1 counts every player's turn separately) — bumped when the turn returns to the starting player, and re-derived rather than incremented for an assembled Replay/Puzzle board.
- **Files:** `game/game_engine.py`, `models/game_state.py`

### First-draw-skip fixed for 3+ player pods (RULE 103.8c)

- **Bug fixed:** `GameEngine._step_draw` skipped turn 1's draw whenever more than one player was in the game, citing a two-player-only rule (RULE 103.8a); RULE 103.8c says the opposite for 3+ players — "no player skips the draw step of their first turn" — so the starting seat at a pod of 3-4 was quietly a card down all game. Gate narrowed to `== 2`.
- **Files:** `game/game_engine.py`

### Vancouver mulligan + interactive scry

- **What:** `RulesEngine.scry` became a real two-phase interactive `pending_choice` (repeated bottom question, then a repeated order question, each independently declinable) instead of a stub that kept every card on top; Vancouver joined `MULLIGAN_STYLES` on top of it, drawing one fewer card per mulligan with the table's scry-1s queued in turn order after everyone has kept.
- **Files:** `game/rules_engine.py`, `services/game_session.py`
- **Why:** Vancouver had been deliberately left unbuilt until scry had a real effect, since its whole point is the resulting choice.

### Two-way control exchange (RULE 701.10)

- **What:** A genuine one-shot two-way controller swap (Gilded Drake) — distinct from the layer-2 `control_change` static and the duration-bounded `GainControlUntilEndOfTurnEffect`, needed so a swapped creature dying afterward doesn't hand it back.
- **Files:** `game/effects.py`
- **Bug fixed:** an "up to one target" trigger with no legal target was being dropped instead of resolving with zero targets, which is what makes Gilded Drake sacrifice itself on an empty board.
- **Cross-target predicates (PAR-30, PARSER_VERSION 211):** the residue the PAR-29 generalization left (see the PAR-29 "Parser-shaped only" entry). RULE 115 verifies at *selection* that the two chosen permanents "share a card type" / the opponent-side one has "equal or lesser mana value" / "power ≤ that creature's power" — this engine has no cross-target legality mechanism (`TargetSpec.distinct_controllers` is enforced client-side per-round, not across two independent specs), so `ExchangeControlEffect` checks these at *resolution* instead in a new `_cross_target_ok`: `shares_type` (`"card"`/`"permanent"`, both folded to a shared-`_PERMANENT_TYPE_WORDS` intersection — RULE 205.2, and `type_words` carries a synthetic "permanent" entry that would make a naïve test vacuous) and `second_not_greater` (`"mana_value"` / `"power"`, the opponent-side pick capped against the controller-side one). A failing pick just doesn't exchange — one more `and` on the existing `exchangeable` gate, exactly the documented simplification the pre-existing `mine.controller_id != theirs.controller_id` no-op already is. **No `legal_targets` / client change.** Parser: an optional `_EXCHANGE_XTARGET_TAIL` appended to the two-explicit and multi handler regexes; a dedicated `_EXCHANGE_CONTROL_SPAWNBROKER_RE` row (its "with power ≤ that creature's power" clause sits *inside* the second target phrase, before "an opponent controls", so `_TARGET_B` can't consume it); new `subgrammars._TARGET_ROWS` entries "target nonland permanent you control" (`nonland_permanent_you_control`) and "another/other target permanent" (→ broad `permanent`); `_EXCHANGE_CONTROL_TARGET_KINDS` widened for the controller-scoped permanent kinds. **+10** — Daring Thief, Legerdemain, Puca's Mischief, Role Reversal, Shifting Loyalties, Spawnbroker, plus four "{T}: untap **another** target permanent" bonus cards (Kiora's Follower, Vizier of Tumbling Sands, Unbender Tine, Nanoform Sentinel) off the new "another target permanent" row. 0 regressed. `tests/test_par30_exchange_control_cross_target.py`.
- **Residue closed (PAR-30, PARSER_VERSION 212) — twelve bespoke singletons, all hand-authored** (`ability_catalogue/entries_016.py` — no new parser recognition needed, each shape appears on exactly one card):
  - **Confusion in the Ranks** — new `TriggeredAbility.controller_from_trigger_event`: RULE 603.1's *chooser* can differ from the ability's own source's controller (a group trigger on any player's own permanent entering, whose controller picks the target — `triggers_mixin._trigger_controller_id`, threaded through every target-selection/choice-prompt call site that used to read `ability.controller_id` bare). `ExchangeControlEffect(first_target_kind="trigger_subject")` reads the entering permanent straight off the firing event (the same `TapEffect`/`ExileEffect` idiom, just for the *first* exchange slot instead of the only one) — the second side is a real target, `shares_type="card"`.
  - **Conjured Currency** — new `permanent_you_neither_own_nor_control` target kind (`targeting.legal_targets`): excludes both this controller's own cards *and* anything they've gained control of, the double-negative RULE 115 exchange cards specifically want.
  - **Djinn of Infinite Deceits** — a `nonlegendary` key on `combat.matches_object_filter`/`TargetSpec.creature_filter` (multi-count mode's `second_creature_filter` now applies to that spec too, not just the two-explicit-targets one) + a new `ActivationCost.not_during_combat` timing flag (RULE 602.5d's converse of `sorcery_speed_only` — still legal at instant speed, ruled out only during combat, `GameEngine._not_during_combat_ok`).
  - **Gauntlets of Chaos** / **Modify Memory** — two RULE 701.10c after-effect riders on `ExchangeControlEffect`, both gated on the exchange *attempt's own outcome*: `destroy_auras_if_exchanged` (every Aura attached to either now-swapped permanent, only if the swap happened) and `draw_if_neither_controlled` (drawn regardless of whether it happened, whenever this ability's controller ends up controlling neither permanent).
  - **Psychic Transfer** — `ExchangeLifeTotalsEffect.life_difference_at_most`, a pre-effect numeric gate (the swap just doesn't happen if the life gap is too wide) — the life-total sibling of `ExchangeControlEffect`'s own cross-target checks.
  - **Mirror Mirror** — `TripleExchangeEffect` (life totals + every permanent either player controls + the three owner-scoped zones — hand/library/graveyard exchanges genuinely move *ownership*, RULE 701.10h, unlike a battlefield control swap) armed by `CreateDelayedTriggerEffect`'s new `capture="target_player"` mode, fed by a `choose_targets` clause declaring the RULE 115 player pick the delayed effect has no target of its own to gather.
  - **Juxtapose** — `JuxtaposeEffect`: two selection+exchange rounds (creatures, then artifacts), each picking the highest-mana-value permanent per player. **Documented simplification:** a mana-value tie is broken by lowest `instance_id` rather than an interactive choice.
  - **Cultural Exchange** — `CulturalExchangeEffect`: two chained interactive rounds via a new `request_choose_objects` action `"gain_control_for"` (control moves to a *named* player, not the chooser — a new `control_recipient_id` payload threaded through the whole choose-objects pipeline) — round 2 queued through round 1's own `then_specs`/`else_specs` (set to the same spec, so it runs either way). **Documented simplification:** the printed "choose the **same** number" isn't enforced — both rounds are independently "any number of".
  - **Perplexing Chimera** / **Sudden Substitution** — new `ExchangeControlSpellEffect` (RULE 701.10i: exchanging a permanent for a **spell** still on the stack, reusing `RulesEngine.gain_control_of_spell`/`change_target` — Commandeer's own primitives — for the spell side, a plain `controller_id` swap for the permanent side). Perplexing Chimera's own reflexive "that spell" + "you may" needed a genuinely new primitive: `_place_triggers`'s reflexive branch (RULE 603.3d — the target is baked in at fire time, never a RULE 115 choice) previously ignored `TriggeredAbility.optional` entirely; it now pauses on the ordinary do/decline `trigger_target` choice instead, carrying the already-resolved object across the pause (`RulesEngine._pending_trigger_reflexive_target`).
  - **Arteeoh, Dread Scavenger** — `ExchangeControlThenCopyTokenEffect`: exchange, then (only if it happened) a RULE 603.11 "when you do" reflexive connector opening a *fresh* triggered ability with its own real target (the third, un-exchanged artifact to copy) — `RulesEngine.enqueue_reflexive_trigger`, refactored out of `_enqueue_pay_cost_then_trigger` (the v206 "when you do" primitive) so both an optional-cost payoff and an arbitrary "if you do" gate can reach it. **Bug found and fixed by execute-testing this card:** `Card.as_copy`'s `add_types` naming "creature" on a non-creature original never flipped `is_creature`, so `CopyPermanentEffect(add_types=["creature"], set_power=1, set_toughness=1)` built a `Card` with printed power/toughness but `is_creature=False`, tripping `Card.__init__`'s own "power/toughness may only be set on creatures" invariant — real, load-bearing for any future "…except it's a(n) `<N>`/`<N>` `<type>` creature… in addition to its other types" card, not just this one. **Documented simplification:** "in addition to its **other colors**" (the green addition) isn't modeled — `CopyPermanentEffect` only has `set_colors` (replace), and this is the only card that would want an *additive* one.
  - **+12** (all twelve, 0 regressed). `tests/test_par30_exchange_control_bespoke.py`. **The whole RULE 701.10 exchange-control / exchange-life residue bullet is now closed.**

### Mass phasing + life-total lock (Teferi's Protection)

- **What:** Mass phasing (RULE 702.26b) phases host and attachment out together (unlike the single-permanent `PhaseOutEffect`, which unattaches); `PlayerShieldEffect` adds "your life total can't change" (RULE 119.6, checked at the `gain_life`/`lose_life` choke points) and player-side protection from everything (RULE 702.16e).
- **Files:** `game/effects.py`

### Pulling a spell off the stack (RULE 400.1)

- **What:** `RulesEngine.move_spell_off_stack` moves a `StackItem` into hand or exile — no existing bounce effect could touch the stack, only battlefield permanents; practically a counter that sends the card somewhere other than the graveyard, which is why Narset's Reversal / Possibility Storm both beat "can't be countered."
- **Files:** `game/rules_engine.py`

### Cloudstone Curio bounce + hand-to-battlefield tutoring

- **What:** `ReturnSharedTypePermanentEffect` computes its legal-return set dynamically off the entering permanent (Cloudstone Curio); `PutFromHandOntoBattlefieldEffect` reuses `request_search` against a new `"hand"` zone for Tooth and Nail, correctly neither shuffling nor firing `LIBRARY_SEARCHED`.
- **Files:** `game/effects.py`

### Naming a card (unenumerable choice)

- **What:** `RulesEngine.request_name_card` — the only choice in the engine whose answer space isn't enumerable from game state; offers visible cards as suggestions while accepting an arbitrary string, substituted into a `"named_card"` criteria sentinel. Powers Demonic Consultation.
- **Files:** `game/rules_engine.py`

### `dig_until` — parameterized cascade-style dig

- **What:** The cascade/discover dig generalized with a predicate and both destinations as parameters, plus a `not_name` key on card-query criteria.
- **Files:** `game/rules_engine.py`

### Repeat-until-a-predicate loop (Helm of Obedience)

- **What:** `MillUntilCreatureEffect` — the first "repeat until a predicate is met" loop primitive; bounded on both sides by construction (X caps it, an empty library ends it early).
- **Files:** `game/effects.py`

### Open-ended pay-life loop (Lim-Dûl's Vault)

- **What:** `request_look_top_pay_life_loop` — the first open-ended loop primitive, bounded only by the player's own life payment (RULE 118.4) rather than a safety cap, driven by a self-re-opening `pending_choice`.
- **Files:** `game/rules_engine.py`

### Scramble-the-spell effect (Possibility Storm, Tibalt's Trickery)

- **What:** `ScrambleSpellEffect` — one atomic effect for "exile the spell, then reveal/dig for a replacement and cast it" since every clause concerns the same spell and its controller; also drove the `SPELL_CAST` event's new `from_hand` key.
- **Files:** `game/effects.py`

### Bespoke wave-6 effects (Dauntless Dismantler, Tevesh Szat, Jeska, loyalty -X)

- **What:** `DestroyEachWithManaValueEffect` (mass destroy filtered by the announced X); `SacrificeEffect` gained `each_opponent`/`greatest_power` selectors; `GainControlOfAllCommandersEffect` (RULE 903.3); `MultiplyDamageFromTargetEffect` (a scoped, duration-bounded damage-doubling replacement); `ActivationCost.loyalty_is_x` for RULE 606.5c's `[-X]` loyalty cost.
- **Files:** `game/effects.py`, `game/costs.py`

### RULE 608.2 suspended resolutions (`deferred_effects`)

- **What:** `GameState.deferred_effects` parks the remainder of a multi-clause resolution's effect list whenever an earlier effect opens an interactive choice, and `RulesEngine.resume_deferred_effects` picks it back up afterward (innermost first) — the prerequisite everything else in Batch 26 built on.
- **Files:** `game/effects.py`, `game/rules_engine.py`
- **Bug fixed:** previously, `GameState.pending_choice` held exactly one decision, so a resolution with 2+ interactive effects let the second silently overwrite the first player's prompt — a real, reachable correctness bug on any multi-clause ability whose clauses both prompt, not just an enabler for new cards.

### Conditional search destinations (RULE 701.19c)

- **What:** `SearchLibraryEffect.destination_if` is a list of `{criteria, destination}` rules checked per found card, resolved only once the player names what they found — e.g. Archdruid's Charm's "onto the battlefield tapped if it's a land card, otherwise into your hand."
- **Files:** `game/effects.py`

### Face-down exile round trip (RULE 701.20a)

- **What:** A search destination of `"exile_face_down"` sets `GameObject.face_down_in_exile` (the first real use of the board's sleeve-art fallback); `CastExiledFaceDownEffect` grants Rebound's own exile free-cast window, with an independent `DelayedTrigger` returning the card to hand at the next end step if it wasn't cast, since the two halves have different conditions.
- **Files:** `game/effects.py`, `game/rules_engine.py`

### General interactive object chooser

- **What:** `RulesEngine.request_choose_objects` replaced the "auto-pick the first candidate" convention across seven cards at once — every effect naming what kind of object to act on but leaving which one to a player now routes through it, one object at a time like a library search, with the whole decision (candidates, picks so far, "if you do" follow-ups as serialized `EffectSpec` dicts) held as plain data so it survives `clone()`-based undo.
- **Files:** `game/rules_engine.py`

### Minor gap-fills found during Batch 26

- **Bug fixed:** `LoseLifeEffect` gained a `player_id` form (a specific named player, the only form a serialized spec can carry); `_matches_permanent_type` learned `creature_or_planeswalker`.
- **Files:** `game/effects.py`, `game/rules_engine.py`

### `request_each_player_pay_or` (PAR-13, RULE 101.4 APNAP "unless")

- **What:** "Each player loses N life unless they `<pay cost>`." (Veils of Fear, Sandfall Cell) as a chained sequence of the existing single-player `request_pay_cost_then` choice, advancing to the next queued player automatically. Also added a compound `ActivationCost.sacrifice` value, `creature_artifact_or_land`, for Sandfall Cell's own three-type-OR cost.
- **Files:** `game/rules_engine.py`, `game/costs.py`

### RULE 119/701.8 hand-disruption "reveal, choose, discard"

- **What:** Duress/Thoughtseize-shaped — the caster (not the hand's owner) chooses which revealed card gets discarded, reusing the existing `request_choose_objects` chooser shape sourced from a hand for the first time. Five filter phrasings recognized (bare/nonland/noncreature+nonland/creature-or-planeswalker/artifact-or-creature).
- **Files:** `game/effects.py`, `parser/oracle/catalogue/handlers.py`

### `RevealTopConditionalToHandEffect`

- **What:** RULE 701.28's "defending player reveals the top card… if it's a land, puts it into their hand" (Goblin Guide) — reveal itself has no separate game state, so the effect models only the conditional move. General over any of the four printed card-type words.
- **Files:** `game/effects.py`

### Miscellaneous small primitives (Imodane final singles batch)

- **What:** `CopySpellEffect.target_count`/`optional` ("copy any number of target spells", Display of Power); `AddManaEffect.target_kind`/`amount_from_target_hand_size` (Jeska's Will's first genuinely targeted use of that effect); a new `artifact_you_dont_control` target kind (Vandalblast); and `RulesEngine.put_hand_card_on_bottom_then_draw` (Volcanic Spite's "may put a card on bottom, if you do draw a card" — auto-taken as a pure exchange, no chooser).
- **Files:** `game/effects.py`, `game/rules_engine.py`, `game/targeting.py`

### RULE 119 "drain" idiom — life-lost-this-way accumulator (Rules Engine Core Loop)

- **What:** `GameContext.life_lost_this_way`, a per-resolution accumulator (the same save/reset/restore idiom as `previous_targets`/`created_objects`), incremented by `GameContext.lose_life`'s facade off the actual post-replacement life delta, read by `GainLifeEffect(count_selector="life_lost_this_way")` — closes Gray Merchant of Asphodel's "you gain life equal to the life lost this way" and 15+ cache siblings.
- **Files:** `game/effects.py`, `game/rules/misc_mixin.py`

### Grafdigger's Cage / Weathered Runestone Graveyard-Library Prohibition

- **What:** `continuous.graveyard_library_cast_prohibited` is one choke point in `GameEngine.can_cast` covering Flashback/Escape/Lurrus-shaped grants/top-of-library casting alike; `continuous.graveyard_library_entry_prohibited` is checked at the two real graveyard/library-to-battlefield routes (`ReturnFromGraveyardEffect._apply_one`, `RulesEngine._finish_search`'s battlefield destination) rather than a nonexistent universal hook.
- **Files:** `game/continuous.py`, `game/effects.py`, `game/rules/misc_mixin.py`.

### Force-End-the-Turn (Day's Undoing)

- **What:** `GameState.end_turn_requested` + `GameEngine.advance_step`'s drain — a `RulesEngine` effect can't reach the turn-loop cursor directly, so `end_the_turn` exiles the stack and queues a flag; `advance_step` runs the real `_step_cleanup()` before fast-forwarding into the next turn. New `EffectSpec.condition` key `is_your_turn`.
- **Files:** `models/game_state.py`, `game/engine/turn_loop_mixin.py`, `game/rules_engine.py`.

### Mass Board-Wipe Damage Selectors (Opponents + Their Permanents)

- **What:** `DealDamageEffect.selector`'s new `each_opponent_and_their_creatures[_and_planeswalkers]` (opponents-only, unlike the existing global `each_creature_and_player`) closes the End the Festivities/Tectonic Hazard/Delayed Blast Fireball board-wipe family.
- **Files:** `game/effects.py`, `parser/oracle/catalogue/handlers.py`.

### Search/Extra-Turn Prohibition Grants (Stranglehold)

- **What:** `GrantSearchProhibitedEffect`/`RulesEngine.request_search`'s guard (RULE 701.19a: a prohibited player instructed to search simply doesn't) and `GrantSkipExtraTurnsEffect`/`GameEngine.begin_turn`'s extra-turn queue skipping past a grant-matched queued taker.
- **Files:** `game/effects.py`, `game/engine/turn_loop_mixin.py`.

## Targeting

### Generalized graveyard-card targeting and Deathrite Shaman

- **What:** The Regrowth/Reanimate recursion family generalized to the full real-card vocabulary (card type × graveyard scope — own/any/an opponent's). New `return_from_graveyard`, `reanimate_under_your_control` (steals control regardless of whose graveyard), and `exile_from_graveyard` effects share a `_graveyard_target_kind` helper.
- **Files:** `game/targeting.py`, `parser/oracle/catalogue/handlers.py`

### "Up to one" targets (RULE 115.1a, N=1)

- **What:** The shared `TARGET` regex fragment grew an optional "up to one" prefix consumed by `TargetSpec(optional=True)`, so every existing `{TARGET}`-based handler recognizes "up to one target X" for free with no per-handler grammar duplication or `apply()` changes (a `None` target is already a no-op everywhere).
- **Files:** `parser/oracle/catalogue/subgrammars.py`, `parser/oracle/spec.py`
- **Why:** Deliberately N=1 only — "up to two/three/N" needs a genuinely bigger interactive multi-select feature, since the engine's `targets` list is one entry per targeting effect, not per "up to N" slot.

### Divided damage (RULE 601.2d)

- **What:** `DealDamageEffect(divided=True)` splits a total {X} pool evenly across the chosen targets, with an optional doubling threshold (`double_at`) — Shatterskull Smashing, Fire Covenant.
- **Files:** `game/effects.py`

### "Target creature with power/toughness/keyword" targeting filter

- **What:** New `TargetSpec.creature_filter` narrows `DestroyEffect`/`ExileEffect`'s target pool by power/toughness threshold or a closed keyword list (flying, first strike, deathtouch, etc.). Deliberately narrow — a compound filter or non-creature noun stays unclaimed rather than guessed.
- **Files:** `game/targeting.py`, `parser/oracle/catalogue/handlers.py`

### N>=2 Multi-Target Generalization (RULE 115.1a)

- **What:** `TargetSpec` gained a `count` field (`optional` becoming the 0-vs-`count` lower bound); `DestroyEffect`/`ExileEffect`/`DealDamageEffect` gained a matching `count` param, applying to `targets[:count]` sliced off the *front* of a shared targets list. New parser grammar recognizes both mandatory and "up to N" phrasing; the board expands a `count>1` requirement into `count` synthetic one-per-round picks reusing the existing multi-pick modal.
- **Files:** `game/targeting.py`, `game/effects.py`, `parser/oracle/catalogue/handlers.py`
- **Why:** Slicing off the front of a *shared* list (not consuming the whole thing) was needed so an unrelated single-target effect on the same stack item isn't over-consumed.

### Per-Effect Target Partitioning (`StackItem.target_groups`)

- **What:** A stack item's `targets` list used to be shared flat across every effect on it, so two *different* targeting effects on one spell/ability would have the second wrongly consume the first's target. `StackItem.target_groups` (index-aligned per targeting effect encountered in order) fixes this for casting/activating (an explicit param threaded to the session action handlers) and fully automatically for triggered abilities (a new `trigger_target_multi` interactive choice gathering one target per effect per round).
- **Files:** `models/game_state.py` (StackItem), `game/effects.py`, `game/rules_engine.py`, `game/game_engine.py`
- **Why:** `None` (the default) keeps every pre-existing flat-`targets` consumer byte-for-byte unaffected — this is additive, not a rewrite.

### New Target Kinds (Wyleth Equip Batch)

- **What:** `nonbasic_land` (Encroaching Wastes), `attached_equipment_you_control`/`equipment_you_control` (Akiri's unattach / Nahiri, Heir of the Ancients' +1).
- **Files:** `game/targeting.py`

### N>=2 Multi-Target for `return_to_hand`/`tap`/`add_counters`/`return_from_graveyard`

- **What:** The existing `count`-slicing idiom extended to four more effect families. `add_counters` needed a new `target_count` key (since `count`/`amount` already meant the counter amount); `return_from_graveyard` got its own plural-clause regex.
- **Files:** `game/effects.py`, `parser/oracle/catalogue/handlers.py`

### Compound Creature-Target Filter

- **What:** "power 4 or greater and flying" — `TargetSpec.creature_filter` already ANDed every dict key; the gap was purely that the parser only ever emitted one key. Extended the filter-suffix regex to an optional second "and [with] `<clause>`".
- **Files:** `parser/oracle/catalogue/handlers.py`

### Cross-Target "Controlled by Different Players"

- **What:** `TargetSpec.distinct_controllers` (Protector of the Wastes-shaped) constrains the *relationship* between targets chosen for one requirement — enforced at offer/pick time across rounds (`legal_targets` now carries `controller_id`) rather than inside the resolving effect, wired into `DestroyEffect`/`ExileEffect`/`ReturnToHandEffect`.
- **Files:** `game/targeting.py`, `game/game_engine.py`

### Pronoun Bound to Previous Clause

- **What:** `GameContext.previous_targets` records what the last *targeting* effect actually chose, so a later clause can name it with `previous_target`/`previous_target_2` pseudo-subjects ("target creature gets +1/+2. It fights target creature…" — Epic Confrontation) instead of needing a bespoke fused effect class per verb pair.
- **Files:** `game/effects.py`

### Per-Effect Target Partitioning for Spell/Ability Casting (ENG-5)

- **What:** `targeting.partition_targets` splits a flat, in-printed-order target list into one group per requirement, derived automatically by `_cast_current_face`/`activate_ability` into `StackItem.target_groups` when the caller supplies none; returns `None` (old shared-list behavior) when the length doesn't match, since that's exactly what a declined "up to one" produces.
- **Files:** `game/targeting.py`, `game/game_engine.py`

### RULE 109.5 Cross-Requirement "Another"

- **What:** `TargetSpec.distinct_from_others` excludes a sibling requirement's own pick ("target creature you control fights **another** target creature") — an offer-time exclusion across rounds with a resolve-time backstop in the effect, the same shape as `distinct_controllers`.
- **Files:** `game/targeting.py`, `game/effects.py`

### Goad Target Count Read Off the Board

- **What:** "For each opponent, goad up to one target creature that player controls" combines a `TargetSpec.count_selector` (RULE 601.2c, resolved at announce time) with the existing `distinct_controllers`. `targeting.expand_counts`/`collapse_groups` split a multi-target requirement into one round each for the trigger-gathering path and merge them back, keeping the one-group-per-spec resolution contract intact. A new `"stop"` answer (distinct from declining) lets RULE 115.1a's "up to N" stop early while keeping the ability.
- **Files:** `game/targeting.py`, `game/rules_engine.py`

### Naming What the Previous Clause Created

- **What:** `GameContext.created_objects` (sibling of `previous_targets`) lets a later clause refer to tokens a previous clause in the same resolution just made, which were never targeted and didn't exist when the ability went on the stack. Also widened the token grammar for "each player/opponent creates" and "creates a tapped …".
- **Files:** `game/effects.py`

### Equip/Fortify/Reconfigure control restriction fix

- **Bug fixed:** RULE 702.6a/702.67a/702.151a's "target creature/land you control" was unenforced — `targeting.py`'s `legal_targets` offered any creature/land including an opponent's, and `rules_engine.py`'s `_attachment_legal` didn't re-check control at resolution either (RULE 301.5b requires checking at both points); Equip's fallback also wrongly allowed targeting any artifact, not just creatures.
- **Files:** `game/targeting.py`, `game/rules_engine.py`

### "Another creature you control" target kind

- **Bug fixed:** `creature_you_control` had been wrongly excluding the ability's own source, so Mother of Runes couldn't target herself and a Karoo land couldn't bounce itself; a new `other_creature_you_control` kind now does the real exclusion, leaving the plain kind correct.
- **Files:** `game/targeting.py`
- **Parser wiring (PAR-30, PARSER_VERSION 161):** the engine kind was fully wired (exclusion, "you control" scoping, German label) but no `subgrammars._TARGET_ROWS` row emitted it, so every card printing "**another target creature you control** gains `<kw>` until end of turn" (Heavenly Qilin, Duke Ulder Ravengard, Selfless Savior, Void Grafter, Blooming Stinger, …) sat UNMODELED on the target phrase alone. Added the row (above the plain "target creature you control" row so the longer phrase wins) + `handlers._pump_target`'s pumpable-kind allowlist gained `other_creature_you_control`. Reaches every `TARGET`-embedding handler, not just pump. +31 real cache cards, 0 regressed. The no-"you control" form ("another target creature" — Arwen, Mortal Queen) stays UNMODELED: its `other_creature` kind is not engine-wired.
- **Tests:** `tests/test_par30_another_target_creature.py` (parse: single/two-keyword forms + no-"you control" fail-closed + real cards; execute: `legal_targets` excludes the source and an opponent's creature, and the pump lands on the friendly non-source creature).

### Two independently-chosen targets in one clause

- **What:** `GameEffect.extra_target_specs` lets one effect gather 2+ independently-typed targets in a single clause (Brass Squire, Halvar, Archdruid's Charm's second mode) — needed because that mode must be atomic (the damage reads the target's power after the +1/+1 counter lands).
- **Files:** `game/effects.py`

### RULE 115.1a "any number of target `<X>`" (PAR-15 + residue)

- **What:** `catalogue.handlers._MULTI_TARGET_QUANTIFIER` gained an "any number of" alternative (capped at 10, `optional=True`), widening nine existing multi-target handler families at once. The named biggest cluster, RULE 601.2d's "deals N damage divided as you choose among any number of targets" (`_DIVIDED_DAMAGE_RE`), reached the pre-existing `DealDamageEffect(divided=True)` primitive for the first time from oracle text — unlocking every Strive card (MEC-4) for the first time, since Strive always pairs with this shape. The follow-up "PAR-15 residue" pass closed the remaining named clusters with the same underlying cap/optional idiom: `AddCountersEffect.divided` (distribute counters among any number of targets), `PumpEffect.target_count` + `TapEffect.previous_subject` ("N target creatures get +X/+X… Untap those creatures."), and two new `ReturnFromGraveyardEffect` destinations (library top; shuffle into library).
- **Files:** `parser/oracle/catalogue/handlers.py`, `game/effects.py`, `game/rules_engine.py`

### Polarity-aware targeting classification (PLR-7/PLR-8)

- **What:** `GameEffect.target_polarity()` classifies an effect as `"harmful"`/`"beneficial"`/`None` (best-effort, non-rules), including sign-aware classification for `PumpEffect`/`AddCountersEffect`/`TapEffect` and a synthesized polarity for an Aura's own layer-7 P/T grant. Stamped onto `TargetSpec.polarity` and threaded to `GreedyBot.rank_targets`, which reverses its "opponent's stuff first" default for beneficial effects. Deliberately not exhaustive — an unclassifiable effect (e.g. `RemoveCountersEffect`, genuinely ambiguous by class alone) stays `None` rather than guessed.
- **Files:** `game/effects.py`, `game/targeting.py`, `services/bots.py`

### Saved-deck-priority parser batch: mass "destroy/exile all X" board wipes (PAR-12)

- **What:** The engine primitive already existed (hand-authored per card); no parser handler recognized the general English phrasing. New `destroy_all`/`destroy_all_no_regen`/`exile_all` rows, plus a new `"all_lands"` mass selector (Jokulhaups-shaped). Only the numeric filter kinds the engine actually implements (mana value, toughness) are recognized; "power N or greater" is left unclaimed.
- **Files:** `parser/oracle/catalogue/handlers.py`

### General N-way "target artifact, enchantment[, or land]" (PAR-12, RULE 115)

- **What:** One general regex covering any 2+ combination of artifact/creature/enchantment/land/planeswalker, mapping to the existing broad `"permanent"` target kind, rather than enumerating every real-card permutation by hand.
- **Files:** `parser/oracle/catalogue/subgrammars.py`

### Mass-destroy power filter + negated creature filters (Hobbits batch)

- **What:** `min_power`/`max_power` joined the pre-existing mana-value/toughness mass-destroy filters (Elspeth, Sun's Champion). `combat.matches_object_filter` also gained `without_card_type` ("target nonartifact creature"), hand-authored for Go for the Throat.
- **Files:** `game/effects.py`, `game/combat.py`

### Filtered creature-target family widenings + `creature_filter` bug fix

- **What:** `RulesEngine.blink` gained a `controller` param (Restoration Angel's "under your control" vs. plain blink's "under its owner's"); `RulesEngine.regenerate` gained a `creature_filter` param ("regenerate another target Elf"); `combat.matches_object_filter` gained `without_color`/`without_subtype`/`"attacking"` keys (Doom Blade's "nonblack", ~47 SOLO cache-wide); and `DrawCardEffect` gained `target_kind`/`.selector` for "target player draws a card", which had no handler at all before.
- **Files:** `game/rules_engine.py`, `game/combat.py`, `game/effects.py`, `game/targeting.py`
- **Bug fixed:** `targeting.legal_targets`'s `creature_you_control`/`other_creature_you_control`/`land_you_control` branch never consulted `TargetSpec.creature_filter` at all — any card needing a filtered "target creature you control" (not just the one that surfaced it) was silently offering every creature regardless of the filter.

### RULE 115.4 "change the target of target spell" (cEDH second pass)

- **What:** A live retarget of an already-existing stack item — genuinely distinct from the pre-existing "choose new targets for a freshly-made copy" (RULE 707.10c). `ChangeTargetEffect`/`RulesEngine.change_target`: the changing player is the effect's own controller (RULE 115.4a, not the targeted spell's), legal alternatives are recomputed fresh against the current board and always include the current target, and a single legal option auto-applies with no prompt. New `"change_target"` `pending_choice` kind reuses the existing generic choice-button rendering with zero frontend changes. Deliberately scoped to spells (not abilities — `StackItem.obj` is `None` for an ability item, a bigger primitive logged separately) with exactly one existing target. Hand-authored for Misdirection (mandatory) and Deflecting Swat (optional) at their real printed mana costs.
- **Files:** `game/effects.py`, `game/rules/misc_mixin.py`, `game/targeting.py`, `game/ability_catalogue.py`

### RULE 115/608.2b "target an activated or triggered ability" (ENG-26)

- **What:** `StackItem.stack_id` gives every stack item (spell or ability alike) a stable identity, backing two new targeting kinds (`"ability"`, `"spell_or_ability"`). `CounterAbilityEffect`/`RulesEngine.counter_ability` (RULE 701.5b) closes Stifle/Trickbind; `ChangeTargetEffect` gained `spell_or_ability=True` for Deflecting Swat's real "target spell or ability" scope.
- **Files:** `models/game_state.py`, `game/targeting.py`, `game/rules/misc_mixin.py`, `game/ability_catalogue.py`
- **Why:** An ability `StackItem`'s own `.obj` is `None` (the permanent lives on `.source` instead), so nothing could previously name "an ability on the stack" as a target at all.

### Otawara, Soaring City + four-permanent-type union target (Targeting)

- **What:** Otawara hand-authored reusing Eiganjo/Boseiju's existing Channel + `ActivationCost.dynamic_reduction` shape; new `targeting.py` kind `artifact_creature_enchantment_or_planeswalker` for its real "target artifact, creature, enchantment, or planeswalker" wording.
- **Files:** `game/ability_catalogue.py`, `game/targeting.py`

### Mindbreak Trap: "exile any number of target spells" (Targeting)

- **What:** `_multi_target_params`'s existing "any number of" cap (`_ANY_NUMBER_TARGET_CAP`) gained a "target spells" row, scoped only to `exile` (destroy/damage never legally target a spell).
- **Files:** `parser/oracle/catalogue/handlers.py`

### RULE 115.4 "change the target" gets its first oracle-text handler (Targeting)

- **What:** `ChangeTargetEffect` (previously only hand-authored per card) gained a generic parser row for "Change the target of target spell [or ability] with a single target," closing Bolt Bend/Redirect Lightning in this pool and Deflection/Shunt/Swerve/Willbender cache-wide.
- **Files:** `parser/oracle/catalogue/handlers.py`

### Auriok Salvagers: mana-value filter on graveyard-recursion targeting (Targeting)

- **What:** `ReturnFromGraveyardEffect` gained a mana-value filter (constructor param, regex capture group, and a `targeting.py` check reusing `destroy_mv`'s `TargetSpec.max_mana_value`) — reaches 102 real cache cards printing "return target `<type>` card with mana value N or less from `<scope>` graveyard" (Sun Titan, Unearth, and others), most already closing outright.
- **Files:** `game/effects.py`, `game/targeting.py`, `parser/oracle/catalogue/handlers.py`
- **Living Death mass recursion (PAR-30, v164):** `ReturnFromGraveyardEffect.players` (`"you"` / `"each_player"`) — a mass, untargeted return over every matching graveyard card, run through the same `_apply_one` (ETB prohibition/redirect, owner-control, haste/tapped riders) as a single target. Parser `_MASS_RETURN_GRAVEYARD_RE` claims "[each player returns / you return / return] all/each creature card[s] from [their/your/its owner's] graveyard to the battlefield/hand". `_vote_majority`'s "a targeted branch can't resolve off-stack" guard was narrowed to spare a `players`-scoped branch (its `target_kind` is just the card filter, not a RULE 115 choice). +2 (Empty the Catacombs; Magister of Worth, whose two vote branches are now both modeled — combined with v163's `all_other_creatures`). Riders on the returned cards (a -1/-1 counter, "each is a 1/1 Spirit") stay fail-closed. Tests: `tests/test_par30_mass_return_graveyard.py`.
- **"Return X target creature cards" (PAR-30, v168):** `ReturnFromGraveyardEffect` gained a `count_selector` param, threaded into its `TargetSpec` (so the targeting layer offers X picks at cast via `targeting.resolved_count`'s pre-existing `"source_x_paid"` reading of `GameObject.x_paid` — the March of Swirling Mist / Change of Plans idiom) plus a multi-target `apply` branch that takes *every* pick the targeting layer handed it (the printed `effective_count` stays 1, so the old `!= 1` branch never fired). New `_RETURN_FROM_GRAVEYARD_X_RE`/handler ("return [up to] X target `<type>` cards from [scope] graveyard to your hand / the battlefield"), tried before the numeric-N plural handler (whose `\d+` can't match "x"). +3 (Death Denied, Entreat the Dead, Wildest Dreams; narrows Wake the Dead / Shattered Crypt / Champion of Stray Souls). Tests: `tests/test_par30_return_x_from_graveyard.py`.

### Assassin's Trophy: unscoped permanent target + controller-redirected search (Targeting)

- **What:** New `permanent_you_dont_control` target kind ("target permanent an opponent controls," no type restriction) plus a widened `destroy` handler whitelist (previously hardcoded to `("creature", "permanent")`, silently dropping any other kind). `SearchLibraryEffect` gained a `payer="previous_target_controller"`-shaped sentinel (`player="previous_target_controller"`) for "its controller may search…" — the destroyed permanent's controller, not the caster.
- **Files:** `parser/oracle/subgrammars.py`, `game/targeting.py`, `game/rules/misc_mixin.py`, `game/effects.py`
- **Bug fixed:** The plain `destroy` handler silently discarded any target kind outside `("creature", "permanent")`, including the pre-existing `creature_you_dont_control` — never exercised through this code path before.

### Mutiny: independently-targeted damage-equal-to-power (Targeting)

- **What:** `DamageEqualToPowerEffect` (built for Rabid Bite) with `extra_target_specs` giving *both* fighters their own `creature_you_dont_control` target.
- **Files:** `game/effects.py`, `game/ability_catalogue.py`

### Bug: `DrawCardEffect` read a shared `targets` list without checking its own target spec (Targeting)

- **What:** Unlike `GainLifeEffect`/`LoseLifeEffect`, `DrawCardEffect` fell back to `targets[0]` whenever `self.player` was unset and *any* `targets` list was non-empty, regardless of whether it had declared its own `target_spec` — surfaced by Arcane Denial's delayed-trigger draw inheriting the arming resolution's target.
- **Files:** `game/effects.py`

### `LookAtCardsEffect` (Targeting)

- **What:** "Look at the top card of target player's library." — a genuine RULE 115 target with no other game-state consequence, kept as its own effect (rather than an empty effects list) specifically so the target requirement survives. Closes Mishra's Bauble/Urza's Bauble.
- **Files:** `game/effects.py`, `game/ability_catalogue.py`

### `pump_up_to_two` (Targeting)

- **What:** "Up to two target creatures each get +N/+N…" (Dauntless Onslaught-shaped) / "One or two target creatures…" both fold to `PumpEffect`'s existing "up to N" idiom — purely a missing recognizer, closing 20 cards including Opera Love Song.
- **Files:** `parser/oracle/catalogue/handlers.py`

### MEC-19: `EventType.BECOMES_TARGET` + `CounterUnlessPayEffect` (Targeting)

- **What:** RULE 115/601.2c targeting had never reached the event bus — `EventType.BECOMES_TARGET` now fires once per target from the same choke point `check_ward` already used (Ward is unchanged, a parallel consumer). New `effect_binder` group-controller key and a `caster_relation` predicate ("opponent"/"you") power the trigger grammar. `CounterUnlessPayEffect`/`counter_unless_pay` is a thin adapter onto the existing `resolve_ward_effect`, closing an 87-card un-keyworded cycle that prints Ward's outcome as plain text. 14 cards fully MODELED; Goldspan Dragon and Tectonic Giant hand-authored as second specs on the same compound-event idiom used elsewhere.
- **PAR-30 (PARSER_VERSION 141, +21):** `_BECOMES_TARGET_TRIGGER_RE` had only ever matched "**Whenever** ~ becomes the target …", but the ~19-card Innistrad/Zendikar **Illusion cycle** (Phantasmal Bear, Frost Walker, Skulking Ghost, Gossamer Phantasm, Illusionary Servant, Phantom Beast, Skulking Fugitive/Knight, Tar Pit Warrior, …) prints "**When** ~ becomes the target of a spell or ability, sacrifice it." — semantically interchangeable here (a self-sacrifice fires identically off the first event either way). One-word widen to `when(?:ever)?`; no engine change. Verified end-to-end (Lightning Bolt at a Phantasmal Bear sacrifices it). Still open: the "sacrifice it **unless you discard a land card**" variant (Cursed Monstrosity) and the quoted-grant forms ("has 'when ~ becomes the target …'" — Crystalline Nautilus, Dismiss into Dream, Boneshard Slasher, Makeshift Mannequin). `tests/test_par30_becomes_target_sacrifice.py`.
- **Files:** `game/rules_engine.py`, `game/effect_binder.py`, `game/effects.py`, `parser/oracle/segmenter.py`

### RULE 601.2c Target-Count Range (`count_max`) (ENG-30)

- **What:** `TargetSpec.count_max` plus `effective_count` property express "N or M target `<X>`" (at least N, at most M) — a genuine third shape alongside exact `count` and "up to N" `optional`. `count` stays the RULE 601.2c minimum for offer-time castability locking; `effective_count` is what every effect class's target-slicing now reads. Threaded through 8 effect classes/factories and both interactive gathering paths (trigger multi-target rounds, client-driven spell/ability rounds), expanding to `count_max` rounds with the first `count` mandatory and the rest declinable.
- **Files:** `game/targeting.py`, `game/effects.py`, `game/rules/misc_mixin.py`, `frontend/src/js/gameBoardView.js`.
- **Why:** Slicing by the minimum (the pre-existing convention) would silently drop a legally-chosen second target for a range spec.
- **Bug fixed:** The pre-existing "up to two target creatures…" pump row set a spec key (`"count"`) the `"pump"` factory never read (it only reads `"target_count"`), silently limiting every card on that template to one target regardless of intent.

### Bounce a Spell Still on the Stack (Sink into Stupor)

- **What:** `RulesEngine.bounce_spell_or_permanent` + `ReturnToHandEffect.spell_or_permanent` pulls a target directly out of `GameState.stack`, since ordinary zone-removal has no idea the stack exists. New target kinds `spell_or_nonland_permanent_you_dont_control`/`spell_you_dont_control`.
- **Files:** `game/effects.py`, `game/rules_engine.py`, `game/targeting.py`.

### Forced Retarget-to-Source (Spellskite, Hydroelectric Specimen)

- **What:** `ChangeTargetEffect.redirect_to_source` + a `card_types` filter — a *forced* redirect onto the effect's own source, implemented by narrowing `legal_targets` to just the source and falling through to the existing mandatory-auto-apply/optional-decline retarget logic rather than a parallel no-choice path.
- **Files:** `game/effects.py`, `game/rules/misc_mixin.py`.

### Colour-OR Targeting (`TargetSpec.colors`)

- **What:** `TargetSpec.colors` (OR of 2+ WUBRG letters) + shared `_color_ok` helper replacing inline per-branch colour checks across `legal_targets`; `DealDamageEffect(colors=[...])` for Rending Volley's "target white or blue creature."
- **Files:** `game/targeting.py`, `game/effects.py`.
- **Pump family (PAR-30, v169):** `PumpEffect` gained a `colors` param threaded into its `TargetSpec` — the field and `_color_ok` were already wired into `legal_targets`, just never reached from a pump. Dedicated parser row `_PUMP_TARGET_TWO_COLOR_RE` / `_pump_target_two_color` ("target `<c1>` or `<c2>` creature gets +N/+M / gains `<kw>` until end of turn", flag keywords only, same-colour-twice rejected) — the `_DAMAGE_TARGET_TWO_COLOR_RE` sibling, a standalone row because the shared `TARGET` macro's fixed rows carry no colour slot. +7 (the Weaver cycle: Hate/Rage/Sky/Might/Spirit Weaver, Sootstoke Kindler, Wilderness Hypnotist). `tests/test_par30_pump_two_color_target.py`.
- **Removal (PAR-30, v170):** `DestroyEffect` and `ExileEffect` gained the same `colors` param, threaded into their `TargetSpec` (the multi-letter sibling of `DestroyEffect.color`'s existing single-letter Pyroblast form). `_DESTROY_COLOR_ADJ_RE` (which already handled a *single* colour adjective) widened to a "`<c1>` or `<c2>`" pair + an optional "with `<kw>`" `creature_filter` tail (Deathmark, Wallop); new dedicated `_EXILE_TARGET_TWO_COLOR_RE` / `_exile_target_two_color` for "exile target `<c1>` or `<c2>` creature/permanent[ you don't control]" (Celestial Purge). Shared `_two_color_letters` helper (same-colour-twice → `None`). +3. `tests/test_par30_removal_two_color_target.py`.
- **Bounce / put-on-library / graveyard-recursion (PAR-30, v171):** `ReturnToHandEffect` / `ReturnToLibraryEffect` / `ReturnFromGraveyardEffect` each gained the same `colors` param → `TargetSpec.colors`; three dedicated `_RETURN_*_TWO_COLOR_RE` handlers (Escape Routes, Hunting Drake, Crypt Angel). Also plugged a latent gap discovered here: the `creature_you_control` / `land_you_control` / `other_creature_you_control` branch of `legal_targets` had never applied `_color_ok` (every other creature branch did) — added, a no-op unless `colors`/`color` is set. +3. `tests/test_par30_movement_two_color_target.py`.
- **Tap / compound bounce (PAR-30, v172):** `TapEffect` gained the same `colors` param; `_TAP_TWO_COLOR_RE` ("tap/untap target `<c1>` or `<c2>` creature[ an opponent controls]") → Tidebinder Mage. New compound `_RETURN_SELF_AND_TWO_COLOR_RE` ("return ~ and target `<c1>` or `<c2>` creature to their owner's hand") emits two `return_to_hand` specs → Snow Hound. Landed folded into the MEC-46 v173 commit (interleaved edits).
- **Graveyard-card exile + N-colour lists (PAR-30, v174):** new `_color_word_list` — the ≥3-colour generalization of `_two_color_letters` ("red, white, or black" → `["R","W","B"]`, repeated colour → `None`). `_EXILE_FROM_GRAVEYARD_RE` gained an optional `(?P<colors>…)` group → `exile` spec's `colors` (the `ExileEffect.TargetSpec.colors` threaded at v170); `targeting.legal_targets`' graveyard-card branch gained the `_color_ok` call every battlefield branch already had, so the narrowing applies to a `graveyard_creature` target too. Paired with a new `grant_until_previous` handler (`_GRANT_UNTIL_PREVIOUS_RE`, `previous_subject_only`) for "It gains `<kw>` until your next turn." binding "it" to the preceding clause's subject — the `_lockdown` / `_return_to_hand_previous` idiom, any non-EOT `_GRANT_DURATIONS` value. +2: Offspring's Revenge (exile RWB graveyard creature → 1/1 copy token → haste until your next turn), Bond of Revival. `tests/test_par30_gy_color_list_and_grant_until_previous.py`.
- **Combat-state target tail (PAR-30, v175):** `_DESTROY_COLOR_ADJ_RE` gained an optional "…that's attacking or blocking / attacking / blocking" group → a `creature_filter` boolean; `combat.matches_object_filter` gained `blocking` / `attacking_or_blocking` keys (siblings of the pre-existing `attacking`, resolved via `blocking_attacker_ids`). +1: Surge of Righteousness. `tests/test_par30_destroy_combat_state_target.py`.
- **"The damage can't be prevented" (PAR-30, v176):** RULE 615.6. `DealDamageEffect` gained an `unpreventable` flag — `apply()` flips `GameState.damage_prevention_disabled` (the flag `_run_replacement_loop` reads to drop every `prevents_damage` effect) for the span of that one call, restoring it in a `finally` so unrelated later damage this turn is unaffected. The two-colour damage-target regex folds in an optional "…the/that damage can't be prevented" rider (Combust). Separately, a new standalone `_DISABLE_DAMAGE_PREVENTION_RE` routes "Damage can't be prevented this turn." to the pre-existing `disable_damage_prevention` effect (`DisableDamagePreventionEffect`, previously reachable only from hand-authored Insult // Injury). +6: Combust, Flaring Pain, Impractical Joke, Unstable Footing, Pyrewood Gearhulk, A-Ready to Rumble. `tests/test_par30_unpreventable_damage.py`. This closes the colour-list target cluster.

### Linked-Exile Tracking (`remember` on Exile/Search)

- **What:** `ExileEffect`/`SearchLibraryEffect` both gained a `remember` flag stamping `GameObject.linked_exile_id`, backing `Cemetery Gatekeeper`'s `shares_type_with_linked_exile` condition.
- **Files:** `game/effects.py`.

## Replacement Effects

### Replacement effect stacking (RULE 616)

- **What:** `RulesEngine.apply_replacements` rewrites an event through each applicable replacement at most once — draw→draw-2→mill chains and full prevention both work.
- **Files:** `game/rules_engine.py`

### Interactive replacement ordering (RULE 616.1e/f)

- **What:** When exactly one replacement applies it's used automatically; when 2+ apply simultaneously, `apply_replacements` opens a `replacement_order` `pending_choice` for the affected player, applying picks one at a time until only one candidate remains. New `EventType.COUNTER`/`CREATE_TOKENS` events and `source_id`/`source_controller_id`/`source_colors`/`combat` on `DAMAGE` let replacements filter by source. New `double_damage`/`additional_damage`/`double_counters`/`double_tokens` families, hand-authored onto Furnace of Rath, Gratuitous Violence, Torbran, Doubling Season, Parallel Lives.
- **Files:** `game/rules_engine.py`, `game/effects.py`, `game/ability_catalogue.py`, `gameBoardView.js`
- **Why:** Mirrors RULE 603.3b's trigger-order pause/resume but is always interactive rather than opt-in, since replacement collisions are rare and always rules-meaningful when they occur.

### Conditional enters-tapped choice (RULE 614.1 replacement)

- **What:** `land_tap_condition` classifies a land's tapped-entry clause (`always`/`never`/`pay_life` shock lands/`unless_types` check lands/`unless_count` fast-slow lands); deterministic shapes resolve immediately, a shock land opens a genuine `land_tapped` `pending_choice` defaulting to tapped, reusing the pending-choice plumbing.
- **Files:** `game/ability_catalogue.py`, `game/rules_engine.py`

### Fourth land-tapped clause variant: opponents'-lands count

- **What:** "~ enters tapped unless your opponents control N or more lands" (the Turbulent cycle) — a new `unless_opponents_count` kind summing lands across every player except the controller, distinct from the existing controller-own-lands and opponent-*player*-count shapes.
- **Files:** `parser/oracle/catalogue/lands.py`, `game/rules_engine.py`

### Replacement-clause oracle-text recognition (double_tokens/double_counters/additional_damage)

- **What:** New `parser/oracle/catalogue/replacements.py` recognizes 3 of the 5 already-bound `ReplacementRegistry` families straight from oracle text — Doubling Season's token/counter doubling and Torbran/Mechanized Warfare's single-color "plus N damage" clause.
- **Files:** `parser/oracle/catalogue/replacements.py`, `parser/oracle/segmenter.py`
- **Bug fixed:** `ParseResult.effect_specs` excluded `ability_kind == "replacement"` entirely, so nothing this handler produced would have reached `obj.replacement_effects` even though the card parsed `MODELED`.

### Innkeeper's Talent Causer-Scoped Counter-Doubling

- **What:** "If **you** would put one or more counters on a permanent or player, put twice that many instead" scopes by who's *causing* the placement, distinct from Doubling Season's recipient-scoping. `add_counters`/`add_player_counters` gained an optional `source` param carried onto the COUNTER event as `source_controller_id`; `_double_counters_replacement` gained a `your_effects_only` flag.
- **Files:** `game/effects.py`, `game/rules_engine.py`

### Mechanized Warfare Compound Damage-Doubling Filter

- **What:** `additional_damage`'s single `color` param generalized to OR-combined `colors`/`types` lists, so a source qualifies if it matches *any* listed colour or type word (e.g. "a red or artifact source").
- **Files:** `game/effects.py`, `parser/oracle/catalogue/replacements.py`

### `prevent_damage` One-Shot Shield

- **What:** `PreventDamageEffect`/`RulesEngine.prevent_damage_to_player` — a resolve-time-built `ReplacementEffect` living on `Player.player_effects` rather than a permanent's own, since nothing is being regenerated. `amount="all"` (Riot Control) never self-removes; an int (Thought Lash) opens a cumulative bank spent across however many DAMAGE events it takes. Swept at cleanup by a new marker-based sweep in `_step_cleanup`.
- **Files:** `game/effects.py`, `game/rules_engine.py`, `game/game_engine.py`

### Damage-Multiplying Replacement Family Recognition

- **What:** `_double_damage_replacement` gained a `multiplier` param (Fiery Emancipation's "triple") and a `creature_only` param for Gratuitous Violence's "a creature you control" scoping, reading a new `source_is_creature` DAMAGE-event field.
- **Files:** `parser/oracle/catalogue/replacements.py`, `game/effects.py`
- **Bug fixed:** The pre-existing hand-authored Gratuitous Violence entry wrongly required `combat_only`, a restriction its real printed text never had.

### Lurrus Trailing "Exile Instead of Graveyard" Clause

- **What:** `GraveyardCastPermissionEffect.exile_if_would_be_put_into_graveyard` redirects a graveyard-cast-permission spell to exile instead, via `RulesEngine._move_to_graveyard` — the one choke point every graveyard-bound move (destroy/sacrifice/SBA dies) funnels through.
- **Files:** `game/effects.py`, `game/rules_engine.py`

### Life-Gain Rewrite Replacement

- **What:** `gain_life_replacement` (`plus`/`multiplier` params) covers Angel of Vitality's additive "plus N instead" and Boon Reflection/Alhammarret's Archive's multiplicative "twice that much instead", needing a new `EventType.LIFE_GAIN` pre-event that `RulesEngine.gain_life` now routes through `apply_replacements` first.
- **Files:** `game/effects.py`, `game/rules_engine.py`

### Recipient-Scoped +1/+1 Counter Replacement

- **What:** `_double_counters_replacement` gained `plus`/`multiplier`/`recipient` params for Hardened Scales/Conclave Mentor's additive "that many plus one" (creature you control) and Branching Evolution/Corpsejack Menace's "twice that many" — distinct from Doubling Season's unscoped clause.
- **Files:** `game/effects.py`

### "If ~ Would Die, Exile It Instead" Replacement

- **What:** `die_to_exile`, subject-scoped (self/you-control/any/opponent), fired off a new `EventType.WOULD_DIE` that `RulesEngine._move_to_graveyard` raises for any creature actually leaving the battlefield — covers destroy, sacrifice and SBA dies since all three funnel through that method.
- **Files:** `game/effects.py`, `game/rules_engine.py`

### Targeted/divided damage prevention (PAR-15 residue, RULE 615)

- **What:** "Prevent the next N damage… to any number of targets, divided as you choose" (Embolden/Angel of Salvation). `PreventDamageEffect` gained `target_kind`/`divided`/`amount_if_kicked` modes and a new `RulesEngine.prevent_damage_to_target` primitive, the any-target sibling of the existing player-only prevention shield, sharing its cumulative-bank/cleanup semantics.
- **Files:** `game/effects.py`, `game/rules_engine.py`

### "Prevent the next N damage… to any target this turn" singular (PAR-12, RULE 615)

- **What:** The singular-target sibling of the already-shipped plural "divided among any number of targets" prevention shape — `PreventDamageEffect`'s `target_kind` branch already supported it; only the oracle-text row (with a different word order than the plural form) was missing.
- **Files:** `parser/oracle/catalogue/handlers.py`

### RULE 615 Fog-shaped unscoped prevention

- **What:** "Prevent all combat damage that would be dealt this turn" — no chosen recipient at all, unlike the pre-existing per-recipient prevention shields. New `PreventAllCombatDamageEffect`/`RulesEngine.prevent_all_combat_damage_this_turn`. One of the most repeated templates in the cache: +36 cards.
- **Files:** `game/effects.py`, `game/rules_engine.py`

### Turn-scoped exile-instead-of-graveyard grant (Imodane batch)

- **What:** `GrantDieToExileThisTurnEffect` (Lava Coil/Smite the Deathless-shaped "exile instead of graveyard, this turn only") — a turn-scoped `ReplacementEffect` appended directly to a target's `replacement_effects` with the firing turn number baked into a closure condition for self-expiry.
- **Files:** `game/effects.py`

### Mox Diamond: RULE 614.12 "would enter, discard a land instead" (Replacement Effects)

- **What:** New `AbilitySpec.enter_or_graveyard_discard_land` + `RulesEngine._offer_enter_or_graveyard`, spliced into `_resolve_permanent_spell`'s continuation chain *before* enter-as-copy/protector/enter-choice/Read Ahead, since declining means the object never becomes a permanent at all.
- **Files:** `game/rules/casting_mixin.py`, `parser/oracle/spec.py`

### Spark Double: copy-with-extra-counter (Replacement Effects)

- **What:** `EnterAsCopyReplacement` gained `extra_counter_if_creature`/`extra_counter_if_planeswalker` (applied post-copy, once the resulting permanent's real type is known); `targeting.py` gained `creature_or_planeswalker_you_control`.
- **Files:** `game/effects.py`, `game/targeting.py`, `game/ability_catalogue.py`

### Prevent Life Gain This Turn (RULE 119.3)

- **What:** `RulesEngine.prevent_life_gain_this_turn`/`PreventLifeGainEffect` — an absolute LIFE_GAIN cancel, the first sibling of `prevent_damage_to_player`'s numeric-shield shape that isn't a bank.
- **Files:** `game/rules_engine.py`, `game/effects.py`.

### Power-Floor Damage Replacement (Ojer Axonil)

- **What:** `_damage_floor_from_source_power_replacement` — sibling of `_additional_damage_replacement`, where the threshold and the replacement amount are the same live value (the source's current power), re-read every firing.
- **Files:** `game/effects.py`.

### MEC-30: standing `prevent_damage` replacement family, carded end to end (RULE 615/616.1)

- **MEC-30 Pass 1: Standing `prevent_damage` Replacement Carded:**
  - **What:** The long-dormant, fully-built standing `_prevent_damage_replacement` (`"prevent_damage"` in `ReplacementRegistry`) got its first real card bindings. Widened with five axes: recipient (`to="attached_permanent"`/`"any_player"`/`"opponent_player"`/`"controlled_permanent"`, plus `recipient_filter`/`recipient_union`), `source_filter` (colour/artifact/creature/spell/opponent-controlled), `amount={"all_but": N}`/`{"half": ...}`/`amount_count_selector`, a generic `rider` follow-up (`RulesEngine.apply_prevent_rider`: gain_life/draw_cards/mill/deal_damage_to_source_controller/create_tokens_scaled/add_self_counter), and RULE 613.6 `active_if` wired generically into `effect_binder.build_replacements` for every replacement, not just this one. Closed 15 cards via new parser regex (Sphere cycle, Urza's Armor, etc.) plus 5 hand-authored (Swans of Bryn Argoll, Hostility, Gisela, Circle of Protection: Red, Deflecting Palm).
  - **Files:** `game/effects.py`, `game/effect_binder.py`, `parser/oracle/catalogue/replacements.py`, `game/ability_catalogue.py`.
  - **Bug fixed:** `_double_damage_replacement` had no `to_opponent_only` param — Gisela's paired opponent-scoped-double/controller-scoped-prevent clauses needed one; passing it previously silently did nothing. `apply_prevent_rider`'s `deal_damage_to_source_controller` kind resolved recipient through the generic "you"/"source_controller" switch (defaulting to "you"), sending Deflecting Palm's reflected damage back onto the shielded player from the same watched source, which the shield then re-intercepted, recursing to a real `RecursionError`; fixed by resolving this rider kind's recipient unconditionally as the source's controller.
- **MEC-30 Pass 2: Circle/Rune of Protection Cycles + Filter Extensions:**
  - **What:** 32 more Family B cards hand-authored (full Circle of Protection and Rune of Protection cycles, Story Circle, Prismatic Circle, Circle of Solace, and others). New `matches_object_filter` keys reused by `RequestPreventDamageSourceEffect`'s candidate gathering: `color_any` (OR of colours), `color_from_source`/`subtype_from_source` (reading a RULE 601.2b live chosen colour/type dynamically at match time instead of a literal baked in at parse time). `apply_prevent_rider`'s `rider` param widened to also accept a list (applied in sequence) for New Way Forward's two independent riders off one prevented amount.
  - **Files:** `game/effects.py`, `game/combat.py`, `game/ability_catalogue.py`.
  - **Why:** Registering Haazda Shield Mate for its shield clause alone would have silently dropped its already-parser-`MODELED` upkeep sacrifice-unless-pay clause (`specs_for` trusts a registered card's specs wholesale) — that clause was hand-authored alongside the shield instead, reusing the existing RULE 701.17 `sacrifice_unless_pay` choice.
- **MEC-30 Pass 3: Remaining Family A Cards (Rem Karolus, Hedron-Field Purists, Battletide Alchemist, Nine Lives, Insult // Injury/Isengard Unleashed, Ajani Steadfast):**
  - **What:** Closed the last 7 Family A cards. Rem Karolus needed `_additional_damage_replacement`'s new `is_spell` filter (mirroring its `_prevent_damage_replacement` sibling). Hedron-Field Purists/Battletide Alchemist were purely mechanical (existing `active_if`/`amount_count_selector` params). Nine Lives got a new `source_counters_at_least` trigger key (an ordinary COUNTER self-subject trigger, rules-equivalent to a real RULE 603.8 state trigger for this card since counters only ever arrive one at a time). Ajani Steadfast needed all three loyalty abilities hand-authored (+1 an "up to one target" pump; -2 two `add_counters` specs, needing a new `other_planeswalkers_you_control` group selector).
  - **Files:** `game/effects.py`, `game/effect_binder.py`, `game/continuous.py`, `game/ability_catalogue.py`.
  - **Why:** Re-verifying each card's real `parse_oracle unclaimed` output before writing anything, rather than trusting the ticket's prior scoping, avoided building an unneeded RULE 603.8 subsystem for Nine Lives and caught that Ajani needed all three abilities hand-authored, not just the emblem.
- **MEC-30 Phase 5: Family B Chooser Extensions (Kithkin Armor, Shadowbane, Honorable Passage, Dazzling Reflection, Samite Blessing):**
  - **What:** Five small, individually-scoped extensions to `RequestPreventDamageSourceEffect`: `recipient="attached_permanent"` (Kithkin Armor); `RulesEngine.prevent_damage_to_player_and_their_creatures` for a dynamic "you and/or creatures you control" recipient set, re-evaluated live (Shadowbane); `rider["if_source_color"]`, the first rider that only sometimes fires, gating on the watched source's own colour (Honorable Passage); `GainLifeEffect.amount_from_target_power` (Dazzling Reflection); confirmed the existing layer-6 `grant_activated_ability` static needs no new primitive to grant a chooser ability onto a host (Samite Blessing).
  - **Files:** `game/effects.py`, `game/rules/damage_death_mixin.py`, `game/rules_engine.py`.
  - **Why:** Kithkin Armor's Enchant keyword and combat restriction were already independently `MODELED` — registering it for the shield alone would have silently dropped them, so the exact `EffectSpec` was hand-copied from an isolated `parse_oracle` run rather than reconstructed.
- **MEC-30 Phase 6: RULE 616.1c Redirection (Opal-Eye, Konda's Yojimbo):**
  - **What:** `RequestRedirectDamageSourceEffect`/`RulesEngine.redirect_damage_from_source` — the first genuine damage redirection this engine modeled, distinct from prevention/doubling: reuses the chooser plumbing but rewrites the watched DAMAGE event's own `target_id`/`is_player` instead of reducing its amount. Deliberately not marked `prevents_damage` (a redirect isn't cancelled by "damage can't be prevented this turn"). New `PreventDamageEffect.self_only` for "prevent the next N damage to `<this permanent>`."
  - **Files:** `game/effects.py`, `game/rules_engine.py`.
  - **Bug fixed:** `RulesEngine.deal_damage`'s `_finish` closure resolved every branch (life loss, counters, damage-marking, loyalty, battle defense, commander damage) against the *original* captured target/is_player, never re-reading the replaced event's own rewritten recipient — so a redirect's `copy_with` override was silently discarded no matter what it said. Fixed by re-deriving the actual recipient once at the top of `_finish` and switching every branch to read it. Verified with an unusually wide regression sweep (~600 cases across combat/planeswalker/battle/poison/infect/wither test files) given how central `deal_damage` is.
- **MEC-30 Pass 6: Activator/Controller Distinction (Mercenaries) and Multi-Player Aggregate Tax (Rhystic Circle):**
  - **What:** `ActivationCost.any_player_may_activate` (RULE 602.2b eligibility widening) + `GameContext.resolving_controller_id`, the activator set/restored by `RulesEngine.resolve_top_of_stack` around a stack item's resolution, mirroring how `trigger_event` already saves/restores — `PreventDamageEffect` gained `recipient_is_activator`/`watched_source_is_self` reading it (Mercenaries). `RequestAllPlayersDeclineOrEffect`/`RulesEngine.request_all_players_decline_or` — every player gets an independent pay/decline chance, the payoff fires once only if *everyone* declines, and the first payer cancels the whole sweep (Rhystic Circle) — genuinely distinct from both `TaxedDrawEffect`/`pay_cost_then` (single specific payer) and `request_each_player_pay_or` (applies its penalty per-decliner independently).
  - **Files:** `game/costs.py`, `game/engine/activation_mixin.py`, `game/effects.py`, `game/rules_engine.py`, `game/rules/casting_mixin.py`.
  - **Why:** Deliberately kept `_controller_of`'s global resolution order unchanged (97 call sites, several plausibly relying on live `source.controller_id`) — the new field is opt-in per effect rather than a global behaviour change.
- **MEC-30 Pass 7: Chosen-Source Coin-Flip Branch (Desperate Gambit) — MEC-30 closed:**
  - **What:** `ChooseSourceCoinFlipEffect` — the chosen-source chooser family's third member (candidates scoped to "a source you control," not "of your choice"); the coin (`RulesEngine.coin_flip`) isn't flipped until the pick resolves. Heads calls the new `RulesEngine.grant_damage_multiplier_from_source` (the single-source-scoped doubling mirror of `prevent_damage_from_source`, distinct from the controller-wide `grant_damage_multiplier_this_turn` since it can't be narrowed to one specific permanent); tails calls the already-shipped `prevent_damage_from_source`.
  - **Files:** `game/effects.py`, `game/rules/misc_mixin.py`, `game/rules/damage_death_mixin.py`.
  - **Why:** Closes the whole standing `prevent_damage` replacement family (MEC-30) — every card from the original 80-row cache search is now MODELED or hand-authored, and every primitive built along the way (RULE 613.6 `active_if` on any replacement, RULE 616.1c redirection, RULE 616.1e's real `can_replace` condition, the RULE 602.2b activator/controller distinction, the multi-player aggregate-outcome tax) is general enough for future reuse.

### "A Source of Your Choice" One-Shot Prevention Family (RULE 615/616.1d)

- **What:** A genuinely new primitive (choosing a source is not RULE 115 targeting — no `"source"` target kind exists): `prevent_damage_to_player`/`_to_target` gained optional `watched_source_id`; new `prevent_damage_from_source` covers the unscoped-recipient shape; `request_choose_objects` gained a `"remember_source"` action plus a `prevent_shield` payload round-tripped through the pending-choice cycle; two new effect classes, `RequestPreventDamageSourceEffect` (chooser path, Circle/Rune of Protection) and `PreventDamageFromTargetEffect` (already-targeted path, Awe Strike/Dazzling Reflection). Deliberately scoped to battlefield permanents only, not a spell still on the stack.
- **Files:** `game/effects.py`, `game/rules_engine.py`, `game/rules/misc_mixin.py`.

### Damage-Can't-Be-Prevented / Damage-Multiplier-This-Turn (Insult // Injury, Isengard Unleashed)

- **What:** New `ReplacementEffect.prevents_damage` marker stamped on every prevention-shaped effect construction site, plus a turn-scoped `GameState.damage_prevention_disabled` flag consulted by `RulesEngine._run_replacement_loop`, implementing "damage can't be prevented this turn." Paired with `RulesEngine.grant_damage_multiplier_this_turn`, the spell-cast sibling of the standing `double_damage` replacement — files a `your_sources_only`-scoped doubling effect on the caster's `player_effects` since a one-shot sorcery has no permanent to hold a standing shield.
- **Files:** `game/rules_engine.py`, `game/effects.py`, `models/game_state.py`, `game/rules/damage_death_mixin.py`.
- **Why:** Deliberately not reusing the existing `damage_prevention_shield` cleanup-sweep flag despite the similar name — that flag means "sweep me at cleanup, I'm one-turn-only," which would have wrongly deleted Family A's *standing* shields (Circle of Protection etc.) at the very next cleanup step.

### RULE 616.1e `can_replace` Condition Fix

- **What:** Extracted each of the 12 `ReplacementRegistry` factories' inline applicability guard into a named `_applies(event, context)` closure wired as `effect.condition`, so `can_replace` (which drives RULE 616.1e simultaneity ordering) reflects the real printed condition instead of just the event type.
- **Files:** `game/effects.py`.
- **Bug fixed:** None of the 12 factories ever passed a `condition` to `ReplacementEffect`, so `can_replace` only ever checked event type — Gisela's two unrelated replacements (opponent-scoped doubling, self-scoped prevention) both reported "applicable" to every DAMAGE event regardless of direction, opening a pointless ordering choice on every single hit even though only one could ever actually change anything.

## Triggered Abilities & Trigger Ordering

### Trigger ordering within a controller (RULE 603.3b)

- **What:** When `state.interactive_ordering` is on and the active player has 2+ simultaneous triggers, `put_triggers_on_stack` opens an `order_triggers` `pending_choice`; picked-first is placed-first (resolves last). Off by default so solo goldfishing is unaffected.
- **Files:** `game/rules_engine.py`

### Triggered-ability target choice (RULE 115/603.3c/603.5)

- **What:** A queued trigger with a targeting effect now opens a `trigger_target` `pending_choice` (one option per legal target) instead of placing blind; a required target with no legal option never goes on the stack at all (RULE 603.3c). Also covers RULE 603.5 for a targetless "you may" ability via a plain do/decline choice.
- **Files:** `game/rules_engine.py`, `game/game_engine.py`

### ENG-4: manual trigger ordering combined with a targeted/modal/optional trigger

- **What:** `resolve_trigger_order_choice` used to place the picked ability with a bare, pause-skipping call, so an ordered targeted/optional trigger lost its target/"you may" prompt. Fixed by routing the picked ability through the same `_place_triggers` pausing path as the deterministic case, with a new `_maybe_continue_ordering` helper resuming the ordering flow once a placement drains without pausing.
- **Files:** `game/rules_engine.py`

### Leaves-the-battlefield triggers "look back in time" (RULE 603.6a)

- **What:** `_move_to_graveyard`/`exile`/`return_to_hand` now fire `LEAVES_BATTLEFIELD`/`DIES` while the object is still spliced into the battlefield, then remove it — the mirror of the existing append-then-fire ordering for entering. `LEAVES_BATTLEFIELD`'s event payload was also enriched to match `DIES`'s.
- **Files:** `game/rules_engine.py`
- **Bug fixed:** A permanent's own "when this dies"/"leaves the battlefield" trigger was structurally unreachable, since trigger collection only scanned the live battlefield at the moment the event fired and the object had already been removed first.

### "When you control no `<basic land type>`, sacrifice ~." (RULE 603.8 state trigger — PARSER_VERSION 180)

- **What:** the original colour-gated creature cycle (Bog Serpent, Sea Serpent, Dandân, Island Fish Jasconius, Barbarian Outcast, Gorilla Pack, …; 11 SOLO). `segmenter._CONTROL_NONE_SACRIFICE_RE` emits an `AbilitySpec("triggered", trigger={"event": "LEAVES_BATTLEFIELD", "controls_none_of_type": "<subtype>"})`; `effect_binder._trigger_condition` grew a `controls_none_of_type` predicate — a live scan of the ability's controller's battlefield for a permanent whose printed subtype line names that basic land type, **excluding the permanent named by the firing event's `instance_id`** (RULE 603.6a: `LEAVES_BATTLEFIELD` fires while the leaving object is still on the battlefield, so the check is "will you control none once this leave completes").
- **Files:** `parser/oracle/segmenter.py`, `game/effect_binder.py`. `tests/test_par30_control_none_sacrifice_trigger.py`.
- **Why this shape:** no general RULE 603.8 state-trigger subsystem exists; this reuses the same "gate an ordinary event on a live state read" pattern `source_counters_at_least` (Nine Lives) documented, since the only way the count reaches zero is a land leaving. The ETB edge (casting the creature while already controlling none) is a documented simplification.

### Modal triggered abilities (RULE 700.2 wrapped in RULE 603)

- **What:** "When ~ enters, choose one —" on a permanent now parses and binds (previously only a modal spell's header worked). Mode selection is resolved as a new interactive `trigger_mode` `pending_choice` opened as the ability is placed on the stack, before the existing target/"you may" checks run against the chosen mode's own effects.
- **Files:** `parser/oracle/gate.py`, `parser/oracle/catalogue/modal.py`, `game/effect_binder.py`, `game/rules_engine.py`
- **Why:** Real-cache yield was much smaller than a template-based estimate suggested (6 cards, all still blocked by an unrelated missing effect family) — logged as a correctness/architecture prerequisite rather than a coverage win.

### EventType.SACRIFICE (RULE 701.17)

- **What:** A move to the graveyard whose cause is a sacrifice now fires a distinct `SACRIFICE` event in addition to DIES/LEAVES, routed through the single `put_into_graveyard` choke point. Unblocks the whole "whenever you sacrifice a permanent" family (Mayhem Devil).
- **Files:** `models/events.py`, `game/rules_engine.py`

### Reflexive per-firing "that object" trigger (RULE 603.3d)

- **What:** `TriggeredAbility.reflexive` lets a triggered ability's targeting effect act on the exact object that fired the event (resolved from the event's `instance_id` at placement time, no `trigger_target` choice needed) — the generic form of the per-firing "that spell/land" reference that Ward/Rampage each hand-built separately.
- **Files:** `game/effects.py`, `game/effect_binder.py`, `game/rules_engine.py`

### Delayed triggered abilities (RULE 603.7)

- **What:** `GameState.delayed_triggers` + `DelayedTrigger` + a `create_delayed_trigger` effect let a resolving spell arm a trigger for a future step, fired at `STEP_BEGIN`, with scope/step/capture/min_turn parameters. Upgraded Mana Drain to fully modeled.
- **Files:** `models/game_state.py`, `game/game_engine.py`, `game/effects.py`

### Reflexive "When you do, `<targeted payoff>`." after an optional cost (RULE 603.11, PARSER_VERSION 206)

- **What:** "You may `<cost>`. **When you do**, `<targeted effect>`." (Sample Collector, Curious Forager, Warren Torchmaster; Surgespanner, Teneb the Harvester, Bearer of Silence, …). `PayCostThenEffect` already handled "if you do, `<effect>`" but ran those effects *off the stack* the instant the choice was answered — a RULE 115 target could never be chosen, so `_pay_cost_then_general` rejected any targeted follow-up outright. Now: a paid cost calls `RulesEngine._enqueue_pay_cost_then_trigger`, which builds a fresh `TriggeredAbility` from the serialized payoff specs (per that class's own docstring's sanctioned "bake per-firing data in at the call site" pattern) and appends it to `pending_triggers`. The very next resolve-loop iteration's `put_triggers_on_stack` → `_place_triggers` gathers its target(s) via the ordinary interactive path and puts it on the stack. The outer trigger's `GameEvent` is carried on the new ability's `StackItem.trigger_event`, so a payoff that names it ("that player") can still read it back.
- **New param:** `pay_cost_then.then_trigger` (a list of `{"type","params"}` specs, whitelisted through `build_effects` like every other effect list). Emitted by `_pay_cost_then_general` when the "When you do" body has a `target_kind`; the untargeted case keeps using the off-stack `effects`. Threaded through `GameContext`-less `RulesEngine.request_pay_cost_then` (`then_trigger_specs` + `then_trigger_event`) and stashed on `_pending_pay_cost_then` so it survives the choice round-trip.
- **Reach:** the `_MAY_COST_THEN_CLAUSE` cost whitelist is mana / typed-sacrifice / discard / pay-life / collect-evidence / forage / blight, so this is not Evidence-specific — it closes the whole "you may pay {cost}. If you do, `<targeted effect>`" family (bounce, edict, reanimation, +1/+1 counter, keyword grant). +43 cache cards, 0 regressed.
- **Not yet:** Memory Vampire (also needs a dynamic multi-target mill + a "cast target nonland card from a graveyard without paying its mana cost" one-shot) and Incinerator of the Guilty (dynamic "collect evidence X" + event-scoped group damage) — tracked in `BACKLOG.md`. Narrows the Red Hulk documented simplification (`DamageEqualToCountersEffect` docstring) to "not yet wired for that card", not "no primitive exists".
- **Files:** `game/effects.py` (`PayCostThenEffect.then_trigger_specs`, `pay_cost_then` factory), `game/rules/misc_mixin.py` (`request_pay_cost_then`/`resolve_pay_cost_then_choice`/`_enqueue_pay_cost_then_trigger`), `parser/oracle/catalogue/handlers.py` (`_pay_cost_then_general`), `parser/oracle/gate.py` (PARSER_VERSION 206).
- **Tests:** `tests/test_reflexive_when_you_do_trigger.py` — parse (targeted → `then_trigger`, untargeted → `effects`), and execute: Sample Collector's reflexive +1/+1-counter ability goes on the stack, offers a `trigger_target` choice, and resolves onto the picked creature; declining the cost queues nothing; the mana-cost variant (Surgespanner bounce) and the blight-cost variant (Warren Torchmaster haste) both resolve end-to-end.

### Self-referential-trigger family: ability words, controller-scoped phases, self-damage

- **What:** Three related gaps closed together: RULE 207.2c ability-word stripping ("Landfall —"/"Constellation —" have no rules meaning and were blocking the trigger match beneath them); controller-scoped phase triggers ("at the beginning of **your** `<step>`"/"each opponent's") via a new `phase_relation` condition; and self-subject "`~` deals (combat) damage to a player/creature" (RULE 120.3) via a dedicated `EventType.DAMAGE` + filter bypass. Also extended granted-trigger scoping to DAMAGE events, closing a prior deferral (Combat Research).
- **Files:** `parser/oracle/normalize.py`, `parser/oracle/segmenter.py`, `game/effect_binder.py`, `game/continuous.py`

### Trigger-Condition Scoping (RULE 603.1)

- **What:** The segmenter emits a `trigger.condition` ({subject: self} or {subject: group, type/controller/other}); ENTERS_BATTLEFIELD/DIES/ATTACKS/BLOCKS events carry `instance_id`+`object_types`; the binder builds the matching predicates.
- **Files:** `parser/oracle/segmenter.py`, `game/effect_binder.py`
- **Bug fixed:** A parsed "when ~ enters" trigger fired for *any* entering permanent, not just its own source — a live over-firing bug closed by the new scoping.

### "Draw a Card at the Beginning of the Next Turn's Upkeep" (RULE 603.7 Recognition)

- **What:** The RULE 603.7 delayed-trigger mechanism already existed (built for Mana Drain); this added the first parser recognition of the phrase, emitting `create_delayed_trigger` with `scope="any"` for the un-qualified "the next turn's upkeep" wording.
- **Files:** `parser/oracle/catalogue/handlers.py`
- **Bug fixed:** `DrawCardEffect`/`DiscardEffect.apply` fell back to `context.active_player` instead of the shared `_controller_of` helper, so a delayed draw/discard crossing into another player's turn credited the wrong player.

### Attached-Permanent & "Deals Combat Damage to a Player" Trigger Families

- **What:** A new `{"subject": "attached_permanent"/"self_or_attached_permanent"}` trigger subject ("whenever equipped/enchanted creature `<verb>`", live-checked off the source's own `attached_to`), plus a `trigger["filter"]` dict for exact-match event-payload conditions (`{"combat": True, "is_player": True}` covers the whole Sword-cycle/Bloodforged Battle-Axe family). Also a `requires_equipped` gate for "an equipped creature you control attacks" (Akiri, Fearless Voyager).
- **Files:** `game/effect_binder.py`
- **Bug fixed:** `RulesEngine.deal_damage`'s post-replacement broadcast event was rebuilt from scratch, silently dropping `combat`/`source_id`/`source_controller_id`/`source_colors` — fixed by copying the resolved event forward instead.

### `spell_subtype_any` Cast-Trigger Gate

- **What:** "Whenever you cast an Aura/Equipment/Vehicle spell" (Sram, Senior Edificer) needs a card-subtype check a `"group"` condition's main-type filter can't express — reads the live spell's own `type_line` instead. Also added `SPELL_CAST → player_id` to the group-controller event-key table.
- **Files:** `game/effect_binder.py`

### Delayed-Trigger Showcase Primitives

- **What:** Ephemerate's Rebound (RULE 702.88b, a standing free-cast window via `GameState.free_cast_instance_ids`), Marchesa the Black Rose's per-firing "counter-death return" delayed trigger, and Sneak Attack/Meek Attack's "cheat a creature into play with haste, sacrifice it at next end step" (`CheatCreatureFromHandEffect`/`RulesEngine.put_hand_creature_onto_battlefield`).
- **Files:** `game/effects.py`, `game/rules_engine.py`, `game/ability_catalogue.py`
- **Bug fixed:** `RulesEngine.blink` left a phantom duplicate reference in the owner's exile zone after returning the object to the battlefield; and `legal_actions`' exile loop never offered a temp-play-permission-exiled card as castable at all, despite `can_cast`/`cast_spell` fully supporting it.

### Group-Subject Damage Triggers

- **What:** RULE 120.3 + 603.1's "a/an/another `<type>` [you control] deals combat damage to a player" subject, needing DAMAGE's own `source_controller_id` threaded through the group-condition builder (`_GROUP_CONTROLLER_EVENT_KEYS`, `_subject_event_key`).
- **Files:** `game/effect_binder.py`
- **Bug fixed:** The group-subject article alternation was `a|another`, so every vowel-initial group subject ("an enchantment you control dies") had been silently failing closed.

### "Sacrifice ~ Unless You Pay `<cost>`." (RULE 701.17)

- **What:** A real interactive pay-or-lose-it choice for the biggest remaining upkeep-trigger template (45 cards), built by renaming and sharing ward's existing "can this player pay an arbitrary cost" helpers (`_can_pay_player_cost`/`_pay_player_cost`) rather than duplicating them. Parser claims a closed cost vocabulary only (mana/life/discard/sacrifice-a-type) rather than free text.
- **Files:** `game/effects.py`, `game/rules_engine.py`, `parser/oracle/catalogue/handlers.py`
- **Why:** Handing free text to the generic cost parser would return a "free" cost for anything unrecognized — silently reading as "pay nothing to keep it."
- **PAR-30 (PARSER_VERSION 159) — the tap/exile consequence siblings + "discard N cards".** `_UNLESS_COST` (the shared closed cost vocabulary) gained "discard N cards" — a plain count, which `parse_activation_cost` reads and `_pay_player_cost` honours; the typed ("discard a creature card" → silently free) and "at random" shapes stay excluded, same fail-closed rule as before. New `_TAP_UNLESS_PAY_RE` / `_EXILE_UNLESS_PAY_RE` for "tap/exile ~ unless you pay `<cost>`" (Carnophage, Sangrophage, Heavyweight Demolisher, Electrozoa, Apocalypse Demon, Demonlord of Ashmouth, Morgul-Knife Wound's granted quoted form) — modeled with **no new effect**: `pay_cost_then` with an empty pay-branch (`effects=[]`) and the `tap`/`exile` spec in `else_effects`, so paying costs the resource and declining/being-unable taps or exiles the source. Registered *before* the plain `tap_self`/`exile_self` handlers so the "unless" half isn't dropped. +8, 0 regressed. `tests/test_par30_tap_exile_unless_pay.py`. Still open in the family: "discard N cards **unless you discard a `<type>` card**" (Alpharael, Arm-Mounted Anchor — a `discard N` consequence + a typed-discard cost) and follow-up "if ~ is destroyed this way, `<effect>`" clauses (Cosmic Horror, Argentum Masticore).

### Quoted Granted Phase/Upkeep Triggers

- **What:** `STEP_BEGIN` joined the grantable trigger events (Commander's Authority/Clawing Torment-shaped) — the one grantable event with no object subject, so its `phase_relation` is resolved against the *granted-to* permanent's controller rather than the granting source's.
- **Files:** `game/continuous.py`

### Aura Lifecycle Triggers

- **What:** RULE 700.4's long "is put into a graveyard from the battlefield" phrasing folds to "dies" (`normalize._fold_dies_long_form`), and `ReturnToHandEffect` gained a self form (Rancor/Flickering Ward) resolving against the source wherever it currently sits.
- **Files:** `parser/oracle/normalize.py`, `game/effects.py`, `game/rules_engine.py`
- **Bug fixed:** `_move_to_graveyard` only fired `EventType.DIES` for creatures, so a dying Aura/enchantment/land was invisible to any dies-trigger — RULE 700.4 isn't creature-scoped at all.

### Trigger Subject Filtered on a Designation ("Goaded")

- **What:** "Whenever a goaded creature attacks/dies" is neither a type, subtype nor controller, so `goaded`/`in_combat` are snapshotted onto the firing event at fire time (needed for DIES since the object is already gone by then, and because RULE 506.4 removes a permanent from combat as it leaves the battlefield anyway).
- **Files:** `game/effect_binder.py`, `game/rules_engine.py`

### ENG-11: Granted Trigger Fails Closed Without Identity Key

- **What:** `continuous._granted_trigger_condition` now refuses (rather than passes) a firing event whose type has no entry in `_GRANTED_EVENT_KEYS` — mirroring the ordinary (non-granted) subject condition's existing "missing instance_id → False" rule. A safety net for a future hand-authored grant, not reachable by any shipped card today.
- **Files:** `game/continuous.py`

### ENG-13: Per-Firing Dynamic Reference for Granted Abilities

- **What:** `GameContext.trigger_event` (already used by an ordinary printed trigger's per-firing pronoun) is demonstrated on a *granted* ability's own resolution via two bespoke effect classes: `ExileTriggerDamagedCreatureEffect` (Kaldra Compleat's "exile that creature", reading the DAMAGE event's `target_id`) and `AttachTriggeringPermanentEffect` (Sigarda's Aid's "attach it to target creature", reading a group-subject trigger's own matched member).
- **Files:** `game/effects.py`, `game/ability_catalogue.py`

### Mill-trigger family (`EventType.MILL_CARD`)

- **What:** A new per-nonland-card `MILL_CARD` event (alongside the existing aggregate `MILL`) lets "whenever a player/an opponent mills a nonland card" bind via the existing group-subject controller-scoping machinery — used for Glowing One, Infesting Radroach (a graveyard-zone trigger, RULE 112.6a), and The Wise Mothman.
- **Files:** `models/events.py`, `game/rules_engine.py`, `game/effect_binder.py`
- **Why:** Infesting Radroach's ability must keep functioning from the graveyard rather than the battlefield, so it's read fresh off every player's graveyard by a dedicated collector instead of the ordinary per-permanent battlefield scan.

### Trigger-condition vocabulary widened (RULE 603.1/500.7)

- **What:** `segmenter._TRIGGER_VERBS` consolidated into one table feeding every subject regex, adding "is turned face up," "leaves the battlefield," "becomes blocked," "becomes tapped," "mutates"; `_PHASE_STEP_WORDS` gained phase-named triggers ("at the beginning of combat on your turn," main phases by ordinal/name, "each player's `<step>`").
- **Files:** `parser/oracle/segmenter.py`
- **Why:** A verb earns a row only if the engine fires an event carrying an `instance_id` for it — "becomes untapped" is deliberately absent since `UNTAP` fires once per step, not per object.

### Interactive surveil + "whenever you scry/surveil" trigger family

- **What:** Scry and surveil unified onto one internal implementation differing only in destination (bottom of library vs. graveyard) while keeping separate `pending_choice` kinds/prompts; a new player-subject trigger-condition table (`_PLAYER_TRIGGER_CONDITIONS`, `{"subject": "you"}`) recognizes "whenever you scry/surveil/scry or surveil" for the first time, since these events carry a `player_id` rather than an `instance_id`.
- **Files:** `game/rules_engine.py`, `parser/oracle/segmenter.py`, `game/effect_binder.py`
- **Why:** Deliberately not routed through `mill` — surveil and mill are distinct RULE 701.31b/701.13 keyword actions. The "for the first time each turn" limiter is deliberately left unmatched (fails closed) since the engine can't express a once-per-turn cap yet — filed as PAR-14, gating 182 cache-wide cards.

### `GameContext.trigger_event` — per-firing event exposure

- **What:** Exposes the event that fired a trigger for exactly one resolution window (threaded through `StackItem.trigger_event` across every pause/resume path), letting an effect depend on which firing without every `apply()` growing a parameter. Reused by six cards across waves 2-4.
- **Files:** `game/effects.py`, `game/rules_engine.py`

### Recipient-side damage trigger ("is dealt damage") — Enrage family

- **What:** The mirror image of the existing "deals damage" trigger family — `segmenter._DAMAGE_RECIPIENT_TRIGGER_RE` recognizes "whenever ~/a `<type>`/enchanted-or-equipped `<type>` is dealt [combat] damage," switching the binder from the `DAMAGE` event's source fields to its (newly added) `target_id`/`target_controller_id` fields. General RULE 603.1 recognition, not gated to the "Enrage —" ability-word label, so it benefits far more cards than the ~25 that print Enrage.
- **Files:** `parser/oracle/segmenter.py`, `game/effect_binder.py`, `game/rules_engine.py`

### "It" pronoun disambiguation in recipient-subject effects

- **Bug fixed:** the existing "put a +1/+1 counter on it" handler always meant the ability's own source, which broke for the first time on a group-subject recipient trigger (Rite of Passage: "it" means the damaged creature, not the Enchantment itself). Fixed by adding `AddCountersEffect.trigger_subject_key` (resolves "it" from `GameContext.trigger_event`) and having the segmenter fail closed for any other effect shape lacking an unambiguous real `target_kind`/`selector`.
- **Files:** `game/effects.py`, `parser/oracle/segmenter.py`

### "Return this card from your graveyard to your hand" + graveyard-sourced triggers (PAR-16)

- **What:** The hand-destination sibling of PAR-10's battlefield-return effect (`ReturnSelfFromGraveyardToHandEffect`), plus a genuinely new engine primitive for the triggered variant (Aurora Eidolon/Chandra's Phoenix-shaped "whenever `<event>`, return this card from your graveyard to your hand"): `TriggeredAbility.functions_from_graveyard`, inferred straight from the effect list the same way `ActivationCost.graveyard_zone` is, plus a new `_collect_graveyard_function_triggers` scan (`_collect_triggers` is battlefield-only). 70 SOLO cache blockers, not the ticket's estimated 20.
- **Files:** `game/effects.py`, `game/effect_binder.py`, `game/rules_engine.py`

### Triggered ability's own "if it was kicked" gate (PAR-17)

- **What:** Widened from spell-only "if this spell was kicked" to also cover "it" (a triggered ability's own body, Heartstabber Mosquito-shaped), "kicked twice" (Multikicker's own count via a new `kicked_at_least` condition), and "bargained" (reaching an already-engine-supported but never-oracle-reachable `ConditionalEffect` key). A new `"kicker_x"` `_substitute_x` sentinel reads `GameObject.kicker_x_paid` for a kicked-wrapped "X" inside the effect.
- **Files:** `parser/oracle/catalogue/handlers.py`, `game/rules_engine.py`
- **Bug fixed:** `_substitute_x` iterated a `TriggeredAbility`'s effects directly, but a kicked-wrapped effect is a `ConditionalEffect` with no `amount`/`count` of its own — only `.inner` does; without unwrapping, "if it was kicked, draw x cards" crashed at resolution.

### RULE 603.2 once-per-turn trigger limiter, oracle wiring (PAR-14)

- **What:** `TriggeredAbility.once_per_turn` already existed (built for a granted ability) but no printed-card oracle-text path ever set it. Added a trailing-sentence marker ("This ability triggers only once each turn.") and an inline "…for the first time each turn" suffix, both folding into `AbilitySpec.trigger["limit"]` at one shared choke point so every trigger-subject family gets it for free.
- **Files:** `parser/oracle/segmenter.py`, `game/effect_binder.py`

### "Whenever you cast a/an `<type>` spell" trigger (PAR-12)

- **What:** A genuinely new trigger-condition family (607 SOLO-blocked cache-wide, the single largest template found in this batch). The underlying machinery (`EventType.SPELL_CAST`'s `object_types`, `effect_binder`'s `spell_card_types` predicate) already existed for a hand-authored card; only oracle-text recognition was missing. Deliberately scoped to `"you"` as subject — "an opponent casts"/"a player casts" is a different subject grammar, left unclaimed.
- **Files:** `parser/oracle/segmenter.py`

### "Whenever ~ or another creature dies" self_or_group trigger (PAR-12)

- **What:** Blood Artist/Falkenrath Noble's plain main-type, no-controller-restriction sibling of the existing subtype-scoped `self_or_group` variant. `effect_binder._build_group_ok` already treated both shapes identically, so no binder change was needed.
- **Files:** `parser/oracle/segmenter.py`

### "Whenever you gain life, `<effect>`" trigger wiring (PAR-12, RULE 119.3)

- **What:** Ajani's Pridemate/Archangel of Thune-shaped. `EventType.LIFE_GAINED` (the post-replacement trigger source, distinct from the earlier replaceable `LIFE_GAIN` pre-event) already existed — only the oracle-text row and its group-controller event key were missing.
- **Files:** `parser/oracle/segmenter.py`, `game/effect_binder.py`

### "Whenever ~ attacks, it gets +N/+N…" self-subject trigger (PAR-12)

- **What:** Borderland Marauder/Kiln Walker-shaped vanilla-creature template, where the body refers to the source as "it" (the trigger's subject) rather than `~`. New `self_subject_only`-gated handler row. A count-scaled variant ("+1/+1 for each attacking creature") stays unclaimed — `PumpEffect` had no count-scaled magnitude param at the time.
- **Files:** `parser/oracle/catalogue/handlers.py`

### "Whenever you gain life, `<effect>`" dynamic-amount family (Hobbits batch)

- **What:** "that much"/"that many" reading `LIFE_GAINED`'s own amount off the firing trigger event: `LoseLifeEffect`/`AddCountersEffect`/`PumpEffect.amount_from_trigger_event`, the same idiom already used elsewhere for a mana-producing card.
- **Files:** `game/effects.py`
- **Bug fixed:** A first cut's bare-pronoun branch would have silently misread "it" as the trigger's own source under a group-subject trigger (where "it" means whichever creature dealt the damage) — gated with a new `EffectHandler.self_subject_only` flag.

### `LIFE_GAINED` as a granted player-subject trigger event (Hobbits batch)

- **What:** "Equipped/enchanted creature has 'whenever you gain life, …'" now resolves "you" against the granted-to permanent's controller, the same treatment `STEP_BEGIN`'s `phase_relation` already gets for phase triggers.
- **Files:** `game/continuous.py`

### "Whenever you sacrifice a Food/Clue/Treasure" (Hobbits batch)

- **What:** `EventType.SACRIFICE` gained a `subtypes` payload (mirroring `DIES`'s existing split from main types), plus a new `sacrifice_type` trigger-condition predicate. Also new: `ConditionalEffect`'s `controls_none_of_type` key for "If you don't control a Food/Clue/Treasure, `<effect>`" (Butterbur, Bree Innkeeper).
- **Files:** `models/game_state.py`, `game/effect_binder.py`, `game/effects.py`

### Conditional granted-trigger effects + `ring_tempted_at_most` (Frodo Sauron's Bane)

- **What:** A granted triggered ability's own effect list had no way to condition an entry ("…loses the game if tempted 4+ times. Otherwise, the Ring tempts you."). `continuous._build_grant_effect` now wraps a `grant_effects` entry in `ConditionalEffect` when it carries an optional `condition` key; new `ring_tempted_at_most` (the upper-bound mirror of `ring_tempted_at_least`) lets two complementary-bound conditionals stand in for an if/else with no dedicated "otherwise" field.
- **Files:** `game/continuous.py`, `game/effects.py`

### Card-type-excluding and creature-subtype spell-cast triggers

- **What:** "Whenever you cast a **non**creature spell" (new `spell_exclude_card_types` predicate, tried before the positive row) and "Whenever you cast an **Elf** spell" (the pre-existing `spell_subtype_any` engine predicate, reached from a curated ~30-word creature-type whitelist rather than any bare word, to avoid both false positives and silent misses).
- **Files:** `parser/oracle/segmenter.py`, `game/effect_binder.py`
- **Bug fixed:** Neither the positive nor negative cast-spell-trigger row ever called `_peel_optional` on its body, so "…you may `<effect>`" continuations had silently failed to parse since those rows were first built.

### COUNTER/CREATE_TOKENS events never fired (Eliferate finish)

- **What:** `RulesEngine.add_counters`/`add_player_counters` and `create_token` each computed their event through `apply_replacements` but the `_finish` closure never called `state.fire_event` on the result — COUNTER and CREATE_TOKENS events were never broadcast to `_collect_triggers` at all. No card in this engine's history could ever have triggered off "a counter is placed" or "a token is created" before this fix.
- **Files:** `game/rules/mana_counters_mixin.py`, `game/rules/misc_mixin.py`

### RULE 603.3d trigger doubling

- **What:** Roaming Throne's "if a triggered ability of a permanent you control triggers, it triggers an additional time." New `continuous.trigger_doubler_bonus` + `TriggerDoublerEffect` marker, wired into `_collect_triggers`'s per-object loop as an extra copy count. No prior analogue existed for "fires again" as opposed to "fires bigger".
- **Files:** `game/continuous.py`, `game/rules_engine.py`

### "Spell watchers" (Imodane batch)

- **What:** `GameState.spell_watchers` — a GameState-level mechanism distinct from both an object-bound `TriggeredAbility` and a step-bound RULE 603.7 `DelayedTrigger`. Dual Strike's "when you next cast an instant or sorcery this turn, copy it" is a standing registration consumed by a `SPELL_CAST` subscriber.
- **Files:** `models/game_state.py`, `game/rules_engine.py`

### Imodane, the Pyrohammer's own trigger

- **What:** "Whenever an instant/sorcery you control that targets only a single creature deals damage to that creature, Imodane deals that much damage to each opponent." New `DealDamageEffect.amount_from_trigger_event` (reading the firing DAMAGE event's own amount, unlike every prior damage-mirroring effect which reads a count selector or flat override) plus two new DAMAGE-event flags computed where both the source's card type and the resolving effect's own target-spec shape are known (`single_target_hint` on `deal_damage`).
- **Files:** `game/rules_engine.py`, `game/effects.py`, `game/effect_binder.py`

### `TaxedDrawEffect` — RULE 118.3 "unless" applied to a draw

- **What:** Rhystic Study/Mystic Remora/Esper Sentinel's "whenever an opponent casts a spell, you may draw a card unless that player pays `<cost>`." The one real difference from sibling "unless" effects: the payer is the *triggering spell's own caster*, read off the firing event, not this ability's controller. `amount_from_source_power` (Esper Sentinel) reads the cost off the source's live power at resolution.
- **Files:** `game/effects.py`

### Smothering Tithe: DRAW group-subject trigger + pay-or-create-Treasure (Triggered Abilities & Trigger Ordering)

- **What:** `effect_binder._GROUP_CONTROLLER_EVENT_KEYS` gained a `"DRAW": "player_id"` row so "whenever an opponent draws a card" group-subject scoping works; `PayCostThenEffect`'s `payer="event_player"` reads the *drawing* player off the firing DRAW event, with `else_effects` creating a Treasure under Smothering Tithe's own controller.
- **Files:** `game/effect_binder.py`, `game/effects.py`, `game/ability_catalogue.py`

### Untyped player-subject cast trigger + mana-value filter (Triggered Abilities & Trigger Ordering)

- **What:** New `_CAST_SPELL_TRIGGER_PLAIN_RE` recognizes "whenever you/an opponent/a player casts a spell" (the previous regex required a typed variant); `_CAST_SPELL_TRIGGER_MV_RE` adds a "with mana value N or less" filter via a new `spell_mana_value_at_most` predicate reading `SPELL_CAST`'s already-stamped `mana_value` field.
- **Files:** `parser/oracle/segmenter.py`, `game/effect_binder.py`

### `DealDamageEffect` "event_player" selector (Triggered Abilities & Trigger Ordering)

- **What:** New `"event_player"` selector — "~ deals N damage to **that player**", the player named by the firing trigger's own event — reused by a new `"that player"` entry in `_DAMAGE_SELECTOR_WORDS`.
- **Files:** `game/effects.py`, `parser/oracle/catalogue/handlers.py`

### "Sacrifice it. When you do, `<effect>`." collapsed to a plain sequence (Triggered Abilities & Trigger Ordering)

- **What:** RULE 603.3's "when you do" only fires if the antecedent happened; for an unconditional (no "may") self-sacrifice that's a certainty, so `_SACRIFICE_THEN_WHEN_YOU_DO_RE` collapses the two clauses to one plain effect list with no interactive branch. Deliberately not generalized to the much bigger "you may `<action>`. When you do, `<effect>`." family, which needs a real optional-antecedent gate.
- **Files:** `parser/oracle/catalogue/handlers.py`

### Mass edicts + "Whenever you/an opponent draws a card" trigger family (Triggered Abilities & Trigger Ordering)

- **What:** "Each player/opponent sacrifices `<n>` `<type>` of their choice" (`_sacrifice_edict`, new `"nontoken_creature"` word on `_matches_permanent_type`); a new `_DRAW_TRIGGER_PLAIN_RE` closes the Sheoldred/Underworld Dreams/Consecrated Sphinx family (the `effect_binder` group scoping over `DRAW` was already proven), paired with a new `"event_player"` `lose_life` selector for "they lose 2 life." +34 cards on the trigger family alone.
- **Files:** `parser/oracle/catalogue/handlers.py`, `game/effects.py`

### Kiki-Jiki / Puppeteer Clique: haste-copy-with-end-step-cleanup primitive (Triggered Abilities & Trigger Ordering)

- **What:** "Create/reanimate a permanent with haste, [sacrifice/exile] it at the beginning of the next end step." `CopyPermanentEffect`/`ReturnFromGraveyardEffect` gained a `haste` param and now populate `GameContext.created_objects`; `create_delayed_trigger` gained `capture="created_objects"`, mutating a freshly-registered delayed effect's target directly (RULE 603.7).
- **Files:** `game/effects.py`, `game/ability_catalogue.py`

### Mikaeus, the Unhallowed: negated-subtype anthem + damage-sourced destroy trigger (Triggered Abilities & Trigger Ordering)

- **What:** New `group_selector_objects` branch `"other_nonhuman_creatures_you_control"` for the anthem; a new `effect_binder` condition `recipient_is_you` (RULE recipient-scoping had only ever matched a *permanent* recipient, never "to you" — `deal_damage` stamps `target_controller_id=None` for a player target) plus `DestroyEffect.target_from_trigger_event="source_id"` destroys the Human that actually fired a group-subject trigger.
- **Files:** `game/effect_binder.py`, `game/effects.py`, `game/continuous.py`, `game/ability_catalogue.py`

### Danny Pink: per-creature "first time each turn" COUNTER-event watch (Triggered Abilities & Trigger Ordering)

- **What:** Reuses `grant_triggered_ability` (Dionus, Elvish Archdruid's own mechanism) watching each creature's own `EventType.COUNTER`.
- **Files:** `game/ability_catalogue.py`
- **Bug fixed:** See the shared `COUNTER`-event-key gap below — the grant fired for no creature at all until fixed.

### Arcane Denial: controller-redirected delayed draw (Triggered Abilities & Trigger Ordering)

- **What:** `create_delayed_trigger`'s new `capture="target_controller"` reads the *countered spell's* controller off the resolving target and mutates the constructed inner `draw` effect's `.player` directly — the delayed draw belongs to them, not this ability's caster.
- **Files:** `game/effects.py`, `game/ability_catalogue.py`

### Black Market Connections: standing "choose one or more" main-phase trigger (Triggered Abilities & Trigger Ordering)

- **What:** A `STEP_BEGIN` main-phase trigger wraps Farewell's own hand-authored `modes={"choose": 1, "at_least": True, ...}` modal shape — no new modal machinery needed.
- **Files:** `game/ability_catalogue.py`

### Bug: `SacrificeEffect`'s multi-player selector overwrote pending choices (Triggered Abilities & Trigger Ordering)

- **What:** `each_player`/`each_opponent` looped every matching player synchronously in one `apply()`, so a second player's real interactive pick silently overwrote the first's unanswered `pending_choice` — one player's sacrifice was skipped forever. Fixed by sequencing through `GameState.deferred_effects` (RULE 608.2), one level down from the sibling-effect sequencing that idiom already covered.
- **Files:** `game/effects.py`

### Bug: `COUNTER` missing from "which event field names the firing object" tables (Triggered Abilities & Trigger Ordering)

- **What:** Both `effect_binder._SUBJECT_EVENT_KEYS` and `continuous._GRANTED_EVENT_KEYS` defaulted to `instance_id` for `COUNTER`, but `RulesEngine.add_counters`'s own event names its subject `target_id` — no prior card had a self-subject or granted `COUNTER` trigger, so it was silently unreachable until Danny Pink's grant fired for no creature at all.
- **Files:** `game/effect_binder.py`, `game/continuous.py`

### Cast-spell trigger subject widened to you/opponent/player + `trigger_copy_spell` (Triggered Abilities & Trigger Ordering)

- **What:** `_CAST_SPELL_TRIGGER_RE`/`_CAST_SPELL_TRIGGER_NEG_RE` widened from "you"-only to all three subjects via a shared `_cast_spell_trigger_condition` helper (+51 cards). Bonus Round's own trigger body ("that player copies it…") is a new `trigger_copy_spell` handler; `CopySpellEffect` gained `spell_from_trigger_event`/`controller_from_trigger_event` params resolving off the firing `SPELL_CAST` event rather than a RULE 115 target.
- **Files:** `parser/oracle/segmenter.py`, `game/effects.py`

### Mistrise Village: spell-watcher payload for "can't be countered" (Triggered Abilities & Trigger Ordering)

- **What:** Reuses `arm_spell_watcher` (built for Dual Strike's "copy it") with a new payload, `MarkCantBeCounteredEffect`, appending a `CantBeCounteredEffect` marker onto the next-cast spell's own `spell_effects` at the moment the watcher fires.
- **Files:** `game/effects.py`, `game/ability_catalogue.py`

### Vexing Bauble: counter-if-free-cast trigger (Triggered Abilities & Trigger Ordering)

- **What:** New `effect_binder` predicate `spell_no_mana_spent` (reads `SPELL_CAST`'s `mana_spent` field, already zero for a free/alt-cost cast); `CounterSpellEffect` gained `target_from_trigger_event`.
- **Files:** `game/effect_binder.py`, `game/effects.py`

### Chain of Vapor: controller-redirected pay-or-not (Triggered Abilities & Trigger Ordering)

- **What:** `PayCostThenEffect` gained a `payer="previous_target_controller"` mode reading `GameContext.previous_targets` — the bounced permanent's controller, not the caster, is asked whether to sacrifice a land. `CopySpellEffect.copy_self` was built for the card's own "copy this spell" tail but confirmed not to work for it (the original spell has already left the stack by the time the pending choice resolves) and was deliberately left unused for this card rather than shipped as a wrong approximation.
- **Files:** `game/effects.py`, `game/ability_catalogue.py`

### MEC-18: RULE 118.3 optional-antecedent family generalized (Triggered Abilities & Trigger Ordering)

- **What:** `catalogue.handlers._pay_cost_then_general` widens `PayCostThenEffect`'s recognition from two hardcoded shapes to the whole "you may `<sacrifice/discard/pay-mana/pay-life>`. When you do, `<effect>`." family, against a closed whitelist of atomic antecedent shapes (`_MAY_COST_THEN_CLAUSE`) rather than a lenient substring search. Closed 89 real cache cards.
- **Files:** `parser/oracle/catalogue/handlers.py`, `parser/oracle/segmenter.py`
- **Bug fixed:** The generic "you may " peel-guard ran before the new handler could see the clause, stripping "you may" and breaking every trigger in the new family, until the guard and the handler were unified on one shared `_MAY_COST_THEN_CLAUSE` constant; a follow-up fix narrowed the guard's sacrifice alternative to typed-only after widening it broke 4 cards correctly modeled through an older, narrower unconditional-sequence collapse.

### Intervening-If: First Combat Phase of the Turn (RULE 603.4)

- **What:** New `GameState.combats_this_turn` counter (incremented per `begin_combat`, reset each turn) backs a new `ConditionalEffect` key `is_first_combat_phase`, closing the extra-combat-granting trigger family (Karlach, Fury of Avernus/Finest Hour/Genji Glove/Raiyuu) that must not re-trigger itself in the extra phase it just created.
- **Files:** `models/game_state.py`, `game/effects.py`, `parser/oracle/segmenter.py`.

### Attached-Permanent "It" Retargeting for Self-Acting Effects (ENG-29)

- **What:** For a `{"subject": "attached_permanent"}` trigger ("whenever equipped/enchanted creature `<verb>`, it `<effect>`"), `effect_binder._retarget_attached_permanent_effects` rewrites a bare "it" effect's `target_kind` from `None` (self) to `"attached_permanent"` at bind time, for the five effect types that already understand that sentinel (`TapEffect`/`PumpEffect`/`CopyPermanentEffect`/`FightEffect`/`DamageEqualToPowerEffect`).
- **Files:** `game/effect_binder.py`.
- **Why:** The clause always parsed correctly; only its bound meaning was wrong — `target_kind=None` always means "the ability's own source," so "untap it" was untapping the Equipment itself instead of the creature it was attached to.
- **Bug fixed:** Genji Glove and equivalent cards untapped the wrong permanent (the Equipment/Aura itself, not the host creature).

### Group-Subject Retarget (`trigger_subject`) (MEC-28)

- **What:** `TapEffect` gained a `"trigger_subject"` `target_kind` mode reading `GameContext.trigger_event` live at resolution; `effect_binder._retarget_implicit_subject_effects` grew a second branch so a `{"subject": "group"}` trigger ("whenever a creature you control attacks alone, untap it.") retargets a self-acting effect onto the actual firing object instead of the ability's source.
- **Files:** `game/effects.py`, `game/effect_binder.py`.

### MEC-49: Per-turn damage-source attribution (PARSER_VERSION 219)

- **What:** "Whenever a creature **dealt damage by ~ this turn** dies, `<effect>`." (Baron Sengir, Abattoir Ghoul, Blood Cultist, Sengir Vampire / Sengir Bats / Vampiric Dragon / Garza Zol / Rot Wolf / Axelrod Gunnarson / Predator Ooze). A *history* question — the creature is gone from every zone by the time the DIES trigger checks — so it needs a recorded fact, not a live scan:
  - **`GameState.creatures_damaged_by_source_this_turn`** — `{damaged_obj_id: {source_id, …}}`, the per-source hit-*set* sibling of `combat_damage_to_players_this_turn` (which tracks the same shape for *players*, Hope of Ghirapur). Recorded by `RulesEngine.deal_damage` for **any** damage to a creature — combat or not, infect/wither included (RULE 702.90b/702.91a still *deal* damage, they only recolor its result) — so it sits after the whole damage-branch chain rather than in a type-specific one. Reset game-wide each `GameEngine.begin_turn`, like the other per-turn damage trackers.
  - **`effect_binder._build_group_ok`'s `damaged_by_source_this_turn` key** — a pure lookup keyed on this ability's own source `instance_id` (the same "read history keyed on my source" idiom `crewed_by_self` uses), checked against the DIES event's own subject id. `segmenter._DAMAGED_BY_SOURCE_SUBJECT_RE` (anchored on the exact "a creature dealt damage by ~ this turn dies" — tried before `_GROUP_SUBJECT_RE`, which would stop at "creature") → `{"subject": "group", "type": "creature", "controller": "any", "damaged_by_source_this_turn": True}`.
- **Files:** `models/game_state.py` (the map), `game/rules/damage_death_mixin.py` (`deal_damage` records it), `game/engine/turn_loop_mixin.py` (`begin_turn` clears it), `game/effect_binder.py` (`_build_group_ok`), `parser/oracle/segmenter.py` (`_DAMAGED_BY_SOURCE_SUBJECT_RE` + its dispatch), `parser/oracle/gate.py` (v219).
- **Yield:** +8, 0 regressed. Coverage 13,569 / 34,811 (39.0%); Commander-legal 12,987 / 31,830 (40.8%).
- **Tests:** `tests/test_mec49_damaged_by_source.py` — the tracker (records a creature-damage source; ignores player damage; `begin_turn` clears it), parser (the condition-dict shape; real-card Blood Cultist), and execute (the trigger fires exactly once — for the creature *this* source damaged, not one damaged by something else).
- **The replacement form (v220, +4).** "If a creature/permanent **dealt damage by ~ this turn** would die[ this turn], exile it/that `<x>` instead." (Kumano, Master Yamabushi / Kumano's Pupils / Frostwielder / Incendiary Oracle) — the RULE 616 static sibling of the trigger above, off the same map. `catalogue/replacements._DIE_TO_EXILE_RE`'s `subject` alternation grew "a (creature|permanent) dealt damage by ~ this turn" (and its tail loosened to "exile (it|that creature|that permanent) instead" + an optional "would die **this turn**") → `die_to_exile` `subject="damaged_by_source_this_turn"`; `_die_to_exile_replacement._applies` gained the matching branch (the dying object's id must be in `creatures_damaged_by_source_this_turn` keyed under this ability's source). New subject tested in `tests/test_replacement_clause_recognition.py` (recognition of both phrasings + an execute case: Kumano exiles the creature it burned, a creature it didn't touch dies normally).
- **The body gaps (v221, +8).** Two small pieces closed **Abattoir Ghoul** and **Baron Sengir** (plus bycatch — Armor Thrull, Proper Burial, Shield Sphere, Spirit Shackle, Trostani Selesnya's Voice, Experiment Five):
  - **`gain_life_eq_that_group`** — "you gain life equal to **that creature's** `<power/toughness>`" on a *group* trigger (Abattoir Ghoul's DIES). The wordier sibling of `gain_life_eq_its_group` (same `_gain_life_eq_its_group` builder, `group_subject_only`, → `amount_from_subject="trigger_subject_<char>"`). Needed a `toughness=obj.toughness` snapshot on the DIES/LEAVES `GameEvent` (mirroring the existing `power=obj.power`) and a `_characteristic_of_subject` `trigger_subject` branch that prefers the event's stamped power/toughness over a stale graveyard re-lookup (RULE 400.7).
  - **`+N/+N` counters** — the `add_counters` handler's `ckind` group widened from `[+\-−]1/[+\-−]1` to `[+\-−]\d/[+\-−]\d`; `_counter_kind_and_multiplier` models Baron Sengir's "+2/+2 counter" (RULE 122.1c — one counter worth +2/+2) as **two +1/+1 counters** (documented simplification — identical net P/T, differs only for a later "remove a +1/+1 counter" reading).
- **The Aura-hosted tail (v222, +1) — MEC-49 fully closed.** "…dealt damage by **enchanted creature** this turn" (Kumano's Blessing): `_DAMAGED_BY_SOURCE_SUBJECT_RE` / `_DIE_TO_EXILE_RE` accept "enchanted creature" as the damage source, and `_build_group_ok`'s new `via_attached` flag + `die_to_exile` `subject="damaged_by_attached_this_turn"` resolve it to the Aura's `attached_to` before the `creatures_damaged_by_source_this_turn` lookup. Vampiric Embrace's own "put a +1/+1 counter on that creature" body (a counter on the just-dead creature — a dead-on-arrival nonbo) is deliberately left unclaimed.

### MEC-28: Group-Subject / Previous-Selector Trigger Flags

- **What:** New `group_subject` flag threaded through `segmenter.parse_effect_body`/`handlers.match_clause` (closing "untap that creature" — Finest Hour) and new `GameContext.previous_selector` field maintained by `_apply_effects_partitioned` plus a `previous_selector` flag (closing "They gain first strike" — Karlach's untargeted mass-selector pronoun, since RULE 601.2c untargeted selectors never populate `previous_targets`).
- **Files:** `parser/oracle/segmenter.py`, `parser/oracle/catalogue/handlers.py`, `game/effects.py`, `game/effect_binder.py`.

### Bare "Whenever You Attack" Trigger Condition

- **What:** RULE 506.4's bare "whenever you attack" recognized via `_PLAYER_TRIGGER_CONDITIONS`'s new `"you attack"` row, reusing the already-firing `EventType.PLAYER_ATTACKED` event; needed `effect_binder._GROUP_CONTROLLER_EVENT_KEYS`'s `"attacking_player_id"` mapping (this event's subject key differs from other player-subject events' `player_id`). Deliberately left the qualified "with N creatures" forms (97+ cards) out of scope.
- **Files:** `parser/oracle/segmenter.py`, `game/effect_binder.py`.

### Aggregate "One or More Creatures Deal Combat Damage to a Player" Event (MEC-29)

- **What:** New `EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER`, fired once per (contributing creatures' controller, player hit) pair per damage step — not once per qualifying creature — carrying `max_power`; a new `contributor_power_at_least` top-level trigger-condition key reads it (the aggregate event names no single acting object for a `"group"` condition's per-object filter to check).
- **Files:** `game/engine/combat_mixin.py`, `game/effect_binder.py`.
- **Why:** Mirrors the existing `EventType.PLAYER_ATTACKED` shape (built for "a player attacks you with one or more creatures"), the same "one or more X `<verb>`" template applied to a different verb — plain per-creature DAMAGE firing would have double-counted a simultaneous two-attacker hit.

### Aggregate Combat-Damage Event Widened: Subtypes/Amount/Commander (MEC-12)

- **What:** `EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER` gained `subtypes` (union of contributing creatures' real subtypes, re-derived honouring layer-4 overwrites), `contributor_is_commander`, and a real `amount` field distinct from the pre-existing `max_power` threshold. New trigger keys `contributor_subtype` (Malcolm) and `contributor_is_commander` (Kediss).
- **Files:** `game/engine/combat_mixin.py`, `game/effect_binder.py`.
- **Bug fixed:** Kediss's damage amount was first wired to `max_power` (a threshold, not actual damage dealt) — wrong whenever more than one attacker contributed; fixed by adding the real `amount` field. Malcolm's tribal filter first read `GameObject.type_words` (main types only, never matches a real subtype like "pirate") instead of re-derived subtypes. Kediss's "commander you control" filter was first built as a `_build_group_ok` condition reading a per-object key this eventless-object aggregate event never carries (always failed closed); replaced with a top-level trigger key.

### Non-Mana-Ability Activation Trigger Event

- **What:** `EventType.ACTIVATED_ABILITY` (RULE 602.2) fired by `GameEngine.activate_ability` — mana abilities never reach the stack (RULE 605.1a) so no filter is needed to exclude them. Closes the "whenever an opponent activates a non-mana ability" family (Harsh Mentor, Immolation Shaman, +8 more).
- **Files:** `game/engine/activation_mixin.py`, `game/effect_binder.py`.

### Land-Tap-for-Mana Punisher Family

- **What:** New `"nonbasic"` supertype filter key on `_build_group_ok` plus `DealDamageEffect.selector`'s `event_player`/`event_controller`/`active_player` close the Manabarbs/Burning Earth/Price of Glory "taps a land for mana" family (9 cards) and Zo-Zu the Punisher's "that land's controller" shape.
- **Files:** `game/effect_binder.py`, `game/effects.py`.

### "No Mana Spent" Counterspell Trigger Generalization

- **What:** The "whenever a player casts a spell, if no mana was spent to cast it, `<effect>`." trigger generalized from Vexing Bauble's hardcoded row to a reusable general form, closing Roiling Vortex's second clause and any future card on the template.
- **Files:** `game/effect_binder.py`, `parser/oracle/catalogue/handlers.py`.

### Nth-Spell/Noncreature-Spell-Count Tracking

- **What:** Fixed `RulesEngine.__init__`'s subscription order (`_track_spell_cast` now runs before `_collect_triggers`) so `spells_cast_this_turn` is current by the time a SPELL_CAST trigger checks it. Added `is_nth_spell_cast_this_turn`, `LoseLifeEffect.amount_from_spells_cast_this_turn`, `DealDamageEffect.amount_from_noncreature_spells_cast_this_turn`, and per-player `GameState.noncreature_spells_cast_this_turn` (resets for every player each turn, unlike the narrower `spells_cast_this_turn`).
- **Files:** `game/rules_engine.py`, `models/game_state.py`, `game/effect_binder.py`, `game/effects.py`.
- **Bug fixed:** Trigger-order bug meant `spells_cast_this_turn` was one cast stale when a SPELL_CAST trigger checked it.

## Continuous Effects & Layer System

### Layer-6 grant of a non-keyword ability (RULE 613.7f)

- **What:** New `grant_mana_ability`/`grant_triggered_ability` `EffectSpec` types let a static grant something richer than a bare keyword slug (Tyvar Kell's "{T}: Add {B}.", Dionus's granted triggered ability). Each grantee gets its own stable, cache-rebuilt instance (`GameState._granted_ability_cache`) so per-instance state like `once_per_turn` tracking survives across recompute passes, scoped per-object so tapping one Elf doesn't fire every other Elf's copy.
- **Files:** `game/effect_binder.py`, `game/continuous.py`, `models/game_state.py`, `game/ability_catalogue.py`
- **Why:** Needed a genuine `TAPPED` event (RULE 701.21b, only on a real untapped→tapped transition) as a new primitive to scope the granted trigger correctly.

### Become a copy of target permanent/creature (RULE 706/707)

- **What:** Three mechanisms sharing one mutate/snapshot/restore primitive (`game/copy_mechanics.py`): (1) permanent ETB copy (Clever Impersonator) via true RULE 614.1c/614.12 replacement timing, resolved before the object ever joins the battlefield; (2) continuous conditional copy (Vesuvan Shapeshifter) as a genuine RULE 613 layer-1 static that mutates only on a condition/target change and locks in permanently once it copies a creature with no equivalent ability; (3) temporary "until end of turn" copy (Cursed Mirror), reverted at cleanup.
- **Files:** `game/copy_mechanics.py`, `game/continuous.py`, `game/rules_engine.py`, `models/card.py` (`as_copy`)

### Board-wide ability strip (layer 6, RULE 613.7f)

- **What:** A `remove_all_abilities` static sets `GameObject.loses_all_abilities`, stripping every keyword and gating both triggered and activated abilities — Humility (paired with a layer-7b base P/T set).
- **Files:** `game/continuous.py`, `game/effects.py`

### MEC-47: Licid — a creature that turns itself into an Aura (first pass, hand-authored)

- **What:** the Tempest Licid cycle's shared ability — "{cost}, {T}: This creature loses this ability and becomes an Aura enchantment with enchant creature. Attach it to target creature. You may pay {cost} to end this effect." — plus each Licid's own "Enchanted creature has `<keyword>`." clause. Shipped for **Gliding / Enraging / Quickening / Corrupting Licid** (flying / haste / first strike / fear); the rest are one `_licid(...)` catalogue entry each (`entries_016.py`), remaining as **MEC-47**.
- **How:** no full RULE 613 layer-4 machinery of its own — it composes existing pieces. `LicidBecomeAuraEffect` (`licid_become_aura`, a `TargetSpec(kind="creature")` effect): sets `GameObject.attached_to` to the chosen creature, sets the new `GameObject.is_licid_aura` flag, writes `parametric_keywords["enchant"] = {"quality": "creature"}` (the field every `_attachment_kind`/`_attachment_legal` reader — and the RULE 704.5n SBA that would otherwise detach a restriction-less "Aura" — reads live, same as `BecomeAuraEffect`), and parks **one** `for_as_long_as` floating `type_change` static (`add_types=["enchantment"]`, `add_subtypes=["aura"]`, `remove_types=["creature"]`, `affects="objects"` on its own id) whose `duration_data.condition` is `{"kind": "is_licid_aura"}` — so `game/durations.is_expired` sweeps it the instant the flag clears, no bespoke un-park. `LicidRevertEffect` (`licid_revert`) just clears the flag + `attached_to` + the `enchant` key. Both activated abilities carry an `activation_condition_marker` (`ACTIVATION_CONDITION_MARKER`, folded into `ActivationCost.activation_condition` by `effect_binder`): the transform is gated `not_licid_aura`, the "pay to end" `is_licid_aura`, so exactly one is ever offered — the RULE 604.3 "loses this ability" is modeled as "the ability is un-activatable while transformed" rather than literally removed. The "Enchanted creature has flying" clause is an ordinary `grant_keyword` `affects="attached_permanent"` static bound off the card text — inert while `attached_to` is `None`, live the moment it's set (`continuous._selector_objects`'s `attached_permanent` branch never checked Aura-ness).
- **New:** `GameObject.is_licid_aura` (+ its `reset_as_new_object` clear, RULE 400.7 — a Licid that leaves comes back a plain creature); `static_conditions` `is_licid_aura` / `not_licid_aura`; `LicidBecomeAuraEffect` / `LicidRevertEffect` + registry.
- **Files:** `models/game_object.py`, `game/static_conditions.py`, `game/effects.py`, `game/ability_catalogue/entries_016.py`.
- **Yield:** +4 (AUTHORED), no `PARSER_VERSION` bump. Coverage 13,586 / 34,811 (39.0%); Commander-legal 13,003 / 31,830 (40.9%).
- **Tests:** `tests/test_mec47_licid.py` — registration (2 activated + 1 static per Licid, fresh objects); transform (becomes non-creature Enchantment, attaches, host gains flying); the ability gating flips (transform gone / revert present while an Aura); "pay to end" reverts fully and the parked static self-sweeps; `reset_as_new_object` clears the flag.
- **Second pass (+5, same commit family).** Calming (`grant_keyword cant_attack`), Convulsing (`cant_block`), Tempting (`all_must_block`), Dominating (`control_change` — defaults `affects="attached_permanent"`), Transmogrifying (a two-static entry: `anthem` +1/+1 and `type_change` add `artifact`, both `affects="attached_permanent"`). All five reuse the exact `EffectSpec`s the parser already emits for the same clause on a real Aura card. **Gotcha fixed:** `_licid()` now builds every `activation_condition_marker` (and copies every granted spec) fresh per call — a shared module-constant `EffectSpec` is mutated by the binder and would corrupt the next Licid / every later `specs_for`. **9 of 13** Licids now AUTHORED (13,591 / 34,811, 39.0%; Commander-legal 13,008 / 31,830, 40.9%).
- **Third pass (+3) — 12 of 13 Licids AUTHORED.** `_licid()` grew a `granted_kind` (`"static"` / `"triggered"` / `"activated"`) so a Licid's own clause can be a trigger or activated ability, not just a static. **Nurturing** — `{G}: regenerate enchanted creature`, a new `RegenerateEffect` `target_kind="attached_permanent"` mode (resolves `source.attached_to`). **Stinging** — `trigger={"event": TAPPED, "condition": {"subject": "attached_permanent"}}` → `damage` `recipient_subject="trigger_subject_controller"` (the tapped creature's controller). **Leeching** — `trigger={"event": STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "attached_permanent"}` (the Dance of the Dead scoping — the *host's* controller's upkeep, not "yours") → `damage` with a new `recipient_subject="attached_permanent_controller"` (`DealDamageEffect` reads `source.attached_to` → its controller). **RULE 704.5n:** `_detach_attachments_from` clears `is_licid_aura` when a Licid's host leaves — the Aura is binned (RULE 704.5m) and its `for_as_long_as` type-change static self-sweeps, so a later reanimation is a plain creature. **Still open:** only **Flanking Licid** (the old "Summon Licid" templating — "becomes a creature enchantment that reads …", a one-off).
- **Note:** during this pass a concurrent process on the shared working tree reverted the uncommitted `tests/test_mec47_licid.py` once (the same hazard behind the stray `test_* 2.py` files); the source changes survived, the test additions were re-applied. Commit + push promptly when working this tree.
- **Fourth pass (+1) — MEC-47 CLOSED, 13 of 13.** **Flanking Licid** (Stronghold) is the lone "Summon Licid" card, never given the errata that turned the others into non-creature Auras: "{R}, {T}: ~ … becomes a creature enchantment that reads 'Enchanted creature gains flanking' instead of a creature." Per Gatherer 2004-10-04 it **stays a creature** and merely gains Enchantment—Aura on top. `LicidBecomeAuraEffect` grew a `keep_creature` flag (registry reads `keep_creature`); when set, the parked `for_as_long_as` `type_change` static uses `remove_types=[]` instead of `["creature"]` — everything else (the `attached_to` set, the `enchant` parametric keyword, the `is_licid_aura`/`not_licid_aura` gating, RULE 704.5m/n binning) is identical, so it's still an Aura for SBA purposes and its host gaining `flanking` is the same `grant_keyword affects="attached_permanent"` static. `_licid()` grew a matching `keep_creature` kwarg that only changes the `licid_become_aura` `EffectSpec` params. Hand-authoring only, no `PARSER_VERSION` bump. Coverage 13,595 / 34,811 (39.1%); Commander-legal 13,012 / 31,830 (40.9%).
- **Tests:** `test_flanking_licid_becomes_an_aura_but_stays_a_creature` — transform makes it Enchantment + Aura subtype (`continuous._has_subtype`) while `is_creature` stays `True`, host gains `flanking`, "pay {R} to end" reverts fully.

### Aura/Equipment attached-permanent grants: control magic and quoted abilities

- **What:** "You control enchanted creature/permanent." (Control Magic-shaped) needed zero new code, just a parser row onto the existing `control_change` static. Quoted full-ability grants (`<subject> has "<ability text>"`, Sword-cycle-shaped) recursively parse the quoted body as an ordinary ability line and wrap it as `grant_triggered_ability` when it resolves to a plain self-subject trigger on ENTERS_BATTLEFIELD/DIES/ATTACKS/BLOCKS.
- **Files:** `parser/oracle/catalogue/static_handlers.py`, `game/effects.py`
- **Why:** Deliberately fails closed on a quoted activated-ability grant (needs a "grant an activated ability" primitive not yet built) and a quoted DAMAGE/phase-scoped grant (blocked by a separate pre-existing segmenter gap).

### RULE 613 Layer System — Full Layer Coverage & Ordering

- **What:** `game/continuous.py` re-derives every battlefield permanent's characteristics across layers 2, 4, 5, 6, 7a-e each recompute, stamping derived P/T, added types, granted keywords and a per-object trace. `StaticAbility` bridges every layer via `anthem`/`pt_set`/`grant_keyword`/`type_change`/`cost_reduction`/`color_change`/`control_change`/`pt_cda`/`pt_switch`, plus `affects="attached_permanent"` for Aura/Equipment. Adds timestamp ordering within a layer, layer 1 (copy) and layer 3 (text-change, scoped to word substitution), and bounded RULE 613.8 dependency ordering for layer 2's controller-scoped effects.
- **Files:** `game/continuous.py`, `game/effects.py`
- **Why:** Layer 3's text substitution deliberately isn't a full oracle re-parse — bound abilities/keywords stay fixed at bind time — since no real card needed more than protection-quality word substitution at ship time.

### Attached-Permanent Static Parsing

- **What:** "equipped/enchanted/fortified … gets +N/+N [and has `<kw>`]" and "… has `<kw>`" now parse to `anthem`/`grant_keyword` specs with `affects="attached_permanent"` — the engine-side machinery already existed, this closed the recognition gap.
- **Files:** `parser/oracle/catalogue/static_handlers.py`

### Layer-6 Grant of an Activated Ability

- **What:** "`<host>` has '`{cost}`: `<effect>`.'" (Umbral Mantle/Squirrel Nest-shaped) — the activated sibling of the existing triggered/mana/keyword layer-6 grants. `GameObject.granted_activated_abilities` is built and cached per relationship each recompute; `can_activate`/`activate_ability`/`legal_actions` read it alongside printed activated abilities. Twice-deferred before shipping.
- **Files:** `game/continuous.py`, `game/effects.py`, `game/game_engine.py`
- **Bug fixed:** `_ACTIVATED_RE` was quote-blind, so a quoted grant whose inner ability itself contained a cost-colon was misparsed; fixing it also revealed ~950 cards whose quoted grant is actually a mana ability had been silently swallowed as "claimed, no spec" by the old buggy regex — closed by a separate non-attached mana-ability grant handler.

### Per-Count Static Anthem Multiplier

- **What:** Layer 7d `pt_mod` gained optional `power_count`/`toughness_count` params for "+1/+1 for each land you control" (Blackblade Reforged, reusing the controller-scoped count-selector vocabulary), a per-object `_equipment_attached_count` for "+2/+0 for each Equipment attached to *it*" (Bruenor Battlehammer), and a `plus_one_counters_on_self` selector (Lion Sash).
- **Files:** `game/continuous.py`

### Layer-6 Keyword Removal

- **What:** A new `remove_keyword` static type mirrors `grant_keyword`, populating `GameObject._removed_keywords`, subtracted last in keyword display/combat checks (Colossus Hammer's "loses flying").
- **Files:** `game/continuous.py`, `game/combat.py`

### Standing Granted Protection (RULE 702.16, Layer 6)

- **What:** `grant_protection_static` → `GameObject._granted_protections`, stamped every recompute and unioned by `combat.is_protected_from`, so it stops applying the instant its source leaves with no teardown code. Covers group (Hungry Lynx), attached, self, and RULE 601.2b's dynamic "protection from the chosen color" forms.
- **Files:** `game/continuous.py`, `game/combat.py`

### Type Grants Past the Battlefield (RULE 613.4a, Layer 4)

- **What:** `continuous._apply_off_battlefield_types` is a dedicated pass over a controller's hand/graveyard/library/exile plus stack spells, stamping `_added_subtypes` for Arcane Adaptation/Leyline of Transformation/Ashes of the Fallen — since the ordinary layer engine only walks battlefield permanents. Tracks what it stamped and clears it first each pass, since those zones never see `reset_derived`.
- **Files:** `game/continuous.py`

### RULE 613.6 Static Condition Vocabulary

- **What:** `game/static_conditions.py` is a single whitelisted `active_if` vocabulary (state, characteristics, whose turn it is, board counts, life/hand/cards-drawn) carried by any static and evaluated live every recompute, replacing four previously-separate ad hoc gate parameters (`active_player_only`/`min_level`/`min_count_selector`/`requires_monstrous`), which are now translated into it rather than kept as a parallel mechanism.
- **Files:** `game/static_conditions.py`, `game/effects.py`
- **Why:** "As long as" leads ~250 cache clauses across five+ unrelated families; the old one-parameter-per-card pattern would have meant a new whitelist entry for every future card.
- **PAR-30 (PARSER_VERSION 156) — `subtype_in_graveyard`.** "As long as there's a `<subtype>` card in your graveyard" — the Avatar: TLA "Lesson" cards (Aang A Lot to Learn, First-Time Flyer, Platypus-Bear), and, since the subtype word is unrestricted, "land card" (Murasa Behemoth) and any other. A live type-line scan of the controller's graveyard (`+ subtype`, `+ min` default 1), the same convention `effects.ConditionalEffect`'s `graveyard_has_type` branch uses — added as a `STATIC_CONDITION_KINDS` row + a `_STATIC_CONDITION_RES` parser row (`"there(?:'s| is| are) an? <sub> card in your graveyard"`) + a German `_describe` string. Its **trigger intervening-if sibling** ("when ~ dies, **if there's a `<subtype>` card in your graveyard**, `<effect>`" — Walltop Sentries) reuses `ConditionalEffect`'s already-built `graveyard_has_type` `EffectSpec.condition` key, which until now had *no* parser recognizer (only the hand-authored Trystan used it); `segmenter._GRAVEYARD_HAS_SUBTYPE_CONDITION_RE` wires it, in the same "wrap the rest, tag the condition" family as `_CONTROLS_NONE_OF_TYPE_CONDITION_RE`. +6 (also Dawnhand Eulogist — "if there is an Elf card in your graveyard"), 0 regressed. Tests in `test_static_conditions_and_durations.py`. **Fire Nation Cadets** — "~ has firebending N as long as there's a lesson card in your graveyard" — its condition half landed here; its self parametric-keyword-grant half landed at v157 (see the Firebending grant-path entry), so the card is now fully MODELED.

### RULE 611 Duration System

- **What:** `game/durations.py` plus `GameState.floating_statics` model any RULE 611 continuous effect duration the `temp_*` fields can't express ("until your next turn", "until end of combat", "for as long as `<condition>`") as an ordinary `StaticAbility` living on the state, swept at its named window. A `for_as_long_as` duration must *remove* the effect on condition failure, not merely skip it, or it's indistinguishable from an `active_if` gate. Unknown durations fail closed as `rest_of_game` (never swept) rather than silently deleting a legitimate effect. Also closed PAR-11's "doesn't untap for as long as it remains tapped" lock-down family purely by composing this with existing pronoun/no-untap primitives, and the board's "Statische Effekte" panel now shows each static's duration/condition bounds, dimming a currently-false gate rather than hiding it.
- **Files:** `game/durations.py`, `models/game_state.py`, `game/effects.py`

### Condition Subject (`of`: source/attached/affected)

- **What:** `static_conditions.condition_holds` resolves a subject first (`source` default, `attached`, `affected`), so every existing `source_*` condition kind works on an Aura's attached host for free ("as long as enchanted permanent is a creature/red/a Vehicle", ~52 cards) rather than needing a duplicated `attached_*` kind per condition.
- **Files:** `game/static_conditions.py`

### Dynamic Threshold on a Group Scope

- **What:** `continuous.dynamic_threshold` reads either the source's own derived characteristics or a full `count_selector` list, for group scopes like "creatures your opponents control with power less than ~'s power are goaded" — a literal `min_power`/`max_power` can't work here since the threshold is itself layer-engine output.
- **Files:** `game/continuous.py`

### ENG-22: `continuous.py` `recompute()` Split into Per-Layer Functions

- **What:** The single 424-line `recompute()` became a ~15-line dispatcher over seven top-level layer functions (`_apply_layer_2_control` through `_apply_layer_7_pt`, plus a post-layer combat-restriction/goad stamping function), extracted via a line-range script keyed to the existing `# -- Layer N:` comments. `animation_pt` (layer 4 → layer 7) is the only value that crosses a layer boundary and is threaded explicitly; everything else stayed fully local.
- **Files:** `game/continuous.py`
- **Why:** Verified harder than the other mixin splits since layer *order* is load-bearing (unlike method order in a mixin file) — full suite plus explicit layer-named tests plus live `engine_bench.py inspect` checks on an anthem and a board-count combat restriction.

### ENG-8: Layer 3 Text-Change Reaches Landwalk

- **What:** `combat._landwalk_slugs` now scans `obj.effective_oracle_text` (the layer-3 word-substitution output) instead of `obj.card.oracle_text` directly, so a text-changing static also flips a permanent's landwalk type, not only its protection.
- **Files:** `game/combat.py`

### ENG-9: RULE 613.8 Dependency Ordering Re-Verified

- **What:** Checked whether any selector added since the layer engine shipped now reads another object's *derived* state outside layer 2 (the ticket's own trigger condition for extending dependency ordering). The candidates found (`min_power`/`max_power`/power-comparison selectors) are consumed only by post-layer-7 combat/goad statics, not a same-sublayer dependency — no code changed; pinned down with a regression test instead.
- **Files:** `game/continuous.py`

### New count-selector kinds (devotion, legendary creatures, named-in-graveyard)

- **What:** `continuous.count_selector` gained `devotion_to_<colour>` (RULE 202.2f, hybrid pips count for both colours), `legendary_creatures_you_control`, and `cards_named_source_in_all_graveyards` — feeding Thassa's Oracle's win condition, Eiganjo's cost reduction, and Rite of Flame's mana amount respectively.
- **Files:** `game/continuous.py`

### Land-type ability removal (RULE 305.7)

- **What:** Setting a land's subtype to a basic land type now correctly strips its rules text/abilities (a Blood-Moon'd Underground Sea makes only {R}); the layer-4 subtype overwrite sets `_loses_all_abilities` and `mana_abilities_for` was taught to honour it.
- **Files:** `game/continuous.py`, `game/mana_abilities.py`
- **Bug fixed:** `mana_abilities_for` never checked `_loses_all_abilities` at all, so Humility and Dress Down had the same hole before this fix.

### MEC-12 — "as long as you're the monarch/have the initiative" conditional statics

- **What:** `static_conditions.py`'s RULE 613.6 whitelist gained `is_monarch`/`has_initiative`, consulted with no `of` subject (always the static's own controller), the same shape `your_turn` already had — both printed clause orders work with zero further engine changes.
- **Files:** `game/static_conditions.py`, `parser/oracle/catalogue/static_handlers.py`
- **Why:** Most of the 56 UNMODELED cards the ticket estimated turned out to be blocked on a separate, already-documented gap (non-creature group scopes like "permanents you control"), not on this condition — real yield was smaller than estimated but the machinery is real and immediately reusable.

### "As ~ enters, choose a basic land type" (PAR-4, RULE 305.6)

- **What:** A third `enter_choice_effects` sibling alongside creature-type/colour choice (`ChooseBasicLandTypeReplacement`), stamping the same `GameObject.chosen_type` field the creature-type family uses, so no continuous-effects change was needed — only a new `choose_basic_land_type` `pending_choice` kind wired through the existing enter-choice dispatch. Realmwright fully modeled on this alone.
- **Files:** `game/effects.py`, `parser/oracle/catalogue/static_handlers.py`, `game/engine/casting_mixin.py`

### Non-creature group scopes for grant families (PAR-3)

- **What:** Keyword-grant/quoted-grant statics (`_GRANT_RE`/`_QUOTED_GRANT_RE`) now recognize a bare card-type word ("Artifacts you control have hexproof.", "Other enchantments have '…'.") via a new `_permanent_type_scope` fallback, reusing existing `continuous.py` selectors (`artifacts_you_control`, `all_lands`, etc.). Deliberately narrow: a compound "artifacts and enchantments" scope stays unclaimed (no selector ORs two card types yet).
- **Files:** `parser/oracle/catalogue/static_handlers.py`, `game/continuous.py`
- **Bug fixed:** Three bugs caught before/via this batch — Sterling Grove's "Other enchantments **you control**" would have granted itself shroud (missing `exclude_self` for the "you control" case); "Artifact creatures you control" anthems (Chief of the Foundry) silently boosted nothing because `_scope` guessed "Artifact" as a creature subtype instead of a card type; and "Enchanted creatures" (Greater Auramancy) hit the same guessed-subtype trap for a characteristic word, now failing closed via `_NONCREATURE_TYPES`.

### Standing protection self-exemption for own Aura (PAR-6, RULE 702.16n/p)

- **What:** A trailing "This effect doesn't remove this Aura." clause is now recognized and honored: a new per-source `GameObject._protection_self_exempt` flag (stamped by the layer-6 pass) is read by `_attachment_legal` so a protection-granting Aura no longer detaches itself the moment its granted protection would otherwise disqualify the attachment. Closed 11 cards (Black/Blue/Green/… Ward, Cho-Manno's Blessing, Flickering Ward, …). Also added `protection_from_chosen_type` (Riders of Gavony), the creature-type sibling of the existing `protection_from_chosen_color` dynamic.
- **Files:** `game/continuous.py`, `parser/oracle/catalogue/static_handlers.py`
- **Bug fixed:** Empty-Shrine Kannushi's "protection from the colors of permanents you control" was being stored as a literal, unmatchable quality string — now correctly rejected by the same `" of "` computed-quality guard rather than half-modeled.

### grant_until P/T-delta and combat-restriction durations (PAR-13)

- **What:** `grant_until`'s new P/T-delta route (`_pump_until`, riding the general layer-7c anthem static) and its "can't attack/block until `<duration>`" sibling — resolve-time grants of a temporary pump or combat restriction (Fungi Cavern, Twisted Caverns dungeon rooms). Also widened group selectors with "creatures your opponents control"/"creatures you don't control".
- **Files:** `game/effects.py`, `parser/oracle/catalogue/static_handlers.py`

### "Commander creatures you own have `<ability>`" grant (PAR-12)

- **What:** A new `continuous.group_selector_objects` selector, `"commander_creatures_you_own"` — scoped by ownership (not control), since RULE 108.3 ownership is what this grant actually means. Honest yield was small (2 of 28 cache cards) since most use a group-subject/conditional inner trigger the quoted-grant recursion doesn't support yet.
- **Files:** `game/continuous.py`, `parser/oracle/catalogue/static_handlers.py`
- **Bug fixed:** `_quoted_ability_grant_effects` checked `trigger["event"] not in _GRANTABLE_TRIGGER_EVENTS`, but a compound self-trigger ("enters or leaves the battlefield") stamps a *list* there — an unhashable value crashing the `in` check with `TypeError` on every pre-existing quoted-grant path, not just this new one.

### Dynamic-magnitude pump effects

- **What:** `PumpEffect.amount_from_count_selector` ("+X/+X where X is the number of creatures you control", Craterhoof Behemoth) and `PumpEffect.per_recipient_controller_counter` ("-1/-1 for each poison counter its controller has", Phyresis Outbreak — the one shape where each recipient in a group scales independently by its own controller's count).
- **Files:** `game/effects.py`

### Selector/filter reach widenings (Keywords Showcase batch)

- **What:** `creatures_you_control_of_type_<X>` and `permanents_you_control` reached `group_selector_objects` for the first time so a one-shot `PumpEffect.selector` can target a filtered group, not just count it; `other_creatures_you_control` reached `TapEffect.selector`.
- **Files:** `game/continuous.py`, `game/effects.py`
- **Bug fixed:** The `TapEffect` selector branch never passed `src=self.source` to `group_selector_objects`, so "other" had been silently inert for any selector needing it.

### RULE 601.2b resolve-time interactive choices (choose type / choose player)

- **What:** A category distinct from the existing enter-battlefield choice pipeline: "choose a creature type, then grant it something" (Selfless Safewright) and "choose a player" (Stuffy Doll), both `request_choose_X`/`resolve_choose_X_choice` pairs dispatched by kind string.
- **Files:** `game/rules/turn_loop_mixin.py`

### `cast_prohibition`/`activation_prohibition` gated on "During your turn" (ENG-28)

- **What:** `cast_prohibited` now consults `active_if` (RULE 613.6) like every other static; a general "During your turn, `<static clause>`." parser wrapper reuses the existing "as long as" recursive-rewrite plumbing, plus a new opponent-scoped "activated abilities of `<type>` can't be activated" row and a combined cast+activation-prohibition parser for compound sentences (Grand Abolisher, Myrel, Linvala, Keeper of Silence).
- **Files:** `game/continuous.py`, `game/effects.py`, `parser/oracle/catalogue/static_handlers.py`
- **Why:** Sizing first showed the ticket's own premise was half wrong — Linvala/Karn's lock clauses carry no turn gate at all; only Grand Abolisher/Myrel print the gated shape.
- **Bug fixed:** `cast_prohibited` never read `active_if` at all, and the `cast_prohibition` `EffectRegistry` factory didn't even thread the param onto the `StaticAbility` — any `cast_prohibition` spec carrying `active_if` was silently dropped at bind time.

### Untap-cap family generalized past lands-only (Static Orb/Winter Moon) (Continuous Effects & Layer System)

- **What:** `continuous.untap_cap_for_lands` (Winter Orb-only, hardcoded) became `continuous.active_untap_caps` (a list of `{count, card_type, nonbasic}` dicts — 2+ caps can be active independently) + `matches_untap_cap_filter`; the "as long as untapped" gate moved onto the ordinary `active_if` wrapper. Closes Static Orb and Winter Moon via one new parser regex, also reaching Damping Field/Imi Statue/Smoke/Stoic Angel.
- **Files:** `game/continuous.py`, `game/engine/turn_loop_mixin.py`, `parser/oracle/catalogue/static_handlers.py`

### Meekstone: unattached group-scoped no-untap (Continuous Effects & Layer System)

- **What:** "Creatures with power N or greater don't untap…" — a new `_NO_UNTAP_GROUP_POWER_RE` row emits `affects="all_creatures"` plus the ordinary `min_power` selector, needing no new engine code.
- **Files:** `parser/oracle/catalogue/static_handlers.py`
- **Bug fixed:** Two `no_untap`/`untap_cap` `EffectRegistry` factories passed `params={}`, silently discarding `min_power`/`card_type`/`nonbasic`/`active_if` even once the parser started emitting them.

### "You control a creature with power N or greater" as a RULE 613.6 condition (Continuous Effects & Layer System)

- **What:** `control_count`'s `selector`/`min` shape gained an optional `min_power` key, scanning the battlefield directly instead of routing through the flat `count_selector` vocabulary (which only counts, never filters by a derived characteristic).
- **Files:** `game/static_conditions.py`

### Back to Basics: unconditional nonbasic-land no-untap (Continuous Effects & Layer System)

- **What:** The unconditional, unlimited-count sibling of the seventh pass's capped Winter Moon shape — `affects="all_lands"` plus the ordinary `nonbasic` selector, one new parser row.
- **Files:** `parser/oracle/catalogue/static_handlers.py`

### Devotion (RULE 700.6) generalized selector + wedge names (Continuous Effects & Layer System)

- **What:** `continuous.count_selector`'s single-colour `devotion_to_<colour>` selector generalized to a colour set or one of five two-colour wedge names, via a shared `subgrammars.DEVOTION`/`devotion_selector` fragment. RULE 613.7f's "isn't a creature" gods needed only a new `_STATIC_CONDITION_RES` row (`control_count`'s existing `max` bound already sufficed) and an unconditional `_NOT_A_CREATURE_RE`.
- **Files:** `game/continuous.py`, `parser/oracle/subgrammars.py`, `game/static_conditions.py`
- **Bug fixed:** `DealDamageEffect._apply_selector`'s mass "to each opponent" path had never actually read `amount_from_count_selector`, masked until Fanatic of Mogis exercised mass+dynamic-amount together for the first time.

### MEC-22: Anger cycle's other four graveyard-sourced statics (Continuous Effects & Layer System)

- **What:** Brawn/Filth/Valor/Wonder registered on the exact `"from_graveyard": True` `grant_keyword` shape Anger already established (a per-land-type `control_count` `active_if` gate); Riftstone Portal is the one structural variant, granting a mana ability instead of a keyword, unconditionally.
- **Files:** `game/ability_catalogue.py`

### Urza's Saga: lasting self-granted activated ability + self-scaling token anthem (Continuous Effects & Layer System)

- **What:** `GrantSelfActivatedAbilityEffect` (RULE 714.2c) appends a real `grant_activated_ability`-shaped, permanent `StaticAbility` onto the Saga's own `static_effects` — outlives the one-shot chapter trigger that creates it, unlike the turn-scoped graveyard-cast-permission shape it otherwise mirrors. `CreateTokenEffect.grant_self_anthem` bakes a self-scaling "+1/+1 for each artifact you control" `StaticAbility` onto a freshly created token.
- **Files:** `game/effects.py`, `game/ability_catalogue.py`

### MEC-21: `grant_borrowed_activated_ability` (RULE 113.7c) (Continuous Effects & Layer System)

- **What:** A new layer-6 static reading a live, board-derived set of granted abilities (rather than one fixed printed ability) — for each matching grantee and each still-exiled creature card in the source's `exiled_with_ids`, builds a fresh `ActivatedAbility` with every nested effect's `.source` redirected to the grantee via a new `_retarget_effect_source`. Cached separately from the ordinary layer-6 cache to avoid a pruning-loop collision. Closes Agatha's Soul Cauldron's ability-borrowing clause.
- **Files:** `game/continuous.py`, `game/effects.py`, `models/game_state.py`

### MEC-26: group/chosen-permanent-scoped ability borrowing (Continuous Effects & Layer System)

- **What:** `grant_borrowed_activated_ability` gained `source_mode="group"` (Drana and Linvala — reads a live `affects` selector off the battlefield every recompute, no exiling involved) and `source_mode="chosen_permanent"` (Scheming Fence — a single donor named once via a new `ChoosePermanentEffect`/`"choose_permanent"` ETB action stamping `GameObject.chosen_permanent_id`). Both also needed no new code for their "activated abilities of `<donor scope>` can't be activated" clause or their any-color wildcard, since existing selector vocabularies already covered both once a real card used them.
- **Files:** `game/continuous.py`, `game/effects.py`, `game/rules_engine.py`, `models/game_object.py`
- **Bug fixed:** `grant_borrowed_activated_ability` defaulted `has_counter_kind` to `"+1/+1"` for every caller, silently filtering Drana and Linvala's own no-counters grantee to an empty set; now `None` unless a caller explicitly opts in.

### Stasis Untap-Step Skip

- **What:** "Players skip their untap steps" — a new `skip_untap_step` `StaticAbility` layer / `continuous.all_untap_steps_skipped`, checked once at the top of `GameEngine._step_untap` rather than per-permanent, distinct from the existing capped `untap_cap` treatment.
- **Files:** `game/continuous.py`, `game/engine/turn_loop_mixin.py`.

### Anthem Non-Creature-Subtype Scope Guard

- **What:** `_ANTHEM_RE`'s `_scope` gained `_ARTIFACT_SUBTYPES`/`_vehicle_scope_params` so a bare non-creature subtype word ("Vehicles") isn't guessed as a creature subtype, falling through instead to the existing non-creature-permanent fallback chain.
- **Files:** `parser/oracle/catalogue/static_handlers.py`.
- **Bug fixed:** "Vehicles you control get +1/+1 and have vigilance and reach." would have parsed to `affects: creatures_you_control`, wrongly excluding every uncrewed Vehicle (not a creature until crewed) from a buff printed to include it. Not yet exercised by any real shipped card, caught before it could be.

### Dynamic P/T-Equals-Mana-Value Type Change (Karn, the Great Creator)

- **What:** `type_change`'s new `pt_selector="mana_value"` plus a new `"noncreature_artifact"` target kind for "becomes an artifact creature with power/toughness equal to its mana value," wrapped in `GrantUntilEffect`/`duration="your_next_turn"`. Karn's -2 needed a new `"exile"` search zone (a choice among public information, not a hidden RULE 701.19 search).
- **Files:** `game/continuous.py`, `game/targeting.py`, `game/rules_engine.py`.

## Combat

### Put onto the battlefield attacking (RULE 508.4) — PAR-30, v177

- **What:** `RulesEngine.put_onto_battlefield_attacking(obj, defender=None)` — an already-on-the-battlefield creature is placed into the current combat *attacking* without being declared: no tap for the attack (RULE 508.4), summoning sickness is irrelevant (it never "attacked"), an `ATTACKS` event fires so "whenever ~ attacks" / battalion triggers still see it. RULE 508.4a's defender choice is auto-made — the defender the rest of the combat is attacking if that's unambiguous, else the controller's sole/first opponent. The shared primitive behind "create a … token that's tapped **and attacking**" (`CreateTokenEffect.attacking`, v177 — Captain's Claws, Hanweir Garrison, Hero of Bladehold, +10) and, when wired, "put a card … onto the battlefield tapped and attacking".
- **Files:** `game/rules/misc_mixin.py`, `game/effects.py` (`CreateTokenEffect`), `parser/oracle/catalogue/handlers.py` (`_TOKEN_TAPPED_ATTACKING` suffix). `tests/test_par30_token_tapped_and_attacking.py`.
- **v178 extended it to `PutFromHandOntoBattlefieldEffect`:** an `attacking` param routes through a new `"battlefield_attacking"` search destination in `_put_searched_card` (enters tapped, then `put_onto_battlefield_attacking`). Parser: `_put_from_hand` gained a creature-subtype filter, a colour filter ("blue or red creature card" → `{"color": […]}`) and the "…tapped and attacking" tail; derived qualities ("historic", "multicolored") fail closed. +7 — Preeminent Captain, Goblin Lackey, Warren Instigator, Mindwrack Liege, Didgeridoo, Dramatic Entrance, Firebrand Ranger. `tests/test_par30_put_from_hand_attacking_and_filters.py`.
- **v179 finished the common shapes + a bycatch:** `CopyPermanentEffect` gained `tapped`/`attacking` (→ `put_onto_battlefield_attacking` per made token). Parser: `_CREATED_ENTERS_ATTACKING_RE` — "Create a token. The token[s] enter[s] tapped and attacking." stamps the preceding `create_token`/`copy_permanent`; `_LOOK_TOP_PUT_ATTACKING_RE` — "look at the top N … put a creature card … onto the battlefield tapped and attacking. Put the rest on the bottom …" → `impulsive_look` with `hit_destination="battlefield_attacking"`. Separately, `_DELAYED_SAC_EXILE_TAIL_RE` grew an **"at end of combat"** timing (→ `create_delayed_trigger` step `"end_combat"`) + "the token[s]" subject — a tail that rides far beyond this cluster (Crumbling Colossus, the Basilisk morph cycle, Ohran Viper). +18 — Geist of Saint Traft, Crumbling Colossus, Serpentine/Stone-Tongue/Lowland Basilisk, Ohran Viper, Fog Elemental, Geist/Invocation of Saint Traft, &c. `tests/test_par30_enters_attacking_and_delayed_combat_tail.py`.
- **v185 — the trailing defender ref:** all four routes (`_PUT_FROM_HAND_RE`, `_LOOK_TOP_PUT_ATTACKING_RE`, `_TOKEN_TAPPED_ATTACKING`, `_CREATED_ENTERS_ATTACKING_RE`) now accept an optional "…tapped and attacking **that player / that opponent**". The named defender is the one the source is already attacking, which `put_onto_battlefield_attacking`'s RULE 508.4a auto-choice already derives from the other attackers, so the phrase is *consumed*, not re-modeled. Alongside it `segmenter._SELF_SUBJECT_RE` and the `PLAYER_ATTACKED` row accept "~ attacks a player / an opponent" and "you attack a player" — the defender kind refines nothing the bare event carries (RULE 508.1). +1 (Soaring Lightbringer — "whenever you attack a player, create a … token that's tapped and attacking that player"), 0 regressed. `tests/test_par30_attacking_that_player_defender_ref.py`.
- **v188 — the per-opponent distributive:** new `CreateTokenEffect.per_opponent` — "**for each opponent**, [you] create a … token[ that's tapped and attacking that opponent]" (Endless Foot Assault, Stampede Surfer). The effect's controller makes one token per opponent (`self.count` apiece), and with `attacking` each token is put into combat against a *distinct* opponent — RULE 508.4a's defender choice made per token via `put_onto_battlefield_attacking(token, defender=…)` rather than the shared auto-pick (verified in a 3-player game: 2 tokens, defenders `{p2, p3}`). Distinct from `creators="each_opponent"` (there each opponent makes their own). Parser: a leading `for each opponent,` group on the inline `create_token` row; also claims the non-attacking "for each opponent, create …" count, though those cards stay UNMODELED on other clauses. +2, 0 regressed. `tests/test_par30_per_opponent_tapped_attacking.py`.
- **v189 — bare-name subject + `populate` before:** `_CREATED_ENTERS_ATTACKING_RE` gained (1) a bare token-name subject ("create Ragavan, …. Ragavan enters tapped and attacking." — Kari Zev; the name only binds a spec whose `token_name` matches it, so a wrong name fails closed) and (2) a `populate` "before" ("populate. That token enters tapped and attacking." — Ghired, Conclave Exile). `PopulateEffect` gained `tapped`/`attacking`, threaded to `RulesEngine.populate(enter_state={"tapped","attacking"})` — applied to the copy in the degenerate 0/1-token paths, carried on the `pending_choice` (`enter_state` key) for the interactive 2+-token path so `resolve_populate_choice` applies it. +2 (Kari Zev, Ghired), 0 regressed. `tests/test_par30_enters_attacking_name_and_populate.py`.
- **v190 — put-from-hand card filters:** `PutFromHandOntoBattlefieldEffect` gained `power_less_than_source` ("with lesser power" — Shadowfax; a `max_power = source.power - 1` cap folded into `criteria` at `apply`, `-1` when the source has no power so it fails closed) and `max_mana_value_selector` ("with mana value X or less, where X is the number of attacking creatures you control" — Kinscaer Sentry; resolved via `continuous.count_selector` at `apply` into `criteria["max_mana_value"]`). The bare "mana value X or less" without the "where X is …" clause fails closed; a fixed "mana value N or less" is accepted directly. +2 (Shadowfax, Kinscaer Sentry), 0 regressed. `tests/test_par30_put_from_hand_attacking_filters.py`.
- **v191 — delayed "return it to hand" tail:** `_DELAYED_SAC_EXILE_TAIL_RE` gained a `return <it/that creature> to (your|its owner's) hand` verb next to sacrifice/exile/destroy → `create_delayed_trigger` with a new `return_specific_to_hand` inner (`ReturnSpecificToHandEffect` — an `.objects` list baked in by `CreateDelayedTriggerEffect`'s `capture="previous_or_self"`, exactly like `SacrificeSpecificEffect`). Broader than the seam it was found on: **+8** — Alora, Merry Thief (the tapped-and-attacking-adjacent unblockable-loan), the "when ~ attacks or blocks, return it … at end of combat" Phantom Whelp / Windscouter / Quicksilver Behemoth / Wall of Junk cycle, The Locust God, Dragon Mask, Scrappy Bruiser. `tests/test_par30_delayed_return_to_hand_tail.py`.
- **v192 — qualified attack trigger:** "whenever ~ attacks **a player who controls N or more lands**" (Owlbear Cub). `_ATTACKS_DEFENDER_LANDS_RE` keeps it a `{"subject": "self"}` ATTACKS trigger with a `defender_controls_lands_at_least` key; `effect_binder._trigger_condition` appends a predicate reading the ATTACKS event's `defending_player_id` and counting that player's battlefield lands (same "gate an ordinary event on a live state read" idiom as `controls_none_of_type` — no state-trigger subsystem). +1. `tests/test_par30_attacks_defender_lands_trigger.py`.
- **v193 — Winota family + the RULE 508.3a batch-attack trigger:** two pieces. (1) The `look_top` "…tapped and attacking." mid-clause **"It gains <keyword> until end of turn."** interpose — `_LOOK_TOP_PUT_ATTACKING_RE` grew an optional group validated against `_LOOK_TOP_HIT_GRANT_KEYWORDS` (a small combat-keyword allowlist, fail-closed), threaded as `hit_grant_keywords` through `impulsive_look` → `ImpulsiveLookEffect` → `request_impulsive_look` (stashed on `pending_choice`) → `resolve_impulsive_look_choice`, which adds the slugs to the placed card's `temp_keywords` (RULE 514.2) only if it actually landed on the battlefield. (2) "whenever **one or more** [<filter>] creatures you control attack[ a player], …" → new `_BATCH_ATTACK_TRIGGER_RE` maps onto the **existing** once-per-combat `EventType.PLAYER_ATTACKED` aggregate (no new event) as `{"subject": "you"}` + optional `group_filter`; `_batch_attack_group_filter` accepts bare / a negated creature subtype / a main type ("modified"/"suspected" → unclaimed); `effect_binder._any_attacking_matches` checks the filter against the live attacking group (still on the battlefield when triggers go on the stack, RULE 508.3). Rides along: a negated-creature-subtype option on `_GROUP_SUBJECT_RE` ("a **non-Human** creature you control attacks/dies") → `_build_group_ok`'s new `excluded_subtypes` (the mirror of the positive `subtypes` tribal filter). +4 (Winota, A-Winota, Dollmaker's Shop, Requiem Angel), 0 regressed. `tests/test_par30_batch_attack_and_look_top_grant.py`.
- **v195 — `create_token_copy_of_named` + the `impulsive_look` else-branch (The Joiner of Cats):** new `CreateNamedCardTokenEffect` ("create a token that's a [tapped and attacking] copy of `<a specific named real card>`" — Lurrus of the Dream-Den) resolves the copiable values from a real card looked up by name (`services.card_lookup.card_by_name`, a `game/`-safe process-wide `CardDatabase` singleton kept in its **own** module — `card_database.py`'s bytes are hashed into `CardDatabase._SCHEMA_SOURCE_FILES`, so adding a function *there* wipes every cached row on the next open). The handler `_CREATE_NAMED_CARD_TOKEN_RE` + `_NAMED_CARD_SHAPE_RE` only fire on a proper-noun name (contains " of "/","/"'"/a word-internal hyphen), never "enchanted creature"/"chosen permanent" (which are the attached-permanent forms `_copy_permanent` already owns). Separately, `impulsive_look` gained `miss_effect_specs`: `_LOOK_TOP_PUT_ATTACKING_RE`'s trailing "if you don't put a card onto the battlefield this way, `<body>`." → serialized `EffectSpec` dicts run via `_apply_effect_specs` when the look places nothing (player declined in `resolve_impulsive_look_choice`, or nothing eligible in `request_impulsive_look`). The source + specs are kept off `state.pending_choice` on `_pending_impulsive_look` (non-serializable, same split `_pending_name_card` uses). +1, 0 regressed. `tests/test_par30_named_card_token_and_look_else.py`.
- **v197 — `cards_discarded_this_turn` + `CopyPermanentEffect.count_selector` (Living Laser):** new `GameState.cards_discarded_this_turn` (a per-player per-turn count, bumped by `RulesEngine._note_discarded` at every `DISCARD_CARD` fire site — the plain `discard`, `discard_specific`, and the Pitch additional-cost land discard; reset for the incoming active player in `GameEngine.begin_turn`, byte-for-byte the `cards_drawn_this_turn` shape) + a `continuous.count_selector` entry for it + `CopyPermanentEffect.count_selector` (resolved off live state at `apply`, overriding `count` like `count_from_trigger_event` does off the event). Parser: `_COPY_SELF_FOR_EACH_RE` — "for each card you've discarded this turn, create a token that's a copy of ~[, except the token isn't legendary]" → `copy_permanent` with `target_kind=None`/`referent="source"` + the selector. The rest of Living Laser's body ("the tokens enter tapped and attacking", "exile the tokens at the beginning of the next end step") already parsed via `_CREATED_ENTERS_ATTACKING_RE` + `_DELAYED_SAC_EXILE_TAIL_RE`. +1, 0 regressed. `tests/test_par30_living_laser_discard_count_copy.py`.
- **v198 — `random_graveyard_exile_copy_loop` (Sin, Spira's Punishment):** a self-contained `RandomGraveyardExileCopyLoopEffect` — "exile a permanent card from your graveyard at random, then create a tapped token that's a copy of that card. If the exiled card is a land card, repeat this process." Loops: `RulesEngine.random_choice` (RULE 706, reproducible) over the graveyard's permanent cards → move it to exile → `create_token` off the exiled card, tapped → stop the moment a non-land is drawn or the permanent-card pool empties (`MAX_ITER` hard stop regardless). Spell cards in the graveyard are never in the pool. The "enters or attacks" trigger already parsed (`_SELF_MULTI_EVENT_RE`). One fixed-phrasing handler (`_RANDOM_GY_EXILE_COPY_LOOP_RE`). +1, 0 regressed. `tests/test_par30_sin_random_gy_exile_copy_loop.py`.
- **v196 — `then_specs_if_none` on `request_search` (The Vast Scrier):** `PutFromHandOntoBattlefieldEffect` gained `miss_effect_specs`, threaded through `request_search`'s new `then_specs_if_none` param — "if you don't put a card onto the battlefield this way, `<body>`." (here `scry 2`) runs `<body>` when the from-hand pick places nothing: the nothing-eligible early return in `request_search`, and the finish-with-nothing-picked path in `resolve_search_choice` (both carry the serialized specs + a `then_source_id` on the search `pending_choice`, which `_search_choice` now serializes and the re-open threads back). `_PUT_FROM_HAND_RE` also swallows the reminder sentence "if it has any 'whenever ~ attacks' triggers, those trigger" as a no-op — `put_onto_battlefield_attacking` already re-fires ATTACKS for the placed creature. +1, 0 regressed. `tests/test_par30_vast_scrier_put_from_hand_else.py`.
- **The RULE 508.4 "tapped and attacking" mechanic and every parser route into it are complete as of v193** — primitive, all four routes, defender ref, per-opponent distributive, bare-name/`populate` subjects, put-from-hand filters + `then_specs_if_none` else-branch, delayed return-to-hand tail, qualified & batch attack triggers, the `look_top` keyword interpose + else-branch. Both `BACKLOG.md` bullets ("Tapped and attacking residue" and the follow-on "`create a token that's a copy of …` body singletons") are now **fully closed**. **Stangg, Echo Warrior** was the last item — hand-authored in `ability_catalogue/entries_003.py` (`normalize` folds the token name "Stangg Twin" → "~ Twin", and "for each Aura/Equipment attached to X, create a copy **attached to Stangg Twin**" is a copy-and-reattach-elsewhere shape no other card needs): a `create_token` (named legendary, tapped + attacking) → the new bespoke `effects.CopyAttachmentsOntoLastCreatedEffect` (iterate the source's attached Auras/Equipment, `create_token` each off its real card, `attach_to_target` the copy to `GameContext.created_objects[-1]` — the Twin) → `create_delayed_trigger` with `capture="created_objects"` (Kiki-Jiki's template) to sacrifice the whole created set at the next end step. `tests/test_par30_stangg_echo_warrior.py`. Batch-attack *bodies* still open on their own grammar: Ancestor Dragon / Angelic Guardian / Alibou / Aloy / Akki Battle Squad / Grand Warlord Radha / Raging River.

### M2 combat-math keywords and hexproof

- **What:** Annihilator (702.86), Afflict (702.130), and Bushido (702.45) synthesized as real `TriggeredAbility` objects at bind time so they go through the normal stack/priority pipeline; needed a new `EventType.BECOMES_BLOCKED` fired once per attacker. Hexproof (702.11b) now actually gates targeting via `targeting._targetable_by`, excluding a hexproof permanent from an opponent's target options only.
- **Files:** `game/effect_binder.py`, `game/combat.py`, `game/targeting.py`, `models/events.py`
- **Why:** Rampage was deliberately deferred here because its pump amount needs a per-firing dynamic amount a bind-once `TriggeredAbility` can't carry (built later, see M2 Rampage).

### M2 Rampage (RULE 702.23)

- **What:** `RulesEngine.check_rampage(attacker, blocker_count)` builds a fresh `TriggeredAbility` with a `PumpEffect` sized to `n * max(0, blocker_count - 1)` and pushes it as a real stack object, called from `declare_blockers` at the same point `BECOMES_BLOCKED` fires.
- **Files:** `game/rules_engine.py`, `game/game_engine.py`
- **Why:** Needed the same "build the effect fresh per firing" trick Ward used, since Rampage's amount depends on the specific block, which a bind-once `TriggeredAbility` can't carry.

### Firebreathing / until-end-of-turn activated pumps

- **What:** "{cost}: this creature gets ±N/±N until end of turn." and its keyword-granting sibling now MODELED with no new effect type — the existing `pump` handler plus `<cost>: <effect>` grammar covers it once the subject folds to `~`.
- **Files:** `parser/oracle/catalogue/handlers.py`

### Combat/evasion static-restriction family (RULE 508.1a/509.1a)

- **What:** "~ can't attack"/"can't block"/"can't be blocked" (and combinations) modeled as synthetic layer-6 keyword flags reusing the existing `grant_keyword`/`activation_prohibition` machinery. `attacks_if_able` (RULE 508.1a's "must attack") is enforced as a requirement check in `_enforce_attacks_if_able` at declare-attackers step exit, since attacker declaration has no natural "I'm done" signal. Also generalized the "doesn't untap" static to attached-permanent scope.
- **Files:** `game/continuous.py`, `game/game_engine.py`, `game/combat.py`
- **Bug fixed:** The self-reference fold from an earlier batch broke `_NO_UNTAP_RE`'s literal "this `<type>`" match, silently dropping 37 cards back to unclaimed; fixed to match `~`.

### Combat Blocking & Creature-vs-Creature Damage Core

- **What:** `GameEngine.declare_blockers`/`can_block`/`_step_combat_damage` handle blocked/unblocked attackers, gang blocks (lethal-first damage spread), and blockers striking back, with SBAs destroying lethally-damaged creatures. Combat/evasion keywords (flying/reach, menace, defender, haste, vigilance, first/double strike, deathtouch, trample, lifelink, indestructible, protection) are recognized off Scryfall keywords + oracle text and surfaced as board badges.
- **Files:** `game/combat.py`, `game/game_engine.py`

### Combat Statics — Qualified/Conditional Restriction Family

- **What:** A new `combat_restriction` static (a non-RULE-613 bucket, evaluated at combat time since who's defending/attacking doesn't exist yet at layer-engine time) covers blocking filters (power/type/keyword qualifiers, min/max blocker counts, the relative "greater power" filter), conditional "unless `<board condition>`" restrictions, "…alone" (both the restriction and a new aggregate `EventType.ATTACKS_ALONE` trigger), the mana-ability activation exception, and "target creature can't block this turn" as an ordinary one-shot (`CantBlockEffect`).
- **Files:** `game/effects.py`, `game/combat.py`, `game/game_engine.py`
- **Bug fixed:** `tap_for_mana` never consulted `activation_prohibited` at all, so an unqualified activation prohibition wasn't stopping mana abilities either (Null Rod).

### Combat Statics — Requirements + Multi-Block Permissions

- **What:** RULE 509.1c/d requirements ("must be blocked if able"/"all creatures able to block ~ do so") as synthetic layer-6 flag keywords, checked by `_enforce_block_requirements` on leaving declare-blockers (deliberately no full requirement-satisfaction optimizer — re-asks `can_block` per candidate instead). RULE 509.1b multi-block permissions (`GameObject.additional_blocking`, `combat.has_block_capacity`) plus `_split_blocker_damage` dividing a multi-blocker's damage evenly across its attackers.
- **Files:** `game/game_engine.py`, `game/combat.py`, `models/game_object.py`

### Combat Statics — Count-Selector Threshold + Qualified Group Scope

- **What:** `matches_object_filter` gained a `power_lt_count_selector` key (a board-count threshold re-evaluated at combat time, e.g. "power less than the number of Islands you control can't block") and `group_selector_objects` gained `min_power`/`max_power`/`min_toughness`/`max_toughness` qualifiers for group scopes like "each creature you control with power 4 or greater can't be blocked by more than one creature."
- **Files:** `game/combat.py`, `game/continuous.py`
- **Bug fixed:** `combat_restriction` used to be stamped *before* the layer-7 P/T pass, so a power qualifier couldn't see a same-pass anthem; moved to run after layer 7 instead.

### Fight (RULE 701.14, MEC-1)

- **What:** `FightEffect` is one atomic effect, not two `DealDamageEffect`s, because 701.14b's cancellation is mutual (either fighter gone/non-creature at resolution → neither deals damage) and both damage events are simultaneous. `fighter_kind` picks the subject (a real target, `None` for the source, `"attached_permanent"` for an Aura host). A shared `subgrammars.target_macro(suffix)` finally lets one regex carry two RULE 115 requirements in one clause.
- **Files:** `game/effects.py`, `parser/oracle/catalogue/handlers.py`, `parser/oracle/catalogue/subgrammars.py`

### One-Sided Fight / Damage Equal to Power

- **What:** `DamageEqualToPowerEffect` — "target creature deals damage equal to its power to target creature" (Rabid Bite) and the "when ~ dies, it deals damage equal to its power" family. Unlike a fight, the damage is one-way and the dealer needn't still be on the battlefield (RULE 608.2h last-known-information for a dies trigger).
- **Files:** `game/effects.py`

### ENG-14: "Defending Player" Resolution Sees Through Reconfigure

- **What:** `effects._defending_player_of` (shared by annihilator/afflict) now falls back to the object its source is `attached_to` before giving up, so Simian Sling's payoff correctly resolves "defending player" even after Reconfigure moves it onto a different attacking creature.
- **Files:** `game/effects.py`
- **Bug fixed:** The resolver only ever checked Simian Sling's own (never-attacking, once-reconfigured) `combat_defender` stamp, finding nobody.

### Interactive blocker declaration (RULE 509.1a)

- **What:** `legal_actions` now offers `declare_blockers`, one entry per eligible blocker carrying which attackers `can_block` legally permits it to be assigned to; the UI submits a complete block as one action, required to satisfy menace-shaped "except by N or more" restrictions.
- **Files:** `game/game_engine.py`

### ENG-15 — subset attacker selection confirmed already supported

- **What:** Verified `GameEngine.declare_attackers` has been additive (not "attack with everything, one control") since the combat-restriction family shipped; the backlog ticket describing a blocker was stale — nothing needed building, just re-verification against a 3-player pod with two independent attacker/defender declarations.
- **Files:** `game/game_engine.py`

### Exert (RULE 702.19)

- **What:** A declare-attackers-time choice (`GameEngine.declare_attackers`'s `exert` flag per attacker) rather than a resolve-time prompt; `GameObject.skip_next_untap` is a genuinely new one-shot flag consumed by the very next untap step, distinct from the sticky `skip_untap` toggle. Fires `EventType.EXERTED` for self- and player-scoped "whenever you exert" triggers. 21/36 exert cards MODELED (was 5).
- **Files:** `game/engine/combat_mixin.py`, `game/engine/turn_loop_mixin.py`, `game/combat.py`, `models/game_object.py`, `game/effect_binder.py`, `game/ability_catalogue.py`.
- **Why:** Combat Celebrant needs a `not_already_exerted` guard reading the firing event's own pre-set snapshot (not the object's live flag, already true by trigger time) to stop its own granted extra-combat from letting it exert forever.

### Mass "Attacking Creatures" Untap Selector

- **What:** `TapEffect._TAP_SELECTORS` gained `"attacking_creatures"`, reusing the existing `continuous.group_selector_objects` branch (built for an anthem) for "untap all attacking creatures." Closed Hellkite Charger.
- **Files:** `game/effects.py`, `parser/oracle/catalogue/handlers.py`.

### RULE 702.122 Crew — Real Behaviour (MEC-29)

- **What:** "Crew N" went from parser-recognized-but-inert to real behaviour for every ~238 cached "Crew N" cards at once: `ActivationCost.crew_power` (an "any number from a pool with total power >= N" cost, distinct from `tap_others`' exact count), `GameEngine._crew_pool`/`_resolve_crew_cost` (player's chosen subset validated, never trimmed; auto-pick falls back to fewest-creatures-first), `effect_binder._crew_activated_ability` building the ability as a `GrantUntilEffect`-wrapped `type_change` static so RULE 702.122a's "becomes an artifact creature" rides the ordinary layer engine, and `GameObject.crewed_by_ids` (RULE 702.122b/c, accumulating across repeat activations in a turn, reset at untap).
- **Files:** `game/costs.py`, `game/engine/activation_mixin.py`, `game/effect_binder.py`, `models/game_object.py`.
- **Bug fixed:** Vehicles had no way to carry their own printed P/T — `Card.__init__` refuses power/toughness on a noncreature and `scryfall_client` discarded a Vehicle's printed P/T entirely, so every freshly crewed Vehicle came in 0/0 and died to the SBA immediately. Fixed with dedicated `Card.vehicle_power`/`vehicle_toughness` fields (not a relaxation of the creature-only P/T invariant); required a full cache reseed.

### `"crewed_by_self"` Trigger Condition (Balthier and Fran, MEC-29)

- **What:** New RULE 603.1 group-subject trigger-condition key checking whether the acting object's live `crewed_by_ids` contains the ability's source, closing "whenever a Vehicle crewed by ~ this turn attacks."
- **Files:** `game/effect_binder.py`.

### Blocker-Side Characteristic Restriction (Void Winnower)

- **What:** New `even_mana_value` filter key on `matches_object_filter`/`cast_prohibited` plus `cant_block_self_filtered` combat-restriction kind — the first restriction that filters the *blocker's* own characteristics rather than the attacker's.
- **Files:** `game/combat.py`, `game/continuous.py`.

## Casting & Costs

### Commander tax (RULE 903.8)

- **What:** `Player.commander_casts` (instance id → count) increments on each command-zone cast; `effective_cast_cost` adds `{2}` per previous cast (floored generic), surfaced in the cast action as `commander_tax`/`effective_cost`.
- **Files:** `game/game_engine.py`, `models/player.py`

### M2 alt-cost keywords: Kicker/Multikicker, Buyback, Escape, Flashback

- **What:** All four went from parsed-but-inert to real cast/resolve behavior. `ManaCost.add` composes printed + additional costs; `GameEngine.cast_spell`/`can_cast`/`effective_cast_cost` grow a `kicked` parameter (RULE 702.33); Buyback returns the spell to hand instead of the graveyard on resolve; Flashback/Escape share one graveyard-cast gate (`_graveyard_cast_keyword`) and substitute their alternative cost for the printed one; Escape gained a dedicated cost-grammar fallback for its "exile N other cards from graveyard" clause.
- **Files:** `models/mana_cost.py`, `models/game_object.py`, `game/game_engine.py`, `game/costs.py`

### "If this spell was kicked, effect" conditional (RULE 702.33b, additional-effect shape)

- **What:** New `EffectSpec.condition` field (whitelisted to `{"kicked": bool}`) and a `ConditionalEffect` wrapper let a second sentence gate on the spell having been kicked, checked against `self.source.kicker_count`. Deliberately only the "additional effect" shape, not the "instead"-override shape (a different, unmodeled grammar).
- **Files:** `parser/oracle/spec.py`, `game/effects.py`, `parser/oracle/segmenter.py`

### {X} cost value threading through resolution

- **What:** `StackItem.x` → `RulesEngine._substitute_x` lets an effect's own amount reference the announced X value at resolution time, not just at the payment step.
- **Files:** `game/rules_engine.py`, `models/game_state.py`

### Channel / Cycling activation cost

- **What:** `ActivationCost.discard_self` models the "discard this card: effect" cost shape shared by Channel and Cycling.
- **Files:** `game/costs.py`

### Conditional Flash / instant-speed loyalty

- **What:** `AbilitySpec.conditional_flash` plus a new `game/condition_query.py` let a card gain Flash, or a planeswalker activate at instant speed, only while a board condition holds.
- **Files:** `game/condition_query.py`, `parser/oracle/spec.py`

### Impulsive look and impulsive draw

- **What:** `ImpulsiveLookEffect`/`ImpulsiveDrawEffect` plus `GameState.temp_play_permissions` model "exile the top card, you may play it this turn"-shaped effects.
- **Files:** `game/effects.py`, `models/game_state.py`

### Board-count cost reduction for a card in hand

- **What:** `continuous.self_cost_reduction_for` reads a live board count to reduce a hand card's own cast cost.
- **Files:** `game/continuous.py`

### Spell-copy on the stack (RULE 707.10)

- **What:** `RulesEngine.copy_spell` builds a fresh token `GameObject` of the spell's copiable card, controlled by the copier, keeping the original's targets/{X}, pushed above the original so it resolves first (Dualcaster Mage, Flare of Duplication). Choosing new targets for the copy is a documented MVP simplification (keeps the original's targets).
- **Files:** `game/rules_engine.py`, `game/effects.py`

### Sorcery-speed-only activation marker (RULE 602.5d)

- **What:** "Activate only as a sorcery."/"…any time you could cast a sorcery." is claimed and folded into `ActivationCost.sorcery_speed_only`, already enforced by `GameEngine.can_activate`. The subtly different "only during your turn"/"before attackers" windows are deliberately left unclaimed rather than conflated.
- **Files:** `parser/oracle/catalogue/handlers.py`, `game/effect_binder.py`

### Standing Graveyard-Cast Permission

- **What:** `GraveyardCastPermissionEffect` lets a permanent grant "you may cast spells from your graveyard" at the card's own normal mana cost — a genuine permission, not an alt-cost keyword like Flashback/Escape. Supports `max_mana_value`/`permanent_only` gates and a per-granting-object `once_per_turn` tracker. Hand-authored for Lurrus of the Dream-Den.
- **Files:** `game/effects.py`, `game/graveyard_cast.py`, `game/ability_catalogue.py`
- **Why:** Paid at the card's own printed cost rather than a keyword cost, so `effective_cast_cost` needed no change at all.

### Modal Spells "Choose One / Choose One or Both" (RULE 700.2)

- **What:** Modal blocks parse into `AbilitySpec.modes`; casting offers one `cast_spell` action per mode (the MDFC per-face pattern), and the chosen mode's effects become the spell's resolve-time effects.
- **Files:** `parser/oracle/catalogue/modal.py`, `game/game_engine.py`

### Additional Cast Costs (RULE 601.2b/601.2h)

- **What:** "As an additional cost …, sacrifice a creature/artifact/land | discard a card | pay N/X life" parses onto `AbilitySpec.additional_cost`, gates cast legality, and is paid at cast time (surviving a later counter). Reuses the activated-ability cost parser.
- **Files:** `game/costs.py`, `parser/oracle/catalogue/handlers.py`

### Modal "Choose N —" / "Choose N or More —" (RULE 700.2)

- **What:** `AbilitySpec.modes` gained a `choose` int (fixed N, Kolaghan's/Austere Command-shaped) and an `at_least` bool (variable N, Farewell-shaped). A spell offers one cast action per legal combination of modes (`itertools.combinations`, chained across sizes for `at_least`); a triggered ability picks modes iteratively, one `pending_choice` round at a time, with a `"done"` early-stop option once the minimum is met for the variable case. Effects always combine in printed order, not pick order.
- **Files:** `parser/oracle/catalogue/modal.py`, `parser/oracle/spec.py`, `game/game_engine.py`, `game/rules_engine.py`

### `{X}` Cost Threading

- **What:** `StackItem.x` (set at cast/activate time) is substituted into a resolving effect's `"x"`-sentinel `amount`/`count` fields by `RulesEngine._substitute_x`, called right before dispatch in `resolve_top_of_stack` for both flat spell effects and wrapped ability effects.
- **Files:** `game/rules_engine.py`, `parser/oracle/spec.py`

### Board-Count Cost Reduction (Delve/Affinity)

- **What:** `continuous.cost_reduction_for` gained an optional `per: <count_selector>` param for battlefield-static reductions; a new `self_cost_reduction_for` reads a `layer="cost", affects="self"` static straight off the spell card's own `static_effects` for Delve/Affinity's printed-on-the-card-itself reduction, since that never touches the battlefield scan.
- **Files:** `game/continuous.py`, `game/game_engine.py`

### Conditional Flash / Conditional Instant-Speed Loyalty Activation

- **What:** A new `AbilitySpec.conditional_flash` field gates cast/activation *legality* live against board state (e.g. "entered this turn") via a new `game/condition_query.py` module, consulted by `can_cast`/`_can_activate_loyalty`. The Wandering Emperor's "activate loyalty abilities any time you could cast an instant" is real now.
- **Files:** `game/condition_query.py`, `game/game_engine.py`, `models/game_object.py`

### Library-Top/Impulsive-Draw Permission Closeout

- **What:** A generic oracle-text static for "you may play lands [and cast spells] from the top of your library" (the parser-recognized sibling of the hand-authored `top_library_permission` entries), plus Elsha of the Infinite's own flash grant (`TopLibraryPermissionEffect.grants_flash`) and Bolas's Citadel's "pay life instead of mana cost" alternative-cost shape.
- **Files:** `parser/oracle/catalogue/static_handlers.py`, `game/top_library.py`, `game/game_engine.py`

### Interactive Sacrifice-as-Cost & Discard Choices

- **What:** An activated ability's own "Sacrifice a `<type>`" cost and looting/forced-discard both became real player choices instead of auto-picking the first candidate. `sacrifice_choice` threads through activation/mana-ability payment (`_sacrifice_cost_choice` offers the pool); `"discard"` joined the choose-object action family with `discard_choice` opening a chooser, respecting that RULE 701.8's *discarding* player (not the effect's controller) picks.
- **Files:** `game/game_engine.py`, `game/effects.py`, `services/game_session.py`

### ENG-3: Interactive Cost-Payment Sacrifice/Discard Choices

- **What:** A spell's own additional-cost "sacrifice/discard" (RULE 601.2b) and a plain "discard N cards" activation cost both gained the same choice shape as ENG-2, but as a pre-call parameter (`sacrifice_choice`/`discard_choices`) rather than a mid-call `pending_choice`, since cost payment is one synchronous call before the spell even hits the stack.
- **Files:** `game/game_engine.py`, `game/costs.py`

### Conditional cast prohibition (`cast_prohibition` static)

- **What:** The conditional sibling of the flat per-turn `cast_limit` static (RULE 601.3a), evaluated against the *casting* player's own board (e.g. "that player's lands") rather than the static's controller.
- **Files:** `game/continuous.py`
- **Why:** That evaluation-against-the-casting-player property is exactly why it can't be expressed as a layer value. Closes Lavinia's other half.

### History-scoped cast restriction (Hope of Ghirapur)

- **What:** `GameState.combat_damage_to_players_this_turn` and the `player_dealt_combat_damage_by_source` target kind answer a "history" question no live board state can answer; `PlayerCastRestrictionEffect` locks casting with no permanent behind it (self-sacrificing source). Introduced the reusable `until_next_turn_of` duration key, swept by `begin_turn`.
- **Files:** `models/game_state.py`, `game/effects.py`, `game/game_engine.py`

### Sacrificed-cost mana value tracking (Eldritch Evolution/Neoform)

- **What:** `GameObject.sacrificed_cost_mana_value` plus new `SearchLibraryEffect` params (`mana_value_from`, `extra_counters`) — `StackItem.x` only ever threads an announced `{X}`, so an additional cost's sacrificed permanent needed its own channel.
- **Files:** `models/game_object.py`, `game/effects.py`

### `pay_cost_then` — general optional-payment primitive (RULE 118.3)

- **What:** Generalized the previously energy-only optional payment into a general "pay a cost, with an 'if you don't' branch and an event-named payer" primitive, built on the shared `_can_pay_player_cost`/`_pay_player_cost` machinery ward already used. Powers Mana Vault's upkeep untap, Wandering Archaic, and both Pacts.
- **Files:** `game/effects.py`, `game/rules_engine.py`

### Bargain

- **What:** A genuinely payable optional additional cost plus an "if bargained" `EffectSpec.condition`, reusing exactly the shape Kicker's "kicked" gate already had.
- **Files:** `game/costs.py`, `game/effects.py`

### Entwine (RULE 702.42a)

- **What:** A real, separately-priced "choose all modes" upgrade offered alongside an ordinary single-mode modal cast, replacing the free `or_both` flag Tooth and Nail had been wrongly borrowing. Also fixed `buyback`/`mutate`/`bargained`/`entwine` never being forwarded through `services/game_session.py` at all.
- **Files:** `game/effect_binder.py`, `game/game_engine.py`, `services/game_session.py`
- **Bug fixed:** Tooth and Nail was getting the both-modes line for free before this (strictly better than printed); the Buyback toggle `legal_actions` already advertised was unusable since the session layer dropped the flag.

### Optional free cast offered, not forced (Tibalt's Trickery, Possibility Storm)

- **What:** `dig_until`'s new `"cast_free_window"` destination grants the same exile-cast window Rebound/Beseech use, and `ReturnUncastExiledEffect` bottoms the card at the next end step if the optional cast is declined.
- **Files:** `game/rules_engine.py`, `game/effects.py`
- **Bug fixed:** cards printed "they **may** cast that card" had been force-cast before this.

### MEC-6 — self-scoped attacking-creature cost reduction

- **What:** Added the missing `attacking_creatures_you_control` (and unscoped `attacking_creatures`) `count_selector` entry to the pre-existing but never-exercised `self_cost_reduction_for` primitive, closing Embercleave's real cost reduction, plus a matching oracle-text handler that models Ancient Stone Idol's bare "for each attacking creature" variant for free.
- **Files:** `game/continuous.py`, `game/effects.py`, `parser/oracle/catalogue/static_handlers.py`

### MEC-7 — targets-a-commander conditional flash

- **What:** `"targets_a_commander"` joined the allowed conditional-flash keys; since RULE 601.3a's timing check runs before targets are chosen (RULE 601.2c), `can_cast`/`effective_cast_cost` gained an optional `targets` param — omitted at offer-time (answers optimistically), supplied at the real cast (enforced for real).
- **Files:** `game/game_engine.py`, `game/rules_engine.py`, `parser/oracle/segmenter.py`

### MEC-4 — Strive cost escalation

- **What:** `AbilitySpec.strive_cost` rides as its own field (Strive isn't a numbered RULE 702 keyword); `effective_cast_cost` adds one full copy of the cost per target beyond the first.
- **Files:** `game/effect_binder.py`, `game/game_engine.py`, `parser/oracle/segmenter.py`
- **Why:** Lands with zero cards reaching full MODELED — every real Strive card also needs a still-unmodeled "any number of target creatures" targeting family (PAR-15), so the cost math is proven but no whole card clears the gate yet.
- **PARSER_VERSION 183 — the last mile:** `normalize._strip_unregistered_keyword_labels` (the 400+-label strip) removes "Strive —" before the segmenter sees the line, so `_STRIVE_LINE_RE`'s mandatory "Strive —" prefix never matched the normalized "This spell costs {cost} more to cast for each target beyond the first." — made optional (one line). +9: Aerial Formation, Ajani's Presence, Blinding Flare, Colossal Heroics, Consign to Dust, Cruel Feeding, Desperate Stand, Kiora's Dismissal, Rouse the Mob. `tests/test_par30_strive_prefix_optional.py`.

### Compound "Activate only as a sorcery and only if `<condition>`" (PAR-10)

- **What:** A new `ActivationCost.activation_condition` field, checked live via the same RULE 613.6 `game/static_conditions` whitelist a permanent's own "as long as" static already uses, so a condition phrase recognized for one reads identically for both. Covers hand/graveyard counts and "cast an instant or sorcery this turn" (new `cast_instant_or_sorcery_this_turn` condition kind, reset per-player each turn). Closed Jin-Gitaxias // The Great Synthesis and several more; ~150 other phrasings left as PAR-12 tail work.
- **Files:** `parser/oracle/catalogue/handlers.py`, `game/engine/activation_mixin.py`, `game/static_conditions.py`, `models/game_state.py`

### "Return this card from your graveyard to the battlefield[, tapped]" (PAR-10 discovery)

- **What:** A full-cache scan (motivated by Dread Wanderer) found 69+ cards using this shape (Reassembling Skeleton, Bloodsoaked Champion, …). `ReturnSelfFromGraveyardToBattlefieldEffect` mirrors the existing transform-return effect minus the forced flip, reusing the pre-existing `"battlefield_tapped"` destination.
- **Files:** `game/effects.py`, `game/costs.py` (`ActivationCost.graveyard_zone`)
- **Bug fixed:** `can_activate`/`legal_actions` had no branch at all for an ability sourced from the graveyard zone (only battlefield/emblem/hand were handled) — a real "MODELED but unplayable" gap, the same shape PAR-8 found for granted hand-zone abilities.

### Kicker's own announced {X} (PAR-7, RULE 702.33b)

- **What:** `GameEngine.can_cast`/`effective_cast_cost`/`cast_spell` all gained a `kicker_x` parameter, wholly independent of a spell's own `x` announcement (two separate RULE 601.2b announcements). `GameObject.kicker_x_paid` records what was actually paid; `legal_actions` and the frontend's cast UI surface a third X-input field so it's playable end to end, not just from Python.
- **Files:** `game/game_engine.py`, `game/engine/casting_mixin.py`, `services/game_session.py`, `frontend/src/js/gameBoardView.js`

### ImpulsiveDrawEffect's first oracle-text route + free-cast draw-reveal (PAR-13)

- **What:** `_exile_top_play` (Runestone Caverns' "Exile the top two cards. You may play them.") is the first parser handler reaching the pre-existing, hand-authored-only `ImpulsiveDrawEffect`. Also new: `DrawRevealCastOneFreeEffect` plus a `RulesEngine.request_choose_objects` `"cast_free"` action (Mad Wizard's Lair's "draw three, reveal, cast one free") — the first hand-zone free-cast chooser action.
- **Files:** `game/effects.py`, `game/rules_engine.py`

### "`<Type>` spells you cast cost `<N>` less/more" (PAR-12)

- **What:** The self-scoped ("you cast") sibling of the already-shipped unscoped cost-tax shape (Baral, Chief of Compliance). New `_SPELL_COST_TAX_YOU_CAST_RE`, riding the RULE 613.6 conditional-static wrapper for free; `continuous._spell_type_matches` widened to OR a two-type list.
- **Files:** `parser/oracle/catalogue/static_handlers.py`, `game/continuous.py`
- **Bug fixed:** `continuous._CARD_TYPE_ATTRS` had no entries for `"instant"`/`"sorcery"`/`"battle"` at all — every prior caller only ever needed the five permanent-type words, so a spell-type check for one of these three silently always returned `False`, meaning the whole family would have parsed but never reduced anything.

### RULE 702.33b override kicked-conditional

- **What:** "Deals N damage… if kicked, deals M damage **instead**" — a different shape from the additive "if kicked, `<effect>`" already supported. `DealDamageEffect.amount_if_kicked`/`CopyPermanentEffect.count_if_kicked`, implemented as properties (not construction-time fields) so `_substitute_x`'s generic X-sentinel substitution keeps composing with the override for an X-kicker spell.
- **Files:** `game/effects.py`

### RULE 118.3 `pay_cost_then`, first oracle-text recognizer

- **What:** "You may pay `<cost>`. If you do, draw a card." The pre-existing `PayCostThenEffect` had no oracle-text path in. Load-bearing subtlety: the trigger itself is mandatory, only the embedded cost is optional, so `_peel_optional`'s existing "don't double-gate" guard (built for the energy-only case) was widened from `{E}`-only to any single mana symbol.
- **Files:** `parser/oracle/catalogue/handlers.py`

### Colour/board-scoped cost reduction widenings (Imodane batch)

- **What:** `continuous.cost_reduction_for` gained a `spell_color` filter for the Medallion cycle; `self_cost_reduction_for`'s existing count-selector mechanism (Delve/Affinity-shaped) reused unchanged with a new unscoped `creatures_on_battlefield` selector for Blasphemous Act.
- **Files:** `game/continuous.py`

### RULE 118.9 alternative-cost family, dropped for four cards

- **What:** Force of Will/Force of Negation/Force of Vigor/Daze each print an alt-cost pitch — confirmed genuinely unbuilt (113 cache-wide cards) and tracked as its own open MEC-12 item rather than built for these four; each hand-authored castable at its real printed mana cost only. Misdirection and Deflecting Swat were investigated and deliberately left UNMODELED (their entire effect is a distinct RULE 115.4 retarget mechanism, not yet built) rather than shipped as a no-op.
- **Files:** `game/ability_catalogue.py`
- **Why:** Dropping the alt-cost rider for Misdirection/Deflecting Swat would have left a genuine no-op card, worse than staying UNMODELED — so those two were left unclaimed pending the real retarget primitive (built in the following pass).

### RULE 118.9 alternative costs — pitch-cost family + free/alt-cost UI wiring (MEC-15)

- **What:** `AbilitySpec.alt_cost` (new structured field), `GameObject.alt_cast_cost`/`alt_cast_condition`, and an `alt_cost: bool` parameter threaded through `can_cast`/`cast_spell` parallel to the existing `free`. New `ActivationCost.exile_hand_card_color` field and `free_cast_condition`'s `not_your_turn`/`your_turn` gate reused. Force of Will/Negation/Vigor/Daze hand-authored at their real alternative "pitch" costs.
- **Files:** `game/costs.py`, `parser/oracle/spec.py`, `game/engine/casting_mixin.py`, `game/game_engine.py`, `services/game_session.py`, `game/ability_catalogue.py`
- **Why:** `free=True` casting had been backend-only and unreachable from a real game session the whole time (`_offer_cast` never surfaced it) — this batch fixed that wiring gap for both `free` and the new `alt_cost` together.

### Colour-scoped and opponent-scoped spell cost tax (Casting & Costs)

- **What:** New `_SPELL_COST_TAX_COLOR_RE` parser row reaches `cost_reduction_for`'s already-built `spell_color` param (Medallion cycle); a genuinely new `affects="opponents_spells"` branch on `cost_reduction_for` plus `_SPELL_COST_TAX_OPPONENTS_RE` covers "Spells your opponents cast cost `{N}` more" (Grand Arbiter Augustin IV's third line).
- **Files:** `parser/oracle/catalogue/static_handlers.py`, `game/continuous.py`

### Activation-cost group scope by main card type (Casting & Costs)

- **What:** `activation_cost_reduction_for` gained a `card_type` group-scope branch (Training Grounds's "Activated abilities of creatures you control cost `{N}` less") alongside its existing subtype branch, switched to `_cost_static_amount` for future count-selector scaling, reached via new `_ACTIVATION_COST_REDUCTION_TYPE_RE`.
- **Files:** `game/continuous.py`, `parser/oracle/catalogue/static_handlers.py`

### "Cast spells this turn as though they had flash" parser recognition (Casting & Costs)

- **What:** New `HANDLERS` row for Emergence Zone claims the unrestricted-"spells" wording of the already-shipped `GrantFlashUntilEndOfTurnEffect` (previously reachable only via Borne Upon a Wind's hand-authored entry). Deliberately doesn't claim type-filtered variants ("sorcery spells"/"creature spells"), leaving them correctly unclaimed.
- **Files:** `parser/oracle/catalogue/handlers.py`

### Mindbreak Trap's board-count free-cast condition (Casting & Costs)

- **What:** New `opponent_spells_cast_this_turn_at_least` key on `AbilitySpec.free_cast_condition` — the family's first count-valued (not boolean) condition, reading `GameState.spells_cast_this_turn`.
- **Files:** `parser/oracle/segmenter.py`, `game/condition_query.py`

### Impulsive-draw regex widened to real printed word orders (Casting & Costs)

- **What:** `ImpulsiveDrawEffect`'s regex (RULE 601.3b) widened to accept both duration-word orders, "that card"/"those cards" pronouns, a singular "the top card," and `count_or_x_of` for a variable count (Commune with Lava). The effect itself already existed but Light Up the Stage's own real text — the card it was named after — didn't match it.
- **Files:** `parser/oracle/segmenter.py`

### `ActivationCost.only_during_your_turn` + `GainControlBySourceEffect` (Wishclaw Talisman) (Casting & Costs)

- **What:** `only_during_your_turn` (RULE 602.5d's wider sibling of `sorcery_speed_only` — legal at instant speed on your own turn only) plus `GainControlBySourceEffect` ("An opponent gains control of ~." — indefinite, source-targeted, not a RULE 115 target at all) close Wishclaw Talisman outright.
- **Files:** `game/costs.py`, `game/effects.py`, `game/ability_catalogue.py`
- **Why:** With no real "choose an opponent" chooser for a player (only `request_choose_objects` for `GameObject` candidates exists), the *next* opponent in seating order is auto-picked — unambiguous in 1v1, a documented MVP simplification for 3+ players.

### Ghostfire Slice: self-cost-reduction `active_if` + multicolour-count selector (Casting & Costs)

- **What:** `self_cost_reduction_for` now honours an `active_if` gate; `count_selector` gained `multicolored_permanents_you_control`; a general "if `<condition>`" recognizer for a spell's own cost-reduction clause was added. Hand-authored for Ghostfire Slice specifically since `segmenter.allow_spell_effect` has no static-ability shape for a true instant/sorcery to emit through yet.
- **Files:** `game/continuous.py`, `parser/oracle/catalogue/static_handlers.py`, `game/ability_catalogue.py`

### "Costs {N} less to cast if it targets a `<criteria>`" (RULE 601.2f, PARSER_VERSION 181)

- **What:** the Ajani's Response / Knockout Blow / Depower cycle (28 SOLO). Unlike Ghostfire Slice's board-state `active_if`, this discount is gated on the spell's own *chosen target*. `cost_reduction` gained a `reduce_if_targets` param (a criteria dict); `continuous.self_cost_reduction_for` gained a `targets` parameter and applies the discount only when one resolved target matches (`_obj_matches_target_criteria` → `combat.matches_object_filter`, which grew a `tapped` boolean key). `game/engine/casting_mixin.py`'s `_adjust_cost` / `effective_cast_cost` thread `targets` through (RULE 601.2c precedes 601.2f, so the real cast knows them); `targets is None` at every offer-time caller treats the discount as available (best case, so affordability isn't understated — same as `help_pay`/kicker). Parser: `static_handlers._targets_reduction_criteria` recognises "it targets a `<card type>`" plus an optional tapped / attacking / blocking / colour qualifier, tried before the board-condition path.
- **Files:** `game/continuous.py`, `game/effects.py` (`cost_reduction` factory), `game/engine/casting_mixin.py`, `game/combat.py`, `parser/oracle/catalogue/static_handlers.py`. `tests/test_par30_cost_less_if_it_targets.py`.
- **v182 widened the criteria vocabulary:** `_targets_reduction_criteria` parses the phrase word by word — a bare subtype / "X or Y" pair, "you control" / "you don't control", "…token", "…with `<keyword>`", "legendary", and "a `<x>` spell" (stack target). `_obj_matches_target_criteria` grew `legendary` / `is_token` / `controller` handling via a threaded `caster_id`. +10 — Grow Extra Arms, Mystical Dispute, Out of Air, Price of Fame, Run Over, Savage Stomp, Swampsnare Trap, This Town Ain't Big Enough, Hunter's Mark, Mascot Interception.
- **Still open:** a mana-value cap (reanimation-spell targets — No One Left Behind, Revoke Demise) and a "…with a +1/+1 counter on it" clause (Titanic Brawl).

### Eye of Ugin: "colorless" search criterion + spell-subtype cost filter (Casting & Costs)

- **What:** `models.card_query`'s `color` key gained a `"colorless"` special case (empty colour-identity check, search-only); `continuous.cost_reduction_for` gained a `spell_subtype` filter (a creature subtype, orthogonal to `spell_type`), composed by AND with `spell_color="colorless"`. Hand-authored (the combined shape is a singleton).
- **Files:** `models/card_query.py`, `game/continuous.py`, `game/ability_catalogue.py`

### Spell-side self-cost-reduction reaches `static_effect_specs` (Casting & Costs)

- **What:** An instant/sorcery's own "this spell costs `{N}` less to cast if/for each…" line had never reached `static_effect_specs` at all (only permanents did). Fixed with a narrowly-scoped addition to the `allow_spell_effect` branch that tries `static_effect_specs` first and only accepts a pure `cost_reduction`/`affects="self"` result.
- **Files:** `parser/oracle/segmenter.py`

### "Your opponents can't cast spells during your turn" trailing phrasing (Casting & Costs)

- **What:** `cast_prohibition`'s existing `scope="opponents"` + `active_if={"kind": "your_turn"}` already expressed this; only the *trailing*-phrasing parser row (`_CANT_CAST_OPPONENTS_YOUR_TURN_RE`) was missing (Voice of Victory, Dragonlord Dromoka, A-Teferi, Jennifer Walters).
- **Files:** `parser/oracle/catalogue/static_handlers.py`

### Snapback/Pyrokinesis: pitch-cost oracle-text handler (Casting & Costs)

- **What:** MEC-15's pitch-cost family (`AbilitySpec.alt_cost`) had no oracle-text recognizer at all — every card besides the four hand-authored Force-of-Will-shaped ones stayed unclaimed. New `_ALT_COST_EXILE_HAND_COLOR_RE` reaches 14 cache-wide cards; scoped to the instant/sorcery `allow_spell_effect` branch only.
- **Files:** `parser/oracle/segmenter.py`

### Remaining RULE 118.9 "pitch" cost shapes (Casting & Costs)

- **What:** Three new `ActivationCost` fields — `return_to_hand_count` (Gush), `sacrifice_filter` (a `matches_object_filter`-shaped dict, Flare of Denial, gaining a new `nontoken` key), and the already-existing `sacrifice`/`sacrifice_count` reused for alt-cast — plus a new `condition_query` kind `control_land_type` (Snuff Out). Also wired `cost.mana` into `_can_pay_alt_cast_cost`/`_pay_alt_cast_cost` for the first time, closing the plain "pay `<mana>` rather than the mana cost" Bringer-cycle shape at the engine level.
- **Files:** `game/costs.py`, `game/engine/casting_mixin.py`, `game/condition_query.py`, `parser/oracle/spec.py`
- **Bug fixed:** `_matches_sacrifice_type`'s fallback for an unrecognized cost word matched *any* permanent instead of doing a real subtype check — harmless until a card named a bare subtype ("sacrifice a Mountain"); and `_can_pay_alt_cast_cost`/`_pay_alt_cast_cost` never read `cost.mana` at all, always routing through the mana-skipping `cast_without_paying`.

### "Sacrifice an artifact or creature" additional-cost sentinel (Casting & Costs)

- **What:** New `additional_cost` sacrifice sentinel `"artifact_or_creature"`, plumbed through the whitelist and all three `_matches_*` copies. +16 cards (Deadly Dispute, Costly Plunder, Artillerize).
- **Files:** `parser/oracle/spec.py`, `game/costs.py`

### Submerge's compound free-cast condition (Casting & Costs)

- **What:** New named boolean key `opponent_controls_forest_and_you_control_island` on `AbilitySpec.free_cast_condition` — a fixed compound condition, not a general "controls X and Y" combinator, matching `control_commander`'s own "one named condition" precedent.
- **Files:** `game/condition_query.py`, `parser/oracle/spec.py`

### `grant_graveyard_cast_permission_this_turn` — Past in Flames (Casting & Costs)

- **What:** The primitive already existed (built for Backdraft Hellkite); Past in Flames just needed an oracle-text recognizer for "Each instant and sorcery card in your graveyard gains flashback until end of turn."
- **Files:** `parser/oracle/catalogue/handlers.py`

### Talon Gates of Madara: hand-zone "put onto the battlefield" activated ability (Casting & Costs)

- **What:** `PutSelfOntoBattlefieldFromHandEffect` + `ActivationCost.hand_zone` — `graveyard_zone`'s hand-zone sibling, auto-stamped onto a matching ability's cost by `effect_binder.bind_ability`, threaded through `can_activate`'s zone-legality branch and the existing hand-zone-ability scan loop.
- **Files:** `game/effects.py`, `game/costs.py`, `game/effect_binder.py`

### MEC-20: RULE 601.2f "Expertise" free-cast-from-hand cycle (Casting & Costs)

- **What:** `FreeCastFromHandEffect` opens a `request_choose_objects` `"grant_free_cast"` action that only *arms* the picked hand card's `free_cast_instance_ids` entry rather than casting it immediately, letting the caster cast it through the ordinary `legal_actions` cast option afterward (full targeting/modal choices intact). Covers a literal cap, the `"x"` sentinel (Electrodominance), and a board-read cap via `count_selector` (Epistolary Librarian). Closed Sram's/Yahenni's Expertise and Epistolary Librarian outright.
- **Files:** `game/effects.py`, `game/rules_engine.py`, `parser/oracle/catalogue/handlers.py`
- **Why:** RULE 601.2f/718 technically require the free cast to happen as the Expertise spell resolves, but the engine has no "pause mid-resolution for a nested cast+targeting cycle" primitive — a same-turn window is offered instead, strictly more permissive than print.

### MEC-24: targeted flashback grant (Casting & Costs)

- **What:** `GameState.temp_flashback_grants` (`instance_id -> cost`), a per-graveyard-card marker (mirroring `temp_play_permissions`' shape); `GrantFlashbackToTargetEffect` stamps it at resolution, defaulting cost to the target's own mana cost. Consulted by the existing Flashback cost/cast-zone/exile-after-cast machinery with no new casting code — closes Recoup/Snapcaster Mage/Slickshot Lockpicker and others.
- **Files:** `game/effects.py`, `models/game_state.py`, `game/engine/lands_mixin.py`, `game/engine/casting_mixin.py`

### Alt-Cost Family Unconditional Gate (Bringer Cycle)

- **What:** The whole RULE 118.9 alt-cost family (`pitch`/`sac_filter`/`sac_type`/`ret_two`/`pay_if`/`pay_mana`) was pulled out of `allow_spell_effect`'s gate and made unconditional so creature spells reach it too, without widening `_is_spell` (which broke 88 tests by exposing unrelated bare-imperative rows to creature cards). 4/5 Bringers now MODELED.
- **Files:** `parser/oracle/gate.py`.

### Snuff Out's Alt-Cost Siblings

- **What:** Alt-cast payment combinations — a board condition paired with a non-mana payment, mana-plus-return-to-hand (Borderpost cycle), and counted sacrifice beyond one — all reused existing `_can_pay_alt_cast_cost` fields. The one real new piece: `tap_others` (RULE 602.1) wired into alt-cast payment for the first time, matching a bare main type via `continuous.has_card_type`; `_return_to_hand_count_candidates` gained a `"basic land"` qualifier.
- **Files:** `game/rules/casting_mixin.py`, `game/continuous.py`.

### Destroy/Exile-Then-Controller-Digs (Polymorph/Transmogrify)

- **What:** `DestroyExileThenControllerRevealCreatureEffect` destroys/exiles a target creature, then that creature's own controller (read before the RULE 400.7 zone change) digs their own library until a creature card, onto the battlefield. `dig_until` gained `rest_destination="library_shuffled"` (an actual reshuffle).
- **Files:** `game/effects.py`, `game/rules_engine.py`.

### Cost Floor (Trinisphere)

- **What:** `continuous.cost_floor_for` + `StaticAbility.min_generic`, kept structurally apart from the existing additive cost-reduction/increase net (two floors take the max, not the sum); applied against the cost's real `converted_mana_cost`, not the generic component alone.
- **Files:** `game/continuous.py`, `game/effects.py`.
- **Bug fixed:** A first attempt compared the floor against `ManaCost.generic_amount()` (just generic pips), producing `{3}{B}` (value 4) under a floor of 3 instead of the card's own reminder-text example `{2}{B}` (value 3); fixed against `converted_mana_cost`, and the now-unused `generic_amount()` was removed.

### Standing Exile-Cast Permission (Lukka's +1)

- **What:** `GameState.exile_cast_condition` + `GameEngine._has_conditional_exile_permission` — a standing, never-turn-swept exile-cast grant (unlike every existing `temp_play_permissions` turn-windowed grant), checked live every time via `static_conditions.condition_holds`. New `planeswalkers_you_control_of_type_<x>` count selector backs its condition.
- **Files:** `models/game_state.py`, `game/engine/casting_mixin.py`, `game/static_conditions.py`.

### Reveal-Then-Free-Cast-If-Match (Powerbalance)

- **What:** `RevealTopThenFreeCastIfMVMatchEffect` reuses `request_choose_objects`'s existing `"cast_free"` action for the interactive "you may cast" half; the "you may reveal" half is a documented simplification to unconditional.
- **Files:** `game/effects.py`.

### MEC-30 Pass 5: Three Cost-Shape Gaps (Penance, Seasoned Tactician, Bone Mask)

- **What:** `ActivationCost.put_hand_card_on_library` (Penance's "put a card from your hand on top of your library" cost, with chosen-or-auto-pick plumbing mirroring `_resolve_discard_cost`) plus a new `recipient="any"` on the prevention chooser for its unscoped "prevent that damage" (protects whoever the chosen source hits, not the caster). `costs.exile_top_of_library` widened from a bare bool to a real printed count (Seasoned Tactician), with all four call sites checked individually. New `apply_prevent_rider` kind `"exile_top_of_library_scaled"` (Bone Mask) — `mill`'s exile-instead-of-graveyard sibling, looping `RulesEngine.exile` directly since no existing primitive exiles a flat count off the top in one call.
- **Files:** `game/costs.py`, `game/engine/activation_mixin.py`, `game/rules_engine.py`, `game/mana_potential.py`.

## Counters

### "Enters with N counters" replacement effect (RULE 614.1-style)

- **What:** "~ enters the battlefield with N/X `<counter-type>` counters on it." parses (`entry_counters_condition`/`entry_counters`, mirroring the tapped-entry split) and resolves via `RulesEngine._apply_entry_counters(obj, x_paid=0)`, called before the object joins the battlefield so triggers/continuous passes see the counters immediately. Works for any counter kind and the variable "X" (RULE 107.3c).
- **Files:** `parser/oracle/catalogue/counters.py`, `game/ability_catalogue.py`, `game/rules_engine.py`

### Bare "proliferate" recognition (RULE 701.30)

- **What:** `ProliferateEffect` already existed and was registered but had no oracle-text handler at all; one handler for bare "proliferate." closes it, including multi-sentence bodies whose only other clause an earlier batch had already unlocked. "proliferate twice"/"...X times" stay unclaimed (no repeat-count parameter exists).
- **Files:** `parser/oracle/catalogue/handlers.py`

### Kicked-conditional entry counters

- **What:** "if ~ was kicked, it enters with N counters on it" and its Multikicker-scaled "…for each time it was kicked" sibling reuse the existing entry-counters machinery via new `kicked_gate`/`kicked_scale` condition-dict keys resolved against `GameObject.kicker_count`.
- **Files:** `parser/oracle/catalogue/counters.py`, `game/rules_engine.py`

### "Remove a Counter From ~" Activation Cost (RULE 701.19/602.1)

- **What:** The cost-parsing/payment machinery already existed; the gap was `segmenter.py`'s `_COST_LOOKS_REAL` sniff not recognizing "remove … counter" as a real cost when it was the ability's *entire* cost (no mana/{T} alongside it). One regex fix unlocked Triskelion end to end. Scope: fixed-count only — variable counts stayed unclaimed at ship time.
- **Files:** `parser/oracle/segmenter.py`, `game/costs.py`

### Variable-Count "Remove a Counter" Activation Cost

- **What:** `ActivationCost.remove_counters` gained `REMOVE_COUNTERS_X`/`REMOVE_COUNTERS_ANY` sentinels for "remove X counters" (32 real cards) and "remove any number of counters" (23 cards), paid against the ability's `{X}`; a new `_max_x_for_activation_cost` merges the mana-`{X}` bound with the counters-available bound.
- **Files:** `game/costs.py`, `game/game_engine.py`
- **Bug fixed:** `_REMOVE_COUNTERS_RE`'s count group already matched the literal word "x" but silently resolved it to `1`.

### "Remove All Counters" Effect

- **What:** `RemoveCountersEffect` (untargeted board-wide or `target_kind="permanent"`) strips every counter of every kind via `context.add_counters` with a negative amount per kind, so a counter-removed trigger still fires correctly (Vampire Hexmage/Oblivion Stone/Aether Snap-shaped).
- **Files:** `game/effects.py`

### "Proliferate Twice / N Times"

- **What:** `ProliferateEffect` gained a `times` param and parser recognition of the literal word "twice" or a digit-folded "N times" (normalize doesn't fold "twice" itself).
- **Files:** `game/effects.py`, `parser/oracle/catalogue/handlers.py`

### Kicked-Gated Entry Counters + Granted Keyword

- **What:** RULE 702.33b's "…and with `<keyword>`" compound entry-counter clause: both kicked entry-counter regexes gained an optional trailing keyword clause, and `RulesEngine._apply_entry_counters` grants the keyword onto `intrinsic_keywords` under the same kicked gate as the counters.
- **Files:** `parser/oracle/catalogue/counters.py`, `game/rules_engine.py`

### "Remove Up to N Counters from Target Permanent"

- **What:** `RemoveCountersEffect` gained a `max_count` param that opens an interactive amount-then-kind chooser (`request_remove_counters_choice`/`_continue_remove_counters`) rather than resolving synchronously — modeled on the "pause mid-resolution" idiom, since no existing chooser combined an amount pick with a kind pick (Glissa Sunslayer/Heartless Act-shaped).
- **Files:** `game/effects.py`, `game/rules_engine.py`

### Player-Counter Primitive

- **What:** `RulesEngine.add_player_counters`/`Player.add_counters` — the engine's first effect-driven way to add poison/energy/experience counters to a *player*, mirroring `add_counters` exactly (through `apply_replacements`, `is_player=True`). Built to land Innkeeper's Talent.
- **Files:** `game/rules_engine.py`, `models/player.py`

### RULE 122 Energy `{E}` Activated-Ability Cost Pips

- **What:** `ActivationCost.pay_energy` handles both repeated-pip ("Pay {E}{E}{E}{E}") and spelled-out-count ("Pay eight {E}") forms, charged via `add_player_counters(player, -amount, "energy")` — previously silently discarded by the cost parser's brace loop.
- **Files:** `game/costs.py`

### Energy Resolve-Time Optional Payment

- **What:** "You may pay {E}{E}. If you do, `<effect>`." (Aether Chaser-shaped) — `pay_energy_then`/`PayEnergyThenEffect` opens an interactive yes/no choice at resolution (modeled on the shock-land pay-life idiom); only untargeted follow-ups (create-token/gain-life/draw) are modeled. Also added `get_energy` production recognition.
- **Files:** `game/effects.py`, `game/rules_engine.py`

### Rad counters (RULE 728)

- **What:** A fourth source-less inherent trigger (alongside Monarch/Initiative) mills cards equal to the active player's live rad-counter count each main phase, loses life for each nonland milled, and removes that many rad counters; reuses `Player.counters` with zero new model field, plus new generic "get N/X rad counters" oracle-text grammar and per-card grants (Feral Ghoul/Glowing One/Infesting Radroach).
- **Files:** `game/rules_engine.py`, `game/effects.py` (`RadiationMillEffect`, `AddPlayerCountersEffect`), `parser/oracle/catalogue/handlers.py`
- **Why:** RULE 728.1 makes rad counters controlled by the active player regardless of who holds them (RULE 113.8 exception), so no designation/holder indirection was needed.

### Rad counters — deferred-gap closure batch

- **What:** Closed all 11 previously-deferred rad-counter cards with real behaviour: new trigger-subject grammar (enchanted/equipped-creature verbs, tribal "self-or-group" subjects), a target-based "if that player is(n't) you" intervening-if, compound "~ verb1 or verb2" multi-event triggers, half-X rounding amount sentinels, a counter-scaled activation-cost reduction, a land's optional-bonus-tapped-entry choice, a damage-prevention-plus-counter-conversion replacement, a third `enter_replacement` "named mode" family, the aggregate `EventType.PLAYER_ATTACKED` event, a recurring bounded-duration player-scoped trigger, and a "return dies as a different synthetic permanent type" primitive.
- **Files:** `parser/oracle/segmenter.py`, `game/effects.py`, `game/rules_engine.py`, `game/continuous.py`
- **Why:** Per the project's "no half-implementations" rule — a second deferral of any of these had to be hand-authored this round rather than rolled forward a third time.
- **Bug fixed:** `mana_abilities.py`'s "any one color" parsing always silently discarded a printed fixed count > 1 down to 1 mana (also affected the real card Jeweled Lotus, whose own test had asserted the buggy behavior).

### Kicked X-scaled entry counters (PAR-7)

- **What:** "If this creature was kicked, it enters with X +1/+1 counters" — X being Kicker's own paid amount (`kicker_x_paid`), not a fixed count. Widened the kicked-gate amount regex to accept "x" and tag the result `kicked_x_scale`, read by `_apply_entry_counters`.
- **Files:** `parser/oracle/catalogue/counters.py`, `game/rules_engine.py`

### Named counter kinds — "spore" (PAR-12, RULE 122.1a)

- **What:** `AddCountersEffect.kind` was already a free string; only "put a counter on X" recognition was hard-restricted to `+1/+1`/`-1/-1`. New `_add_named_counter` handler + `_NAMED_COUNTER_KINDS` whitelist (currently just "spore"), kept as a separate handler row so a named counter can't get silently mis-typed as a P/T counter.
- **Files:** `parser/oracle/catalogue/handlers.py`
- **Bug fixed:** The refactor that split this handler out initially dropped the original P/T handler's `_optional_param` call, silently breaking "put a +1/+1 counter on **up to one** target creature" — caught by the full pytest suite, not by coverage measurement, which only tracks MODELED/UNMODELED status, not emitted-param correctness.
- **v186 — widened to 29 kinds (+53 cards):** `_NAMED_COUNTER_KINDS` gained charge, oil, storage, verse, ki, page, plan, soul, fuse, depletion, flood, bounty, brick, study, plague, doom, growth, point, infection, hatchling, pressure, slime, tide, ice, flame, hour. Selection rule: each kind was grepped across `game/` + `models/` and confirmed to have **no reader** — it's a pure card-text-driven count tracker (the card's own "remove N `<kind>` counters: …" ability does all the consuming), so the generic `AddCountersEffect.kind` free-string models it with nothing missing. Kept a fail-closed frozenset rather than a bare `[a-z-]+` because three families would half-model if they slipped through: RULE 122.1e **keyword counters** (`flying`/`indestructible`/`menace`/… — the layer engine has no keyword-counter reader), **subsystem** counters the engine keys off by name (`age` cumulative-upkeep, `time` vanishing/fading, `level` leveler, `loyalty` planeswalker, `lore` Saga, `rad`, `energy`), and **replacement-carrying** ones (`stun` skip-untap, `shield`). Closes the counter-body gap that ITER 24's "you attack a player" trigger recognition left on Long-Range Sensor; also the mana-battery cycle, Coretapper, Firemind's Research, the storage-land cycle. `tests/test_par30_named_counter_kinds_widened.py`.

### Counter/Token-Creation Count-Amount Resolver Wiring (MEC-27)

- **What:** `AddCountersEffect` gained `amount_from_count_selector` (mirroring `DealDamageEffect`) with a new `add_counters_devotion` parser row for "put X counters on `<target>`, where X is `<DEVOTION>`" (closed Leyline Invocation, Strength Bobblehead); `CreateTokenEffect`'s existing token-count-devotion row was widened from a narrow subtype-only alternation to the full `DEVOTION` fragment.
- **Files:** `game/effects.py`, `parser/oracle/catalogue/handlers.py`.
- **Bug fixed:** `devotion_selector`'s `count_subtype` catch-all guessed `creatures_you_control_of_type_<word>` for any bare noun, silently reading 0 for a non-creature subtype like "Bobbleheads"/"Shrines"; fixed with a denylist rather than un-modeling correctly-scoped cards.

## Card Types & Structures

### Loyalty / planeswalker abilities (RULE 606)

- **What:** `ActivationCost.loyalty` parses signed `[±N]` costs; planeswalkers enter with printed starting loyalty; activation is gated to sorcery speed + once-per-turn; damage removes loyalty; the 0-loyalty SBA (RULE 704.5i) sends the planeswalker to the graveyard.
- **Files:** `game/costs.py`, `game/game_engine.py`, `models/card.py`

### Aura / Equipment attachment resolution (RULE 303/301.5)

- **What:** An Aura attaches to its cast-time target on resolution (fails to attach → straight to graveyard); Equip/Fortify/Reconfigure are sorcery-speed activated abilities, each restricted to their legal attachment targets (creatures/artifacts, lands for Fortify, creatures for Reconfigure). RULE 704.5m/n: an Aura's host leaving sends it to the graveyard, an Equipment/Fortification just becomes unattached. RULE 702.151b: a Reconfigure permanent stops being a creature while attached. The attached buff flows through the layer engine via `affects="attached_permanent"`.
- **Files:** `game/rules_engine.py`, `game/targeting.py`, `game/continuous.py`
- **Bug fixed:** `_attachment_legal` had no `fortify` branch, so Fortify wrongly offered any permanent instead of narrowing to lands.

### Commander zone-replacement choice (RULE 903.9a/9b)

- **What:** Replaced an unconditional command-zone diversion with a real owner-chosen `pending_choice`, split by mechanism: 903.9a (graveyard/exile, a state-based action — the commander actually lands there first, then a `commander_zone` choice opens on the next SBA pass) and 903.9b (hand/library, a replacement effect — object lands in hand as the declined default, choice opens immediately to redirect). Also flagged from `mill()`/`discard()`'s direct graveyard writes.
- **Files:** `game/rules_engine.py`, `game/game_engine.py`
- **Why:** Previously `exile()` skipped the diversion entirely on an incorrect docstring claim that 903.9 was graveyard/death-only, and `return_to_hand()` offered no diversion at all.

### Graveyard-Sourced "Return This Card Transformed"

- **What:** `ReturnFromGraveyardTransformedEffect`/`RulesEngine.return_from_graveyard`'s new `transformed` param flips a card onto its back face right after being placed from the graveyard — the graveyard-sourced sibling of the existing exile-and-return-transformed effect (Fable of the Mirror-Breaker-shaped).
- **Files:** `game/effects.py`, `game/rules/*_mixin.py`

### Token Lifecycle (RULE 704.5d)

- **What:** `GameObject.is_token` plus a new SBA, `RulesEngine._remove_stranded_tokens`, implements RULE 704.5d/111.7-8: a token that leaves the battlefield reaches its zone long enough to fire dies/leaves triggers, then ceases to exist. Both exile and destroy funnel through it.
- **Files:** `game/rules/sba_mixin.py`, `models/game_object.py`

### Enters-Tapped Clause Recognition (RULE 614.1)

- **What:** Tap-condition recognition moved to a pure `parser/oracle/catalogue/lands.py` handler with `game/ability_catalogue.land_tap_condition` delegating to it, and gained two new engine-side kinds: `unless_opponents` (Battlebond lands) and basic-land `unless_count`.
- **Files:** `parser/oracle/catalogue/lands.py`, `game/ability_catalogue.py`

### Phasing (RULE 702.26)

- **What:** A new `GameObject.phased_out` flag, filtered out of `GameState.permanents()`/`permanents_controlled_by` (the sanctioned battlefield-reading choke point) so combat, SBAs and static-ability scans treat a phased-out permanent as nonexistent for free. `PhaseOutEffect` detaches any attached Equipment/Aura on phase-out; `_step_untap` gained the phase-in sweep. Scoped to Robe of Stars' single-permanent case, not the full "phase out together" attachment-chain family.
- **Files:** `game/rules_engine.py`, `game/game_engine.py`, `models/game_state.py`

### ENG-6/ENG-10: Copy-of-a-Copy (RULE 707.2)

- **What:** `become_copy` now sets `obj._front_card = obj.card` right after the copy mutation, so a later copy of an already-copied object reads its current form rather than the pristine original.
- **Files:** `game/copy_mechanics.py`
- **Bug fixed:** `become_copy` read a copy target's copiable values off `_front_card` (set once at `__init__`, never updated), so a copy of an already-copied permanent copied the original card underneath instead of the copied form — RULE 707.2 silently unmet.

### ENG-7: Token's Own `enter_as_copy` Choice

- **What:** `create_token`'s build loop is now a recursive continuation (`_next(remaining)`) that pauses on a token's own `enter_as_copy_effects` (RULE 614.1c/614.12) before battlefield entry, then resumes the rest of the batch — the same continuation-passing idiom the ordinary cast-permanent path already used, generalized to a multi-token loop.
- **Files:** `game/rules_engine.py`
- **Bug fixed:** A token copy of an enter-as-copy creature (e.g. a token copy of Clever Impersonator) previously entered as itself, silently skipping its own replacement effect.

### Battles (RULE 310)

- **What:** The whole card type from scratch: defense as counters rather than a separate stat (seeded on entry alongside planeswalker loyalty), a third `"battle"` defender kind for attacking, and RULE 310.8d's protector (the defending player for the battle, distinct from its controller — a Siege can be attacked by its own controller) chosen interactively as it enters.
- **Files:** `models/card.py`, `models/game_object.py`, `game/rules_engine.py`, `game/game_engine.py`
- **Why:** Defeat (RULE 310.11b) is noticed by the SBA pass rather than at any single counter-removal site, so every route to zero defense (combat, burn, anything) reaches it, with a `battle_defeat_triggered` latch preventing re-firing; a defeated Siege is kept alive long enough for its own trigger to exile-and-transform it, reusing the Rebound-style free-cast window.
- **Bug fixed:** Adding `Card.defense` changed the model schema hash, forcing a full ~34k-card cache reseed (no network needed — rebuilt from `RawCardStore`); the frontend's `defenderPayload` had been branching on `kind === 'planeswalker'` and would have mis-sent a battle as a player, now branches on which key the spec carries.

### Saga chapter abilities (RULE 714.2d)

- **What:** Saga chapter lines ("I, II — effect") now resolve as ordinary triggered abilities (`EventType.SAGA_CHAPTER`) through the existing one-shot effect handler table, via a shared roman-numeral grammar. Also added a group ("creatures you control") one-shot pump for chapter-III anthem-style effects (e.g. History of Benalia).
- **Files:** `parser/oracle/catalogue/saga.py`, `game/rules_engine.py`, `game/effect_binder.py`
- **Why:** Chapters flow through the ordinary triggered-ability pipeline so targeting/"you may"/interactive ordering all work for free, instead of bespoke Saga-specific machinery.

### Saga timing fixes + Read Ahead (RULE 714.3b/714.3c)

- **What:** Fixed the lore counter to be added at precombat main phase begin (not the draw step); narrowed the final-chapter sacrifice check to only wait on this Saga's own chapter trigger, not any unrelated stack item; implemented Read Ahead (RULE 702.155) — choosing a starting chapter 1..final skips every lower chapter for good.
- **Files:** `game/rules_engine.py`, `game/game_engine.py`
- **Why:** RULE 702.155a means skipped chapters are gone for good, not delayed — an earlier draft firing chapters 1..N in sequence was wrong and corrected before shipping.
- **Bug fixed:** the sacrifice check keyed off "is the whole stack empty," wrongly delaying a finished Saga's sacrifice whenever any unrelated spell/ability sat on the stack.

### Class (RULE 716) and Leveler (RULE 711)

- **What:** Multi-line block structures — Leveler's mutually-exclusive `LEVEL` tiers and Class's cumulative sequential levels — parsed via a new pure grammar module, with a sorcery-speed-only activation gate not tied to planeswalkers.
- **Files:** `parser/oracle/catalogue/levels.py`, `game/costs.py`, `game/effect_binder.py`
- **Why:** Needed the first genuinely general RULE 613.6 "as long as" conditional-static primitive (`min_level`/`max_level`/`level_counter`, gating on the ability's own source's counter), reused later for other conditionals.
- **Bug fixed:** a Leveler's whole printed text (all tiers) is one `oracle_text`/`keywords` blob in Scryfall data, so a tier-only keyword (e.g. Kargan Dragonlord's Level 7+ flying/haste) was being treated as always-on by both the intrinsic-keyword bind and `combat.keywords_of`; both now cross-check against the pre-`LEVEL` base text.

### Class trigger-wrapper recognition

- **What:** Recognized "When this Class becomes level N, `<effect>`." as a real one-shot trigger (fires once, doesn't re-fire on a higher level) and "When this Class enters, `<effect>`." by widening self-reference folding to include "this Class."
- **Files:** `parser/oracle/catalogue/levels.py`, `parser/oracle/normalize.py`
- **Bug fixed:** both trigger wrappers were silently failing to parse at all before this — "becomes level N" had no recognizing regex, and normalize's self-reference folding had deliberately excluded "this Class" (only "this Saga" had dedicated parsing).

### DFC transform + day/night (RULE 712.8, 731, 702.145)

- **What:** `RulesEngine.transform_permanent` actually flips a permanent's face and rebinds catalogue-derived abilities (`GameObject.transform()` alone never did); a new "transform" one-shot effect makes "[0]: Transform ~." or "whenever ~ attacks, transform it." fully oracle-modeled; RULE 731 day/night is tracked via `GameState.day_night`/`spells_cast_this_turn`, checked at untap and SBA cadence.
- **Files:** `game/rules_engine.py`, `services/game_session.py`, `services/replay.py`
- **Bug fixed:** Replay's deserializer had bound abilities *before* transforming (backwards order); daybound/nightbound recognition needed a fresh oracle-text cross-check since `Card.back_face()` carries no separate keywords array.
- **PAR-30 — the pre-daybound werewolf check (PARSER_VERSION 139, +27):** the *legacy* Innistrad werewolf template ("At the beginning of each upkeep, if no spells were cast last turn, transform ~." front → werewolf / "…if a player cast 2 or more spells last turn, transform ~." back → human) was a long-standing "deliberately deferred, superseded by RULE 731" gap. Now modeled as a RULE 603.4 intervening-if: two `segmenter.parse_effect_body` leading-if handlers wrap the `transform` spec with `ConditionalEffect`'s new `no_spells_cast_last_turn` / `two_or_more_spells_cast_last_turn` condition keys (whitelisted in `spec._ALLOWED_CONDITION_KEYS`). Both read `GameState._last_turn_spell_count` — the previous turn's active player's final cast count, captured at turn rotation by `begin_turn`, the *same field* `apply_day_night_turn_check` already uses for the daybound/nightbound successor mechanic, and the condition never holds on turn 1 (`_last_turn_player_id is None`), matching that check's own turn-1 no-op. `ConditionalEffect` gating a `transform` (checked at resolution) is the standard intervening-if simplification. Closes the whole 27-card DFC werewolf cycle (Reckless Waif, Kruin Outlaw, Mayor of Avabruck, Mondronen Shaman, Village Messenger, Instigator Gang, Call of the Full Moon's Aura form, …). The legacy `test_batch9_conditional_transform_family.py::test_legacy_werewolf_no_spells_cast_stays_unclaimed` negative assertion was flipped to a positive one; full behaviour test in `tests/test_par30_werewolf_transform.py`.

### Adventure and Split/Fuse casting (RULE 715, 709)

- **What:** Both card types are now actually castable, generalizing the MDFC back-face casting machinery to a third `"fuse"` face value; Adventure's creature snapshot is stashed through resolution and exiled (not graveyarded) after its instant/sorcery half resolves. Fuse builds a synthetic merged `Card` with concatenated mana cost/oracle text rather than a new dual-binding architecture.
- **Files:** `models/card.py`, `game/game_engine.py`, `game/rules_engine.py`
- **Why:** `ManaCost.parse` already sums every `{N}` token regardless of source, and Scryfall's `cmc` is already the two halves' sum, so string concatenation alone *is* "pay both costs" — no new payment logic needed.

### Prepared cards (RULE 722)

- **What:** A permanent "becoming prepared" spawns a token copy of just its inset prepare-spell into exile, castable only while the source stays prepared and on the battlefield — distinct from Adventure/Split despite sharing the two-face frame, since the second face can never be cast from hand.
- **Files:** `game/effects.py` (`BecomePreparedEffect`), `game/rules_engine.py` (`make_prepared`), `services/scryfall_client.py`
- **Why:** Reuses the existing RULE 704.5d "token disappears when stranded" SBA (scoped by checking the source is still prepared and on the battlefield) rather than a parallel expiry mechanism.

### Token copies and "becomes a copy of" (RULE 707)

- **What:** `RulesEngine.copy_permanent` creates a token clone of a target's copiable card; "becomes a copy of target permanent" is a genuine layer-1 continuous effect (Vesuvan Shapeshifter).
- **Files:** `game/rules_engine.py`, `game/effects.py`

### Delver-shaped conditional transform + MDFC commander casting

- **What:** `RevealTopThenTransformEffect` implements "look at the top card; if it's a[n] `<type>`, transform ~." as a general, criteria-parameterized primitive (Delver of Secrets hand-authored on it); separately, `legal_actions`' command-zone loop now offers an MDFC commander's back face for casting (RULE 903.6), matching what the hand-cast loop already did.
- **Files:** `game/effects.py`, `game/ability_catalogue.py`, `game/game_engine.py`
- **Bug fixed:** the command-zone cast loop had no back-face branch at all, silently making an MDFC commander's back face uncastable from the command zone even though `can_cast`/`cast_spell` already supported `face="back"` generically.

### Face-down permanents — morph, megamorph, disguise, manifest, cloak (RULE 708)

- **What:** Modeled as a face swap (`GameObject.turn_face_down` stashes the whole face-up bundle and swaps in a synthetic 2/2 with no text/abilities) so the layer engine, combat and targeting need no special case; casting face down is a fourth cast face ({3} flat, mana value 0); turning face up is a genuine no-stack RULE 116.2b special action offering every legal route (morph/disguise cost, or a manifested/cloaked creature's own mana cost per RULE 701.40c/701.58c).
- **Files:** `game/face_down.py`, `models/game_object.py`, `game/game_engine.py`, `game/rules_engine.py`
- **Why:** RULE 708.9's "reveal as it changes zones" lives at the single `GameState.remove_from_battlefield` chokepoint as a bare model transition rather than through `turn_face_up`, since that reveal fires no trigger and charges no cost.

### Dungeons and venturing (RULE 309, RULE 701.49)

- **What:** A dungeon is plain data on `Player.dungeon` (not a `GameObject`, mirroring the Emblem reasoning), with its room graph parsed off the raw pre-normalize card text since the "(Leads to: …)" parenthetical is real rules arrows, not reminder text. `venture_into_the_dungeon` implements all three RULE 701.49 branches; completion is appended to the bottommost room's own ability rather than a separate SBA scan.
- **Files:** `models/dungeon.py`, `game/dungeons.py`, `services/dungeon_database.py`, `game/rules_engine.py`
- **Why:** Room abilities are collected the source-less way Monarch/Initiative's are, since there's no permanent for the per-object trigger scan to find — this also completed RULE 726.2's initiative venture trigger left open since batch 10.

### Formats and casual variants — Planechase, Archenemy, Vanguard (RULE 8/9, 901, 904, 902)

- **What:** `models/game_format.py` replaces ad-hoc starting-life params with a named format record driving starting life/hand size/singleton and which RULE 9 variants are on; all three variants reuse the dungeon-established shape (cards outside the game, living in the command zone as ordinary bound `GameObject`s) — Planechase's shared planar deck + planeswalk/chaos die, Archenemy's per-player scheme deck with "set top card in motion" as a turn-based action, Vanguard's per-player avatar hand/life modifiers.
- **Files:** `models/game_format.py`, `game/variants.py`, `services/variant_card_database.py`
- **Why:** Team variants (RULE 809-811) are deliberately excluded — they change the turn structure itself rather than adding a card pool, tracked separately as PLR-14.

### Planar deck could return short decks

- **Bug fixed:** `variants.build_planar_deck` sampled exactly `size` cards then dropped any past the RULE 901.15 phenomena cap with nothing to replace them, producing ~6% undersized planar decks (7-9 cards instead of 10); fixed to deal off a shuffle of the whole pool, skipping a phenomenon once the cap is reached, preserving the real random 0-2 phenomena distribution.
- **Files:** `game/variants.py`

### Dungeon room bindings, 29/30 rooms (PAR-13)

- **What:** The RULE 309 dungeon engine and room graphs were already complete; a room with no matching effect handler simply fails closed rather than breaking the graph. Closed 8 of 9 remaining unmodeled rooms via several small handler additions (below); Throne of the Dead Three's "reveal top 10, place a creature with counters, shuffle" stays a documented residual gap with zero non-dungeon cache siblings.
- **Files:** `game/dungeons.py`, `parser/oracle/catalogue/handlers.py`

### Legendary named token creation (PAR-13)

- **What:** `CreateTokenEffect`/`synthesize_token_card` gained a `legendary` param (Cradle of the Death God's "The Atropal"), setting `Card.is_legendary` directly and folding "Legendary" into the synthesized type line so `Card.is_token`'s "starts with Token" contract still holds.
- **Files:** `game/effects.py`, `services/token_database.py`

### Format switch reaches the goldfish/multiplayer API (PLR-13)

- **What:** `GameEngine.new_game` already understood `game_format`/`archenemy_id`, but neither `api/game.py` nor `api/multiplayer.py` passed one through, so Planechase/Archenemy/Vanguard were engine-complete but unreachable from the UI. `build_goldfish_engine`/`build_multiplayer_engine` gained their own `_setup_variants` handling (run before the opening hand is drawn); one shared `GET /api/game/formats` backs both the Goldfisch start screen and the Multiplayer Setup table options.
- **Files:** `services/game_session.py`, `api/game.py`, `api/multiplayer.py`, `models/game_format.py`

### Reveal-land cycle: interactive check-land (Hobbits batch)

- **What:** RULE 614.1's optional sibling to the deterministic check-land: `catalogue.lands`'s new `reveal_types` kind, resolved via a genuine interactive `land_tapped_reveal` `pending_choice` since the controller can hold a matching card and still decline (unlike a deterministic board-state check). 8 SOLO cache-wide (Fortified Village, the "Snarl" cycle).
- **Files:** `parser/oracle/catalogue/lands.py`, `game/rules_engine.py`

### "Create a token and attach ~ to it" (Hobbits batch)

- **What:** `AttachEffect`'s new `target_kind="created"`, reading `GameContext.created_objects` — a Living-Weapon-adjacent shape printed as ordinary text instead of the keyword.
- **Files:** `game/effects.py`, `parser/oracle/catalogue/handlers.py`

### Frodo, Sauron's Bane: two-stage transform state machine

- **What:** "{cost}: If Frodo is a Citizen, it becomes a Halfling Scout with base P/T 2/3 and lifelink." / a second ability escalating to Halfling Rogue. Composed entirely from existing primitives: a free-text custom counter kind (`frodo_stage`) bumped by each ability, gating two `static` specs with `active_if: {"kind": "source_counters", ...}` using `min`-only (no `max`), so both stages stay active once unlocked and RULE 613.7 timestamp layering lets the later stage's subtype override sit on top without restating P/T.
- **Files:** `game/ability_catalogue.py`, `game/costs.py` (`activation_condition` settable directly from a hand-authored cost dict)

### Bare "create a token that's a copy of target X" recognizer

- **What:** `CopyPermanentEffect` existed but had no oracle-text recognizer (Ephemerate-adjacent cards were always hand-authored). Narrow by design — only a bare `{TARGET}` phrase with no "except it's/has/isn't…" modification clause. Closes Cackling Counterpart, Rite of Replication.
- **Files:** `parser/oracle/catalogue/handlers.py`

### Dynamic-magnitude token creation

- **What:** `CreateTokenEffect.count_from_trigger_event` ("create that many tokens", Lathril, Blade of the Elves) plus two dynamic-*count* oracle recognizers sharing a selector vocabulary with the pump widenings below: "for each `<subtype>` you control" and "X…, where X is the number of `<subtype/attacking>`…".
- **Files:** `game/effects.py`, `parser/oracle/catalogue/handlers.py`

### Bug: `_matches_permanent_type` missing planeswalker/battle branches (Card Types & Structures)

- **What:** All three near-duplicate copies of `_matches_permanent_type` (kept separate per the mixin-split architecture) had no `"planeswalker"`/`"battle"` branch, silently matching *any* permanent — discovered when Liliana's −9 swept nearly an opponent's entire board.
- **Files:** `game/rules/misc_mixin.py`, `game/rules/damage_death_mixin.py`, `game/rules_engine.py`

### Bug: token synthesis dropped the Artifact type on "N/N artifact creature token" (Card Types & Structures)

- **What:** `synthesize_token_card` treated "Creature"/"Artifact" as strict either/or, and all three parser word-splitting loops recognized "artifact" as a supertype marker and discarded it — every Construct/Thopter/Servo/Golem token cache-wide silently lost its Artifact type. Fixed with a combined `is_artifact` flag and a single shared `_split_token_mid_words` helper replacing three duplicated loops.
- **Files:** `services/token_database.py`, `parser/oracle/catalogue/handlers.py`, `game/effects.py`
- **Bug fixed:** Surfaced by Urza's Saga's own Construct — invisible to its own artifact-counting anthem, it stayed 0/0 and died to RULE 704.5f one SBA pass after `create_token` had genuinely already placed it on the battlefield.

### Copy-Except `not_legendary` / `add_types` / `add_subtypes`

- **What:** `Card.as_copy` gained `not_legendary` (strips `is_legendary` and the printed word, RULE 205.4a) alongside the pre-existing `add_types`/`add_subtypes`; `CopyPermanentEffect` gained all three (previously only `EnterAsCopyReplacement` had them), threaded through `RulesEngine.copy_permanent`.
- **Files:** `models/card.py`, `game/effects.py`, `game/rules_engine.py`.

### `ReturnSelfFromGraveyardEffect.transformed` Wiring

- **What:** Threaded the existing `transformed` flag (RULE 400.7 + 712.8) through `ReturnSelfFromGraveyardEffect` for Ojer Axonil's death trigger.
- **Files:** `game/effects.py`.
- **Bug fixed:** The effect's pre-existing `tapped` param had been accepted since Malakir Rebirth but never actually applied (`return_from_graveyard` reads "tapped" off the destination string, not a separate flag) — Malakir Rebirth's granted return had been silently returning creatures untapped.

## Keyword Catalogue

### M2 Ward (RULE 702.21)

- **What:** Ward pushes a real `StackItem` (a genuine ability the target's controller controls, RULE 603.3a) above the spell/ability that triggered it, so both players get a normal priority window before it resolves — replacing an earlier same-day inline-choice shortcut that skipped that window. Cost is paid through the full activated-ability cost vocabulary (mana/life/discard/sacrifice), not mana-only.
- **Files:** `game/rules_engine.py`, `game/costs.py`, `parser/oracle/catalogue/keywords.py`
- **Why:** Built directly rather than through the generic trigger pipeline because a bind-once `effects` list can't carry per-firing data (which stack item, which caster).

### Regenerate (RULE 701.16)

- **What:** A new pre-emptive `EventType.DESTROY`, fired by `RulesEngine.destroy` and run through the existing replacement machinery, lets a regeneration shield (a `ReplacementEffect` tagged `regeneration_shield`) intercept it: removes the permanent from combat, taps it, clears damage, and cancels the move to graveyard. Multiple shields stack independently; an unused shield expires at cleanup.
- **Files:** `game/rules_engine.py`, `game/effects.py`, `models/events.py`
- **Bug fixed:** RULE 701.16c — sacrifice previously routed through `destroy` too, so a regeneration shield could illegally save a sacrificed permanent; a new non-destructive `RulesEngine.put_into_graveyard` choke point now handles sacrifice instead.

### Phasing (RULE 702.26)

- **What:** `GameObject.phased_out` built to unblock Robe of Stars, scoped initially to a single-permanent case.
- **Files:** `models/game_object.py`

### Granted protection (RULE 702.16)

- **What:** `GameObject.temp_protections`, read by `combat.is_protected_from`, granted via an interactive `grant_protection` effect and cleared at cleanup — Mother of Runes, Giver of Runes.
- **Files:** `models/game_object.py`, `game/combat.py`, `game/effects.py`

### Cycling suffix generalization and keyword-line recognition bug fixes

- **What:** Generalized `<type>cycling` (Islandcycling, Basic landcycling, …) the same way `<type>walk` already was, fixing "Basic landcycling" being silently skipped entirely. Also fixed `is_keyword_line`'s coverage-gate scan to recognize alias display spellings (Multikicker, Megamorph) and to stop misreading a comma inside a keyword's own compound cost/parameter (Escape's "…, Exile N other cards…", Partner with's named epithet) as a second unrecognized token.
- **Files:** `parser/oracle/catalogue/keywords.py`, `parser/oracle/segmenter.py`

### Ward Cost `{X}` Resolution (RULE 702.21b)

- **What:** A ward ability's own `{X}` cost is now resolved fresh at the ward ability's *resolution* time (not when it triggers) via a new `ActivationCost.x_selector`, scoped to the warded permanent's controller and reusing the layer-7a count-selector vocabulary.
- **Files:** `game/costs.py`, `game/rules_engine.py`
- **Why:** Previously an unresolved `{X}` defaulted to amount 0, so a hypothetical board-count ward cost would have silently resolved as free — fixed pre-emptively even though no cached card needed it yet.

### Living Weapon & Renown Real Behavior

- **What:** RULE 702.92/702.112 went from recognized-only to real behavior: a Living Weapon's ETB now creates and self-attaches a germ token (`LivingWeaponEffect`, one atomic effect since attach target is the same effect's own creation), and Renown places counters and fires a new `EventType.RENOWNED` so a card's *separate* "becomes renowned" trigger (Relic Seeker) can key off it independently.
- **Files:** `game/effect_binder.py`

### RULE 702.8b Flash Gates Cast Timing

- **What:** `GameEngine.can_cast`'s sorcery-speed timing check now actually consults the Flash keyword (`sorcery_speed = not (card.is_instant or combat.has(obj, "flash"))`).
- **Files:** `game/game_engine.py`
- **Bug fixed:** Flash was recognized as a keyword but never consulted for cast timing at all, so a Flash permanent could only ever be cast at sorcery speed (hit directly by Embercleave/The Wandering Emperor).

### Channel / Cycling (RULE 702.29/702.28)

- **What:** A hand-zone, non-mana "Discard this card: `<effect>`" activated ability, distinct from the hand-exile mana-ability shortcut since Channel/Cycling use the stack. New `ActivationCost.discard_self` and `RulesEngine.discard_specific` (discards a specific hand object rather than an auto-choice).
- **Files:** `game/costs.py`, `game/rules_engine.py`, `game/game_engine.py`

### Monstrosity (RULE 701.37)

- **What:** `RulesEngine.monstrosity` is atomic (guard + counters + designation in one conditional). `GameObject.is_monstrous` is a sticky designation (until it leaves the battlefield) firing `EventType.BECAME_MONSTROUS` once, feeding a new `requires_monstrous` conditional-static gate so a granted keyword (Fleecemane Lion's hexproof) appears/disappears with the designation every recompute rather than being granted once.
- **Files:** `game/rules_engine.py`, `game/continuous.py`
- **Why:** Deliberately not unified with Adapt — monstrosity's gate is a sticky designation, adapt's is the creature's live counter count, so sharing an implementation would give one of them a flag it must never read.

### Adapt (RULE 701.46)

- **What:** A separate `RulesEngine.adapt`, gated purely on current +1/+1 counter count — no event, no designation. "As long as ~ has a +1/+1 counter on it" statics needed nothing new, reusing the existing `min_level` gate.
- **Files:** `game/rules_engine.py`

### RULE 702.94b Soulbond Reaches Existing Primitive

- **What:** The `soulbond_pair` selector shipped with the cEDH cube batch had no card text able to invoke it; three new parser rows (quoted grant, anthem, bare keyword) let "each of those creatures has …" reach it.
- **Files:** `parser/oracle/catalogue/`

### Dethrone (RULE 702.107)

- **What:** "Whenever this creature attacks the player with the most life (or tied), put a +1/+1 counter on it" — a per-firing procedural check (`RulesEngine.check_dethrone`) rather than a bind-on-load trigger, since Dethrone is also grantable to other creatures by a layer-6 static (Marchesa, the Black Rose) that never runs bind-on-load on them.
- **Files:** `game/rules_engine.py`, `game/combat.py`
- **Why:** Resolves the defending player off `attacker.combat_defender`, so a planeswalker/battle attack still checks that permanent's controller's life — a real ruling.

### Fading (RULE 702.32)

- **What:** Entry counters and the upkeep "remove one or sacrifice" behavior are both bound to the keyword itself (not to any specific card), reading counters off the parsed keyword rather than a printed reminder sentence, so every Fading/Vanishing card gets it for free.
- **Files:** `game/effects.py`, `game/rules_engine.py`

### Soulbond (RULE 702.94)

- **What:** Real pairing state (`GameObject.paired_with` on both objects) rather than a continuous effect, since RULE 702.94c breaks pairing on events; swept as an SBA so no removal site needs to tear it down manually. The grant is an ordinary layer-6 static over a `soulbond_pair` selector.
- **Files:** `models/game_object.py`, `game/continuous.py`

### Mutate (RULE 702.140)

- **What:** An alternative cast cost that merges onto its target instead of entering the battlefield; the host stays the surviving `GameObject` per RULE 702.140c (counters/damage/Auras/summoning sickness carry over, no ETB fires), with "all abilities from under it" re-derived through the ordinary bind path. New `EventType.MUTATES`.
- **Files:** `game/rules_engine.py`, `models/game_object.py`

### Granted Escape (Underworld Breach)

- **What:** `continuous.granted_escape_for` lets a permanent grant Escape (RULE 702.138) rather than only a printed keyword, consulted by the same `_graveyard_cast_keyword`/`_escape_cost` machinery unchanged.
- **Files:** `game/continuous.py`

### Mutate under the pile (RULE 702.140b)

- **What:** `mutate_onto(..., under=True)` keeps the host's characteristics and merges the mutating card's abilities instead, chosen as the spell is cast; the host is validated against a genuine `non_human_creature_you_own` target kind (ownership, not control, per RULE 108.3).
- **Files:** `game/rules_engine.py`, `game/targeting.py`
- **Bug fixed:** the merge previously rewrote the shared printed `Card` object in place.

### Ascend / the city's blessing (RULE 702.131)

- **What:** Previously a bare recognized keyword with zero bound behaviour. `Player.has_city_blessing` is a plain idempotent per-player flag, never cleared once granted; the permanent form (10+ permanents) is checked at SBA cadence, the instant/sorcery form is a one-shot `GetCityBlessingEffect` appended to `spell_effects`.
- **Files:** `game/rules_engine.py`, `game/effects.py`, `game/continuous.py`

### Hexproof-from-quality keyword shape (PAR-5)

- **What:** `Hexproof` moved from a bare `FLAG` keyword shape to `QUALITY` (mirroring `Protection`), so "Hexproof from black" (Knight of Grace) keeps its colour instead of collapsing to blanket hexproof. Recorded for future engine consumption; the engine itself still treats hexproof as an unscoped boolean.
- **Files:** `parser/oracle/catalogue/keywords.py`
- **Bug fixed:** The protection/hexproof extractor regex failed on a keyword line immediately followed by reminder text with no leading punctuation; and the "create a token with `<keywords>`"/"`<X>` you control have `<keywords>`" grant families both hard-required `FLAG` shape, silently breaking every bare-hexproof grant (45 real cards) the moment Hexproof stopped being a FLAG — both special-cased to keep working.

### Granting Cycling to hand cards (PAR-8)

- **What:** "Each `[<filter>]` card in your hand has cycling `<cost>`." (Jo Grant, Rhet-Tomb Mystic) — a layer-6 grant whose targets are hand cards rather than the battlefield. New `_apply_hand_cycling_grants` continuous pass with its own cache, kept separate from the ordinary layer-6 grant cache since that dict's pruning loop only recognizes its own key shapes.
- **Files:** `parser/oracle/catalogue/static_handlers.py`, `game/continuous.py`
- **Bug fixed:** `legal_actions_mixin.py`'s hand-zone Cycling loop only ever scanned `source.activated_abilities`, never `granted_activated_abilities` — a granted hand-zone ability was correctly bound but never actually offered to the player.

### Generic Cycling execution for unregistered cards (PAR-9)

- **What:** A bare, unregistered "Cycling `<cost>`" keyword line was claimed for the coverage gate but bound to nothing. `effect_binder._cycling_activated_ability` now binds a real `{cost}, Discard this card: Draw a card.` ability, guarded against colliding with a `<type>cycling` variant spelling or a pre-existing hand-authored discard-cost ability on the same card.
- **Files:** `game/effect_binder.py`

### "Choose a Background" keyword recognition (PAR-12, RULE 702.124)

- **What:** Registered as a bare FLAG keyword purely so a card whose only other lines are ordinary effects reaches `MODELED` instead of parking on this deckbuilding-only clause forever (Background pairing legality itself is a separate, unimplemented `commander_legality.py` gap).
- **Files:** `parser/oracle/catalogue/keywords.py`

### Investigate mechanic (PAR-12, RULE 701.19a)

- **What:** A pure `create_token` alias ("Clue" was already a known token word) for bare "Investigate.", "Investigate twice.", and "Investigate `<n>` times." — 87+ cards, the widest single template found in this session. A dynamic "investigate X times" stays unclaimed. Notable as the case study that established the "check reuse breadth, not origin set" rule for basic-vs-set-specific parser triage.
- **Files:** `parser/oracle/catalogue/handlers.py`

### RULE 702.90/91 Infect and Wither: real behaviour

- **What:** Recognized as keywords with zero behaviour before this batch. `RulesEngine.deal_damage`'s finishing closure now branches on `combat.has_infect`/`has_wither`: infect converts player damage to poison counters and creature damage to -1/-1 counters (both already replacement-aware, so a poison-doubling effect composes for free); wither is the creature-only half.
- **Files:** `game/rules_engine.py`, `game/combat.py`

### RULE 702.28c Cycling trigger, from nothing

- **What:** "When you cycle this card, `<effect>`." had no event to watch — the generic Cycling activated-ability binder gave no signal that a Cycling discard (vs. a Channel-cost one) had happened. New `EventType.CYCLED` + `ActivationCost.is_cycling`, found via a graveyard-scoped trigger scan mirroring the existing dies-from-graveyard one. Its own `{X}` preservation (`GameObject.cycling_x_paid`) closes Shark Typhoon's X/X cycling bonus specifically.
- **Files:** `game/effect_binder.py`, `game/rules_engine.py`, `models/game_state.py`

### Cumulative Upkeep (RULE 702.24) (MEC-16)

- **What:** `CumulativeUpkeepEffect` adds an age counter then reuses RULE 701.17's "sacrifice unless you pay" machinery, with the parsed cost repeated (scaled) once per age counter. `effect_binder.py`'s keyword-to-behaviour dispatch table gained the missing entry.
- **Files:** `game/effects.py`, `game/effect_binder.py`
- **Bug fixed:** The keyword was already parser-recognized but had no binder dispatch entry at all, so every Cumulative Upkeep card was inert regardless of hand-authoring; fixing the binding retroactively closed Mystic Remora's and Thought Lash's own "not built yet" documented simplifications for free.

### Imprint (RULE 702.45-adjacent) (MEC-17)

- **What:** `RulesEngine.request_choose_objects` gained a `remember` flag that stamps a chosen exiled object's id onto `GameObject.linked_exile_id`; `ImprintEffect` is the ETB "you may exile a card from your hand" half; `ManaAbility.color_selector`'s new `"imprinted_card_colors"` reads the exiled card's colors fresh every tap. Chrome Mox hand-authored.
- **Files:** `game/rules/misc_mixin.py`, `game/effects.py`, `game/mana_abilities.py`, `game/ability_catalogue.py`

### Slip Out the Back: `PhaseOutEffect` previous-clause pronoun (Keyword Catalogue)

- **What:** `PhaseOutEffect` (RULE 702.26) gained a `previous_subject` flag reading `GameContext.previous_targets`, matching `GrantUntilEffect`/`TapEffect`/`ReturnToHandEffect`'s existing pronoun idiom — "Put a +1/+1 counter on target creature. **It** phases out." Closes 8 cache-wide cards.
- **Files:** `game/effects.py`, `parser/oracle/catalogue/handlers.py`

### Phasing out an opponent's permanent as a spell effect (RULE 702.26) (Keyword Catalogue)

- **What:** `PhaseOutEffect` already accepted an arbitrary `target_kind`; the gap was purely parser-side. New `PhaseOutEffect.self_target` plus three parser rows (self/attached/target) close 9 cache-wide cards (Blink Dog, Vaporous Djinn, Crystal Golem, and others).
- **Files:** `game/effects.py`, `parser/oracle/catalogue/handlers.py`

### Delirium (RULE 702.137) (Keyword Catalogue)

- **What:** `normalize._strip_ability_words` strips "delirium" (a labeled ability word, RULE 207.2c, no rules meaning of its own), letting the bare "as long as…" clause fall through the existing RULE 613.6 machinery; new `card_types_in_graveyard_at_least` static condition (explicitly excluding the synthetic `"permanent"` type marker). Closes Dragon's Rage Channeler + 3 siblings.
- **Files:** `parser/oracle/normalize.py`, `game/static_conditions.py`

### Granted Ward With Its Own Cost (RULE 702.21b)

- **What:** `GameObject.granted_ward_cost` + `RulesEngine.check_ward`'s fallback, populated by `grant_keyword`'s new `ward_cost` param — a *granted* Ward with its own cost, the quoted-grant sibling of bare-keyword flag grants which can't express a cost. Closes ~9 cache-wide cards.
- **Files:** `game/continuous.py`, `game/rules_engine.py`, `parser/oracle/catalogue/static_handlers.py`.

### RULE 702.64 Absorb — Real Behaviour

- **What:** Absorb went from a recognized-but-inert numbered keyword to real behaviour: bound structurally in `effect_binder.attach_to_object`'s keyword branch, straight off `parametric_keywords["absorb"]["n"]` onto the `"prevent_damage"` factory (`to="self"`) — no prior keyword-to-`ReplacementEffect` dispatch table existed. Closes every cached Absorb-N creature (e.g. Lymph Sliver).
- **Files:** `game/effect_binder.py`.

### RULE 702.164 Toxic — Real Behaviour

- **What:** Toxic N was already parser-recognized as a bare numbered keyword but had zero engine consumer — the poison-counter substitution in `deal_damage` only ever fired for Infect. Added `combat.has_toxic`/`toxic_value` (reading `GameObject.parametric_keywords["toxic"]["n"]`, the same shape `has_infect`/`has_wither` already use) and a new additive branch in `damage_death_mixin.deal_damage`: for combat damage from a Toxic source, the poison counters stack *on top of* ordinary damage/life-loss rather than replacing it — the opposite composition rule from Infect (RULE 702.90b, damage-type conversion), and the two compose correctly if a source somehow has both.
- **Files:** `game/combat.py`, `game/rules/damage_death_mixin.py`
- **Why not one shared mechanism with Infect:** RULE 702.164c is explicitly additive ("in addition to the damage's other results"); RULE 702.90b is a substitution. Sharing code would have required a branch anyway, so two small, clearly-named predicates were simpler than one overloaded one.
- **Tests:** `tests/test_toxic_family.py`

### RULE 702.184a/721 Station (Edge of Eternities)

- **What:** A third "striated text box" card structure alongside Leveler/Class — a Spacecraft (or Planet land) whose text splits into a fixed Station reminder line (the real activated ability, RULE 702.184a: tap another untapped creature, put charge counters on this permanent equal to its power, sorcery-speed only, no once-per-turn cap) plus one or more `"N+ | <ability>"` bracket lines that are **cumulative** (>= comparison), not Leveler's mutually-exclusive tier ranges. `parser/oracle/catalogue/station.py`'s `split_station_blocks` classifies every line by shape in printed order (RULE 721.4 allows an ordinary line both before *and* after the brackets, unlike Leveler's strict preamble-then-blocks shape); `station_creature_threshold` reads the reminder line's own trailing "It's an artifact creature at N+." sentence from **raw**, pre-`normalize` text, since the per-bracket P/T box a real card prints doesn't survive into Scryfall's `oracle_text` at all (confirmed against all 30 cached Station cards). `gate.py` gained a new `is_station` dispatch branch reusing Leveler/Class's own `min_level`/`level_counter` gate mechanism, pointed at `"charge"` counters, for both the cumulative per-bracket grants and the creature-hood static.
- **Engine side:** the reminder line's activated ability is bound *structurally* off Scryfall's own `keywords: ["Station"]` entry (`effect_binder._station_activated_ability`, mirroring Crew/Saddle's PAR-9/MEC-40-shaped "recognized but inert keyword" fix), not emitted by the parser module. A new `ActivationCost.station` cost (exact-count-one from `_crew_pool`'s existing "other untapped creatures you control" pool, unlike Crew/Saddle's own power-threshold subset) stamps `GameObject.station_tapped_power` (the `sacrificed_cost_power` idiom's cost-payment sibling), read back by `continuous.count_selector`'s `"station_tapped_power"` entry for the charge-counter amount. The creature-hood static reuses `Card.vehicle_power`/`vehicle_toughness` (RULE 208.1's general noncreature-permanent-P/T slot) — which required widening `services/scryfall_client.py`'s Vehicle-only P/T capture to also recognize "Spacecraft" in the type line (the same latent-bug shape MEC-29 fixed once already for Vehicle/Crew, caught before shipping this time).
- **Bug found and fixed:** `combat.keywords_of`'s oracle-text regex fallback had no concept of "only active at N+ counters" — confirmed live on Entropic Battlecruiser, whose "8+ | Flying, deathtouch" bracket leaked a permanent, unconditional `deathtouch` (comma-anchored right after the "8+ | " prefix) even at 0 charge counters, on a card where no static had even bound yet. The exact same leak `is_leveler`'s `leveler_base_text` restriction already prevents for "LEVEL N+" blocks, just never extended to Station. Fixed with `station.station_base_text` — filters bracket *lines* out rather than truncating at the first one (RULE 721.4's own before-and-after shape means a real trailing unconditional line must still be found), wired into `keywords_of` alongside the existing `is_leveler` branch.
- **Files:** `parser/oracle/catalogue/station.py` (new), `parser/oracle/gate.py`, `game/effect_binder.py`, `game/engine/activation_mixin.py`, `game/engine/legal_actions_mixin.py`, `game/costs.py`, `game/continuous.py`, `game/combat.py`, `models/card.py` (`is_station`), `models/game_object.py` (`station_tapped_power`), `services/scryfall_client.py`
- **Tests:** `tests/test_game_engine.py` (the `keywords_of` leak regression, both directions)

### MEC-48: Specialize (Alchemy Horizons: Baldur's Gate — digital keyword, PARSER_VERSION 223)

- **What:** "Specialize {cost}" — an Arena-only keyword with **no paper CR entry**. Rules-analogue: "{cost}, Discard a card: This permanent specializes (becomes its specialized version for a colour of the discarded card). Activate only as a sorcery." Its five per-colour specialized faces live in Arena's own card data, which this repo's Scryfall `oracle_cards` seed doesn't carry — so the model is the *activation + designation*, deliberately not the characteristic swap (documented simplification, same class as Layer-3's "not a full oracle re-parse").
- **Parser:** one `("Specialize", COST)` row in `catalogue/keywords.py` — `_KEYWORD_TOKEN_RE`/`_COST_KEYWORD_ALT`/`is_keyword_line` are all auto-built from that table, so a bare "Specialize {cost}" line is recognized for free. `segmenter._TRIGGER_VERBS` gains `("specializes", "SPECIALIZED")` (also claims "specializes from your graveyard / from any zone" — the from-zone phrase rides along, the engine fires the same event regardless). **Fail-closed rider guard:** a "Specialize {cost}. `<rider>`" line (cost-reduction / "activate only if" / "you may also activate … from your graveyard") would be swallowed whole by `_KEYWORD_TOKEN_RE`'s greedy `.*$` and its rider silently dropped, so `segment_line` matches `_SPECIALIZE_WITH_RIDER_RE` *before* `is_keyword_line` and returns the line UNMODELED — the same pre-`is_keyword_line` intercept pattern PAR-28 used for "Boast — [ability]". Those ~5 rider cards stay MEC-48 (trimmed ticket).
- **Engine:** `effect_binder._specialize_activated_ability` (mirroring PAR-9 Cycling / MEC-29 Crew / Station's "recognized-but-inert keyword" fixes) builds a real `ActivatedAbility`: `parse_activation_cost(f"{cost}, Discard a card")` → `ActivationCost.discard = 1` (the ordinary auto-pick discard path) + `sorcery_speed_only = True`. Body is `SpecializeEffect` (`"specialize"`) — the `MonstrosityEffect` shape: untargeted, self-scoped, guards on `is_specialized`, sets the persistent `GameObject.is_specialized` (+ `specialized_color` when a single-coloured discard made one determinable) and fires `EventType.SPECIALIZED` with `instance_id`/`controller_id`/`color`. `reset_as_new_object` clears both fields (RULE 400.7).
- **New:** `EventType.SPECIALIZED`; `GameObject.is_specialized` / `specialized_color`; `SpecializeEffect` + registry; `effect_binder._specialize_activated_ability`; `segmenter._SPECIALIZE_WITH_RIDER_RE`.
- **Files:** `parser/oracle/catalogue/keywords.py`, `parser/oracle/segmenter.py`, `parser/oracle/gate.py`, `models/events.py`, `models/game_object.py`, `game/effects.py`, `game/effect_binder.py`.
- **Yield:** +12 (PARSER_VERSION 222→223). Coverage 13,607 / 34,811 (39.1%); Commander-legal unchanged at 13,011 / 31,830 (the Baldur's Gate Alchemy cards are `not_legal` in Commander, digital-only). The +12 = 6 bare-cost base faces (Gale/Jaheira/Rasaad/Vhal/Viconia/Wilson) + 6 specialized faces (Jaheira ×4, Klement Death Acolyte, Lae'zel Wrathful Warrior) whose "when ~ specializes, `<already-modeled effect>`" body now parses via the new verb.
- **Tests:** `tests/test_mec48_specialize.py` — bare line MODELED; rider line stays UNMODELED; "specializes" is a recognized trigger verb; the activated ability is offered at sorcery speed with a `discard=1` cost; activating it sets `is_specialized` + fires `SPECIALIZED`; refused at instant speed; `reset_as_new_object` clears the flag. `test_trigger_condition_vocabulary.py` updated (its "verb with no engine event" example moved from "specializes" to "phases out").

### Generic Flavor-/Ability-Word-Label Stripping (RULE 207.2c, PARSER_VERSION 99)

- **What:** `_ABILITY_WORD_RE`'s fixed 7-word evergreen whitelist (landfall/constellation/battalion/enrage/delirium/veil of time/avoidance) is what let a "Word — `<effect>`" ability-word label get stripped so the effect sentence behind it could parse normally — but a hand-maintained list can't scale to the open-ended, one-off "signature ability" names Universes Beyond sets (Final Fantasy, Marvel, Warhammer 40,000, Doctor Who, Fallout) mint per legendary character using that exact same RULE 207.2c template ("10,000 Needles — Whenever this creature attacks, it gets +9999/+0 until end of turn.", Jumbo Cactuar) — Scryfall's own keyword-extraction heuristic dutifully lists these in the card's `keywords` array right alongside real keywords, and the parser had no way to tell "one-off flavor label" from "unparseable clause". New `normalize._strip_unregistered_keyword_labels`, driven by the card's own raw Scryfall `keywords` array (threaded through as `normalize()`'s new optional `keywords` param, from `gate.py`'s single call site): any listed string that isn't a registered real RULE 701/702 keyword (checked against `catalogue.keywords.KEYWORDS`, so a genuine keyword's own line is never touched) is stripped wherever it appears as a line-leading label — safe by the same RULE 207.2c guarantee `_ABILITY_WORD_RE`'s own docstring already relies on: the label never changes what follows, so stripping it can only ever help.
- **Yield:** 1,449 real cache-wide cards print this exact "unregistered-label — effect" shape; 1,349 were previously `UNMODELED` solely because of the unstripped label. Re-parsing the whole cache after the fix: **+117 cards actually flip to `MODELED`** (the rest still have a *separate*, unrelated unclaimed clause on the same card — this fix only removes the label, not other gaps — but since it's a structural fix rather than per-card, those cards will flip for free the moment whatever their *other* gap is gets closed too, with no further work on this fix itself). Also incidentally closed a real gap in the fixed evergreen list itself: Threshold/Domain/Raid/Heroic/Metalcraft/Magecraft/Morbid/Imprint/Converge/Alliance/Corrupted/Ferocious/Hellbent/Strive/Coven and 400+ more distinct real ability-word/templated-keyword strings were being used this same way and were never in `_ABILITY_WORD_RE` at all.
- **Files:** `parser/oracle/normalize.py`, `parser/oracle/gate.py`
- **Tests:** `tests/test_oracle_pipeline.py`

### Keyword-line recognition: comma-containing keyword parameters (PAR-27, PARSER_VERSION 100)

- **What:** PAR-27's remaining scope was an audit — spot-check all 195 registered `catalogue/keywords.py` entries against real cache cards for `segmenter.is_keyword_line` false-negatives (a line that is *only* a keyword ability but that the coverage gate can't see, dropping the card to `UNMODELED` for a formatting reason). The audit ran full-cache (a throwaway harness: for each keyword, every card whose Scryfall `keywords` array carries it, `parse_oracle`, flag any `unclaimed` clause that mentions the keyword and isn't already accepted). The one structural cause it found: `is_keyword_line` tokenises by splitting on commas, so **any keyword ability whose own parameter contains a comma** fails — a compound keyword cost (`Flashback—{1}{U}, Pay 3 life.`, `Recover—Pay half your life, rounded up.`, `Eternalize—{3}{U}{U}, Discard a card.`, `Buyback—Pay 3 life, discard a card at random.`), a comma-listed `Protection from X, from Y, and from Z` / `Hexproof from A, B, and C` / `Enchant creature, land, or planeswalker`, a variable-N NUMBER keyword (`Firebending X, where X is …`, `Mobilize X`, `Devour X`), and the labelled `Companion — <deckbuilding restriction>`. Fixed with five whole-line recognisers in `segmenter.py` (`_COMPOUND_COST_LINE_RE` built from `KEYWORDS` by `KeywordShape.COST`/`NUMBER_COST`, `_MULTI_QUALITY_LINE_RE`, `_ENCHANT_MULTI_LINE_RE`, `_VARIABLE_N_LINE_RE` built from `KeywordShape.NUMBER`, `_COMPANION_LABEL_LINE_RE`) consulted at the top of `is_keyword_line` *before* the comma split. Each is anchored `^…$` and excludes `:` and a mid-line sentence period from every fragment, so it can never swallow a real ability body — the Visions of X cycle's `Flashback {8}{G}{G}. This spell costs {X} less …` cost-reduction sentence and the whole `Keyword — <activated ability>` family (Boast/Exhaust/Solved/Max Speed/Power-up/Forecast) stay `UNMODELED`, correctly (that family is now `BACKLOG.md`'s `PAR-28` — stripping the label alone would model a working-but-unrestricted ability). `_is_keyword_token` also gained the multi-word landwalk variants Scryfall names (`legendary landwalk`, `nonbasic landwalk`, `snow forestwalk`, `snow-covered plainswalk` — the base pattern was `^[a-z]+walk\b`) and `<type> offering` (the Patron cycle).
- **Nature of the fix:** pure recognition — no new or changed `AbilitySpec`. The keyword specs still come entirely from `parse_keywords` off Scryfall's `keywords` array, exactly as before; this only changes whether the *line* counts as covered by the gate. A flashback card's `cost` param is still mana-only (`"pay 3 life"` was never captured — pre-existing, and a separate Ward/Escape-style free-text-cost-fallback follow-up, not touched here because `_flashback_cost`/`_buyback_cost`/`_evoke_cost` feed `ManaCost.parse`).
- **Yield:** **+23 cache cards** flip to `MODELED` immediately (`parser_probe diff`, −0 regressed): Acorn Harvest, Conflagrate, Crippling Fatigue, Deep Analysis, Flowstone Flood, Garza's Assassin, Sinuous Striker, Elite Inquisitor, Oversoul of Dusk, Planar Disruption, Old Fogey, Ayumi/Dryad Sophisticate/Zombie Musher/Rime Dryad/Legions of Lim-Dûl (landwalk), Patron of the Akki/Patron of the Kitsune (offering), Avenger of the Fallen/Devoted Mardu/Firebending Student/Sun Warriors/Thromok the Insatiable (variable-N, inert). Structural, so more follow as unrelated co-blockers close.
- **Out of scope / reported:** the `Keyword — <ability>` label family → `PAR-28`. "Double team" (an Alchemy digital keyword absent from the CR-scoped `_TABLE`, so `Flying, double team` fails) → `PARSER_LONG_TAIL.md`'s set-specific table, with the recommendation to decide the whole Alchemy keyword family (Conjure/Draft/Boon/perpetual) as one unit rather than piecemeal.
- **Files:** `parser/oracle/segmenter.py`, `parser/oracle/gate.py` (`PARSER_VERSION` 99 → 100 + `PARSER_VERSION.lock`)
- **Tests:** `tests/test_batch6_cost_keyword_family.py` (PAR-27 section — the recognisers, the adversarial `Keyword — <ability>` / Visions / prose cases, Deep Analysis modeled end-to-end, Varragoth stays UNMODELED)

### "Keyword — [ability]" families: Boast, Exhaust, Power-up, Forecast, Solved, Max Speed (PAR-28, PARSER_VERSION 101)

- **What:** Six RULE 702 keywords print a RULE 207.2c-style em-dash label in front of a *real* activated / triggered / static ability, with the keyword itself adding a fixed rules-restriction to it. All were parser-recognized-but-inert (a bare keyword-line claim). PAR-28 makes each a genuine bound ability. One shared parser handler (`segmenter._segment_keyword_labeled_ability`, checked *before* `is_keyword_line` so `_KEYWORD_TOKEN_RE`'s greedy `.*$` can't swallow the whole line) strips the label, parses the body with the ordinary `segment_line` machinery, and folds the keyword's restriction onto the resulting spec via `_apply_keyword_restriction`. It is a **strict upgrade**: a body that fully parses gets the real restricted ability; one that doesn't falls back to the exact inert keyword-line claim `is_keyword_line` already made pre-PAR-28 (comma-free lines only — a comma-containing `Boast — {c}, sacrifice…: …` was never claimed before, so it fails closed rather than being promoted to `MODELED` with the ability inert); a body that is a *mana* ability (Loot, the Pathfinder's `Exhaust — {G}, {T}: Add three mana…`, the very card RULE 702.177b's example is about) is claimed with no spec, the once-per-game cap on a keyword mana ability left as a known simplification.
  - **Boast** (RULE 702.142a): `ActivationCost.activation_condition = {"kind": "source_attacked_this_turn"}` + `once_per_turn`. New `GameObject.attacked_this_turn` — set in `combat_mixin.declare_attackers` alongside `attacking`, but (unlike `attacking`, cleared the instant combat ends per RULE 511.3) swept for *every* permanent in the untap step so a boast ability is still activatable in the second main phase. New `static_conditions` kind `source_attacked_this_turn`.
  - **Exhaust** (RULE 702.177a) & **Power-up** (Marvel): `ActivatedAbility.once_per_game` — a per-ability, per-game cap keyed on the ability's own printed text in `GameObject.used_once_per_game_abilities` (a card with two exhaust abilities tracks each separately), checked/recorded in `can_activate`/`activate_ability`, never reset. Power-up additionally carries `ActivationCost.powerup_cost_reduction` — a generic reduction equal to the source's *own* mana value while `turn_entered == turn_number`, applied in `_reduced_activation_mana`.
  - **Forecast** (RULE 702.57): `cost.hand_zone` (reusing the existing hand-zone activation branch of `can_activate`) + `activation_condition = {"kind": "your_upkeep"}` (new `static_conditions` kind — active player + `current_step == "upkeep"`) + `once_per_turn`. "Reveal this card from your hand" is stripped from the cost text as RULE 702.57b bookkeeping.
  - **Solved** (RULE 702.169b-d / 719): a genuine **Case subsystem**. `GameObject.is_solved` is the persistent RULE 719.3b designation (set once, kept until the Case leaves the battlefield, not per-turn, not copiable). `"To solve — [Condition]"` (RULE 719.3a) parses to an ordinary phase-triggered ability — `STEP_BEGIN` / `filter={"step":"end"}` / `phase_relation="you"` / `active_if=<condition>` / effect `become_solved` — but **only** for the `[condition]` phrasings that map onto the whitelisted `static_conditions` vocabulary ("you have no cards in hand", "you control N or more artifacts/lands/creatures/detectives", "N or more cards in your graveyard"); the rest fail closed, exactly like a battle whose body grammar isn't covered — the RULE 310 engine is done, per-card oracle coverage is parser long-tail. `BecomeSolvedEffect` (new, `EffectRegistry`) sets `is_solved` and fires the new `EventType.SOLVED`. The `Solved — [ability]` line itself gates on a new `source_solved` `static_conditions` kind: `active_if` for a static, `trigger["active_if"]` for a triggered ability (new `_trigger_condition` predicate — the triggered-ability sibling of the replacement/static `active_if` gate), an `activation_condition` marker for an activated ability. `normalize._SELF_REFERENCE_RE` gained `case` so "this Case" folds to `~`.
  - **Max Speed** (RULE 702.178a) & the **Speed subsystem** (RULE 702.179): `Player.speed` (0 = no speed, 4 = max), `Player.speed_increased_this_turn`. **Start Your Engines!** (RULE 702.179a) is a real SBA — `_sba_check_start_your_engines` (mirroring `_sba_check_ascend`, read off `combat.has(obj, "start_your_engines")`) sets a controller with no speed to speed 1. **RULE 702.179d**'s sourceless inherent ability ("whenever one or more opponents lose life during your turn, if your speed < 4, +1, once per turn") is built fresh per `EventType.LIFE_LOST` in `_collect_inherent_triggers`, controlled by the active player like the rad-counter ability — resolving via the new `IncreaseSpeedEffect` (capped at 4). `Max speed — [ability]` gates on a new `your_speed_is_max` `static_conditions` kind (`speed >= 4`), on whichever of static/triggered/activated the body is.
  - `_KEYWORD_TOKEN_RE`'s trailing `\b` → `(?![a-z0-9])` so a keyword-line whose display name ends in punctuation ("Start Your Engines!", "For Mirrodin!") is recognised at all — the last gap in "every registered RULE 702 keyword's bare line is claimed" (verified: 195/195).
- **Yield:** **+26 cache cards** to `MODELED` (`parser_probe diff`, −0 regressed) — mostly Aetherdrift Start-Your-Engines cards, plus the Boast/Exhaust/Power-up/Max-Speed cards whose bodies fully parse. Structural: more follow as the effect-grammar gaps in individual Case/Boast bodies close. No Case card reaches `MODELED` yet (every cached one has an unmodeled clause somewhere — an unbuilt "N …this turn" solve-condition tracker, or an effect-body gap in its `Solved —`/ETB clause), same standing situation as the battle pool.
- **Files:** `parser/oracle/segmenter.py`, `parser/oracle/normalize.py`, `parser/oracle/catalogue/handlers.py`, `parser/oracle/gate.py` (`PARSER_VERSION` 100 → 101 + lock); `game/static_conditions.py`, `game/effect_binder.py`, `game/costs.py`, `game/effects.py`, `game/engine/activation_mixin.py`, `game/engine/combat_mixin.py`, `game/engine/turn_loop_mixin.py`, `game/rules/misc_mixin.py`, `game/rules/sba_mixin.py`, `game/rules/triggers_mixin.py`; `models/game_object.py`, `models/player.py`, `models/events.py`
- **Tests:** `tests/test_par28_keyword_labeled_abilities.py` (19 — parse + execute per keyword: Boast can't-fire-before-attacking / once-per-turn / flag reset; Exhaust once-per-game and two-abilities-tracked-separately; Power-up cost reduction only the turn it entered; Forecast from-hand + upkeep-only; Start-Your-Engines SBA, once-per-turn speed increase capped at 4, only-your-turn, Max-Speed static gated at speed 4; Case solve trigger at end step + `source_solved` anthem turning on, designation persistence)

### Combat-evasion & targeting keywords: Shroud, Fear, Intimidate, Skulk, Shadow (PAR-22)

- **What:** Five RULE 509.1b / 702.18b keywords that the parser already
  recognised as flag keywords (rows in `catalogue/keywords.py`, docked
  onto `GameObject.intrinsic_keywords` by `attach_keyword`) but that *no
  engine code consulted* — a Shroud permanent could be freely targeted, a
  Fear/Intimidate/Skulk attacker freely blocked, a Shadow creature blocked
  by (and blocking) anything. Wired to real behaviour off the same
  `combat._obj_keywords` union `has_hexproof` already reads, no new
  recognition path:
  - **Shroud** (702.18b) — new `combat.has_shroud`, consulted in
    `targeting._targetable_by` right after the hexproof check but with **no
    opponent-scoping** (shroud stops the permanent's own controller too).
  - **Fear** (702.36b) / **Intimidate** (702.13b) / **Skulk** (702.118b) /
    **Shadow** (702.28b/c) — four predicates (`has_fear`/`has_intimidate`/
    `has_skulk`/`has_shadow`) plus a block-legality branch each in the pure
    `combat.can_block(attacker, blocker)` evasion hook (the same place
    flying/protection live), reading a new `_obj_colours` /`_is_artifact`
    (`type_words`-derived, layer-4 aware) helper. Shadow runs **both ways**
    — a non-shadow creature can't block a shadow one and vice versa
    (`has_shadow(attacker) != has_shadow(blocker)`).
- **Display:** `combat.display_keywords` gained badge labels for all five
  (+ hexproof, which had none), surfaced via `GameObject.to_dict`'s
  existing `intrinsic_keywords`-as-granted pass.
- **Files:** `game/combat.py`, `game/targeting.py`,
  `frontend/src/js/implementationStatusView.js`
- **Tests:** `tests/test_par22_evasion_keywords.py` (14 — parse-still-
  recognised per keyword; shroud blocks own-controller and opponent
  targeting + drops out of a `legal_targets` offer; fear artifact/black-
  only; intimidate shared-colour-or-artifact incl. the colourless case;
  skulk greater-power-only; shadow both directions; an end-to-end
  `GameEngine.declare_blockers` refusal)

### Triggered keyword abilities: Prowess, Exalted, Battle Cry, Mentor (PAR-24)

- **What:** Four RULE 702 keywords whose text *is* a triggered ability,
  parser-recognised but with zero engine consumer (`inspect` showed
  `triggered 0` on a pure-Prowess Monastery Swiftspear). Synthesized in
  `effect_binder._KEYWORD_TRIGGERED_BUILDERS`, the same table
  Annihilator/Afflict/Bushido already use:
  - **Prowess** (702.108a) — `SPELL_CAST` trigger, "you" read *live* off
    `obj.controller_id` in the condition (RULE 702.108b, so a control-
    change hands it over), "noncreature" off the event's `object_types`
    payload; effect is the same `PumpEffect(1, 1)` (self, until EOT)
    Bushido uses.
  - **Exalted** (702.83a) — `ATTACKS_ALONE` aggregate trigger (already
    fired by `_fire_attacks_alone_event`), condition scoped to the lone
    attacker's controller being this ability's controller; new
    `PumpEffect.trigger_subject=True` mode pumps whichever object the
    firing event names ("*that* creature"), the pump-family analogue of
    `AddCountersEffect.trigger_subject_key`.
  - **Battle Cry** (702.92a) — self-only `ATTACKS` trigger; effect is an
    untargeted group `PumpEffect(1, 0, selector="other_attacking_
    creatures")`, a new `continuous.group_selector_objects` branch (every
    attacker except the source, regardless of controller).
  - **Mentor** (702.134a) — self-only `ATTACKS` trigger with a *targeted*
    `AddCountersEffect`: target is an attacking creature with power
    strictly less than the source's, expressed as a new
    `AddCountersEffect.creature_filter` (`{"attacking": True,
    "power_vs_reference": "less"}`) threaded onto its `TargetSpec`. Needed
    `targeting._creature_matches_filter` to pass a `reference`/`state`
    through to `combat.matches_object_filter` (the relative-power keys had
    silently no-opped from the `creature` target branch before — a
    latent gap, not just this ticket).
- **Files:** `game/effect_binder.py`, `game/effects.py` (`PumpEffect.
  trigger_subject`, `AddCountersEffect.creature_filter`),
  `game/continuous.py` (`other_attacking_creatures`),
  `game/targeting.py`, `frontend/src/js/implementationStatusView.js`
- **Tests:** `tests/test_par24_triggered_keywords.py` (7 — prowess pumps
  on a noncreature spell but not a creature spell; exalted pumps the lone
  attacker and stays silent when two attack; battle cry pumps each *other*
  attacker; mentor counters a lesser-power attacker and is dropped
  (RULE 603.3c) when no attacker qualifies)

### Death/graveyard keywords: Undying, Persist, Unearth, Embalm, Eternalize, Dredge (PAR-25)

- **What:** Six RULE 702 keywords parser-recognised but with zero engine
  implementation (the ticket's headline: even the hand-authored *grant* of
  "undying" in `ability_catalogue/entries_003.py` did nothing).
  - **Undying** (702.93) / **Persist** (702.79) — collected in a new
    `RulesEngine._collect_undying_persist_triggers` (called from
    `_collect_triggers` next to `_collect_counter_death_return_triggers`)
    off the `combat._obj_keywords` union, *not* synthesized at bind time,
    specifically so a layer-6 *grant* works too. On a creature's own `DIES`
    event, if the pre-death counter snapshot (`event["counters"]`, RULE
    603.10 last-known-information) has no `+1/+1` (undying) / `-1/-1`
    (persist) counter, a fresh `TriggeredAbility` with the new
    `UndyingPersistReturnEffect` returns the card and places one such
    counter (`return_from_graveyard`'s own `reset_as_new_object` clears the
    stale counters first, RULE 400.7).
  - **Unearth** (702.84) / **Embalm** (702.128) / **Eternalize** (702.129)
    — three `KeywordShape.COST` keywords whose whole text is a
    sorcery-speed activated ability *functioning from the graveyard*. Bound
    in a new `effect_binder._graveyard_keyword_activated_ability` (alongside
    Cycling/Crew/Saddle/Station in `_keyword_activated_ability`) with
    `ActivationCost.graveyard_zone` (reused from PAR-10's "return this from
    your graveyard" family — surfaced by `legal_actions`' existing
    `player.graveyard` scan) + `sorcery_speed_only`. New `UnearthEffect`
    (return self + haste + a `DelayedTrigger` end-step exile, `scope="any"`,
    plus a `WOULD_DIE`→exile replacement so a dying unearthed creature
    isn't re-unearthable — a bounce/blink keeping it is a known
    simplification) and `EmbalmEternalizeEffect` (exile self, then
    `RulesEngine.copy_permanent` with `add_subtypes=["Zombie"]` and, for
    Eternalize, `set_power=set_toughness=4` — the same copy-modifier
    vocabulary `CreateTokenCopyOfLinkedExileEffect` uses; the white/black
    colour override is dropped, `Card.as_copy`'s documented limitation).
  - **Dredge** (702.52) — a `NUMBER` keyword (`parametric_keywords
    ["dredge"]["n"]`, read by a new `draw_discard_mixin._dredge_value`,
    Toxic-style). Offered as an interactive `dredge` `pending_choice` from
    the single-card fast path of `RulesEngine.draw` (a multi-card `draw()`
    is a documented simplification): if the drawing player has one or more
    dredge cards in their graveyard with `n <= len(library)` (RULE
    702.52c), the draw is deferred; `resolve_dredge_choice` either mills
    that card's N and returns it to hand (RULE 702.52b) or, on "draw"/
    decline, falls back to `_single_draw`. `GameEngine.resolve_choice`
    dispatch + `gameBoardView.js` `CHOICE_ICONS` entry added.
- **Files:** `game/rules/triggers_mixin.py`, `game/rules/draw_discard_mixin.py`,
  `game/effects.py` (`UndyingPersistReturnEffect`/`UnearthEffect`/
  `EmbalmEternalizeEffect`), `game/effect_binder.py`,
  `game/engine/turn_loop_mixin.py`, `frontend/src/js/gameBoardView.js`,
  `frontend/src/js/implementationStatusView.js`
- **Tests:** `tests/test_par25_death_graveyard_keywords.py` (13 — undying
  returns with +1/+1 / stays dead if it died with one; persist returns
  with -1/-1 / dies for good the second time; granted undying via a
  layer-6 static; unearth returns with haste + arms the end-step exile,
  is exiled at that end step, and is exiled rather than left re-unearthable
  when it dies; embalm makes a white-Zombie same-P/T token copy and exiles
  the card; eternalize makes a 4/4 Zombie copy; dredge replaces a draw with
  mill+return, can be declined to draw, and isn't offered below N library
  cards)

### Cost keywords: Affinity, Convoke, Delve, Improvise (PAR-23)

- **What:** Four `KeywordShape.QUALITY`/`FLAG` cost keywords, all
  parser-recognised but wired to nothing.
  - **Affinity for `<quality>`** (702.41) — Scryfall names it by the full
    phrase in the `keywords` array ("Affinity for artifacts", "Affinity
    for Islands"), never a bare "Affinity", so `keywords._resolve` never
    matched it and `parse_keywords` emitted no spec. Fixed with an
    `affinity_for_*` → `affinity` row resolution (same "one Scryfall name
    per variant" shape as the walk/cycling families), so its existing
    `_SPECIAL_REGEX` recovers the quality from oracle text. `effect_binder.
    _attach_affinity_static` then synthesizes a `StaticAbility(layer=
    "cost", affects="self", params={"generic": 1, "per": <count_selector>})`
    on `obj.static_effects` — exactly the shape `continuous.self_cost_
    reduction_for` / `_cost_static_amount` already read for a hand-authored
    Delve/Affinity-style reduction. `_AFFINITY_SELECTORS` maps the
    supported qualities (artifacts / creatures / lands / each basic land
    type) to a `count_selector`; an unrecognised quality (a rare tribal
    "Affinity for Dwarves") synthesizes nothing, fail-closed. The board's
    "was {4}, now {1}" cost display works for free (legal_actions already
    surfaces `self_cost_reduction_for`'s contributors).
  - **Convoke** (702.51) / **Delve** (702.66) / **Improvise** (702.126) —
    a single opt-in `help_pay` cast flag (not one per keyword — no cached
    card carries two), threaded through `can_cast`/`effective_cast_cost`/
    `_auto_tap_for_cast_if_needed`/`_cast_current_face`/`cast_spell`
    parallel to `evoke`, round-tripped by `game_session._dispatch_cast_
    spell` off the flag `_cast_action` stamps. `effective_cast_cost(help_
    pay=True)` folds in the *best-case* generic reduction (`_cast_help_
    capacity`) for `can_cast` / the offer's displayed cost;
    `_cast_current_face` does the *minimal* real consumption
    (`_consume_cast_help` — tap untapped creatures / tap untapped
    artifacts / exile graveyard cards, one at a time, only until the pool
    can pay, *after* `_auto_tap` has put in what lands it could).
    `legal_actions._offer_cast` adds a "cast using Convoke/Delve/Improvise"
    action (with `help_pay_kind`) whenever the keyword is present, a help
    resource exists, and that mode is castable — including the
    `_castable_now_or_via_potential` path so a spell castable *only* with
    help still appears. **Generic-only** (Convoke's RULE 702.51b "or one
    mana of that creature's colour" is a documented simplification) and
    auto-*minimal* rather than a per-resource "which creatures" picker
    (a future UI refinement); an {X} convoke spell's offered `max_x`
    ignores the help capacity (server re-validates on cast).
- **Files:** `parser/oracle/catalogue/keywords.py` (`_resolve`),
  `game/effect_binder.py` (`_attach_affinity_static`),
  `game/engine/casting_mixin.py` (`_help_pay_keyword`/`_cast_help_pool`/
  `_consume_cast_help`/`_cast_help_capacity` + `help_pay` threading),
  `game/engine/legal_actions_mixin.py`, `services/game_session.py`,
  `frontend/src/js/implementationStatusView.js`
- **Tests:** `tests/test_par23_cost_help_keywords.py` (6 — affinity for
  artifacts / for a basic land type reduces the cost per matching
  permanent; convoke taps creatures, delve exiles graveyard cards,
  improvise taps artifacts, each covering exactly the generic shortfall;
  `help_pay` is refused for a spell without any of the three keywords)

### Cast-alternative/timing keywords: Backup, Dash, Madness, Miracle, Ninjutsu, Bestow (PAR-26)

- **What:** All six cast-alternative/timing keywords, all
  parser-recognised but implemented nowhere. **PAR-26 is closed** — Bestow,
  the dual-card-type member deferred from the first wave, shipped
  2026-08-29 (see its own bullet below).
  - **Backup N** (702.165) — `effect_binder._kw_backup`: an
    `ENTERS_BATTLEFIELD` self-trigger with a targeted `AddCountersEffect`
    (`amount=N`). New `targeting` kind `"creature_including_self"` (the
    plain `creature` branch without RULE 115.6's self-exclusion) because
    RULE 702.165a explicitly allows targeting the source — the common
    line, since it enters alone. The "lends its other abilities" clause is
    a documented simplification (a resolve-time ability-snapshot grant,
    MEC-23-shaped).
  - **Dash** (702.109) — bound as a RULE 118.9-style alternative cost
    (`obj.alt_cast_cost`, reused from Force of Will — the offer/dispatch/
    payment path is all wired) plus a `dash` marker and `GameObject.cast_
    via_dash`, stamped in `_cast_current_face`'s `alt_cost` branch; at
    resolution (next to `cast_via_evoke`) it grants haste and arms a
    `DelayedTrigger` "return to hand at the beginning of the next end
    step" (`ReturnToHandEffect` self form). Known papercut: the `alt_cost`
    path skips auto-tap, so the dash mana must be in the pool.
  - **Madness** (702.35) — `draw_discard_mixin._maybe_madness`, called
    from both `discard` and `discard_specific`: exiles the card instead of
    graveyarding it, arms a `temp_play_permissions` (same-turn-only)
    window + `obj.madness_exiled`, and arms a `MadnessToGraveyardEffect`
    delayed trigger for the next end step (RULE 702.35b). The cast is via
    `obj.alt_cast_cost` (the madness cost); `_offer_cast` suppresses the
    *printed*-cost offer for a `madness_exiled` card in exile so only the
    madness-cost cast is available.
  - **Miracle** (702.94) — `draw_discard_mixin._arm_miracle`, called from
    `_single_draw` when the drawn card is the first this turn: sets
    `obj.miracle_armed` + `GameState.miracle_armed_ids`. The cast is via
    `obj.alt_cast_cost` (the miracle cost), and `_offer_cast`/
    `_castable_now_or_via_potential` gate that offer on `miracle_armed`
    (otherwise a Miracle card just sits in hand castable normally). The
    window is a whole-turn simplification of RULE 702.94b's "before you
    get priority", torn down in `_step_cleanup`.
  - **Ninjutsu** (702.49) — `GameEngine.ninjutsu(player, ninja,
    returned_attacker)`, a RULE 702.49b special action offered by
    `legal_actions` to the active player during the declare-blockers step
    (one entry per ninja-in-hand × unblocked-attacker-you-control pair
    whose mana cost is payable), dispatched by `game_session.
    _dispatch_ninjutsu`. Pays the mana, returns the attacker to hand
    (the printed cost), and puts the ninja onto the battlefield tapped +
    attacking in its combat slot (same `combat_defender`), firing its own
    `ENTERS_BATTLEFIELD` and `ATTACKS` events. `obj.ninjutsu_cost`
    (`ManaCost`) is the bound marker.
  - **Bestow** (702.103, 2026-08-29) — a fourth `face` on `cast_spell`
    (`face="bestow"`, next to `"back"`/`"fuse"`/`"face_down"`). No card
    swap: `RulesEngine._begin_bestow` sets `GameObject.bestowed` and adds
    a **synthetic `parametric_keywords["enchant"] = {"quality":
    "creature", "bestow": True}`** entry, which is all the *existing* Aura
    machinery needs — `_attachment_kind` → `"enchant"`,
    `targeting.spell_target_specs` synthesizes the "enchant creature"
    requirement (RULE 702.103b/601.2c), and `_resolve_permanent_spell`'s
    attach branch attaches it on resolution with no new code.
    `GameObject.is_creature` returns `False` while `bestowed` (RULE
    702.103b/d), so combat/SBAs/the board read it as an Aura; its printed
    "Enchanted creature gets +X/+X"/"…and has …" clauses are the ordinary
    parser-bound `affects="attached_permanent"` statics, inert while it's
    a plain creature and live once attached — nothing bestow-specific.
    The cost is read off the parser's own `bestow` keyword param
    (`_bestow_cost`, same shape as `_buyback_cost`/`_kicker_cost`) and
    substituted for the mana cost via a `face="bestow"` branch in
    `effective_cast_cost` + a `bestow=True` branch in `_cast_current_face`
    (an ordinary paid `rules.cast_spell(..., cost=…)`, unlike the no-mana
    free/alt-cost paths). **Un-bestow** (RULE 702.103e/f) is
    `_end_bestow` (clears the flag + the synthetic entry), driven from
    three sites: `_detach_attachments_from`/`_revalidate_attachments`
    (host leaves / attachment becomes illegal — the RULE 704.5m exception,
    stays on the battlefield as a creature rather than going to the
    graveyard), the new SBA `_sba_check_unbestow` (catch-all for any other
    route to "unattached"), and the resolve-time illegal-target branch
    (RULE 702.103e/608.3b — finishes resolving as a creature spell, no
    fizzle). `_offer_cast` adds the Bestow offer as an independent payment
    method alongside the plain creature cast (locked with RULE 601.2c's
    "no creature to enchant" reason when the board has none). Documented
    simplification: RULE 702.103d ("only bestow-modified characteristics
    are evaluated to determine if it can be cast", i.e. "creature spells
    can't be cast" doesn't stop a bestow cast) isn't honoured — `can_cast`
    reads the printed `Card` for its per-turn/prohibition checks. Purely
    engine work: no PARSER_VERSION bump (the keyword line was already
    recognised, and the ~22 still-`UNMODELED` bestow cards are each held
    up by *other*, unrelated effect-body grammar).
- **Files:** `game/effect_binder.py` (`_kw_backup` + the dash/madness/
  miracle/ninjutsu keyword-bind hooks), `game/targeting.py`
  (`creature_including_self`), `game/engine/casting_mixin.py` (`cast_via_
  dash` stamp; `_bestow_cost`, `cast_spell`/`_cast_current_face`/
  `effective_cast_cost`/`can_cast` bestow branches), `game/rules/
  casting_mixin.py` (dash resolution; `_begin_bestow`/`_end_bestow`,
  bestow-aware `_detach_attachments_from`/`_revalidate_attachments`/
  `_resolve_permanent_spell`), `game/rules/sba_mixin.py`
  (`_sba_check_unbestow`), `game/rules/draw_discard_mixin.py`
  (`_maybe_madness`/`_arm_miracle`), `game/effects.py`
  (`MadnessToGraveyardEffect`), `game/engine/combat_mixin.py`
  (`ninjutsu`), `game/engine/legal_actions_mixin.py` (ninjutsu offer +
  madness/miracle offer gates; `_cast_action`/`_offer_cast` bestow
  offer), `game/engine/turn_loop_mixin.py` (miracle cleanup),
  `services/game_session.py` (`_dispatch_ninjutsu`; `face` already
  round-trips for bestow), `models/game_object.py` (`cast_via_dash`/
  `madness`/`madness_exiled`/`miracle`/`miracle_armed`; `bestowed` +
  `is_creature`/`type_words`), `models/game_state.py`
  (`miracle_armed_ids`), `frontend/src/js/gameBoardView.js` (`faceHint`
  bestow label), `frontend/src/js/implementationStatusView.js`
- **Tests:** `tests/test_par26_cast_timing_keywords.py` (15 — backup
  counters another creature / itself when alone; dash grants haste and
  bounces at the end step; madness exiles on discard, is castable only
  for the madness cost, and goes to the graveyard if not cast that turn;
  miracle arms only the first draw of the turn and the window closes at
  cleanup; ninjutsu swaps an unblocked attacker for a ninja and is
  refused for a blocked one; bestow offers a second action, casts as an
  Aura that buffs the host and isn't a creature, un-bestows to a creature
  when the host leaves, is locked with no creature to enchant, resolves
  as a creature on an illegal target, and still casts normally as a plain
  creature)

## Designations & Standing Systems

### Goad (RULE 701.15)

- **What:** Goaded is modeled as a *set of goaders* per creature (not a flag), so multiple simultaneous goads and repeat-goading fall out naturally. "Attacks each combat if able" rides the existing `attacks_if_able` check; "attacks a player other than the goader if able" is a new whole-attack `_enforce_goad_requirements` check leaving declare-attackers. A parallel `_goaded_by_static` store handles the Aura-granted form (re-derived every recompute so it vanishes with the Aura), unioned with the sticky resolve-time set by `combat.goaders`.
- **Files:** `game/rules_engine.py`, `game/game_engine.py`, `game/combat.py`
- **Why:** The requirement-audit check deliberately asks `_attack_conditions_ok`, not `_can_attack` — by audit time the creature is already declared/tapped, so `_can_attack` would wrongly read the state its own declaration just created.

### Monarch, Initiative and Emblems (RULE 725, 726, 114)

- **What:** Monarch/Initiative are plain player designations with source-less inherent triggered abilities (built fresh off live state per firing rather than found by the per-permanent scan, since neither is attached to a permanent); Emblems get a minimal `Emblem` stand-in (`controller_id` + `timestamp` only) whose quoted ability is recursively parsed at parse time and bound once at resolve time into `Player.emblems`.
- **Files:** `game/rules_engine.py` (`_collect_inherent_triggers`, `create_emblem`), `models/emblem.py`, `parser/oracle/catalogue/handlers.py`
- **Why:** Subject/selector shapes meaningful only relative to a source permanent ("self"/"attached_permanent") are rejected fail-closed at emblem parse time, since an emblem has no host permanent to bind onto.
- **Bug fixed:** `continuous._source_name` read `ability.source.name` unconditionally, crashing on any static emblem ability since `Emblem` has no `.name`; fixed with a `getattr` fallback.

### The Ring tempts you (RULE 701.51/701.52)

- **What:** `Player.ring_level` (0-4) is the designation itself (no quoted card text, unlike a RULE 114 emblem — the four abilities are fixed by the rules); `Player.ring_bearer_id` is re-chosen on every temptation via an interactive choice and swept by the SBA pass when its creature stops qualifying. Ability 1 splits between a layer-4 legendary grant and a blocking restriction; abilities 2-4 are built fresh per firing, source-less like Monarch/Initiative.
- **Files:** `game/rules_engine.py`, `game/continuous.py`, `models/player.py`

### MEC-8 — an emblem's own activated ability

- **What:** RULE 114.4 permits an emblem to carry an activated ability. `models/emblem.py` gained `activated_abilities`/an `instance_id`/a `name` so the existing activation call sites work unchanged; the emblem-quote parser handler's hard rejection of nested activated specs was widened with the same fail-closed self-reference guard the triggered/static branches already use.
- **Files:** `models/emblem.py`, `game/rules_engine.py`, `parser/oracle/catalogue/handlers.py`
- **Bug fixed:** an `ActivatedAbility` (and a list of `TriggeredAbility` from a compound trigger) returned by `bind_ability` was being silently dropped by `create_emblem`'s if/elif chain.

### MEC-9 — Monarch/Initiative succession on player leave (RULE 725.4/726.4)

- **What:** `remove_player_from_game` now passes a departing Monarch/Initiative holder's designation to the active player before clearing their board; Initiative succession is routed through the real `take_initiative` call (firing the venture-into-Undercity trigger), not a bare field assignment, so the handoff is genuine Comprehensive-Rules behaviour.
- **Files:** `game/rules_engine.py`

### "The Ring tempts you" + RING_TEMPTED trigger (PAR-12, RULE 701.51/701.52)

- **What:** The resolve-time alias (`the_ring_tempts_you`) already existed for one hand-authored card; general oracle recognition closed 36+ more. "Whenever the Ring tempts you, `<effect>`" needed a genuinely new engine primitive though: `RulesEngine.the_ring_tempts_you` fired no event at all. New `EventType.RING_TEMPTED`, fired once the Ring-bearer choice is *settled* (immediately for 0/1-candidate paths, deferred to `resolve_ring_bearer_choice` for the interactive 2+-candidate path) so a trigger reading "if you chose a creature other than ~" always sees the final bearer.
- **Files:** `game/rules_engine.py`, `parser/oracle/catalogue/handlers.py`, `game/effect_binder.py`

### Frodo, Adventurous Hobbit's compound Ring conditions (PAR-12)

- **What:** Closed the deck's own commander with three small resolve-time primitives: `GameState.life_gained_this_turn` (a new per-turn tracker, reset only on the incoming active player); `"is_ring_bearer"` and `"ring_tempted_at_least"` `EffectSpec.condition` keys; and `ConditionalEffect._condition_holds` generalized from an if/elif to an AND-fold over every condition key present, since this card is the first needing two conditions to hold together.
- **Files:** `game/effects.py`, `game/rules_engine.py`, `parser/oracle/spec.py`
- **Bug fixed:** The first cut of the life-gained condition wrapper greedily captured the card's entire remaining text as its "rest", silently overwriting the second sentence's own, unrelated Ring-bearer gate — a card that would have parsed `MODELED` but drawn on the wrong trigger. Caught only by a real execute-level test, not coverage measurement.

### Emblem Replacement-Effect Plumbing

- **What:** Three-part fix so a granted `ReplacementEffect` on an emblem actually works: `models/emblem.py`'s `Emblem` gained a `replacement_effects` list; `RulesEngine._all_replacement_effects` now walks `player.emblems`, not just permanents/`player_effects`; `create_emblem`'s dispatch loop, which previously silently dropped anything not a `StaticAbility`/`TriggeredAbility`, now handles replacements too.
- **Files:** `models/emblem.py`, `game/rules_engine.py`.
- **Bug fixed:** Found while scoping Ajani Steadfast's -7 emblem — a replacement-granting emblem would have bound and then gone nowhere.

## Game Engine / Turn Loop & Actions

### Extra turns (RULE 500.7)

- **What:** `GameState.extra_turns` is a FIFO consumed by `GameEngine.begin_turn`; a `take_extra_turn` effect inserts a turn right after the current one (Final Fortune, paired with a delayed trigger for its own-turn-end loss clause).
- **Files:** `models/game_state.py`, `game/game_engine.py`, `game/effects.py`
- **PAR-30 parser wiring (PARSER_VERSION 166, +13):** the `take_extra_turn` effect type existed from cube-batch-18 but nothing in the oracle parser emitted it. `handlers._take_extra_turn` (`_TAKE_EXTRA_TURN_RE`) now claims the plain "take an extra turn after this one" body ("one"→"1"; an optional leading "you "), fullmatch-only so the segmenter still splits riders off. Closes the modelable half of Plea for Power's "Will of the council" vote outcome (`_vote_majority`'s `parse_effect_body` picks it up in the branch) plus a broad temporal spill — Time Walk, Temporal Manipulation/Mastery/Trespass, Capture of Jingzhou, Part the Waterveil, Alrund's Epiphany, Timestream Navigator, Time Sieve, Teferi Timebender. `_vote_per_vote` explicitly fail-closes on a `take_extra_turn` body — `_tally_and_apply_vote`'s per-vote branch scales an int `count`/`amount` by the option's tally and this effect has neither, so Expropriate's "take an extra turn … for each time vote" must not half-model. Riders left as their own tickets: "skip the untap step of that turn" (Savor the Moment — `extra_turns` is a bare id list with no skip-untap slot), "…you lose the game" (Last Chance), "…for each coin that comes up heads" (Ral Zarek). `tests/test_par30_take_extra_turn.py`.

### "Play/cast from the top of your library" permission

- **What:** A new self-contained `TopLibraryPermissionEffect` marker (look/play_lands/cast_spells/min_mana_value/requires_attached params) is read live off the battlefield by a dedicated `game/top_library.py` reader rather than the layer system, so the permission disappears the instant its source leaves (or is unattached). `can_play_land`/`can_cast`/`legal_actions` each grew one more zone-agnostic disjunct for the library top; multiple simultaneous grants OR together. Oracle of Mul Daya and Glarb, Calamity's Augur hand-authored.
- **Files:** `game/top_library.py`, `game/effects.py`, `game/game_engine.py`, `game/ability_catalogue.py`
- **Why:** RULE 701 has no native "play from the top" provision — every real card grants it as its own static ability, so this is a genuinely new mechanism rather than an extension of an existing zone-permission family.

### ENG-16: Shared `_chosen_targets` Helper

- **What:** Consolidated an identical RULE 115.1a "up to N targets off a possibly-shared list" resolution block, independently reimplemented by seven `GameEffect` subclasses, into one module-level `_chosen_targets` helper — pure deduplication, no behavior change.
- **Files:** `game/effects.py`

### ENG-18: Shared Combat-Damage-Marker Trigger Scaffold

- **What:** Only two of nine `_collect_*_triggers` methods turned out to be genuinely byte-for-byte identical outside their own effect construction (Ragavan's impulsive-draw trigger, the rad-counter damage trigger); extracted into a shared `_collect_combat_damage_marker_trigger(event, marker_attr, build_effect, description)`. The other three candidates each scan a genuinely different domain and were left alone.
- **Files:** `game/rules_engine.py`
- **Why:** Forcing one driver over all five candidates would have meant threading unrelated parameters through call sites that don't share logic — not real deduplication.

### ENG-19: Duplicate `_halvar_god_of_battle` Removed

- **What:** An incomplete early version of Halvar, God of Battle's catalogue entry (predating `extra_target_specs`) was still defined alongside the real, complete version from the cEDH-cube batch — dead code, since `register()` re-keys the dict entry and the second call always won at runtime. Removed; verified a no-op via full suite + `engine_bench.py inspect`.
- **Files:** `game/ability_catalogue.py`

### ENG-21: `rules_engine.py` Split into Per-Responsibility Mixins

- **What:** The single 7,849-line, 236-method `RulesEngine` class now composes nine mixins under `game/rules/` (triggers, casting, draw/discard, damage/death, mana/counters, copies, search, SBA, misc); `rules_engine.py` itself shrinks to `__init__`, the RULE 616 replacement core, and the class composition. Mechanical `ast`-based extraction preserving exact method spans and public method names/signatures.
- **Files:** `game/rules_engine.py`, `game/rules/*_mixin.py`
- **Why:** The 8-times-repeated `_finish(resolved)` closure pattern was investigated and deliberately *not* extracted — each has a genuinely different mechanic-specific body; only the callback name/signature repeats, and wrapping a 2-line null guard would add an indirection layer without removing real duplication.

### ENG-24: Table-Driven Keyword-Triggered-Ability Dispatch

- **What:** `_keyword_triggered_abilities` (soulbond/living_weapon/fading/renown/annihilator/afflict/bushido) became seven `_kw_<name>` builder functions in a `_KEYWORD_TRIGGERED_BUILDERS` dict, replacing a seven-armed if/elif chain — the same registry-over-if/elif pattern `EffectRegistry` already uses. `_keyword_activated_ability` (Equip/Fortify/Reconfigure) was investigated and left untouched since it has no per-keyword branching to convert.
- **Files:** `game/effect_binder.py`

### Legal-actions validation

- **What:** `legal_actions(player)` returns the validated action set (play land, cast at correct timing/affordability, tap for mana, declare attacker, pass) plus per-action `can_*` guards, wired to the frontend goldfish board via the session API.
- **Files:** `game/game_engine.py`

### Goldfisch mode session (UC3)

- **What:** Single-player game against the real rules engine, exposed as a server-held session (`GameSession`/`GameSessionManager`) with Restart and Rewind (undo), both via full `GameState.clone()` snapshots.
- **Files:** `services/game_session.py`, `api/game.py`
- **Why:** `Card.__deepcopy__` shares immutable card defs so clones stay cheap, and the step cursor travels with each snapshot so a mid-turn undo doesn't jump turns.

### ENG-17: shared `_resolve_pool_cost` helper

- **What:** Consolidated `_resolve_tap_others` and `_resolve_discard_cost`'s duplicated RULE 602.1 "choose N from a pool" logic (auto-pick first N, or validate `chosen_ids` names exactly N eligible objects) into one static helper.
- **Files:** `game/game_engine.py`

### ENG-20: `game_engine.py` split into per-responsibility mixins

- **What:** The single ~4,700-line `GameEngine` class (~130 methods) was recomposed from eight mixins (`turn_loop_mixin.py`, `combat_mixin.py`, `casting_mixin.py`, `lands_mixin.py`, `activation_mixin.py`, `mana_mixin.py`, `legal_actions_mixin.py`, `misc_mixin.py`) under a new `game/engine/` subpackage, with zero method-name/signature changes.
- **Files:** `game/engine/*_mixin.py`, `game/game_engine.py`
- **Why:** Mixins rather than delegation to sub-objects, because every method reads/writes the same `self.state`/`self.rules`, and ~100 test files plus services call methods on `GameEngine` directly by name.

### ENG-23: `GameSession._dispatch` table-driven dispatch

- **What:** The 264-line if/elif action-dispatch chain became a `_ACTION_HANDLERS` dict of `_dispatch_<kind>` methods (mirroring `EffectRegistry`'s registry-over-if/elif pattern), with cross-cutting guards (setup gate, pending-choice gate, priority gate) staying inline.
- **Files:** `services/game_session.py`

### Leyline's opening-hand battlefield permission (PLR-11, RULE 103.6a)

- **What:** "If this card is in your opening hand, you may begin the game with it on the battlefield." — a pregame setup permission, not a static/resolve-time effect, so it's recognized clause-only (no spec) by `parser/oracle/catalogue/opening_hand.py` and read via `ability_catalogue.opening_hand_battlefield_permission`. Engine side mirrors the existing Vancouver-scry queue: `GameSession._start_opening_hand_choices` walks each qualifying card one at a time as a new `opening_hand_battlefield` `pending_choice`, before Vancouver's scry per RULE 103.6's ordering. Closed 6 of 18 Leyline-cycle cards outright.
- **Files:** `parser/oracle/catalogue/opening_hand.py`, `services/game_session.py`, `game/rules/misc_mixin.py`

### Gemstone Caverns / Buried Ogre pregame-setup shapes (PLR-11 follow-up)

- **What:** Generalized the plain Leyline permission into `PregameSetupPermission` (`destination`, `condition`, `counter_type`/`counter_count`, `cost_kind`/`cost_amount`) covering Gemstone Caverns' "and you're not the starting player… with a luck counter… if you do, exile a card from your hand" and Buried Ogre's graveyard-destination variant with its own "if you do, lose N life." The offered choice's accept-option id is now the permission's own destination string instead of a hardcoded "battlefield", so the existing generic choice-button frontend needed no changes.
- **Files:** `parser/oracle/catalogue/opening_hand.py`, `services/game_session.py`, `game/rules/misc_mixin.py`

### Search criteria: colour-word qualifier + "equipment" subtype (Game Engine / Turn Loop & Actions)

- **What:** `SearchLibraryEffect`'s search grammar accepts a leading colour word ahead of a type list (consumed and dropped, not modeled as a filter) and "equipment" as a searchable subtype word.
- **Files:** `parser/oracle/catalogue/handlers.py`
- **Bug fixed:** A regex-precedence bug (`\s+` binding only to the last alternative in a colour-word group) made every colour but the last silently fail to match.

### `card_query` power/toughness bounds (Game Engine / Turn Loop & Actions)

- **What:** `models/card_query.py` gained `max_power`/`min_power`/`max_toughness`/`min_toughness` criteria keys (fail-closed for a non-creature's `None` power), hand-wired for Imperial Recruiter/Recruiter of the Guard since the parser doesn't yet parse a power/toughness qualifier after a search noun phrase.
- **Files:** `models/card_query.py`

### `WheelOfFortuneEffect` (Game Engine / Turn Loop & Actions)

- **What:** "Each player discards their hand, then draws seven cards." — the flat-count sibling of the already-shipped `WheelEffect`/`WindfallEffect`. Hand-authored (single-card template).
- **Files:** `game/effects.py`, `game/ability_catalogue.py`

### `DestroyEffect` "nonbasic" mass-wipe filter (Game Engine / Turn Loop & Actions)

- **What:** "Destroy all nonbasic lands." (Ruination) — a new `"nonbasic"` filter key paired with the existing `selector="all_lands"`.
- **Files:** `game/effects.py`, `game/ability_catalogue.py`

### `_substitute_x` walks `filter`/`criteria` dicts generically (Game Engine / Turn Loop & Actions)

- **What:** `RulesEngine._substitute_x`'s "x"/"-x" sentinel substitution now walks any effect's `filter`/`criteria` attribute, not just a plain `amount`/`count`/`power`/`toughness` field — closes both Meltdown's `DestroyEffect.filter.max_mana_value` and `SearchLibraryEffect.criteria` in one fix.
- **Files:** `game/rules_engine.py` (or its mixin)

### Mass "destroy each X" singular alternative + tutor colour/mana-value qualifiers (Game Engine / Turn Loop & Actions)

- **What:** `_MASS_DESTROY_NOUNS_SINGULAR` adds "destroy **each** X" alongside "destroy all Xs" (Meltdown). The tutor grammar's captured colour word now actually reaches `SearchLibraryEffect.criteria["color"]` (previously consumed and silently dropped — a real gap, not a documented over-approximation). A shared "with mana value X or less/greater" trailing qualifier (`_SEARCH_MV_QUALIFIER`) feeds `criteria["max_mana_value"]`/`min_mana_value`, including the `"x"` sentinel for an announced `{X}` (Chord of Calling).
- **Files:** `parser/oracle/catalogue/handlers.py`

### `ShuffleSelfIntoLibraryEffect` (RULE 701.20) (Game Engine / Turn Loop & Actions)

- **What:** "Shuffle ~ into its owner's library." (Green Sun's Zenith) overrides the default RULE 608.2m graveyard routing via the same `obj.zone != Zone.STACK` self-move override an earlier trailing-exile shape already used.
- **Files:** `game/effects.py`, `game/game_engine.py`

### Stonehewer Giant / Quest for the Holy Relic: search-then-attach (Game Engine / Turn Loop & Actions)

- **What:** `SearchLibraryEffect.attach_to_creature_you_control` applies right after `extra_counters`, auto-picking the first eligible creature (no RULE 115 target printed). A fully general oracle-text handler closes both cards outright.
- **Files:** `game/effects.py`, `parser/oracle/catalogue/handlers.py`

### Tainted Pact: repeated-dig-until-a-choice loop (Game Engine / Turn Loop & Actions)

- **What:** `ExileUntilDuplicateNameEffect`/`RulesEngine.exile_until_duplicate_name` opens a real "take vs. continue" `pending_choice` on every non-duplicate hit — a genuinely new loop shape, confirmed not an instance of `dig_until` since it stops for either of two reasons on cumulative per-iteration state.
- **Files:** `game/rules/search_mixin.py`

### Transmute Artifact: cost-comparison-gated placement (Game Engine / Turn Loop & Actions)

- **What:** `TransmuteArtifactEffect`/`RulesEngine.transmute_artifact` — a bespoke three-choice sequence (sacrifice → search → optional pay-the-difference) since the cost of the last step is computed from what a just-made choice turned out to be, something no general search/sacrifice/`pay_cost_then` primitive can express.
- **Files:** `game/rules/misc_mixin.py`, `game/ability_catalogue.py`

### RULE 702.26b extra-combat-phase grants (Game Engine / Turn Loop & Actions)

- **What:** `GameEngine.insert_additional_combat_phase` splices a fresh combat (and, for "…an additional main phase," a fresh main) into the mutable per-turn `_turn_steps` list right after the next upcoming `end_combat`. An effect queues onto `GameState.pending_extra_combats` (a FIFO, the same shape `extra_turns` already uses) since it can't reach `_turn_steps`/`_cursor` directly. Closes Godo, Aurelia, Aggravated Assault.
- **Files:** `game/game_engine.py`, `game/effects.py`, `models/game_state.py`

### "Destroy target X. It can't be regenerated." (Game Engine / Turn Loop & Actions)

- **What:** The single most repeated removal-spell tail cache-wide. `segmenter._NO_REGEN_SENTENCE_RE` retroactively flags the previous sentence's `destroy` spec with `can_be_regenerated=False`, then recurses — +40 cards (Terminate, Putrefy, Execute, and others). Deliberately doesn't match "…this turn" (a different, free-standing effect).
- **Files:** `parser/oracle/segmenter.py`

### The "threaten" effect family (Game Engine / Turn Loop & Actions)

- **What:** "Gain control of target creature [with mana value N or less] until end of turn. Untap it. It gains haste." `catalogue.handlers._gain_control_eot` claims the first sentence via the existing `GainControlUntilEndOfTurnEffect`; a second capture absorbs the untap/haste tail. Gained `max_mana_value` and a mass `selector="all_creatures"` form (Insurrection). +59 cards.
- **PAR-30 antecedent widening (PARSER_VERSION 138, +6):** `_gain_control_eot` now also accepts "`(?:another )?target`" (Akroan Conscriptor — the RULE 601.2c self-exclusion is a documented simplification), a bare "target artifact" kind (Metallic Mastery), and an optional "with power N or less/greater" filter threaded to a new `GainControlUntilEndOfTurnEffect.creature_filter` → `TargetSpec` (Enthralling Victor). A new whole-clause `_GAIN_CONTROL_EOT_PER_OPPONENT_RE` ("for each opponent, gain control of up to 1 target creature that player controls until end of turn. untap those creatures. they gain haste until end of turn.") reaches the `count_selector="opponents"` one-requirement-per-opponent shape `_goad_per_opponent` already uses — and `GainControlUntilEndOfTurnEffect.apply` now iterates *every* chosen target rather than `targets[0]`, so the whole list a `count_selector` yields is taken (Mass Mutiny, Molten Primordial). `_GAIN_CONTROL_HASTE_TAIL_RE` also gained "untap that artifact" and the "another " prefix. `tests/test_par30_threaten_antecedents.py`.
- **PAR-30 residue closed (PARSER_VERSION 199–201, +9):** `_GAIN_CONTROL_HASTE_TAIL_RE`'s `grant` group now captures whatever the restatement sentence says beyond bare haste and recurses it through `parse_effect_body(previous_subject=True)`, so the shipped `pump(previous_subject=True)` claims "untap it. it gains trample and haste until end of turn" (Traitorous Blood) / "…haste and myriad…" (Firbolg Flutist). A new `previous_subject_only` handler `_gain_control_rich_prev_grant` claims the *leading* "until end of turn, it …" forms — "it gains haste and '`<quoted ability>`'" (Furnace Reins — wraps `static_handlers._quoted_ability_grant_effects` in `grant_until(previous_subject=True)`, `affects` stripped), "it becomes a `<subtype>` in addition to its other types and gains haste" (Loki's Scepter — layer-4 `type_change` add-subtype), "it has base power and toughness N/N and gains `<kws>`" (`pt_set` grant + residual `pump`); `_DAMAGE_TRIGGER_RE` also accepts "…to a player or battle" (RULE 310 — documented simplification, the battle case rides the same `is_player` filter). The opponent-scoped *mass* threaten — "gain control of all `<type>` [your opponents / target opponent] control[s] until end of turn. untap them. they gain haste …" — is a new whole-body `_GAIN_CONTROL_MASS_EOT_RE`: `selector="opponents_artifacts"` (Broadcast Takeover — the mass path also now *passes `source`* to `_mass_selector_objects`, it was dropping it) or a new `GainControlUntilEndOfTurnEffect.mass_of_target_player` (one RULE 115 opponent target, then all their creatures/artifacts — also narrows Ashiok Sculptor of Fears / Tezzeret Master of Metal). Card-specific conditional after-tails: "if that creature is a `<subtype>`, it also gets +N/+M until end of turn" (Goatnap) and "if it's equipped, you may destroy all Equipment attached to that creature" (Awaken the Sleeper — the "you may" isn't an interactive choice, documented simplification) ride new `ConditionalEffect` keys (`previous_target_has_subtype` / `_is_equipped` / `_power_at_most`, all reading `GameContext.previous_targets`) plus a new `equipment_attached_to_previous` mass selector. Bycatch: Kaseto Orochi Archmage, Beamtown Beatstick, Archpriest of Shadows.
- **PAR-30 residue closed out — the trailing items (PARSER_VERSION 203–204, +23):** the bullet's last five, each a distinct primitive. **"When you cast this spell, `<effect>`."** (RULE 601.2i) — `segmenter._CAST_THIS_SPELL_TRIGGER_RE` → `trigger={"event": "SPELL_CAST", "condition": {"subject": "self"}}`, body parsed `self_subject`. The engine side was already MEC-43 (`RulesEngine._collect_self_cast_triggers` scans stack items; `effect_binder.bind_ability` sets `TriggeredAbility.functions_from_stack` off exactly that trigger shape) — only the recognizer was missing. +15 (Flayer of Loyalties — whose threaten body already parsed at v200 — plus the Emerge/Emrakul-brood cycle: Elder Deep-Fiend, Vexing Scuttler, Wretched Gryff, Artisan of Kozilek, Decimator of the Provinces, World Breaker, Desolation Twin …). **"enters or transforms into ~"** (Brutal Cathar) — new `EventType.TRANSFORMED`, fired by `RulesEngine.transform_permanent` *after* the face flip + ability rebind (so the payload names the new face and the freshly-bound trigger is already attached); `_SELF_MULTI_EVENT_RE` accepts "transforms into ~" as a verb slot → the existing event-list shape (one `TriggeredAbility` per event, `_SUBJECT_EVENT_KEYS`' default self scoping matches TRANSFORMED's `instance_id` — the face-name gate is implicit since the ability only exists on the object while it's that face). +5 (Huntmaster of the Fells, Ulrich of the Krallenhorde, Ashling Rekindled, Brigid Clachan's Heart). **"when ~ enters and at the beginning of your first main phase"** (Crack in Time) — `_ENTERS_AND_MAIN_PHASE_RE` → one self `ENTERS_BATTLEFIELD` spec + one controller-scoped `STEP_BEGIN` (`filter={"step":"main1"}`, `phase_relation="you"`) + the O-Ring companion LEAVES_BATTLEFIELD return. **Call for Aid** — the mass gain-control body's two anti-abuse riders: "you can't sacrifice those creatures this turn" (`GainControlUntilEndOfTurnEffect.mark_no_sacrifice` stamps `GameObject.cant_be_sacrificed_this_turn` on each taken creature — no separate "which objects" plumbing; checked at `RulesEngine.sacrifice` / `_sacrifice_candidate` / `_sacrifice_cost_choice`, cleared at cleanup) and "you can't attack that player this turn" (new `PreventAttackingPlayerThisTurnEffect` reads the shared opponent target → `GameState.no_attack_pairs_this_turn`, enforced in `GameEngine._can_attack` against the *assigned* defender only, cleared at cleanup). **Shackles of Treachery** — `_DAMAGE_TRIGGER_RE` now accepts a bare "deals damage" (no "to a …" — the whole recipient clause optional; empty filter = any damage instance), and a new `equipment_attached_to_source` target kind + `_destroy_equipment_attached_to_it` handler cover the granted quoted trigger's "destroy target Equipment attached to it" ("it" = the granted-to creature, i.e. the granted ability's source). **The BACKLOG bullet is deleted — the `gain_control_until_eot` / exile-until-leaves grammar is complete.** `tests/test_par30_cast_this_spell_trigger.py`, `test_par30_transform_trigger.py`, `test_par30_enters_and_phase_trigger.py`, `test_par30_call_for_aid_riders.py`.
- **Files:** `parser/oracle/catalogue/handlers.py`, `parser/oracle/segmenter.py`, `parser/oracle/gate.py`, `game/effects.py`

### Combined "basic Island, Swamp, or Mountain card" search criteria (Game Engine / Turn Loop & Actions)

- **What:** `_SEARCH_CRITERIA`'s `basic`/`types` groups (previously mutually exclusive) widened to combine freely, closing the Panorama/Landscape/Monument tri-land fetch cycles. Combined with `_SACRIFICE_THEN_WHEN_YOU_DO_RE` (below) for Maestros Theater's own cycle. +94 cards combined.
- **Files:** `parser/oracle/catalogue/handlers.py`

### "Each creature deals N damage to its controller" selector (Game Engine / Turn Loop & Actions)

- **What:** New `DealDamageEffect` selector `"each_creature_controller"` (Rakdos Charm's third mode) — recipient varies per creature (N independent hits) rather than one amount fanned to a fixed group.
- **Files:** `game/effects.py`

### Liliana, Dreadhorde General's −9: `count="all_but_one"` sacrifice sentinel (Game Engine / Turn Loop & Actions)

- **What:** "Each opponent chooses a permanent they control of each permanent type and sacrifices the rest" — six independent `sacrifice` calls (one per permanent type), sequenced via RULE 608.2's existing deferred-effects idiom, resolved against the *live* candidate count at each call.
- **Files:** `game/rules_engine.py`, `game/ability_catalogue.py`
- **Why:** A multi-typed permanent kept by one type's cut can still be swept by another type's cut in this model — real rules let the same permanent count as the kept pick for two types at once; unobservable on a single-typed board.

### `look_top_select` (Game Engine / Turn Loop & Actions)

- **What:** `RulesEngine.look_top_select`/`LookTopSelectEffect` — "Look at the top N cards. Put M of them into your hand and the rest `<destination>`." (Anticipate/Dig Through Time-shaped) — the fixed-selection-count sibling of scry/surveil's per-card decision: a two-phase choice, pick exactly M for hand, then (only "in any order") order the rest before it goes to the rest destination. Closed 40+ cards.
- **Files:** `game/rules/search_mixin.py`, `parser/oracle/segmenter.py`

### `return_to_library` (RULE 701.3) + mass `ReturnToHandEffect` (Game Engine / Turn Loop & Actions)

- **What:** `RulesEngine.return_to_library`/`ReturnToLibraryEffect` — "put target creature on top/bottom of its owner's library" — closing 10 cards (Time Ebb, Griptide, Roil Spout). `ReturnToHandEffect` also gained `selector`/`filter` mass "return all X" support (`DestroyEffect`'s own shared selectors reused) for Displacement Wave.
- **Files:** `game/rules_engine.py`, `game/effects.py`
- **Bug fixed:** RULE 903.9b's commander-zone redirect prompt hardcoded a `zone != Zone.HAND` check for German grammatical gender, silently mis-declining Hand's own feminine article; replaced with an explicit `_COMMANDER_ZONE_FEMININE` set the new Library label joins correctly.

### Intuition: two-player interactive search (Game Engine / Turn Loop & Actions)

- **What:** `IntuitionEffect`/`RulesEngine.request_intuition` — two chained `pending_choice`s: the caster picks three cards, then a real RULE 115 target (an opponent) chooses one for the caster's hand, the rest to graveyard. Not composable from `request_search`, whose single `destination` can't express "hold aside for a second player's pick."
- **Files:** `game/rules/search_mixin.py`, `game/ability_catalogue.py`

### Ral, Monsoon Mage: `CoinFlipEffect` (RULE 705.1) (Game Engine / Turn Loop & Actions)

- **What:** `CoinFlipEffect` branches into `win_effects`/`lose_effects` off `RulesEngine.coin_flip` — a reproducible RNG primitive that existed but had no consumer anywhere until this card. Win branch reuses `exile_return_transformed`; lose branch reuses `DealDamageEffect`'s `selector="controller"`.
- **Files:** `game/effects.py`, `game/ability_catalogue.py`

### MEC-21: "exiled with ~" tracker (Game Engine / Turn Loop & Actions)

- **What:** `GameObject.exiled_with_ids` (an accumulating list, stamped by `ExileEffect(track_exiled_with=True)`) generalizes the single-slot `linked_exile_id` for a repeatable "exile a card from a graveyard" ability — ~185 cache-wide cards print this shape and can reuse the tracking without their own bespoke field. A consumer re-resolves each id and confirms it's still genuinely in exile.
- **Files:** `game/effects.py`, `models/game_object.py`

### MEC-23: resolve-time single-target ability-borrowing snapshot (Game Engine / Turn Loop & Actions)

- **What:** `GainActivatedAbilitiesOfTargetEffect` (Quicksilver Elemental) is the resolve-time, single-target sibling of MEC-21's standing layer-6 grant: at resolution it reads a target's `activated_abilities` once, redirects each via the existing `_retarget_effect_source`, and appends onto a new turn-scoped `GameObject.temp_granted_activated_abilities` field unioned into the same `granted_activated_abilities` property every consumer already reads. A later change to the target's own abilities doesn't retroactively change what was copied.
- **Files:** `game/effects.py`, `models/game_object.py`

### Control of a Spell on the Stack (Commandeer)

- **What:** `GameContext.gain_control_of_spell`/`GainControlOfSpellEffect` — RULE 608.2m/111.5's owner/controller split applied to a still-stacked spell: only `StackItem.controller_id` moves, so it resolves into a permanent under the new controller for free. Optional retarget runs before the control flip so RULE 115.4a's "you"/"your" still reads against the original caster.
- **Files:** `game/effects.py`.

## Multiplayer

### Multiplayer priority primitive → real RULE 117 loop

- **What:** `GameEngine.pass_priority(player)` originally added groundwork-only APNAP handling (record pass, hand to next player, resolve top of stack once all pass, RULE 117.3b reset). It was later actually *driven*: `GameSession.interactive_priority` (on only for MULTIPLAYER) makes `_run_step` only place triggers instead of auto-draining the stack, a no-priority step clears the holder, and `GameSession._pass_priority` supplies RULE 117.4's "all passed on an empty stack ends the step" branch, which the engine itself can't reach since it doesn't drive the turn.
- **Files:** `game/game_engine.py`, `services/game_session.py`
- **Why:** Built as an opt-in flag rather than a rewrite so every solo/goldfish path keeps auto-draining unchanged (2,300+ existing tests passed through untouched). Consequence: there is no "advance the turn" action in a shared game — only the priority holder may act, enforced in `_dispatch` itself (not just filtered from `legal_actions`), except RULE 509.1a's defending-player exemption.

### Lobby layer — rules-free people/tables model

- **What:** `services/lobby.py` models `LobbyPlayer` (id/name/presence) and `LobbyGame` (seats/status/observers) with zero imports from `game/`. Presence is `online`/`available`/`playing`, with `playing` derived from holding a seat rather than settable; a seat's `ready` flag clears on any table change.
- **Files:** `services/lobby.py`

### Multiplayer session bridging

- **What:** `api/multiplayer.py` resolves each seat's saved deck the same way `api/game.py` resolves a goldfish deck (same `expand_entries`, same legality gate); `Lobby.start()` takes an already-built `GameSession` id, and `build_multiplayer_engine` is the N-player sibling of `build_goldfish_engine` (no passive dummy seat, seat order is turn order).
- **Files:** `api/multiplayer.py`, `services/game_session.py`

### Per-seat mulligan setup

- **What:** `GameSession`'s single setup-complete flag became a per-seat pending set, and mulligan count became per-player, so every seat mulligans independently in parallel.
- **Files:** `services/game_session.py`

### Actor-attributed actions

- **What:** `apply_action(action, actor_id=...)` — the engine's existing per-player rules validation (RULE 601.3a timing, "the attacking player does not declare blockers") does the legality work for a non-active seat for free, with no second drifting rules list in the session layer.
- **Files:** `game/game_engine.py`, `services/game_session.py`

### Hidden-zone redaction (RULE 400.2)

- **What:** `GameSession.view(perspective=...)` strips every other player's hand and every player's library from the payload (keeping only counts), routes a pending choice only to the addressed player (others see a "waiting_on_choice" marker), and `observer_view()` applies the same redaction against a perspective matching nobody.
- **Files:** `services/game_session.py`

### Concede with deferred board cleanup (RULE 104.3a, 800.4a)

- **What:** Concede is legal at any time, bypassing timing gates; the RULE 800.4a board cleanup (removing the conceded player's objects) is deferred onto `GameState.pending_leave_ids` and swept when the next turn begins, so a concession doesn't yank a board away mid-turn.
- **Files:** `game/rules_engine.py`, `game/game_engine.py`

### Seat reclaimed by player name, not server id

- **What:** Lobby identity keyed off `normalize_name(name)` rather than the server-issued id, since name is the only handle that survives a page reload — reconnecting with the same Profil name walks back into the same seat mid-game. Two people sharing a name are deliberately the same player, and the second connection takes the seat over.
- **Files:** `services/lobby.py`

### Disconnect grace period

- **What:** `Lobby.disconnect` marks a player absent and starts a grace period (default 90s) rather than dropping them; meanwhile `pass_for_absent_players` passes priority for them so the table keeps moving; letting the grace lapse concedes for them.
- **Files:** `services/lobby.py`, `api/multiplayer_ws.py`

### Idle priority-holder timeout

- **What:** A player holding priority who stays silent past a configurable idle timeout (default 120s) has their socket closed — not to police slow play, but because a tab that died without closing cleanly would otherwise hold the table forever. Both this and the disconnect timer are swept once a second from the app lifespan.
- **Files:** `api/multiplayer_ws.py`

### `/ws/lobby` presence + per-participant push

- **What:** One socket per client doubles as the presence signal and the push channel; after any move it sends each participant their own redacted view rather than one shared payload; a `disconnected` frame tells a dropped client why (idle/replaced/timeout) before closing.
- **Files:** `api/multiplayer_ws.py`

### Finished-table cleanup

- **What:** `Lobby.leave` now drops a FINISHED table the same way it already did a SETUP one, instead of leaving a played-out table sitting in every remaining player's lobby list until the last socket died.
- **Files:** `services/lobby.py`

### Per-seat take-back (undo) budget

- **What:** A table-configured, host-set/capped undo convenience distinct from `rewind` — legal regardless of priority (same exemption as concede), scoped to the caller's own most recent `_history` entry, discarding it and everything after since there's only one shared timeline.
- **Files:** `services/game_session.py`
- **Why:** History entries now carry an actor id; slicing both `_history` and `move_log` by a tail-relative depth (not a front-based index) is required since `_history` trims past `MAX_HISTORY` but `move_log` never does, so the two lists can differ in length.

### Tables of two to four seats (PLR-2)

- **What:** `services/lobby.py`'s `MAX_SEATS` raised from 2 to 4 (plus an explicit `MIN_SEATS=2`) — the whole backend change, since the engine had already been N-player throughout (`build_multiplayer_engine`, turn rotation, per-seat redaction, deferred-leave sweep were already generalized). Four is a UI readability cap, not a rules limit.
- **Files:** `services/lobby.py`

### Random seating / random starting player (RULE 103.1/103.2)

- **What:** Two independent host-set table options (`randomize_seating`, `random_starting_player`) applied once by `LobbyGame.seating_order()` at game start. Seating shuffles the ring; starting-player choice rotates it instead of reshuffling, so picking a different start doesn't disturb who sits next to whom.
- **Files:** `services/lobby.py`, `api/multiplayer.py`

### Seat banner colours

- **What:** `Seat.banner_color` lives in the lobby (not the `GameState`) since it must be visible in Setup before a game exists; normalized rather than validated (any WUBRG subset collapses to a canonical key, anything else becomes grey "colourless"), doesn't clear a seat's acceptance when changed, and defaults to the picked deck's colour identity unless explicitly chosen.
- **Files:** `services/lobby.py`, `api/multiplayer.py`

### Face-down-in-exile redaction (PLR-3, RULE 400.2)

- **What:** A card exiled face down (RULE 701.20a, Beseech the Mirror-shaped) sits in an otherwise-public zone, so whole-zone redaction didn't cover it. New `_redact_face_down_exile` resets a fixed set of identity fields to an "unknown card" placeholder for every non-owning viewer, while keeping `instance_id`/zone info real so the board still renders a face-down tile in place.
- **Files:** `services/game_session.py`

### In-progress UI selection survives a reconnect (PLR-6)

- **What:** A mid-cast targeting sequence or half-assembled block lived only in frontend state, so a reconnect had nothing to rebuild from. New `GameSession._ui_drafts` (opaque, size-capped per player), a quiet `POST /api/game/{id}/ui-draft` that deliberately skips the broadcast path, surfaced back via `view()`'s `ui_draft` field, and cleared automatically by that same player's next real action.
- **Files:** `services/game_session.py`, `api/game.py`
- **Bug fixed:** Investigating this found the more common trigger: `gameBoardView.js`'s `applyView` unconditionally wiped the local draft on *every* pushed view, including another player's socket merely reconnecting — one player's wifi blip was nuking everyone else's in-progress selection.

### A `ping` counts as liveness too (PLR-5)

- **What:** The idle watchdog only reset a player's `last_action_at` from a real game action, so a player genuinely still at the table but just thinking got disconnected-and-immediately-reconnected for no real absence. `/ws/lobby`'s existing `ping`/`pong` keepalive now also calls `lobby.touch(player_id)`.
- **Files:** `api/multiplayer_ws.py`

### `move_actors` — a move/priority feed (VIS-5)

- **What:** `move_log` had labels but no actor, so a shared-board "Bob played X" feed had nothing to build from. `GameSession.view()` gained a parallel `move_actors` list, derived by zipping `move_log`'s tail against `_history`'s tail (which already carries an `actor_id` per entry) — no new bookkeeping needed since the two lists are always appended/trimmed together at every call site.
- **Files:** `services/game_session.py`

### Client-Token Identity Stub (PLR-4)

- **What:** A browser that has saved a Profil name gets a random `crypto.randomUUID()` client token (`mtg_client_token` cookie, sliding 90-day validity), letting two browsers sharing a display name stay distinct players instead of merging into one lobby seat.
- **Files:** `frontend/src/js/settings.js`, `backend/mtg_analyzer/services/lobby.py`, `api/multiplayer_ws.py`, `api/schemas.py`.
- **Why:** `Lobby.connect`'s reclaim order becomes `player_id` -> `client_token` (if present) -> `name` (legacy, only when no token) — once a token is presented, name is never consulted, which is what stops the collision. The token is deliberately excluded from `LobbyPlayer.to_dict()` since the lobby snapshot is broadcast to every connected client and leaking it would let an opponent replay it.
- **Bug fixed:** N/A — new capability, not a fix.

### Client-Token Expiry & Asset Purge (PLR-4)

- **What:** `Lobby.expired_token_players()`, swept once a second, forgets a client token unused for 90 days (`MTG_CLIENT_TOKEN_VALIDITY`) — never while connected or mid-game — and purges that name's uploaded sleeves/token-art/favorites via `PlayerAssetStore.delete_all_for_player` only if no other still-recognized player shares the display name.
- **Files:** `backend/mtg_analyzer/services/lobby.py`, `api/multiplayer_ws.py` (`sweep_once`).
- **Why:** The `name_in_use_by_other` guard exists because two browsers can now legitimately share a display name at once — without it, one stale browser expiring would delete a still-active namesake's uploads.

## Bots

### Bot plays through the client surface only

- **What:** A bot reads `GameSession.view(perspective=<its own id>)` — the same RULE 400.2-redacted payload a browser gets — and submits only entries from its own `legal_actions` via `apply_action(actor_id=...)`; it never reads `engine.state` directly, so the engine's per-player validation is what makes it legal, and every bot game doubles as a redaction test.
- **Files:** `services/bots.py`

### Bot base class — fixed decision order, policy hooks

- **What:** `Bot.decide()` fixes the order a seat must handle things in (pending choice, then setup/mulligan, then RULE 509.1a declare-blockers, then `play()` only if holding priority); subclasses override only policy (`setup`/`answer_choice`/`blocks`/`play`/`rank_targets`). `pick_targets()` respects count/"up to"/`distinct_controllers` and returns `None` (skip) rather than posting an illegal pick.
- **Files:** `services/bots.py`

### Bots driven externally by `run_bots`

- **What:** `run_bots(session, bots)` applies one action at a time, called after any human action, right after `lobby.start()` (so a bot keeps its opening hand before humans see the mulligan screen), and once a second from the sweeper — which is what drives an all-bot table. Runs before the broadcast so a human move and every bot response reach clients as one push.
- **Files:** `services/bots.py`, `api/multiplayer.py`, `api/multiplayer_ws.py`

### Failed bot action doesn't wedge the table

- **What:** If a bot's chosen action raises `GameActionError`, the bot records that offer's signature to avoid re-picking it and passes priority instead (always legal) — keeps an unmodeled card corner from hanging a game instead of just skipping a play.
- **Files:** `services/bots.py`

### GreedyBot policy

- **What:** Attacks with everything first, then in its own main phase plays a land, taps for its scarcest colour, casts/activates cheapest-first (never `{X}`=0), blocks by spreading untapped creatures across attackers, and targets "opponent's things first."
- **Files:** `services/bots.py`

### Bot seats in the lobby

- **What:** A bot is an ordinary `LobbyPlayer`/`Seat` (plus `Seat.bot_kind`, opaque to the lobby) so the rules engine never learns bots exist; a bot seat with a deck counts as ready, is excluded from presence sweeps, and a table whose last human leaves is dropped along with its bots. The host acts for a bot (`add_bot`/`remove_bot`/`set_deck`).
- **Files:** `services/lobby.py`, `api/multiplayer.py`

### Cast-action `mana_value` exposed

- **What:** `GameEngine._cast_action` now carries `mana_value` alongside `has_x`/`max_x`, so a client (or a bot ranking casts cheapest-first) can order offered casts by cost without re-deriving it.
- **Files:** `game/game_engine.py`

### `ManaMaximizerBot`

- **What:** A diagnostic bot that plays a land every turn and taps every remaining mana source dry but never casts or attacks, added so the "mana produced" simulation metric reads as the board's true per-turn ceiling instead of being bottlenecked by a real bot's casting policy. Registered in the shared `BOT_TYPES` registry, so it's automatically offered everywhere a bot kind is picked.
- **Files:** `services/bots.py`

### GreedyBot: explicit main-phase development loop (PLR-7/PLR-8)

- **What:** `GreedyBot._develop_board` now tries a land, then `_cast_or_activate`, falling back to manual `tap_for_mana` only once neither offers anything, re-checking `legal_actions` fresh after every action rather than assuming a fixed plan.
- **Files:** `services/bots.py`

### GreedyBot: casting leans on mana-potential auto-tap (PLR-7/PLR-8)

- **What:** A cast/activate offer is only made once real pool or mana-potential can pay for it, and applying it auto-taps the exact needed sources — replacing the bot's old "tap everything first" behaviour, which could strand the wrong colour exactly like a human clicking lands one at a time.
- **Files:** `services/bots.py`

### GreedyBot: Equip/Fortify/Reconfigure sort last (PLR-7/PLR-8)

- **What:** `ActivatedAbility` gained an `attach_kind` field (set by the keyword-activated-ability binder, surfaced on the `activate_ability` action) so the bot can push an equip-family offer behind every other ability without guessing from description text.
- **Files:** `game/effect_binder.py`, `game/engine/legal_actions_mixin.py`, `services/bots.py`

### `RulesEngine.predict_land_tapped` + land-untapped preference (PLR-7/PLR-8)

- **What:** A read-only preview of RULE 614.1's enter-tapped outcome for every deterministic check/fast/slow/Battlebond land shape, surfaced on the `play_land` offer as `enters_tapped`; `GreedyBot._pick_land` sorts known-untapped ahead of unknown ahead of known-tapped.
- **Files:** `game/rules_engine.py`, `game/engine/legal_actions_mixin.py`, `services/bots.py`

### GreedyBot: weakest-opponent targeting in a 3+ pod (PLR-7/PLR-8)

- **What:** `_attack` used to take the first player-kind defender in whatever order was returned — fine at 2 players, arbitrary at 3-4. New `_weakest_defender` breaks the tie by life total already present in the view.
- **Files:** `services/bots.py`

## Replay/Puzzle Mode

### Replay / Puzzle mode

- **What:** Build an arbitrary 1-2 player board and play from it. Reuses `GameSession` with `mode="replay"`/`require_setup=False`; a family of `edit_*` actions mutate state directly (move objects across zones, tap, transform, set counters/life/poison/player-counters/commander-damage/turn-phase). Save/load uses a re-resolvable JSON descriptor since models have no `from_dict`.
- **Files:** `services/game_session.py`, `services/replay.py`
- **Why:** Poison (new `Player.poison`, 10 → SBA loss) and generic player counters (energy/experience, `Player.counters`) were added here specifically to support Replay editing of any board state.

### Replay/Puzzle mode: 3-4 player pods

- **What:** `blank_replay` was capped at 2 players even though the turn engine and Multiplayer both already support up to 4 seats. Raised the cap to `[1, 4]`, naming blank seats "Du"/"Gegner 1-3"; the play-mode board needed no engine change since it already runs the same `GameSession`/`gameBoardView.js` Multiplayer uses at 3-4 seats.
- **Files:** `services/replay.py`

## Oracle-Text Parser Front-End

### Parse-on-load memoization

- **What:** `parse_oracle` is called once per `GameObject` built, so a popular card was re-parsed from scratch on every copy/every game. The public entry point now memoizes its `ParseResult` in a content-keyed (not name- or identity-keyed) module-level dict and returns a deep copy per call.
- **Files:** `parser/oracle/gate.py`

### Class level-header regex fix (RULE 716.3)

- **What:** `CLASS_LEVEL_RE` assumed "Level N: `<cost>`" but every real Class card prints the cost first ("{3}{W}: Level 2") — the regex had never matched a single real card, only backwards-ordered test fixtures. Fixed the regex direction and the fixtures.
- **Files:** `parser/oracle/catalogue/levels.py`
- **Bug fixed:** A correctness fix with no immediate coverage gain — all 9 real Class cards remained `UNMODELED` on other unrelated gaps, but the level-header line itself is now a prerequisite correctly claimed.

### Full-universe card-pool import and coverage ledger

- **What:** Bulk-loaded the full ~34k-card Scryfall Oracle universe into a persistent `RawCardStore`, with coverage measured/ranked by `scripts/coverage_report.py` against a persistent engineering ledger that only re-parses changed cards.
- **Files:** `scripts/import_bulk.py`, `services/raw_card_store.py`, `services/coverage_db.py`

### Self-reference fold ("this creature" normalization)

- **What:** `normalize._fold_self_reference` folds modern templating's "this creature"/"this permanent"/"this artifact"/etc. to the same `~` the card-name fold already emits, so every handler that accepts `~` covers the "this `<type>`" phrasing uniformly, deliberately excluding "this spell"/"this card"/"this ability" and the structured Saga/Class self-references.
- **Files:** `parser/oracle/normalize.py`

### Stickers (RULE 123) Declared Permanent Non-Goal

- **What:** The parser gate now recognizes any card mentioning "sticker" and fails closed with a new `NEVER_SUPPORTED` verdict distinct from `UNMODELED`, so it contributes zero backlog/processing-list noise instead of perpetually cluttering the coverage ranking.
- **Files:** `parser/oracle/gate.py`, `parser/oracle/processing_list.py`, `services/coverage_db.py`, `scripts/coverage_report.py`
- **Why:** No handler will ever claim Sticker text, so leaving it as ordinary `UNMODELED` would permanently pollute the "what to build next" ranking.

### Oracle-Text Parser Front-End — Phase 0/1 Bootstrap

- **What:** First two phases of the two-stage oracle-text compiler: a keyword catalogue mapping all RULE 702 keywords to their `AbilitySpec` shape, plus an effect-clause front-end (`normalize`/`segmenter`/`catalogue/handlers`/`gate.parse_oracle`) producing `AbilitySpec`s and a fail-closed `MODELED`/`UNMODELED` verdict. `ability_catalogue.specs_for` falls back to it for unregistered, fully-`MODELED` cards. Ships handlers for damage/draw/discard/gain_life/destroy/counter/mill/exile/tap/+1-1 counters/token creation, static anthem/lord clauses, landwalk binding, replacement binding (`prevent_damage` first), parametric keywords, pump, and scry, plus activated-ability `<cost>: <effect>` parsing.
- **Files:** `parser/oracle/normalize.py`, `parser/oracle/segmenter.py`, `parser/oracle/catalogue/`, `parser/oracle/gate.py`, `game/ability_catalogue.py`
- **Why:** A card only ever gets parsed effects when fully `MODELED` — never half-resolved — which is what makes `gate.parse_oracle`'s coverage verdict the safety boundary for the whole front-end.

### Battle oracle-text recognition

- **What:** `normalize._SELF_REFERENCE_RE` folding "this battle"/"this Siege" to `~` alone unlocked most of the 12/39 cached battles that reached MODELED; three shared-grammar widenings came along with it — "any **other** target," "target creature an opponent controls / you don't control," and discard subjects (target opponent/each player/each opponent).
- **Files:** `parser/oracle/normalize.py`, `parser/oracle/catalogue/handlers.py`
- **Bug fixed:** the discard handler never passed a `target_kind` through, so "target player discards a card" had been making the *source's controller* discard instead of the named player.

### Inline "gets +1/-1 or -1/+1" split into two abilities (RULE 700.2)

- **What:** `segmenter._inline_pt_modal_bodies` rebuilds a compact "or"-joined full P/T clause pair into two complete activated abilities (Pemmin's Aura), only tried after the ordinary parse fails and only on two full P/T clauses.
- **Files:** `parser/oracle/segmenter.py`

### Alchemy `A-` self-name folding fix (PAR-4)

- **What:** `normalize._fold_self_name` now also folds an `A-`-stripped sibling of every name form it tries, so an Arena-rebalanced card's oracle text (which self-refers by the un-prefixed name) resolves its own pronoun correctly. Found via A-Thran Portal; fixed 16 more Alchemy cards for free.
- **Files:** `parser/oracle/normalize.py`

### `is_registered` DFC/split coverage-lookup fallback (Hobbits batch)

- **What:** `ability_catalogue.is_registered` didn't share `specs_for`'s own DFC/MDFC/split "//" front-face fallback, so a card registered under its front face alone reported UNMODELED when looked up by its full combined name — despite binding correctly in every real game.
- **Files:** `game/ability_catalogue.py`

### `normalize`: leading "Until end of turn, `<body>`." fold

- **What:** Folds the less-common leading-duration phrasing (Triumph of the Hordes-shaped) into the far more common trailing "`<body>` until end of turn." every duration handler already expects. Deliberately conservative — single-sentence lines only, a leading duration wrapping a quoted granted ability is left unclaimed.
- **Files:** `parser/oracle/normalize.py`

### `_COST_LOOKS_REAL` exile-from-hand cost recognition

- **What:** "Exile this card from your hand: Add `<mana>`." (Simian/Elvish Spirit Guide) was unclaimed purely because the cost-shape sniff's recognized-cost-verb list never included "exile from your hand" — the RULE 605.1a hand-zone mana-ability engine primitive already fully existed.
- **Files:** `parser/oracle/segmenter.py`

### Mana-ability coverage-classification fix for Bloom Tender (Oracle-Text Parser Front-End)

- **What:** Bloom Tender was already fully playable but scored `UNMODELED` because the segmenter's mana-ability claim check only recognized an effect line starting with "add"; Bloom Tender's "for each color…, add…" puts "add" mid-sentence. New `_COLORS_AMONG_PERMANENTS_MANA_RE` mirrors the `game/` regex.
- **Files:** `parser/oracle/segmenter.py`

### General Count-Amount Resolver (MEC-27 origin)

- **What:** "X is the number of `<noun phrase>` you control" folded into the existing `subgrammars.DEVOTION` fragment (not a parallel constant), so every handler already embedding `{DEVOTION}` (pump/damage/life-loss/token-count families) picks up the reading for free; closed 446-card-scale gap for the plain noun-phrase cases (bare creatures/permanents/artifacts/lands you control, attacking/tapped creatures, one creature-type word, three two-word compounds). Qualified phrases stay unclaimed (residual filed as MEC-27).
- **Files:** `parser/oracle/catalogue/subgrammars.py`, `game/continuous.py`.

### Qualifier Grammar & Draw/Life Verb Families for Count-Amount Resolver (MEC-27)

- **What:** `DEVOTION` gained "creatures you control with power N or less/greater" and generalized "tapped `<type>` you control"; `DrawCardEffect` gained `amount_from_count_selector` plus six new devotion-scaled parser rows for bare/combined draw+life-gain+life-loss clauses.
- **Files:** `parser/oracle/catalogue/subgrammars.py`, `game/continuous.py`, `game/effects.py`.
- **Bug fixed:** A combined "draw and lose life" clause split by the generic " and " connector matched the first half against the plain `_lose_life_selector` row, whose `"x"` is the announced-X sentinel — crashed comparing a string to an int for a triggered ability with no X cost; caught by an execute test before shipping.

### Extra-Combat-Phase Regex Word-Order Widening

- **What:** `_EXTRA_COMBAT_PHASE_RE` widened to recognize the subject-first word order ("there is an additional combat phase after this phase") alongside the original ("after this phase, there is an additional combat phase").
- **Files:** `parser/oracle/catalogue/handlers.py`.
- **Bug fixed:** Surfaced a stale hand-authored `ability_catalogue.py` entry for Raiyuu, Storm's Edge (predating the extra-combat primitive, deliberately narrowed to "untap it" only) that silently shadowed the now-fully-correct parser reading; deleted rather than left to shadow the parser forever.

### Multi-Target Range Grammar & `PumpEffect.previous_subject` (ENG-30)

- **What:** The shared `_MULTI_TARGET_QUANTIFIER` gained a third alternative for "N or M" ranges, widening `tap`/`return_to_hand`/`return_from_graveyard`/`add_counters`/`pump` for free; `divided_damage` and pump's dedicated "up to two" rows got matching dedicated range rows. New `PumpEffect.previous_subject` mode (mirroring `TapEffect`/`ReturnToHandEffect`'s "They…" idiom) for two-clause "…1 or 2 target creatures…. They get/gain `<X>`." shapes.
- **Files:** `parser/oracle/catalogue/handlers.py`, `game/effects.py`.

### RULE 701.47/48 Amass — First Parser Handler

- **What:** "Amass `<Type>` N" ("amass Orcs 1"/"amass Zombies 2") had zero parser recognition even though the engine primitive (`AmassEffect`) already existed and was proven end-to-end via the hand-authored Orcish Bowmasters entry (MEC-42). New `_AMASS_RE`/`_AMASS_UNTYPED_RE` handlers reach it from real oracle text for the first time (+33 cache-wide cards) — the printed type word is always a plain "+s" trailing plural in real Oracle text, singularized and capitalized to match `AmassEffect`'s own convention.
- **Files:** `parser/oracle/catalogue/handlers.py`
- **Deliberately unclaimed:** a literal `{X}` sentinel ("amass Orcs X", Assault on Osgiliath/Barad-dûr) — `EffectRegistry.register("amass", ...)` forces `int(count)` at bind time, so emitting the sentinel would crash rather than resolve; the third-person "its controller amasses…" form (Azog, Moria's Ruin); and any "amass…, where X is…"-scaled count. Real remaining work, not silently modeled.
- **Tests:** `tests/test_amass_family.py`

### PAR-21: RULE 701 keyword-action audit + Connive/Discover parser handlers

- **What:** PAR-21 asked for the audit its RULE 702 half (195-row keyword catalogue) had already had — a walk of the full RULE 701 keyword-action list (CR 701.2–701.70, `docs/Reference/rules_wiki/`) against `catalogue/handlers.py`, confirming each has a **real** handler rather than an incidental `MODELED` verdict off an unrelated clause. Two clean wins fell out and were closed in the same pass: **Connive** (RULE 701.50) and **Discover** (RULE 701.57) each already had a shipped, registered engine effect (`effects.ConniveEffect` via the hand-authored Ledger Shredder entry; `effects.DiscoverEffect`, Cascade's sibling) but **zero parser recognition**. New handler rows: `connive_self_named` (`~ connives`) + `connive_self_pronoun` (`it/he/she connives`, `self_subject_only`), and `discover` (`discover <n>`, literal mana value). +30 real cache cards total, 0 regressed (`parser_probe.py` diff, full cache) — 16 Connive (the ETB/attack/cast trigger family), 14 Discover ("discover N." literal cycle: Trumpeting Carnosaur / Daring Discovery / Etali's Favor / the Hidden* land cycle / …).
- **Files:** `parser/oracle/catalogue/handlers.py`, `parser/oracle/gate.py` (PARSER_VERSION 104)
- **Deliberately unclaimed:** a Connive pronoun bound to an *earlier clause's* target ("target Villain you control gains menace. It connives.", Doctor Doom — `ConniveEffect` connives its own source, so this would connive the wrong permanent); "connive N" (RULE 701.50d) and "connives x" (the registered effect is the fixed draw-one/discard-one form); "discover X, where X is `<selector>`" (Pantlaza/Aloy — `DiscoverEffect` takes no dynamic amount).
- **Audit result — the genuine RULE 701 gaps** (no handler *and*, unless noted, no engine primitive; cache-wide solo-blocker counts from `parser_probe.py`): **Explore** (RULE 701.44, ~43 — a whole Ixalan mechanic, no primitive), **Connive N** (RULE 701.50d — effect needs a count param), **Populate** (701.36, ~22), **Bolster** (701.39, ~20) / **Support** (701.41, ~11), **Vote** (701.38, ~28 — voting subsystem), **Clash** (701.30, ~33), **Detain** (701.35, ~11 — goad-shaped designation), **Learn** (701.48, ~16), **Incubate** (701.53, ~25 — generic `incubate N` → Incubator DFC token; hand-authored per-card only today), **Face a Villainous Choice** (701.55, ~11), **Collect Evidence** (701.59, ~12 — additional-cost mechanic), **Suspect** (701.60, ~14 — menace + can't-block designation), **Forage** (701.61, ~5), **Endure** (701.63), **Blight** (701.68, ~13 — `blight N` = N -1/-1 counters on your creature; hand-authored per-card only), **Fateseal** (701.29, ~3 — scry's opponent-library mirror), **Time Travel** (701.56, ~3), **Behold** (701.4, ~6 — additional cost), **Harness** (701.64) / **Heal** (701.69) / **Recruit** (701.70), and the **Avatar bending quartet** — Airbend (701.65), Earthbend (701.66, ~18), Waterbend (701.67, ~11 — cost mechanic), plus the un-numbered firebend. Also parser-shaped (engine already fine): standalone **"double/triple target creature's power and toughness"** (RULE 701.10/11 — damage-doubling and token/counter-doubling are covered) and general **"exchange control / exchange life totals"** (RULE 701.12 — only per-card hand-authored today). All are filed as **PAR-29** in `BACKLOG.md`; none is a "keyword ability entirely absent from a registry" the way PAR-21's 702 half worried about — they are ordinary effect-grammar gaps, most needing a new engine primitive first.
- **Confirmed NOT gaps** (real handler verified action-by-action, not incidental): Attach, Counter, Create, Destroy, Discard, Exile, Fight, Goad, Investigate, Mill, Regenerate, Scry, Search, Shuffle, Surveil, Tap/Untap, Transform/Convert, Proliferate, Monstrosity, Adapt, Amass, Manifest/Cloak, Manifest Dread, Venture, The Ring Tempts You, plus the engine-action verbs with no oracle grammar (Activate, Cast, Play) and the variant-only ones handled by their subsystem (Planeswalk/Set in Motion/Abandon, Meld). Assemble (701.45) is explicitly out of the CR (Unstable); Open an Attraction / Roll to Visit (701.51/52) are the standing Attractions non-goal.
- **Tests:** `tests/test_par21_keyword_actions.py`

### RULE 604.3 characteristic-defining P/T — first oracle-text handler (PAR-20 follow-up, PARSER_VERSION 105)

- **What:** "`~`'s power and toughness are each equal to the number of `<X>`." (Maro / Molimo / Psychosis Crawler / Dakkon Blackblade / Ashaya-shaped) had no parser recognition — the engine layer for it (`continuous.recompute`'s 7a `pt_cda` pass, reading a `count_selector` for both power and toughness) shipped with the Ashaya batch (MEC-12) but was only ever reachable via a hand-authored catalogue entry. PAR-20 named this as its follow-up (1): check whether the two templates ("cards in your hand", "lands you control") generalize for free, else a small paired handler. They didn't. New `static_handlers._PT_CDA_RE` full-matches the clause and maps `<X>` against a **fixed whitelist** of phrases that already have a `continuous.count_selector` — `cards in your hand` (new selector `cards_in_your_hand`, the hand sibling of `cards_in_your_graveyard`), `lands you control`, `cards in your graveyard`, `creatures you control` — emitting `EffectSpec("pt_cda", {"affects": "self", "power_count": <sel>, "toughness_count": <sel>})`. Any other quantity phrase fails closed (a CDA reading an unmodeled quantity would silently define the creature 0/0).
- **Files:** `parser/oracle/catalogue/static_handlers.py`, `game/continuous.py` (`count_selector` — `cards_in_your_hand`), `parser/oracle/gate.py` (PARSER_VERSION 105)
- **Deliberately unclaimed:** `<type>` you control ("Islands you control", "artifacts you control", "differently named lands you control"), "creature cards in your graveyard", "cards in all graveyards", "cards in your opponents' graveyards" — each a different, unwired selector; the quoted-grant / land-animate shapes ("… becomes a creature and gains '~'s power and toughness are each equal to …'", Druid Class / Beorn's Hospitality) — those route through the quoted-grant path, not `static_effect_specs`.
- **Yield:** +20 real cache cards (`parser_probe.py` diff, full cache, 0 regressed) — Maro, Molimo, Psychosis Crawler, Dakkon Blackblade, Body of Knowledge, Soramaro, Sturmgeist, Battle Squadron, Crusader of Odric, Flora Colossus, Ulvenwald Hydra, Rubblehulk, and more.
- **Tests:** `tests/test_par20_pt_cda_family.py`

## Deck/Cube Playability Batches

### cEDH staples cube (Batches 13, 14, 25 and 26)

- **cEDH staples cube playability push (Batch 13):**
  - **What:** Five subagent waves (2 generic-parser, 3 hand-authored) raised the 611-card "cEDH staples"/"cEDH staples 2" cube pool from 185 to 271 playable cards, combining reusable parser/engine extensions (colour-restricted destroy/counter, Magecraft trigger family, `AbilitySpec.free_cast_condition`, non-mana activation costs, several layer-6 static families) with dozens of hand-authored catalogue entries (Mana Drain, Brainstorm, Toxic Deluge, Dockside Extortionist, and others).
  - **Files:** `game/ability_catalogue.py`, `parser/oracle/catalogue/handlers.py`, `parser/oracle/catalogue/static_handlers.py`
  - **Why:** Cards left unmodeled were each logged individually against a genuine engine gap (control-exchange, coin-flip, Soulbond/Mutate/Bargain) rather than half-modeled.
- **cEDH staples cube playability continuation (Batch 14):**
  - **What:** Direct-authored continuation raising the cube pool from 271 to 285 playable, centered on a "destroy/counter target X; its controller creates a token" cluster. New reusable pieces: `CounterCreateTokenEffect` (stack-side sibling of `destroy_create_token`), controller-scoped `nonland_permanent_you_control`/`_you_dont_control` target kinds, single-type artifact/enchantment target kinds, a bare "spells cost {N} more/less" parser (no type word), and `ReturnFromGraveyardEffect` library-top/bottom destinations plus a mana-value-scaled life-loss rider.
  - **Files:** `game/effects.py`, `game/targeting.py`, `parser/oracle/catalogue/static_handlers.py`
- **cEDH staples cube — Batch 25 + Batch 26 (43 cards):**
  - **What:** Made all 43 cards of the "cEDH staples cube" pool playable (2026-07-22), organized in six waves around shared primitives (state-tracking, mana, control/zones, naming+loop shapes, RULE 702 keywords, bespoke tail), then closed the nine documented residual simplifications in a same-day Batch 26 follow-up.
  - **Files:** `game/effects.py`, `game/rules_engine.py`, `game/ability_catalogue.py`

### Deck Batch: Wyleth Equip (Boros Voltron)

- **What:** Hand-authored the ~50-card "Wyleth Equip" Boros voltron commander deck (2026-07-17), shipping a batch of generic reusable Equipment/Aura payoff primitives alongside it rather than one-off card code.
- **Files:** `game/ability_catalogue.py`

### Enrage stragglers — hand-authored batch (11 cards)

- **What:** Closed the entire ~25-card Enrage population by hand-authoring the 11 cards still UNMODELED after the trigger fix, per explicit "do not defer" instruction — adding reusable selectors (`each_other_creature_you_control`, `each_creature_and_planeswalker`), new `opponent`/`opponent_or_planeswalker` target kinds, `DamageEqualToCountersEffect`, and `AddManaEffect.amount_from_trigger_event`, while documenting three deliberate simplifications (Indoraptor's escape clause, Vrondiss's token downside, Stalwart Speartail's perpetual-effect clause) as genuinely unsupported rather than approximated.
- **Files:** `game/ability_catalogue.py`, `game/effects.py`, `game/targeting.py`

### "Hobbits"/"Wyleth Equip" saved decks made fully playable

- **What:** User-directed batch closing 50 of 51 unmodeled cards across two saved Commander decks (Hobbits 42, Wyleth Equip 9) — every card's full ability set bound to real behaviour, not just parsed. ~30 cards hand-authored in `ability_catalogue.py`; the rest via several new general primitives (below). Frodo, Sauron's Bane was the one card left, closed in a dedicated follow-up.
- **Files:** `game/ability_catalogue.py`

### "Keywords Showcase" and "Eliferate" saved decks made fully playable

- **What:** User-directed batch: "Keywords Showcase" fully modeled (18/18); "Eliferate" reached 64/91 (remaining 27 genuinely bespoke — planeswalker loyalty bodies, trigger-doubling, Channel abilities, three separate "chosen type" payoff reads, a token-vs-copy replacement — deliberately left rather than half-modeled). Almost every fix started as "what does this one card need" and turned out to close a whole family. +239 cards, 0 regressions.
- **Files:** `game/ability_catalogue.py`, `parser/oracle/catalogue/handlers.py`

### "Eliferate"/"Imodane" saved decks made fully playable

- **What:** User-directed follow-up ("no deferrals"): closed Eliferate's remaining 27 cards and brought "Imodane" (69 unique cards, from-scratch) to full coverage. Both decks end fully playable: Eliferate 91/91, Imodane 69/69.
- **Files:** `game/ability_catalogue.py`

### The seven "cEDH"-named saved decks/cubes (MEC-12)

- **What:** A 700+-unique-card pool across Ojer cEDH, cEDH Rocco, [cEDH] Glarb Bloomsday, cEDH staples, cEDH staples 2, cEDH M-K and cEDH Kinnan, worked across ten passes (2026-08-06 through 2026-08-11) as ordinary open work rather than forced to one sitting given the size. Each pass below closed a batch of cards and, where noted, landed a reusable primitive.
- **The seven "cEDH" saved decks/cubes: first playability pass (MEC-12):**
  - **What:** Made the highest-frequency shared staples across all seven cEDH-named saved decks/cubes (393 unique cards combined) playable, tracked as ordinary open work across sessions rather than forced to one sitting. 13 real cards fixed this pass, each shared across 2-6 of the seven decks.
  - **Files:** `game/ability_catalogue.py`, `parser/oracle/segmenter.py`
- **The seven "cEDH" decks — third pass (Deck/Cube Playability Batches):**
  - **What:** Closed 436/764 unique cards across the seven cEDH-named saved decks/cubes (`MEC-12`), prioritizing highest deck-frequency cards. Combined a mana-ability coverage-classification fix, a RULE 118.7/601.2f cost-reduction generalization (colour/opponent-scoped spell tax, activation-cost group scope by type), Otawara hand-authored, Mindbreak Trap's free-cast condition, and Smothering Tithe hand-authored (see individual entries below).
  - **Files:** `parser/oracle/segmenter.py`, `parser/oracle/catalogue/static_handlers.py`, `game/continuous.py`, `game/ability_catalogue.py`
- **The seven "cEDH" decks — fourth pass (Deck/Cube Playability Batches):**
  - **What:** Closed 451/764 across the pool by working the unclaimed-clause list end to end rather than by frequency; landed several general primitives reused far past this pool (see below). ~300 cards remained, several needing whole new subsystems (devotion, a "players can't `<verb>`" family, broader pitch costs).
  - **Files:** `parser/oracle/segmenter.py`, `game/effect_binder.py`, `game/effects.py`, `models/card_query.py`
- **The seven "cEDH" decks — fifth pass (Deck/Cube Playability Batches):**
  - **What:** Closed six cards (Meltdown, Chord of Calling, Green Sun's Zenith, Finale of Devastation, Wishclaw Talisman, Ghostfire Slice), each landing a reusable primitive.
  - **Files:** `game/rules/misc_mixin.py`, `parser/oracle/catalogue/handlers.py`, `game/continuous.py`
- **The seven "cEDH" decks — sixth pass (Deck/Cube Playability Batches):**
  - **What:** Closed Mox Diamond, Mindbreak Trap, Eye of Ugin, Stonehewer Giant/Quest for the Holy Relic, Tainted Pact, and Transmute Artifact — all six previously-deferred gaps closed rather than rolled to a third deferral.
  - **Files:** `game/rules/misc_mixin.py`, `parser/oracle/catalogue/handlers.py`, `game/continuous.py`
- **The seven "cEDH" decks — seventh pass (Deck/Cube Playability Batches):**
  - **What:** Prioritized shapes generalizing well past the pool: the untap-cap family, Meekstone, RULE 115.4 change-target's first oracle-text handler, a power-qualified control-count static condition, spell-side self-cost-reduction, and "opponents can't cast during your turn."
  - **Files:** `game/continuous.py`, `parser/oracle/catalogue/static_handlers.py`, `parser/oracle/segmenter.py`
- **The seven "cEDH" decks — eighth pass (Deck/Cube Playability Batches):**
  - **What:** Closed Back to Basics, Auriok Salvagers, and Assassin's Trophy via three tightly-scoped, individually reusable primitives.
  - **Files:** `game/continuous.py`, `game/effects.py`, `game/targeting.py`, `parser/oracle/subgrammars.py`
- **The seven "cEDH" decks — ninth pass (Deck/Cube Playability Batches):**
  - **What:** Closed Slip Out the Back and Snapback/Pyrokinesis; investigated (but didn't build) Grafdigger's Cage/Weathered Runestone's zone-cast-restriction pair, finding it needs multi-site surgery across every graveyard-bound zone-transition call site, not an extension of the existing `_move_to_graveyard` choke point.
  - **Files:** `game/effects.py`, `parser/oracle/segmenter.py`
- **The seven "cEDH" decks — tenth pass: devotion, phasing, extra combat, remaining pitch costs (Deck/Cube Playability Batches):**
  - **What:** Closed the fourth pass's own "broader gaps, needs real design" list in one sitting — devotion (RULE 700.6), phasing an opponent's permanent as a spell effect, RULE 702.26b extra-combat grants, and the remaining RULE 118.9 pitch-cost shapes — each turning out to need only a well-contained gap fix, not a ground-up build.
  - **Files:** `game/continuous.py`, `game/static_conditions.py`, `game/effects.py`, `game/game_engine.py`, `parser/oracle/subgrammars.py`

### Marchesa V4.2 (saved deck, fully playable) (Deck/Cube Playability Batches)

- **What:** Closed all 21 `UNMODELED` cards of the 96-card Marchesa V4.2 saved deck via seven general parser handlers plus seven hand-authored entries. Coverage 31.83% → 32.22% (+134 cards), 0 regressions.
- **Files:** `parser/oracle/catalogue/handlers.py`, `game/ability_catalogue.py`, `game/effects.py`

### Vivi B4 (saved deck, fully playable) (Deck/Cube Playability Batches)

- **What:** Closed all 18 `UNMODELED` cards of the 99-card Vivi B4 storm-shell Commander deck (11 via general parser handlers, 7 hand-authored), several of the biggest single templates found to date. Coverage 32.23% → 32.6% (+145 cards).
- **Files:** `game/rules/search_mixin.py`, `parser/oracle/segmenter.py`, `game/effects.py`, `game/ability_catalogue.py`

### Kinnan/M-K Batch: New General Primitives (MEC-12)

- **What:** Completed `cEDH Kinnan` (100/100) and `cEDH M-K` (97/97), 31 unique cards, entirely hand-authored. Numerous new general primitives shipped along the way (each detailed as its own entry below): destroy/exile-then-controller-digs, still-on-stack bounce, forced retarget-to-source, blocker-side characteristic filter, mana multiplier, cost floor, control exchange of a spell on the stack, force-end-the-turn, standing exile-cast permission, aggregate combat-damage event widened with subtype/amount/commander fields, and several search/copy/delayed-trigger extensions.
- **Files:** `game/ability_catalogue.py` (per-card detail), various `game/` modules per primitive below.
- **Other Kinnan/M-K Primitives (searches, copies, delayed triggers, misc):**
  - **What:** A cluster of smaller reusable additions from the same batch: `ReturnToLibraryThenDigSharedTypeEffect` (dig for a card sharing a bounced permanent's own printed types); `card_query`'s `has_mana_ability`/`"or"` compound criteria; `EnterAsCopyReplacement.grant_mana_option` (re-granting a copy's overwritten mana ability); `ReturnSelfToBattlefieldEffect` via the existing RULE 603.7 delayed-trigger mechanism; `DiesReturnAsEnchantmentEffect` (RULE 613.4b characteristic-setting on return); `is_nth_draw_this_turn` trigger key; `RevealTopThenLandBattlefieldOrDrawEffect` chained after `scry`; `AbilitySpec.modes.optional` / `TriggeredAbility.modes_optional` (RULE 700.2's "choose up to one"); `source_x_paid` criteria sentinel for a search firing after the casting resolution ends; `PutFromHandOntoBattlefieldEffect.tapped` flag.
  - **Files:** `game/effects.py`, `game/effect_binder.py`, `game/rules_engine.py`.
  - **Bug fixed:** `StaticAbility(affects="self")` reads `ability.source`, not the permanent whose `static_effects` list it lives on — constructing one with no explicit `source=` silently affects nothing; hit twice (Enduring Vitality, Machine God's Effigy) before fixed both places. `EnterAsCopyReplacement`'s `ability_kind` must be `"enter_replacement"`, not `"static"`, or the ETB choice is never offered. `GameContext.change_target`'s wrapper was initially missing the new `redirect_to_source` parameter.

### "Return it to the battlefield under its owner's/your control" — direct oracle-text route (PARSER_VERSION 184)

- **What:** `ReturnSelfToBattlefieldEffect` (built above for the delayed-trigger shape only — Nezahal's own "exile ~, return it tapped … at the beginning of the next end step") gained `under_your_control` and `extra_counters` params, and a new `_RETURN_SELF_TO_BATTLEFIELD_RE` parser handler reaches it directly (no delay) from two real shapes: a *granted* DIES-trigger continuation via `_quoted_ability_grant_effects` — "target creature gains 'When this creature dies, return it to the battlefield tapped under its owner's control with a +1/+1 counter on it.'" (Feign Death, Undying Malice; the outer `_GRANT_QUOTED_ABILITY_UNTIL_EOT_RE` wrapper already existed, only the inner trigger body was unrecognised) — and a plain "exile ~, then return it to the battlefield under its owner's control" blink chain (Flicker of Fate, Aethergeode Miner, Changing Loyalty, Flickering Spirit, Fungal Fortitude, Planar Incision).
- **Files:** `game/effects.py`, `parser/oracle/catalogue/handlers.py`. `tests/test_par30_return_self_to_battlefield.py`.
- **Still open:** Demonic Gifts' compound "gets +2/+0 **and** gains '…'" wrapper (a different outer shape); "face down"/"flipped"/"transformed" destinations (Ashcloud Phoenix, Homura, Loyal Cathar); riders after the return ("…and you create a treasure token", a following "It deals 1 damage…" sentence).

### Ojer cEDH Batch: New General Primitives (MEC-12)

- **What:** Closed 26/28 previously-unmodeled cards (49/77 -> 75/77) in `Ojer cEDH`, mostly via new general parser/engine primitives (each below) plus hand-authored singleton entries (Manabarbs, Karn the Great Creator, Ojer Axonil, Cemetery Gatekeeper, Powerbalance, others).
- **Files:** `game/ability_catalogue.py`.

### Rocco Batch: Cast-Intervening-If and Cast-Zone Prohibition (MEC-12)

- **What:** Closed 4 cards in `cEDH Rocco` (74/98 -> 78/98). `GameObject.was_cast` (RULE 601.2, stamped at cast time, cleared on reset) + `EffectSpec.condition`'s `source_was_cast` key + a dedicated "When ~ enters, if you cast it, `<effect>`." parser row — closes **57 cache-wide cards** (the RULE 601.2b intervening-if distinguishing a real cast from a searched/reanimated/token entry). `continuous.cast_prohibited`'s new `hand_only` flag (Drannith Magistrate) forbids flashback/foretell/graveyard-cast attempts while allowing an ordinary hand cast. `continuous.max_noncreature_spells_per_turn` (Deafening Silence).
- **Files:** `game/rules_engine.py`, `models/game_object.py`, `game/effects.py`, `game/continuous.py`, `game/engine/casting_mixin.py`, `parser/oracle/segmenter.py`.

### Glarb Bloomsday Batch: New General Primitives (MEC-12)

- **What:** Closed 6 cards in `[cEDH] Glarb Bloomsday` (82/100 -> 88/100). Primitives: `AddManaEffect.color_from_source_chosen_color` (a triggered mana ability reading a live chosen-colour, Utopia Sprawl); a resolve-time quoted-ability grant reusing the Aura/Equipment quoted-grant parser wrapped in `GrantUntilEffect` for "gains '`<cost>`: `<effect>`.' until end of turn" (23 cache-wide cards, Retraction Helix); `ReturnToLibraryEffect`'s new self mode plus recognizing "look at the top N, put them back in any order" as the existing `scry` resolution (28 cache-wide cards, Sensei's Divining Top); `lands.py`'s "Sanctuary cycle" named-land-type-count variant plus `source_entered_untapped` condition key (Mystic Sanctuary); `type_change`'s "every basic land type" recognition (Dryad of the Ilysian Grove); `continuous.has_standing_flash_permission` (8 cache-wide cards, High Fae Trickster).
- **Files:** `game/ability_catalogue.py`, `game/effects.py`, `game/continuous.py`, `game/rules_engine.py` (lands module), `parser/oracle/catalogue/subgrammars.py`.
- **Bug fixed:** `subgrammars.py`'s "target nonland permanent" TARGET row mapped to the bare `"permanent"` kind (silently allowing lands too), even though a proper `"nonland_permanent"` kind existed at the engine level — it was never added to `targeting.ALLOWED_TARGET_KINDS`.

### "Enter as a copy, except …" family widened (MEC-12)

- **What:** `EnterAsCopyReplacement`/`Card.as_copy` gained four new "except" clause params, closing four `cEDH staples 2` cards at once: `only_types` (RULE 706.2's copiable types replaced wholesale rather than appended — "…except it loses all other card types", Imposter Mech, which also needed moving a no-longer-creature copy's power/toughness to the `vehicle_power`/`vehicle_toughness` slot, since `Card.__init__` refuses plain P/T on a noncreature); `add_keywords`/`add_keywords_if_target_lacks` (Imposter Mech's granted "Crew 3", Flesh Duplicate's "…except it has vanishing 3 if that creature doesn't have vanishing" — appended to both the bare `keywords` list, for `combat.keywords_of`'s evasion-keyword subset, *and* as a new `oracle_text` line, since a keyword needing its own bound ability, like Vanishing's upkeep trigger or Crew's activation, is only ever reached by `bind_from_catalogue` re-parsing text); `keep_own_abilities` (Sakashima of a Thousand Faces' "…except it has ~'s other abilities" — snapshots the object's own triggered/static/activated/replacement abilities before `become_copy` clears them per RULE 706.2, reattaches them after); and `max_mana_value_from_mana_spent` (Mockingbird's "…of any creature with mana value less than or equal to the amount of mana spent to cast this creature", reading `GameObject.mana_spent_to_cast` live when the choice is offered). Sakashima's own second clause, "the legend rule doesn't apply to permanents you control" (RULE 704.5j), is a new standing `ignore_legend_rule` static — `continuous.player_ignores_legend_rule`, consulted by `RulesEngine._apply_legend_rule` exactly like the existing `no_max_hand_size` permission static.
- **Bug fixed (generically scoped, not just Mockingbird):** `GameObject.mana_spent_to_cast` read `cost.converted_mana_cost`, which deliberately reports 0 for an unresolved `{X}` per RULE 202.3b's printed-cost model (`ManaSymbol.cmc`) — even *after* `ManaCost.with_x` resolves the symbol's `amount`, `cmc` still ignores it. Every `{X}` spell had therefore been under-tracking its own real spend since the field was added. Fixed at the source with a new `ManaCost.resolved_value` property (`converted_mana_cost` plus the resolved `{X}` amount) rather than patched at the one call site, so any other "how much mana was spent" reader benefits too. Also found: `Card.as_copy`'s first pass put a keyword's full parametric text ("Vanishing 3") into the bare `keywords` list, which `parser/oracle/catalogue/keywords.py`'s `parse_keywords` slug-matches verbatim against Scryfall's real convention (bare "Vanishing", no number) — silently failing every match. Fixed by keeping the list bare-name-only and pushing the parametric line into `oracle_text` instead, where the number is actually read from.
- **Also shipped in this batch:** RULE 702.61 **Vanishing**, previously parser-recognized but unbound (the same "recognized but inert" gap PAR-9/MEC-29 closed for Cycling/Crew) — `effect_binder._kw_vanishing`, sharing `RemoveCounterOrSacrificeEffect` with Fading via a new `sacrifice_on_last_removed` flag (Vanishing's RULE 702.61b has no Fading-style off-by-one: the removal that empties the last time counter sacrifices the permanent in that same upkeep, not the next one).
- **Files:** `models/card.py`, `models/mana_cost.py`, `game/effects.py`, `game/copy_mechanics.py`, `game/continuous.py`, `game/effect_binder.py`, `game/rules/casting_mixin.py`, `game/rules/sba_mixin.py`, `game/ability_catalogue.py`.
- **Tests:** `tests/test_enter_as_copy_family.py` (new), `tests/test_cedh_cube_keyword_mechanics.py` (Vanishing block).

### Plain "exile, then return" blink template + trigger-level "up to one" fix (MEC-12)

- **What:** `BlinkEffect`/`RulesEngine.blink` (RULE 400.7, already shipped for Ephemerate/Restoration Angel) had no oracle-text recognizer for the *plain* template — no subtype exclusion, "creature"/"permanent"/"nonland permanent", "another", "up to N" — only `_BLINK_NON_SUBTYPE_RE`'s narrower Restoration Angel shape existed. New `_BLINK_PLAIN_RE`/`_blink_plain` handler (`parser/oracle/catalogue/handlers.py`, PARSER_VERSION 93) closes it, plus `BlinkEffect` itself gaining `optional`/`count`/`count_max` (previously single-target-only) for Displacer Kitten's "up to 1". Closed 3 `cEDH staples` cards: Felidar Guardian (ETB, "you may", permanent, owner's control), Displacer Kitten (triggered off casting a noncreature spell, "up to 1", nonland permanent), Emiel the Blessed (hand-authored — its own activated-ability half reuses this same `"blink"` `EffectSpec`; its second ability is `pay_cost_then` wrapping a new `AddCountersEffect.amount_if_trigger_subject_subtype`/`_value` override for "put a +1/+1 counter on it. If it's a Unicorn, put two instead" — narrowly scoped to this one recurring "bonus for a named type" shape, not the still-open general "if X, A instead of B" primitive noted in `BACKLOG.md`'s kicker "instead" gap).
- **Bug fixed (generic, found building Emiel):** `context.trigger_event` is only live for a triggered ability's own *first*, synchronous `apply()` — `pay_cost_then`'s "if you do" branch runs later, after the interactive payment choice is answered, by which point that window has closed, so any effect trying to read "the trigger's subject" off `context.trigger_event` there silently found nothing. New `GameObject.remembered_instance_id` (a generic single-slot cross-resolution-gap memory, same shape as `linked_exile_id`) bridges it: `PayCostThenEffect.remember_trigger_subject=True` stamps the subject there at the live first call; `AddCountersEffect.trigger_subject_key="remembered"` reads it back on the deferred side.
- **Bug fixed (generic, found building Displacer Kitten):** RULE 115.1a's "up to one target" is a *target-level* optionality (`TargetSpec.optional`) distinct from RULE 603.5's *whole-ability* "you may" (`TriggeredAbility.optional`) — a mandatory trigger can still decline its own "up to one" target. The "no legal targets at all" fallback already read `spec.optional` correctly, but the interactive prompt-building call site (`RulesEngine._offer_trigger_target`'s single-spec branch) only ever consulted `ability.optional`, so a genuine "up to one" trigger with at least one legal target never actually offered a decline button — a latent bug on every such card in the pool, not just this one. Fixed by passing `allow_decline=spec.optional or ability.optional` through to `_trigger_target_choice`.
- **Ability word gap fixed:** "Avoidance —" (Displacer Kitten's own printed ability word) wasn't in `normalize._ABILITY_WORD_RE`'s hardcoded whitelist (`landfall`/`constellation`/`battalion`/`enrage`/`delirium`/`veil of time` only), so the whole clause stayed unclaimed regardless of the effect body parsing fine on its own. Added.
- **Files:** `game/effects.py`, `models/game_object.py`, `game/rules/triggers_mixin.py`, `parser/oracle/catalogue/handlers.py`, `parser/oracle/normalize.py`, `parser/oracle/gate.py` (PARSER_VERSION), `game/ability_catalogue.py`.
- **Tests:** `tests/test_blink_family.py` (new).

### Aven Mindcensor's search narrowing + a second "up to one" decline fix (MEC-12)

- **What:** RULE 701.19a-adjacent "If an opponent would search a library, that player searches the top N cards of that library instead." (Aven Mindcensor) — a *narrowing* sibling of the already-shipped `GrantSearchProhibitedEffect` (Stranglehold's outright "your opponents can't search libraries" block). New `GrantSearchLimitedToTopNEffect`/`grant_search_limited_to_top_n`, scanned by `RulesEngine._search_zone_objects` at the exact choke point `request_search` already scans for the prohibition — the library portion of the pool becomes just `library[-n:]` (the list end is the top of the deck, `.pop()`'s own convention) for anyone but the effect's own controller. Closes Aven Mindcensor in all three decks it appears in (`cEDH Rocco`/`cEDH staples`/`cEDH staples 2`) from one hand-authored entry.
- **Files:** `game/effects.py`, `game/rules/search_mixin.py`, `game/ability_catalogue.py`.
- **Tests:** `tests/test_search_restriction_family.py` (new).

### Pithing Needle / Phyrexian Revoker's free-text naming lock (MEC-12)

- **What:** RULE 601.2b's "as ~ enters, choose a card name" — but naming any Magic card rather than picking a creature type/colour/mode from an enumerable list, so it needed its own `enter_choice_effects` family member: `ChooseCardNameReplacement`, a free-text fourth sibling of `ChooseCreatureTypeReplacement`/`ChooseColorReplacement`/`ChooseNamedModeReplacement`. `RulesEngine._offer_enter_choices` offers the battlefield's own card names as suggestions only (`"free_text": True` on the `pending_choice`, the same convention `request_name_card` already uses for Demonic Consultation) and `resolve_enter_choice` accepts any string verbatim for this one kind rather than validating against the offered options, stamping `GameObject.chosen_card_name`. The static half is a new `card_name_from_source` selector param on `continuous.group_selector_objects` — the naming-choice sibling of the existing `subtype_from_source`/`color_from_source` params, consulted by the already-shipped `activation_prohibition` static (previously only ever scoped by a literal `card_type`/`affects`, never a per-instance chosen name). Phyrexian Revoker and Pithing Needle share the exact same two-clause shape (an `enter_replacement` naming choice + an `activation_prohibition` static reading it) and differ only in one rider: Revoker is unconditional (no `except_mana_abilities`, so naming a mana dork silences its mana ability too — matching its printed "Activated abilities … can't be activated" with no carve-out), Needle carries `except_mana_abilities: True` (its own printed "…unless they're mana abilities"). Revoker's printed "nonland card name" restriction on the choice itself isn't enforced — this engine's naming choices are never validated against real card data (`request_name_card` accepts any string the same way); naming a land simply matches nothing, the same as any other name absent from the board.
- **Files:** `game/effects.py` (`ChooseCardNameReplacement`, `_SELECTOR_KEYS`'s new `card_name_from_source` entry, the `"choose_card_name_on_enter"` factory), `game/continuous.py` (`group_selector_objects`'s new filter), `game/effect_binder.py` (routes the new replacement onto `enter_choice_effects`), `game/rules/casting_mixin.py` (`_offer_enter_choices`/`resolve_enter_choice`'s new `choose_card_name` branch), `game/engine/turn_loop_mixin.py` (dispatch), `models/game_object.py` (`chosen_card_name`, RULE 400.7 reset), `game/ability_catalogue.py`.
- **Tests:** `tests/test_named_lock_family.py` (new) — both cards' lock/carve-out behaviour plus the free-text choice mechanism itself end to end via a real cast (proving an answer outside the suggestion list is accepted, not just defaulted).

### Defense Grid / Suppression Field / Tithe Taker's "costs {N} more" tax family (MEC-12)

- **What:** RULE 601.2f/602's cost-*increase* side of the existing `cost_reduction` static, on both a spell's cast cost and an activated ability's own activation cost. Two latent gaps surfaced and were fixed at the root rather than worked around: (1) `continuous.cost_reduction_for` had never consulted a static's own `active_if` gate at all — `cost_floor_for`, the very next function in the same file, already did, for the same `"cost"` layer; needed for Tithe Taker's "**during your turn**, spells your opponents cast cost {1} more". (2) `activation_cost_reduction_for` only ever supported a *reduction* across three narrow, named scopes (`attached_permanent`/`subtype`/`card_type`) — any other `scope="activation"` static, including an outright tax, silently matched none of its branches and fell through the trailing `else: continue`. Widened to a genuine signed net (a negative result taxes) across five scopes (adding unscoped `all_permanents` — Suppression Field's unqualified "activated abilities cost {N} more…" — and `opponents_permanents`, the activation-cost mirror of `activation_prohibited`'s own opponents scope), an `is_mana_ability`/`except_mana_abilities` carve-out mirroring `activation_prohibited`'s identically-named rider, and the same `active_if` gate. `GameEngine._reduced_activation_mana` itself had a matching bug: `if reduction <= 0: return mana` silently discarded any tax outright rather than growing the cost — fixed to call `ManaCost.increase_generic` for a negative net, the same "positive reduces, negative increases" convention `CastingMixin._adjust_cost` already used spell-side. `is_mana_ability` had to be threaded through the whole activation-cost call chain (`_can_pay_activation_cost`/`_pay_activation_cost`/`tap_for_mana`, plus the two existence-only "can this mana ability be paid at all" probes in `misc_mixin.py`/`legal_actions_mixin.py`) so the mana-ability carve-out reaches real payment, not just a legality check that would then diverge from what's actually charged. Defense Grid's own "except during **its controller's** turn" needed a *third*, genuinely new rider rather than reusing `active_if`'s `your_turn`/`not_your_turn`: "its controller" means the *taxed spell's own caster*, not the tax's own controller, so `except_caster_own_turn` is checked directly against `cost_reduction_for`'s own `player` argument — the caster passed in by the caller — rather than through the ability-source-relative `static_conditions` vocabulary Tithe Taker's ordinary "during your turn" gate uses correctly.
- **Files:** `game/effects.py` (`cost_reduction` factory's three new params), `game/continuous.py` (`cost_reduction_for`'s new `active_if`/`except_caster_own_turn` checks, `activation_cost_reduction_for`'s widened scope/tax/carve-out), `game/engine/activation_mixin.py` (`_reduced_activation_mana`'s increase branch, `is_mana_ability` on `_can_pay_activation_cost`/`_pay_activation_cost`), `game/engine/mana_mixin.py` (`tap_for_mana` passing `is_mana_ability=True`), `game/engine/misc_mixin.py`, `game/engine/legal_actions_mixin.py` (both existence-only mana-ability probes), `game/ability_catalogue.py`.
- **Tests:** `tests/test_cost_tax_family.py` (new).

### Solitude / Parallax Wave / Skyclave Apparition — the O-Ring/exile family's remaining shapes (MEC-12)

- **What:** Three more single-target/leaves-battlefield exile shapes, each needing one small, genuinely reusable addition to the existing O-Ring family (`ExileEffect(remember=True)`/`GameObject.linked_exile_id`, MEC-21's accumulating `exiled_with_ids`) rather than a bespoke build per card. **Solitude** ("exile up to one other target creature. That creature's controller gains life equal to its power.") needed `GainLifeEffect.recipient="target_controller"` — the *who receives* sibling of the already-shipped `amount_from_target_power` (Dazzling Reflection, MEC-30): both read the same shared target (RULE 608.2, one target requirement, two effects), but `recipient` decides who gains the life rather than how much. Evoke isn't modeled (same documented simplification as Endurance's own entry — no alternative-cast-cost mechanism exists for it); "target creature" already excludes the source itself in this engine's `targeting.py` (`kind in ("creature", "permanent")` always filters `o is not source`), so "up to one **other** target creature" needed no new exclusion. **Parallax Wave** ("Remove a fade counter from this enchantment: Exile target creature. When this enchantment leaves the battlefield, each player returns to the battlefield all cards they own exiled with it.") needed `ReturnAllExiledWithEffect`/`"return_all_exiled_with"` — the mass sibling of `ReturnLinkedExileEffect`, reading `exiled_with_ids` (built for a *different* card, Agatha's Soul Cauldron, MEC-21) instead of the single-slot `linked_exile_id`, since a repeatable ability can exile several different creatures owned by several different players over its lifetime, all returning together under their own respective owners. Fading and the "remove a counter" activation cost (`ActivationCost.remove_counters`, `{"remove_counters": ["fade", 1]}`) were both already-shipped primitives. **Skyclave Apparition** ("exile up to one target nonland, nontoken permanent you don't control with mana value 4 or less. When this creature leaves the battlefield, the exiled card's owner creates an X/X blue Illusion creature token, where X is the mana value of the exiled card.") needed two things: `ExileEffect` gained its own `max_mana_value` param (the same target-offer-time cap `DestroyEffect` already had, just never threaded onto exile), and a new `CreateTokenForLinkedExileEffect`/`"create_token_for_linked_exile"` — `ReturnLinkedExileEffect`'s token-creating sibling, reading the same `linked_exile_id` link one last time for the exiled card's owner and mana value, then handing off to `GameContext.create_token` under *that* owner's control rather than the caster's. `target_kind="nonland_permanent_you_dont_control"` doesn't itself exclude tokens (no `exclude_tokens` selector exists yet) — a narrow, documented simplification, the same shape Leonin Relic-Warder's own `target_kind="permanent"` type-union already uses.
- **Files:** `game/effects.py` (`GainLifeEffect.recipient`, `ReturnAllExiledWithEffect`, `CreateTokenForLinkedExileEffect`, `ExileEffect.max_mana_value`), `game/ability_catalogue.py`.
- **Tests:** `tests/test_solitude_family.py`, `tests/test_parallax_wave_family.py`, `tests/test_skyclave_apparition_family.py` (all new).
- **PAR-30 — the parser recognizer for the modern one-sentence shape (PARSER_VERSION 140, +42):** every primitive above was already built, but the classic O-Ring / Banisher Priest / Fiend Hunter clause — "exile `<TARGET>` [an opponent controls] until ~ leaves the battlefield." — had never been reachable from oracle text (Oblivion Ring itself parses as UNMODELED to this day). The obstacle: that one clause is *two* abilities (an ETB/attacks exile + a LEAVES_BATTLEFIELD return), and a body handler emits one ability's effects. `handlers._exile_until_leaves` emits the `exile` spec with `remember=True` plus a new signal param `until_source_leaves`; `segmenter.segment_line`, immediately after building the primary triggered `AbilitySpec`, scans its effects for that param and appends a companion `AbilitySpec("triggered", effects=[return_linked_exile], trigger={"event": "LEAVES_BATTLEFIELD", "condition": {"subject": "self"}})` through the existing `Segment.extra_specs` channel. Target-kind resolution maps a trailing "an opponent controls" onto the `_you_dont_control` kinds ("target artifact or creature an opponent controls" → `permanent_you_dont_control`); "defending player controls" (Colossal Whale) stays a bare kind. Covers Banisher Priest, Banishing Light, Cast Out, Conclave Tribunal, Glass Casket, Fairgrounds Warden, Detention Chariot, Chained to the Rocks, and ~35 more; verified end-to-end (ETB exiles the opponent's creature, the Priest dying returns it). `tests/test_par30_exile_until_leaves.py`.
- **PAR-30 — the old two-sentence templating (PARSER_VERSION 202, +10):** the classic cycle prints the two abilities as separate lines. A new `_return_exiled_card` handler claims a standalone "return the exiled card[s] to the battlefield under its/their owner's control." line (→ `return_linked_exile`); `_exile` gains an "exile **another** target `<X>`" ETB row (RULE 601.2c self-exclusion is the same documented simplification `_gain_control_eot`'s "another" already uses); and `gate.parse_oracle` runs a cross-line pass — seeing any `return_linked_exile` effect on the card, it stamps `remember=True` onto every plain (non-`selector`) `exile` effect so `GameObject.linked_exile_id` is populated for the return to read back (the engine primitives all pre-existed). Covers Oblivion Ring itself, Journey to Nowhere, Faceless Butcher, Fiend Hunter, Petravark, Petradon, Slithery Stalker, The Princess Takes Flight (Saga chapter III), Eldrazi Displacer (the "another" widen alone). Also closes **Driftgloom Coyote**'s own after-tail — "if that creature had power N or less, put a +1/+1 counter on ~." — via `ConditionalEffect`'s new `previous_target_power_at_most` key (a documented simplification: the exiled creature is off the battlefield by resolution, so its last-known power is read). Verified end-to-end (ETB exiles the opponent's creature, the source going to the graveyard returns it). The multi-event trigger forms — "enters **or transforms into** ~" (Brutal Cathar) and the compound "enters **and at the beginning of your first main phase**" (Crack in Time) — closed at PARSER_VERSION 203; see the threaten-family entry above. `tests/test_par30_old_oring_two_sentence.py`.

### Soul Partition's owner-held, opponent-taxed exile permission (MEC-12)

- **What:** "Exile target nonland permanent. For as long as that card remains exiled, its owner may play it. A spell cast by an opponent this way costs {2} more to cast." Two new `ExileEffect` params: `grant_owner_play_permission` stamps `GameState.exile_cast_condition[target.instance_id] = (target.owner_id, {})` — the standing sibling of Lukka, Coppercoat Outcast's own board-gated grant (an empty condition dict always holds, per `static_conditions.condition_holds`'s own "no condition = always true"), but keyed to the exiled card's *owner* rather than the exiling effect's controller, which is the entire point of this card (only the owner, never the exiler, may ever cast it). `owner_play_permission_tax` builds a genuinely new per-*instance* `cost_reduction` static (`EffectSpec("cost_reduction", {"affects": "self", "except_same_controller_as": exiler_id, ...})`, via `build_effects` — the same "construct a spec-backed static at resolve time, not raw Python" idiom `CreateTokenEffect.grant_self_anthem` already uses) and stamps it directly onto the *exiled card itself*, not onto Soul Partition — since the card can leave its caster's hand, graveyard, wherever, and travel indefinitely; the tax needs to survive on the taxed object, not the no-longer-relevant spell that created it. Reading it required widening `continuous.self_cost_reduction_for` with a new `caster_id` param (previously it only ever answered "what does this card's own printed reduction total to", with no notion of *who* is actually attempting to cast it) and threading `player.id` through from `CastingMixin._adjust_cost`, the one caller. Found and fixed a real latent bug along the way, the same "parse-only masks real bugs" shape this project's testing convention exists to catch: `legal_actions`'s own exile-zone offer-list loop checked `_castable_from_exile`/`_has_temp_play_permission` but never `_has_conditional_exile_permission` at all — Lukka, Coppercoat Outcast's grant worked when driven directly through `can_cast`/`cast_spell` (how its own batch's tests exercised it), but nothing had ever actually offered it as a real, clickable action; both permission kinds are now checked there.
- **Files:** `game/effects.py` (`ExileEffect.grant_owner_play_permission`/`owner_play_permission_tax`, the `"cost_reduction"` factory's new `except_same_controller_as`), `game/continuous.py` (`self_cost_reduction_for`'s new `caster_id` param), `game/engine/casting_mixin.py` (`_adjust_cost` threading `player.id` through), `game/engine/legal_actions_mixin.py` (the `_has_conditional_exile_permission` fix), `game/ability_catalogue.py`.
- **Tests:** `tests/test_soul_partition_family.py` (new).

### Abdel Adrian, Gorion's Ward's "exile any number you control" selection (MEC-12)

- **What:** "When Abdel Adrian enters, exile any number of other nonland permanents you control until Abdel Adrian leaves the battlefield. Create a 1/1 white Soldier creature token for each permanent exiled this way." — the O-Ring/exile family's last remaining member in this batch, and a genuinely different shape from the rest: not a RULE 115 target at all (the printed line never says "target"), just a *selection* among the controller's own permanents. New `ExileAnyNumberYouControlEffect` opens `RulesEngine.request_choose_objects`'s existing "choose N of these objects" chooser (offering every eligible permanent at once, `optional=True` so the player may stop after any number including zero) rather than `ExileEffect`'s own RULE 115 target-gathering. That chooser's `"exile"` action already just called `RulesEngine.exile` — needed one new capability, `track_exiled_with=True` (threaded through `request_choose_objects`/`_choose_objects_choice`/`resolve_choose_objects_choice`/`_apply_chosen_object`, the same four-call-site plumbing `remember` already has), the multi-pick sibling of `remember`'s single-slot `linked_exile_id`, appending every pick onto `GameObject.exiled_with_ids` instead. The token count needed a new `continuous.count_selector` kind, `"exiled_with_count"` (reads that same list's length), which in turn needed `CreateTokenEffect.apply`'s existing `count_selector` call to actually pass its own `source` through — it never had before, since no prior `count_selector` kind needed the calling permanent's own identity. The leaves-battlefield half needed **no new code at all**: `ReturnAllExiledWithEffect` (built minutes earlier in this same batch for Parallax Wave) reads `exiled_with_ids` and returns each card to its own owner — which for Abdel Adrian is always its own controller, since it only ever exiles its own permanents, but the effect itself has no idea of that and doesn't need to. Confirms this engine's RULE 608.2 "suspended resolution" machinery (`GameState.deferred_effects`, MEC-12's earlier batch) correctly parks the trailing `create_token` effect until the interactive multi-round chooser fully resolves, rather than running it against a still-empty `exiled_with_ids` list. Background deckbuilding (choosing a second commander) is not a board-state mechanic and needs no engine support.
- **Files:** `game/effects.py` (`ExileAnyNumberYouControlEffect`, `CreateTokenEffect.apply`'s `source` passthrough), `game/continuous.py` (`count_selector`'s new `exiled_with_count` kind), `game/rules/misc_mixin.py` (`request_choose_objects`'s new `track_exiled_with` param, threaded through its three helper methods), `game/ability_catalogue.py`.
- **Tests:** `tests/test_abdel_adrian_family.py` (new).

### Dark Confidant's non-draw "reveal, take, lose life" upkeep trigger (MEC-12)

- **What:** "At the beginning of your upkeep, reveal the top card of your library and put that card into your hand. You lose life equal to its mana value." One new atomic effect, `RevealTopThenTakeAndLoseLifeEffect` — deliberately *not* routed through `DrawCardEffect`/`RulesEngine.draw` at all: RULE 121.4 is explicit that a card entering hand without the printed word "draw" isn't a draw, so it must never trip a draw-replacement effect or a "whenever you draw a card" trigger, and must never be tallied in `GameState.cards_drawn_this_turn`. Fully deterministic (there is only one card and nothing to choose among), so both clauses — the zone move and the life loss — are one atomic effect rather than two sequenced ones needing a resolve-time referent to share, the same reasoning `ExileTopThenGrantConditionalCastEffect` (Lukka) already uses for its own top-of-library move.
- **Files:** `game/effects.py` (`RevealTopThenTakeAndLoseLifeEffect`), `game/ability_catalogue.py`.
- **Tests:** `tests/test_dark_confidant_family.py` (new).

### The land-animate family — Kamahl, Heart of Krosa and Ashaya, Soul of the Wild (MEC-12)

- **What:** Two cards making a permanent's card type cross the land/creature line in opposite directions — neither reachable by the oracle-text parser (both fully hand-authored; Kamahl's Partner keyword and combat-trigger pump were already parser-`MODELED` and copied verbatim rather than re-derived). **Kamahl** ("{1}{G}: Until end of turn, target land you control becomes a 1/1 Elemental creature with vigilance, indestructible, and haste. It's still a land.") needed no new primitive at all, just the first card to chain two already-shipped ones onto the same resolve-time target: two `grant_until` `EffectSpec`s in one effect list, the first targeting the land (`target_kind="land_you_control"`) and stamping a `type_change` static (`add_types=["creature"]`, literal power/toughness 1/1), the second reusing `GrantUntilEffect`'s existing `previous_subject` pronoun (`target_kind=None`, the same "Tap target land. It doesn't untap …" idiom `_apply_effects_partitioned` already threads through any effect exposing `target_specs`) to lay a `grant_keyword` static onto that exact land without a second target prompt. "It's still a land" needs no code — `add_types` only ever *adds* a type, never removing the printed one. **Ashaya** ("Ashaya's power and toughness are each equal to the number of lands you control. Nontoken creatures you control are Forest lands in addition to their other types.") is the reverse direction and needed two real additions: the first ability is `pt_cda` (registered in `effects.py` since an earlier batch but never bound to any card until now) reading the already-existing `"lands_you_control"` `continuous.count_selector`; the second needed a new `continuous.affected_objects` scope, `"nontoken_creatures_you_control"` (RULE 108.3's token filter applied to the ordinary controller-scoped creature set), and — the real find of this batch — a general, previously-invisible bug: `GameObject.is_land` had only ever read the printed card, never folding in a layer-4 `add_types` grant the way `is_creature` already does, so *no* card could ever have made something a land via a static before, regardless of phrasing; every prior "land becomes a creature" card worked fine (that direction only ever touches `is_creature`), which is exactly why this had stayed invisible. Fixed generally (mirrors `is_creature`'s own printed-or-added/removed pattern), not special-cased for this card. With `is_land` fixed, the Forest subtype grant reaches `mana_abilities._derived_basic_mana_options`'s existing RULE 305.6 pass with no extra code, so a creature Ashaya grants Forest to picks up "{T}: Add {G}." for free — confirmed by test, along with the real, documented ruling that Ashaya's own ability makes *herself* a Forest land too (she's a nontoken creature she controls), so her power/toughness count includes herself.
- **Files:** `models/game_object.py` (`is_land` fix), `game/continuous.py` (`affected_objects`'s new `nontoken_creatures_you_control` scope), `game/ability_catalogue.py`.
- **Tests:** `tests/test_land_animate_family.py` (new).

### Yawgmoth's Will's graveyard-wide play permission and exile-redirect (MEC-12)

- **What:** "Until end of turn, you may play lands and cast spells from your graveyard. If a card would be put into your graveyard from anywhere this turn, exile that card instead." Two new *player*-scoped, turn-limited primitives, neither expressible as a permanent-anchored static the way every prior graveyard-cast permission was — the sorcery granting them is gone from every zone but graveyard/exile long before end of turn, so there's no permanent left on the battlefield for the layer engine or `game/graveyard_cast.py`'s existing permanent-scan to find. `GraveyardPlayPermissionThisTurnEffect` stamps `Player.graveyard_play_permission_until_turn` to the current turn number; a new `has_temporary_graveyard_play_permission` helper reads it back from both `GameEngine.can_play_land` (a new branch in its `in_playable_zone` check) and `_graveyard_cast_permission` (widened alongside the existing Lurrus-shaped `graveyard_cast_grant_for` check) — the first graveyard-cast permission source of any kind to cover lands, since every prior one (`graveyard_cast_grant_for`'s own `if card.is_land: return None`) explicitly excluded them. `legal_actions`'s graveyard-zone loop gained a matching `can_play_land` offer, the same "found while wiring a real UI-reachable action" gap this batch's earlier entries (Soul Partition) already hit once. `GraveyardRedirectToExileEffect` stamps `Player.graveyard_redirect_to_exile_until_turn`, checked directly in `RulesEngine._move_to_graveyard` — the one choke point every graveyard-bound move funnels through regardless of cause — against whichever player *owns* the moving card (a card only ever enters its own owner's graveyard, RULE 404.4/700.4, which is exactly what "your graveyard" means here). It sits right next to the pre-existing per-*object* check for Lurrus's own "exile instead" trailing clause (`GameObject.cast_via_graveyard_cast_permission_until_turn`) — that one only ever catches the one spell cast via its own permission; this one catches every card the player owns, from any zone, for the whole turn.
- **Files:** `models/player.py` (`graveyard_play_permission_until_turn`, `graveyard_redirect_to_exile_until_turn`), `game/effects.py` (`GraveyardPlayPermissionThisTurnEffect`, `GraveyardRedirectToExileEffect`, their registry entries), `game/graveyard_cast.py` (`has_temporary_graveyard_play_permission`), `game/engine/lands_mixin.py` (`can_play_land`'s new branch, `_graveyard_cast_permission`'s widened check), `game/engine/legal_actions_mixin.py` (graveyard-zone land offer), `game/rules/damage_death_mixin.py` (`_move_to_graveyard`'s new player-scoped redirect check), `game/ability_catalogue.py`.
- **Tests:** `tests/test_yawgmoths_will_family.py` (new).

### Protean Hulk's total-mana-value-budgeted search (MEC-12)

- **What:** "When this creature dies, search your library for any number of creature cards with total mana value 6 or less, put them onto the battlefield, then shuffle." Needed a genuinely new `SearchLibraryEffect` shape: every existing multi-pick search bounds each round by a fixed per-card `max_mana_value` in `criteria`, but this is a *running total* shared across the whole open-ended pick — a 5-drop and a 1-drop are each individually well under 6, but picking both exhausts the budget for anything else. `SearchLibraryEffect.total_mana_value_budget` threads a `spent_mana_value` running total through the existing recursive multi-round search loop (`RulesEngine.request_search` → `_search_choice` → `resolve_search_choice`, plus `GameContext.request_search`'s thin proxy, all four needing the new parameter): each round's eligible pool is narrowed to whatever still fits `total_mana_value_budget - spent_mana_value`, on top of `criteria`'s ordinary type filter — orthogonal to, and stackable with, a real per-card cap should some future card need both at once. "Any number" reuses the pre-existing `count=99` sentinel other open-ended searches (Craterhoof Behemoth-shaped triggers, etc.) already use, since the real stopping condition is the budget running out, not the count.
- **Files:** `game/effects.py` (`SearchLibraryEffect.total_mana_value_budget`, its registry factory, `GameContext.request_search`'s widened proxy), `game/rules/search_mixin.py` (`request_search`/`_search_choice`/`resolve_search_choice`'s threaded budget), `game/ability_catalogue.py`.
- **Tests:** `tests/test_protean_hulk_family.py` (new).

### Helm of the Host, Twinflame and Heat Shimmer — the copy-a-creature family (MEC-12)

- **What:** Three "create a token that's a copy of [equipped/target] creature, except …" cards, closing the whole cluster BACKLOG.md had named but not individually diagnosed. **Helm of the Host** ("At the beginning of combat on your turn, create a token that's a copy of equipped creature, except the token isn't legendary. That token gains haste.") needed no new primitive at all — `CopyPermanentEffect` already independently supported `target_kind="attached_permanent"` (Mirrormind Crown), `not_legendary` (Multiversal Recruitment-shaped), and `haste` (Kiki-Jiki-shaped); this is simply the first card combining all three on one effect. **Twinflame** ("Choose any number of target creatures you control. For each of them, create a token that's a copy of that creature, except it has haste. Exile those tokens at the beginning of the next end step.") needed two real additions: `CopyPermanentEffect` gained a genuinely new `target_count`/`target_count_max`/`target_optional` param triple (deliberately distinct from the pre-existing `count`, which still means "N copies of the *one* target" — Rite of Replication-shaped, and could combine with this on some future card) — when the target spec's own `effective_count != 1`, `apply()` now makes one token copy *per* chosen target instead of `count` copies of just the first, mirroring the established `PumpEffect`/`AddCountersEffect` "each of up to N gets the full amount" idiom, and reusing the parser's own `_ANY_NUMBER_TARGET_CAP` (10) sentinel for "any number of". The delayed exile needed `ExileSpecificEffect`, the plural sibling of `SacrificeSpecificEffect` (Kiki-Jiki-shaped): the existing `CreateDelayedTriggerEffect`'s `capture="created_objects"` branch already special-cased any inner effect exposing a plain `.objects` list, but `ExileEffect` only ever carried one `.target`, silently dropping every token past the first for a multi-target source. Strive itself was already a shipped primitive (`AbilitySpec.strive_cost`, per-extra-target cost scaling in `casting_mixin.py`) needing no changes. **Heat Shimmer** ("Create a token that's a copy of target creature, except it has haste and 'At the beginning of the end step, exile this token.'") is simply the single-target sibling of Twinflame's own delayed-exile shape (`target_count` defaults to 1) — deliberately *not* modeled as a literal granted quoted triggered ability on the token (a real but heavier mechanism this engine already avoids for exactly this template, per the Marchesa V4.2 batch's Kiki-Jiki/Puppeteer Clique entry above), since the caster-side delayed trigger reaches the identical board outcome regardless of which player ends up controlling the token.
- **Files:** `game/effects.py` (`CopyPermanentEffect.target_count`/`target_count_max`/`target_optional`, `ExileSpecificEffect`, its registry factory), `game/ability_catalogue.py`.
- **Tests:** `tests/test_helm_of_the_host_family.py`, `tests/test_twinflame_family.py`, `tests/test_heat_shimmer_family.py` (all new).

### Necrotic Ooze's "all graveyards" ability-borrowing source (MEC-12)

- **What:** "As long as this creature is on the battlefield, it has all activated abilities of all creature cards in all graveyards." The third `source_mode` for `grant_borrowed_activated_ability` (MEC-21/MEC-26's `exiled_with`/`group`/`chosen_permanent` family) — `"all_graveyards"` reads straight off every player's live `Player.graveyard` list (no staleness check needed, unlike `exiled_with`'s snapshot of ids that may have moved on) rather than a single donor or a battlefield selector. Reuses `_apply_borrowed_activated_abilities`'s existing per-(grantee, donor, ability-index) caching, RULE 113.7c source-redirect, and creature-only donor filter unchanged — the whole addition is one new `elif` branch collecting donors. "As long as this creature is on the battlefield" needed no `active_if` gate: a static ability only ever applies while its own source is on the battlefield in the first place (RULE 613.1). Closes the "Necrotic Ooze-adjacent" line item BACKLOG.md had carried since the copy-a-creature cluster was first named — it turned out to mean Necrotic Ooze itself (a different mechanic entirely, ability-borrowing rather than token-copying), not an unnamed fourth card.
- **Files:** `game/continuous.py` (`_apply_borrowed_activated_abilities`'s new `"all_graveyards"` `source_mode` branch), `game/ability_catalogue.py`.
- **Tests:** `tests/test_necrotic_ooze_family.py` (new).

### MEC-32: the draw-replacement family's event granularity

- **What:** Alms Collector ("If an opponent would draw two or more cards, instead you and that player each draw a card."), Notion Thief and Chains of Mephistopheles (both "…except the first one they draw in each of their draw steps…") had all three been diagnosed and deferred more than once, blocked on the same real architectural gap: `RulesEngine.draw(player, count)` called `_single_draw` once per requested card, each firing its own independent, hardcoded `count=1` `EventType.DRAW`, so no replacement effect could ever see "this player is attempting to draw 2+ cards as one instruction" or "this is the first draw in the current draw step" — only ever "one card, right now." Fixed with two additions, kept deliberately separate so neither changes behavior for any of the many existing per-card DRAW replacements (the empty-library win-instead shield, count doublers, the draw→mill conversion): (1) a new `EventType.DRAW_INSTRUCTION`, fired once per `draw()` call with the real requested `count`, *before* the call splits into that many per-card `DRAW` events exactly as before — a genuinely new event type rather than reusing `DRAW` at the instruction level, since firing the same event type twice (once for the instruction, once per card) would have double-applied every ordinary per-card replacement (a doubler would double once at the instruction level and again per split-out card). Only Alms Collector's own replacement registers against it. (2) `GameState.first_draw_done_this_step` (per player, reset to `False` the instant a player's own `"draw"` step begins — `GameEngine._run_step`, right alongside the existing `combats_this_turn` per-step bump), read and flipped by `RulesEngine._single_draw`, which only ever computes `first_in_draw_step=True` while `state.current_step == "draw"` for the drawing player themself — a draw from a spell at any other point in the turn always reads as "not first," correctly, since RULE 120.3 says each card in a multi-card draw is independently replaceable *and* a draw outside the draw step can never be that step's own first card. **Alms Collector** (`effects._split_multi_draw_replacement`, registered as `"split_multi_draw"`) intercepts `DRAW_INSTRUCTION` for an opponent's `count >= 2` attempt, cancels it outright, and issues one fresh, un-doubled `draw()` call for each of the two players — neither resulting draw's own count ever re-triggers the same replacement. **Notion Thief** (`_steal_non_first_draw_replacement`, `"steal_non_first_draw"`) reads `first_in_draw_step` on the ordinary per-card event, scoped to opponents only: a non-first draw is cancelled and redirected into a draw for its own controller instead. **Chains of Mephistopheles** (`_discard_instead_of_non_first_draw_replacement`, `"discard_instead_of_non_first_draw"`) reads the same flag but applies table-wide (including its own controller) with a genuinely bespoke three-branch body: discard a card if the hand isn't empty, then draw a replacement card (itself a fresh `draw()` call — which, since it's still not the step's first draw, is *itself* replaced by this same effect again, RULE 616.1f's "repeat until no more replacements apply" loop) or mill a card once the hand is empty. This recursive self-replacement is the real, famously punishing behavior of the printed card (a non-first draw attempt empties the drawing player's whole hand into the graveyard via repeated discards, then mills exactly one card) — not a bug, confirmed against the card's real reputation — and terminates naturally because each recursive discard strictly shrinks the hand, bounding the recursion depth by the hand's own size. The discard itself is the engine's existing non-interactive `RulesEngine.discard` (auto-chosen, no chooser in MVP), the same documented simplification every other untargeted discard in this engine already uses. `draw()` also gained a deliberate fast path: `count == 1` (the overwhelming majority of real draws — every turn-based draw-step draw, most card-draw spells) skips the `DRAW_INSTRUCTION` pass entirely and calls `_single_draw` directly, since no shipped instruction-level replacement's `min_count` is ever satisfiable at 1 anyway. Without it this restructure doubled `draw()`'s replacement-scan cost (`_all_replacement_effects()` runs once at the instruction level *and* once per card) for the single-card case specifically — caught not by a functional test but by a long-running bot test tripping the per-test timeout, confirmed via a stashed before/after comparison that the same test was already borderline-slow on unrelated, pre-existing grounds (a `GameState.clone()` deep-copy on every action) but this change's added overhead was what pushed it over.
- **Files:** `models/events.py` (`EventType.DRAW_INSTRUCTION`), `models/game_state.py` (`GameState.first_draw_done_this_step`), `game/engine/turn_loop_mixin.py` (`_run_step`'s per-draw-step reset), `game/rules/draw_discard_mixin.py` (`draw`/`_single_draw` restructure), `game/effects.py` (`_split_multi_draw_replacement`, `_steal_non_first_draw_replacement`, `_discard_instead_of_non_first_draw_replacement`, their `ReplacementRegistry` entries), `game/ability_catalogue.py` (Alms Collector, Notion Thief, Chains of Mephistopheles).
- **Tests:** `tests/test_draw_replacement_family.py` (new, 13 tests).

### MEC-34: Animate Dead — RULE 303.4f's "Enchant creature card in a graveyard" reanimator Aura

- **What:** Animate Dead's own target isn't a permanent at all (RULE 303.4f's special case for the handful of Auras that enchant a graveyard *card*), so `RulesEngine._resolve_permanent_spell`'s ordinary "attach the freshly-entered Aura to its RULE 115 target, or send it to the graveyard on a failed attach" branch had always misfired on it: `attach_to_target` can only ever fail against a non-battlefield object, so the Aura was unconditionally sent straight back to its own graveyard before its own "when this enters" ability — which is what's actually supposed to fix the attachment — ever got a chance to resolve. Fixed with four small, independently-reusable pieces rather than one Animate-Dead-specific hack: (1) `_resolve_permanent_spell` now recognizes a graveyard-zone attach target and skips the auto-graveyard branch for exactly that case, leaving the Aura on the battlefield unattached and stashing the target's id on a new `GameObject.reanimate_target_id` (the graveyard card can't simply ride along as an ordinary RULE 115 chosen target into the later triggered-ability resolution, since that's a separate `StackItem`/resolution boundary — this is the one genuinely new piece of state the whole fix needed); (2) `targeting.legal_targets` gained a graveyard-wide branch for an "Enchant `<type>` card in a graveyard" quality (parsed off the printed "Enchant …" line the same way every other Aura's restriction already is) — the pre-existing "enchant" branch only ever searched `state.permanents()`, so without this the spell would have had *no* legal targets to offer at cast time at all, a gap the original diagnosis had missed entirely (it only covered the resolution-time failure, not the cast-time targeting one); (3) `ReturnFromGraveyardEffect` gained a fifth referent mode, `target_kind="self_enchant_target"` (alongside its ordinary RULE 115 target/self shapes), reading `self.source.reanimate_target_id` back and resolving it via `GameState.find_object` (which already searches every zone, graveyards included) rather than a passed-in `targets` list; (4) the already-shipped `AttachEffect(target_kind="created")` — no changes needed — attaches the Aura to whatever `ReturnFromGraveyardEffect` just put on the battlefield, since `_apply_one` already appends its return value to `context.created_objects`. The "when this Aura leaves the battlefield, that creature's controller sacrifices it" clause is a new, genuinely reusable `SacrificeAttachedPermanentEffect`: it reads `self.source.attached_to` live at resolution (not a baked-in object the way `SacrificeSpecificEffect` needs, since the acting object is only known once this specific LEAVES_BATTLEFIELD firing happens) — safe because `GameState.remove_from_battlefield` never clears `attached_to`, so the just-departed Aura's own field still names the creature it was attached to the instant it left. Confirmed, rather than assumed, that RULE 704.5n's "Aura attached to nothing → owner's graveyard" SBA sweep (`_revalidate_attachments`) can't interfere in the window between the Aura entering and its own ETB resolving: that sweep only ever processes a permanent whose `attached_to` is *already set* (`if host_id is None: continue`), so a never-yet-attached Aura is invisible to it by construction — no exemption needed, unlike the original diagnosis's "may already be safe — verify" hedge. The self-referential "it loses 'enchant creature card in a graveyard' and gains 'enchant creature put onto the battlefield with this Aura'" text-change clause is RULE 303.4f reminder text describing exactly this behavior with no separate gameplay effect once the above is right, so it isn't modeled as its own clause. Necromancy, this ticket's other named card, turned out to be a structurally different, *non*-Aura reanimator template (no "Enchant X" line at cast time, a real RULE 115 target on its own triggered ability instead, and a "becomes an Aura with `<quoted text>`" clause that would need `GameObject.parametric_keywords` to become genuinely mutable mid-game) — re-diagnosed and re-filed as its own ticket, [MEC-44], rather than forced through the same shape.
- **Files:** `models/game_object.py` (`GameObject.reanimate_target_id`), `game/rules/casting_mixin.py` (`_resolve_permanent_spell`'s graveyard-target bypass), `game/targeting.py` (`legal_targets`'s graveyard-quality "enchant" branch), `game/effects.py` (`ReturnFromGraveyardEffect`'s `target_kind="self_enchant_target"`, `SacrificeAttachedPermanentEffect`, its `EffectRegistry` entry), `game/ability_catalogue.py` (Animate Dead).
- **Tests:** `tests/test_animate_dead_family.py` (new, 3 tests).

### MEC-36: Damping Sphere — mana-type override by amount + per-caster storm tax

- **What:** "If a land is tapped for two or more mana, it produces {C} instead of any other type and amount. Each spell a player casts costs {1} more to cast for each other spell that player has cast this turn." Two independent, unscoped statics. The mana half is a new `StaticAbility` layer, `"mana_type_override"` — not a RULE 613 layer effect at all (nothing here is a characteristic), consulted directly by `GameEngine.tap_for_mana` via the new `continuous.mana_type_override_for`, positioned right after the already-shipped `mana_multiplier` (Nyxbloom Ancient) check and before the produced mana lands in the pool, so the threshold is checked against the *true*, post-multiplier total. It's a boolean override (not additive), unscoped by controller (any land tapped by anyone), and multiple copies don't compound — the same shape `mana_multiplier` already established, just a type override instead of an amount scale. The cost half needed no new `StaticAbility` layer at all: `cost_reduction`'s existing `per` count-selector vocabulary just gained a new key, `"spells_cast_this_turn"`, in `continuous.count_selector` — and it turned out to already be exactly the right shape, because `continuous._cost_static_amount` (which `per` feeds through) evaluates the count against the *casting* player, not this static's own controller, and `RulesEngine._track_spell_cast` increments `GameState.spells_cast_this_turn` strictly *after* the spell being cast has already had its own cost computed — so "for each **other** spell" fell out for free, no off-by-one correction needed. The one real prerequisite fix: `spells_cast_this_turn`'s own reset (`GameEngine.begin_turn`) had always been scoped to just the incoming active player's entry (RULE 731.2's day/night check is the only prior consumer, and it only ever reads the *active* player's own count right before rotation) — widened to reset *every* player's entry every turn, the same `mana_produced_this_turn`/`noncreature_spells_cast_this_turn` game-wide idiom already used nearby, since a non-active player's own running total needed to stay accurate for Damping Sphere's cross-player read too. Confirmed the widening is safe rather than assumed: the sole existing consumer (`_last_turn_spell_count`) already snapshots the outgoing player's count *before* this reset runs each turn, so nothing reads a value the wider reset could clobber.
- **Files:** `game/continuous.py` (`mana_type_override_for`, `count_selector`'s `"spells_cast_this_turn"` key, `_NON_RULE_613_LAYERS`), `game/effects.py` (the `"mana_type_override"` `EffectRegistry` factory), `game/engine/mana_mixin.py` (`tap_for_mana`'s override consult), `models/game_state.py` (`spells_cast_this_turn`'s widened docstring), `game/engine/turn_loop_mixin.py` (`begin_turn`'s widened reset), `game/ability_catalogue.py` (Damping Sphere).
- **Tests:** `tests/test_damping_sphere_family.py` (new, 3 tests).

### MEC-37: Doomsday — no new search primitive, but two real engine bugs

- **What:** The original ticket framing ("exile up to five cards in a pile") described a mechanic Doomsday doesn't actually have — its real printed text is "Search your library and graveyard for five cards and exile the rest. Put the chosen cards on top of your library in any order. You lose half your life, rounded up," which needed no new search primitive at all once checked against the real oracle text: `SearchLibraryEffect` already supports `zones=["library", "graveyard"]` (combined-zone search) and `exile_rest` (its own docstring already said "…Doomsday-shaped," built with this exact card in mind but never actually reached by a real card before now), and a multi-card `destination="library_top"` search already offers its picks one at a time, each stacking *above* the last — so the player already has full control over the final order simply by choosing which card to name each round (name the card that should end up on top last), no new ordering mechanism needed. The only genuinely new piece was `LoseLifeEffect`'s new `amount_from_half_own_life` param ("half your life, rounded up," RULE 107.3, via ceiling division), resolved against this ability's own controller. Hand-authoring the card immediately surfaced two real, previously-unreachable engine bugs — no prior card had combined "a search with `zones` including graveyard and a broad `criteria`" with "a multi-effect spell whose search isn't its only effect," or "a search whose `destination` is itself one of its own searched `zones`," respectively:
  1. **RULE 608.2m premature spell routing.** `_apply_effects_partitioned`'s "an effect opens a `pending_choice`, defer the remainder" mechanism (batch 26) only ever stopped the *remaining effects in the same list* from running early — it never told its caller, `RulesEngine._apply_stack_item`, that the whole resolution had paused. So for a plain (non-permanent) spell whose *own* effects list has 2+ effects and the first one opens an interactive choice, `_apply_stack_item` immediately fell through to its "route this spell to the graveyard" tail as if resolution had finished — while the spell's own search was still waiting on an answer. For Doomsday specifically, this meant the still-resolving Doomsday card showed up as an eligible pick in its *own* search (zones include "graveyard," criteria is unrestricted) a full turn before RULE 608.2m says it's actually there. Fixed generally: `_apply_effects_partitioned` now returns whether it deferred, `_apply_stack_item` skips its routing tail when it did (extracted into `_finish_spell_routing`, reused so the fix isn't duplicated), and `resume_deferred_effects` — now threading a `stack_item` reference through the parked `deferred_effects` entry — runs that same tail once the remainder it was waiting on finally drains with nothing left to pause on. Not a Doomsday special case: this fixes the same latent premature-routing window for *any* future multi-effect spell whose first effect is interactive.
  2. **`exile_rest` re-catching its own chosen cards.** `SearchLibraryEffect.exile_rest`'s sweep re-scanned the *same* searched `zones` for anything still criteria-matching and exiled all of it — never excluding the cards the search had *just* chosen and moved, so a destination that puts a pick back into one of the searched zones (`library_top`/`library_bottom` while `"library"` is itself a searched zone — exactly Doomsday's own shape) immediately re-caught and exiled every card the player had just picked, silently gutting the entire "put the chosen cards on top" clause. An existing test (`test_search_effects.py::test_exile_rest_engine_moves_leftover_matches_to_exile_and_skips_shuffle`) had unknowingly encoded this bug as its own expected outcome (asserting the library ended up empty after picking *every* available card to `library_top`) — corrected once the real bug surfaced, rather than left passing against wrong behavior. Fixed by excluding the chosen cards' own instance ids from the exile-rest candidate pool.
- **Files:** `game/effects.py` (`LoseLifeEffect.amount_from_half_own_life`, `_apply_effects_partitioned`'s `stack_item` param + `bool` return), `game/rules/casting_mixin.py` (`_apply_stack_item`/`_finish_spell_routing` split, `resume_deferred_effects`'s stack-item-aware resumption), `game/rules/search_mixin.py` (`exile_rest`'s chosen-card exclusion), `game/ability_catalogue.py` (Doomsday).
- **Tests:** `tests/test_doomsday_family.py` (new, 2 tests); `tests/test_search_effects.py` (one existing assertion corrected to match the fixed `exile_rest` behavior).

### MEC-38: Necropotence's three-clause engine

- **What:** "Skip your draw step. Whenever you discard a card, exile that card from your graveyard. Pay 1 life: Exile the top card of your library face down. Put that card into your hand at the beginning of your next end step." Three real pieces, each closing a gap no prior card had exercised. (1) The draw-step skip is a new `StaticAbility` layer, `"skip_step"`, consulted live off the battlefield by `continuous.skipped_steps_for` — `RulesEngine.should_skip_step` already existed and already checked `Player.player_effects` for a `StaticEffect`, but that whole path turned out to be a designed-but-never-instantiated primitive (`StaticEffect` was never constructed anywhere in the codebase before this). Rather than build the "sync a StaticEffect onto player_effects as this permanent enters/leaves the battlefield" lifecycle the original ticket assumed was needed, this reuses the same "live battlefield read, no separate lifecycle" shape `mana_type_override_for` (MEC-36) already established — `_battlefield_static_abilities` re-derives every permanent's own statics fresh on every recompute regardless. (2) The discard trigger needed a new per-card `EventType.DISCARD_CARD` — the existing `DISCARD` only ever carried an aggregate `count` (the same granularity gap MEC-32 found on the draw side), so nothing could name *which* card was discarded. All three discard sites (`RulesEngine.discard`'s loop, `discard_specific`, and RULE 614.12's "discard a land card instead") now fire it alongside the unchanged aggregate event. `ExileEffect` gained a new `target_kind="trigger_subject"` (mirroring `TapEffect`'s own identically-named mode) to read the discarded card's `instance_id` straight off the firing event rather than a chosen RULE 115 target — by the time this trigger resolves the card is already sitting in the graveyard (discard moves it there before firing), so this is a real, correctly-timed zone change into exile. (3) The activation cost is the already-shipped `ActivationCost.pay_life`; the effect body needed a new `ExileTopOfLibraryEffect` — deterministic, no chooser at all, unlike `SearchLibraryEffect` (which offers the *whole* zone as a real pick even at `count=1`) — feeding the pre-existing `CreateDelayedTriggerEffect`'s `capture="created_objects"` mechanism, widened with a third captured-attribute name (`exiled_object`, alongside the pre-existing `objects`/`target`) so the delayed half could reuse `ReturnUncastExiledEffect` — previously only ever constructed directly in Python inside another effect's own `apply()` (Beseech the Mirror/Rebound's "if it wasn't cast this way" tail), never reachable through the ordinary `EffectSpec` whitelist until this ability needed it as a ordinary delayed effect rather than a bespoke one. One real bug surfaced building `ExileTopOfLibraryEffect`: setting `GameObject.face_down_in_exile` *before* calling `context.exile()` silently lost the flag, because `RulesEngine._remove_from_current_zone` (which `exile()` calls internally to pull the card out of its prior zone) unconditionally clears that flag as its own RULE 400.7 "a card leaving exile turns face up" behavior — correct for that direction, but it also undoes a card *entering* exile face down if set beforehand. Fixed by setting the flag after the move, not before (the pre-existing Beseech the Mirror search path never hit this, since it moves zones via the lower-level `Player.add_to_zone` directly rather than `RulesEngine.exile()`).
- **Files:** `game/continuous.py` (`skipped_steps_for`, `_NON_RULE_613_LAYERS`), `game/effects.py` (`"skip_step"` `EffectRegistry` factory, `ExileEffect.target_kind="trigger_subject"`, `ExileTopOfLibraryEffect`, `CreateDelayedTriggerEffect`'s `exiled_object` capture, `"return_uncast_exiled"` `EffectRegistry` factory), `game/rules/misc_mixin.py` (`should_skip_step`'s new check), `models/events.py` (`EventType.DISCARD_CARD`), `game/rules/draw_discard_mixin.py` (`discard`/`discard_specific`'s new per-card firing), `game/rules/casting_mixin.py` (RULE 614.12's own discard site), `game/effect_binder.py` (`_GROUP_CONTROLLER_EVENT_KEYS`'s `DISCARD_CARD` entry), `game/ability_catalogue.py` (Necropotence).
- **Tests:** `tests/test_necropotence_family.py` (new, 3 tests).

### MEC-39: Opposition Agent — search-result redirect, not a real control exchange

- **What:** "You control your opponents while they're searching their libraries. While an opponent is searching their library, they exile each card they find. You may play those cards for as long as they remain exiled, and you may spend mana as though it were mana of any color to cast them." The original ticket assumed a genuine RULE 269.4 player-control exchange, conditional and scoped to a choice's duration — a real, unbuilt shape. Rereading the actual printed text found a simpler, already-mostly-buildable one instead: the first sentence's "control" never changes anything this engine's search flow would otherwise decide (the searching player still picks which cards they find — the only thing that changes is where those cards end up), and the second sentence spells out that mechanical outcome completely on its own. Modeled as a new `StaticAbility` layer, `"search_redirect"` (`continuous.search_redirect_controller_for`), consulted by `RulesEngine._finish_search` at the exact point it computes each found card's destination: when the searching player is an opponent of the static's controller, every found card's destination is overridden to exile (regardless of what the search itself asked for — hand, battlefield, library placement, all redirected alike) and the already-shipped `GameState.exile_cast_condition`/`mana_wildcard_permission` pair — the same standing "play this exiled card, spending mana of any color" permission every other exile-and-play card already grants — is stamped for this permanent's controller instead of the found card's own owner. The one genuine generalization needed: every prior grantor of those two maps had only ever pointed them at the exiled card's own owner (`ExileEffect.grant_owner_play_permission` is even named for that assumption); `exile_cast_condition`'s own dict shape (`instance_id -> (player_id, condition)`) was already fully general, so no widening was needed there, only a new caller passing a different `player_id`.
- **Files:** `game/continuous.py` (`search_redirect_controller_for`, `_NON_RULE_613_LAYERS`), `game/effects.py` (`"search_redirect"` `EffectRegistry` factory), `game/rules/search_mixin.py` (`_finish_search`'s redirect consult + permission grant), `game/ability_catalogue.py` (Opposition Agent).
- **Tests:** `tests/test_opposition_agent_family.py` (new, 2 tests).

### MEC-35: Leonin Arbiter — a widened prohibition and a genuine RULE 116.2a special action

- **What:** "Players can't search libraries. Any player may pay {2} for that player to ignore this effect until end of turn." Two parts, both real. (1) The already-shipped `GrantSearchProhibitedEffect` (Stranglehold's own "your opponents can't search libraries") gained a `scope` param — `"opponents"` (the pre-existing, now-default behavior) vs. `"all"` (this card's own unqualified "**Players** can't…," which restricts its own controller too). (2) "Any player may pay {2}… to ignore this effect until end of turn" is a genuine RULE 116.2a special action, built from scratch on the exact template `turn_face_up` already established: no stack, offered only when payable, reclaims priority for its taker on completion. `GameEngine.pay_search_exemption`/`pay_search_exemption_actions` are the new pair; `GameState.search_exempt_until_turn` (`{player_id: turn_number}`) is the same "stops matching once the turn advances, no cleanup step needed" idiom `temp_flash_until_turn` already uses. `RulesEngine.request_search`'s own prohibition guard was refactored into a new public `is_search_prohibited_for(player)` (checking the exemption first, then scanning for an applicable `GrantSearchProhibitedEffect` by the widened `scope` rule) so both the guard itself and the new action's "is this even worth offering" check share one definition instead of two independently-maintained copies of the same logic. Deliberately reads the exemption as "ignore every current search prohibition," not literally only the one named "this effect" in the printed text — no shipped card yet combines Leonin Arbiter with a second, independent prohibition source, so the simpler reading is unobservably different today.
- **Files:** `game/effects.py` (`GrantSearchProhibitedEffect.scope`), `game/rules/search_mixin.py` (`is_search_prohibited_for`, `_has_search_exemption`, the widened prohibition guard), `game/engine/misc_mixin.py` (`pay_search_exemption`/`pay_search_exemption_actions`), `game/engine/legal_actions_mixin.py` (offering the new action), `models/game_state.py` (`search_exempt_until_turn`), `services/game_session.py` (the new action's dispatch entry), `game/ability_catalogue.py` (Leonin Arbiter).
- **Tests:** `tests/test_leonin_arbiter_family.py` (new, 3 tests).

### MEC-31: Spree (RULE 702.172a) and Escalate (RULE 702.120) — two "choose one or more" cost shapes, one selection primitive

- **What:** Neither keyword did anything before this ticket — both are variants of RULE 700.2's "choose one or more" modal shape (already fully built: `AbilitySpec.modes["at_least"]`/`"choose"`, `_effects_for_mode`/`_modal_cast_actions` offering one action per legal combination of 1..N modes), but each prices the combination differently from an ordinary modal spell, where every combination costs the same. **Spree** prices each mode *individually* — the total is the sum of every chosen mode's own cost, on top of the printed mana cost. **Escalate** prices the combination by a single *flat* cost paid once per mode chosen *beyond the first*, regardless of which modes those are. The two never appear on the same card, and neither needed a new mode-*selection* mechanism — RULE 700.2's `at_least`/`choose=1` combination sweep was already exactly "choose one or more." What was missing was purely on the *cost* side: `GameEngine.can_cast`/`effective_cast_cost`/`_auto_tap_for_cast_if_needed` never took a `mode` parameter at all (every existing modal shape prices identically regardless of which mode is chosen, so there was nothing to read it for), and `_cast_action`/`_modal_cast_actions` never priced or locked a combination individually. All four gained a `mode` parameter; a new `GameEngine._modal_extra_cost(obj, mode)` computes the surcharge for a given combination (Spree: sum `obj.spell_modes[i]["cost"]` for each chosen `i`; Escalate: `_escalate_cost(obj)` times `len(mode) - 1`), consulted everywhere cost is computed or checked, and `_cast_action` now locks each combination independently (`"modal_extra_cost"`/`"locked"`/`"Manakosten nicht bezahlbar"`) since, unlike Farewell's flat "choose N or more," two combinations of a Spree/Escalate card can differ in whether they're affordable at all.
- **Parser:** Spree needed real new grammar (`catalogue/modal.split_spree_block`, PARSER_VERSION 94): a bare "spree" header line (its reminder text already stripped by `normalize` by the time the segmenter sees it) followed by 2+ "+ `<cost>` — `<body>`" mode lines, each carrying its own mana cost — a shape `MODAL_HEADER_RE`'s "choose N —" grammar can't express at all, since Spree's header carries no count (always "choose one or more" by definition) and its mode lines aren't bare "• " bullets. `AbilitySpec.modes["mode_costs"]` (parallel to `options`/`descriptions`, validated in `spec.py` to match 1:1 and require the `at_least`/`choose=1` shape) carries the per-mode costs into `effect_binder._build_mode_entries`, which folds `mode_costs[i]` onto `spell_modes[i]["cost"]`. **Escalate needed no parser handler at all** — "Escalate `<cost>`" is already a plain cost-bearing parametric keyword (`parser/oracle/catalogue/keywords.py`'s `_C` table, same shape as Buyback/Mutate), and "Choose one or more —" is the ordinary already-shipped RULE 700.2 header; `GameEngine._escalate_cost` just reads `parametric_keywords["escalate"]["cost"]`, mirroring `_buyback_cost`/`_mutate_cost` exactly.
- **Return the Favor** (`Ojer cEDH`'s own named blocker) is hand-authored rather than reached through the new parser grammar: its "change the target of target spell or ability with a single target" mode is the parser's own already-built `change_target` handler output verbatim (`EffectSpec("change_target", {"spell_or_ability": True})`, ENG-26), but its "copy target … spell, activated ability, or triggered ability … choose new targets" mode needs a real ability-copy primitive `CopySpellEffect`/`RulesEngine.copy_spell` don't have (`copy_spell` returns `[]` outright when `item.obj is None`, i.e. for any ability stack item — copying a spell is all it has ever done) — tracked as its own future gap rather than built here. Hand-authored with the same two simplifications every other targeted-copy catalogue entry already carries (Reiterate/Narset's Reversal/Dualcaster Mage, per `CopySpellEffect`'s own docstring): spells only, original targets kept (no interactive "choose new targets" pick, though `copy_spell`'s own `new_targets` param already exists for whenever a caller wires one up).
- **Files:** `parser/oracle/catalogue/modal.py` (`SPREE_HEADER_RE`/`SPREE_MODE_LINE_RE`/`split_spree_block`), `parser/oracle/gate.py` (`_process_spree_block`, dispatch loop, `PARSER_VERSION` 94), `parser/oracle/spec.py` (`mode_costs` validation + `to_dict`/`from_dict`), `game/effect_binder.py` (`_build_mode_entries`'s `"cost"` key), `game/engine/casting_mixin.py` (`_escalate_cost`, `_modal_extra_cost`, `mode` threaded through `can_cast`/`effective_cast_cost`/`_auto_tap_for_cast_if_needed`/`_cast_current_face`), `game/engine/legal_actions_mixin.py` (`_cast_action`'s per-combination cost/lock, `_modal_cast_actions` docstring), `game/ability_catalogue.py` (Return the Favor).
- **Tests:** `tests/test_spree_family.py` (new, 14 tests — parser grammar, `AbilitySpec` validation, binder, legal-actions cost/lock, casting with 1/2 modes and insufficient mana, Escalate's flat per-additional-mode surcharge, Return the Favor's two modes end to end).

### MEC-33: Omen Machine — an existing draw cap at zero, plus a genuine "each player's step, that player" tail

- **What:** "Players can't draw cards. At the beginning of each player's draw step, that player exiles the top card of their library. If it's a land card, the player puts it onto the battlefield. Otherwise, the player casts it without paying its mana cost if able." Two independent pieces, both diagnosed against what already existed rather than assumed new. (1) "Players can't draw cards" turned out to need **no new code at all**: `continuous.max_draws_per_turn` (RULE 121.5-adjacent, already built for Spirit of the Labyrinth/Narset, Parter of Veils) is a flat per-turn draw cap, `affects="all"` already its own default — a cap of `max_per_turn=0` *is* an outright ban, a value nobody had ever asked the primitive for before. (2) The replacement action needed a real primitive: a `STEP_BEGIN` trigger on the "draw" step with **no `phase_relation` at all**. Since RULE 500.1 gives only the active player a draw step on any given turn, an unscoped "at the beginning of the draw step" trigger already fires exactly once per turn, for whoever that is — the same set of firings "each player's draw step" describes, just never phrased that way in this catalogue before. `ExileTopOfLibraryEffect` (MEC-38, Necropotence) gained a `player_selector="active_player"` option, reading `GameState.active_player` live at resolution instead of the source's own controller — the same "no subject of its own" idiom `DealDamageEffect`'s existing `"active_player"` recipient key already established (Roiling Vortex-shaped, RULE 121-adjacent), just not previously reused anywhere else. The land/free-cast tail is a new `LandOrFreeCastEffect`, reading whatever the exile effect just made available (`GameContext.created_objects[-1]`, the same "read what an earlier clause created" idiom `AttachEffect`/`ReturnFromGraveyardEffect` use) — a land goes straight to the battlefield (`RulesEngine._remove_from_current_zone` first, a real bug caught in testing: `GameState.add_to_battlefield` never removes the object from wherever it currently sits, so skipping this left it listed in both `player.exile` and the battlefield at once), anything else is cast via `RulesEngine.cast_without_paying` when RULE 601.2c's target requirements are satisfiable (replicated directly off `targeting.requirements_with_targets`/`all_requirements_satisfiable` — an effect has no `GameEngine` to call `has_legal_targets` through, only `GameContext.engine`, which is the `RulesEngine`), left in exile untouched otherwise ("if able" names no other fallback). **Documented simplification**, consistent with the rest of the codebase: a castable card is auto-targeted at its first legal option per requirement rather than opening a real interactive choice — this engine has no "pause mid-resolution for a nested cast+targeting cycle" primitive yet (`game/rules/misc_mixin.py`'s own `"grant_free_cast"` branch, MEC-20, already names the identical gap for Expertise's same-turn free cast), so every other automatic-cast primitive already accepts the same reading.
- **General primitive, not a one-off:** the exact same tail — "if it's a land card, the player puts it onto the battlefield. Otherwise, the player casts it without paying its mana cost if able." — also prints on Wild Evocation, off a *revealed random hand card* rather than an exiled library card. `LandOrFreeCastEffect` only consumes `created_objects[-1]`, so a future Wild Evocation catalogue entry only needs its own source half (a random-hand-reveal effect) to reuse this tail unchanged.
- **Files:** `game/effects.py` (`ExileTopOfLibraryEffect.player_selector`, `LandOrFreeCastEffect`, the `"exile_top_of_library"`/new `"land_or_free_cast"` `EffectRegistry` factories, `targeting` imports widened), `game/ability_catalogue.py` (Omen Machine).
- **Tests:** `tests/test_omen_machine_family.py` (new, 6 tests — flat draw ban incl. the controller's own draws, the land branch, the free-cast branch with life loss, an uncastable-nonland-card-stays-exiled negative case, and the trigger firing for both players' own draw steps across a turn rotation).

### MEC-44: Necromancy — RULE 303.4f's non-Aura reanimator, and how much smaller its "real blocker" turned out to be

- **What:** "You may cast this spell as though it had flash. If you cast it any time a sorcery couldn't have been cast, the controller of the permanent it becomes sacrifices it at the beginning of the next cleanup step. When this enchantment enters, if it's on the battlefield, it becomes an Aura with 'enchant creature put onto the battlefield with Necromancy.' Put target creature card from a graveyard onto the battlefield under your control and attach this enchantment to it. When this enchantment leaves the battlefield, that creature's controller sacrifices it." Animate Dead's own sibling ticket (MEC-34) — that card is a real Aura from load time; Necromancy prints as a plain Enchantment and only *becomes* one once its own ETB ability resolves. Three real gaps, each smaller once actually measured than the ticket's own filing had assumed. (1) The unconditional flash grant: `ALLOWED_CAST_CONDITION_KEYS` had only ever carried *conditional* keys (`entered_this_turn`/`targets_a_commander`) — added `"unconditional"` (`condition_query.conditional_flash_holds`'s new trivially-true branch), the whitelist's first member that gates nothing at all. (2) "If cast at a time a sorcery couldn't have been cast, sacrifice at next cleanup": a new `GameObject.cast_outside_sorcery_speed` flag, stamped once at cast time (`GameEngine._cast_current_face`, right where `player is active_player and _in_main_phase() and not stack` is cheap to compute and about to become unanswerable once the board moves on) and read by a new `EffectSpec.condition` key of the same name — no new delayed-trigger primitive needed at all, since `CreateDelayedTriggerEffect`'s existing `step`/`scope` params already reach "at the beginning of the next cleanup step" (RULE 514) and `sacrifice_self` was already registered (Dress Down/Underworld Breach). (3) "It becomes an Aura with `<quoted text>`" — the ticket's own flagged "real blocker," estimated as needing `parametric_keywords` threaded through every reader as a genuinely mutable field. Measured instead of assumed: `_attachment_kind`/`_attachment_legal`/`_detach_attachments_from` all already read `GameObject.parametric_keywords` fresh off the live object on every call — nothing caches or snapshots it anywhere — so the only real gap was that nothing had ever *written* to it after bind time. The new `BecomeAuraEffect` does exactly that (`self.source.parametric_keywords["enchant"] = {"quality": ...}`), and every consumer picks it up for free with zero threading. Scoped deliberately to the `enchant` key specifically, not RULE 305.1c's fully general "becomes a `<type>` with `<quoted ability>`" template (which could grant *any* ability, not just an attachment restriction) — that stays real, separate future work for whichever next card actually needs it.
- **Reuse:** `ReturnFromGraveyardEffect`/`AttachEffect(target_kind="created")`/`SacrificeAttachedPermanentEffect` (all MEC-34) carry over wholesale, but with a genuine RULE 115 target on the reanimate clause itself (`target_kind="any_graveyard_creature"` — "**a** graveyard", any player's) rather than Animate Dead's cast-time-stashed shape, since Necromancy carries no "Enchant" line at cast time for `_resolve_permanent_spell`'s graveyard-attach recognition to key off — its target is chosen when the *triggered ability* resolves instead, an ordinary interactive `pending_choice`. **Documented simplification**, matching Animate Dead's own: the "it loses/gains" self-referential quality-text-change (RULE 303.4f reminder text describing exactly this behavior, no separate gameplay effect) isn't modeled as its own clause — `BecomeAuraEffect`'s `quality="creature"` default is close enough that `_attachment_legal`'s existing permissive fallback (an unrecognized quality string matches everything) covers it regardless.
- **Files:** `models/game_object.py` (`cast_outside_sorcery_speed`), `game/engine/casting_mixin.py` (the stamp in `_cast_current_face`), `parser/oracle/spec.py` (`ALLOWED_CAST_CONDITION_KEYS`'s `"unconditional"`, `_ALLOWED_CONDITION_KEYS`'s `"cast_outside_sorcery_speed"`), `game/condition_query.py` (`conditional_flash_holds`'s new branch), `game/effects.py` (`ConditionalEffect._condition_holds`'s new branch, `BecomeAuraEffect`, the `"become_aura"` `EffectRegistry` factory), `game/ability_catalogue.py` (Necromancy).
- **Tests:** `tests/test_necromancy_family.py` (new, 6 tests — instant-speed castability, reanimation under the caster's control + becoming an Aura, the leaves-battlefield sacrifice, sorcery-speed cast arming no delayed trigger, instant-speed cast arming one, and that delayed trigger actually firing at cleanup).

### MEC-40 batch 1: six small cards closed via three general primitives (`cEDH Rocco`/`cEDH staples`/`cEDH staples 2`)

- **What:** The first pass at `cEDH Rocco`'s own residue (MEC-40), sized against the live cache with `author_card.py`/`engine_bench.py` before writing anything — every one of the six closed cards had been diagnosed as needing a whole new mechanism somewhere in a prior batch's notes, and none actually did. **Abrupt Decay** ("This spell can't be countered. Destroy target nonland permanent with mana value 3 or less.") was a pure parser bug, not a gap at all: `_destroy_mv`'s own docstring already named Abrupt Decay by name, but its allowed-kinds tuple was `("creature", "permanent")` — missing `"nonland_permanent"`, even though `targeting.py`'s `nonland_permanent` branch already honours `max_mana_value` and `_cant_be_countered` was already claimed. One line. **Culling Ritual** ("Destroy each nonland permanent with mana value 2 or less. Add {B} or {G} for each permanent destroyed this way.") needed the same one-word gap fixed on the *mass*-destroy side (`_MASS_DESTROY_NOUNS`/`_MASS_DESTROY_NOUNS_SINGULAR` had no "nonland permanent(s)" entry, despite `all_nonland_permanents` already being a real `_mass_selector_objects` selector, built for `_return_all_nonland`'s bounce sibling) plus one new same-resolution accumulator: `GameContext.permanents_destroyed_this_way`, `life_lost_this_way`'s exact sibling (same save/reset/restore in `_apply_effects_partitioned`, same "the *actual* effect, not the nominal ask" before/after check, this time in `GameContext.destroy` instead of `lose_life`), read by two new `AddManaEffect` params (`any_color_choices` — narrows the existing "ANY" colour-choice menu the way `add_mana_any_color`'s own `colors` param already narrows Kinnan's "any type that permanent produced"; `any_amount_from_context` — sizes that "ANY" pick off the new accumulator instead of `amount_from_target_count_selector`). **Documented simplification**: the real card lets the caster split the produced mana between {B} and {G} independently, mana by mana (RULE 106.1); this offers one colour choice for the *whole* batch instead, since no per-unit "how many of each" interactive shape exists yet — still fully usable colored mana, just less flexible than printed. **Cabal Ritual** ("Add {B}{B}{B}. Threshold — Add {B}{B}{B}{B}{B} instead if there are seven or more cards in your graveyard.") sidesteps the still-open general "if `<condition>`, `<effect>` **instead**" override primitive (CLAUDE.md's Notable Gaps — the same shape RULE 702.33b's "if kicked, `<effect>` instead" needs) entirely: 5 = 3 + 2, so it's modeled as a flat 3 B plus a *conditional extra* 2 B, mathematically identical to the real "instead" wording without needing an override at all. The condition itself is new and genuinely reusable: `EffectSpec.condition`'s `cards_in_graveyard_at_least` key, a plain graveyard-size read distinct from `static_conditions.py`'s own `card_types_in_graveyard_at_least` (a *distinct-types* count for a permanent's standing `active_if`, not reachable from a resolve-time `ConditionalEffect` at all). **Ranger-Captain of Eos** ("When this creature enters, you may search your library for a creature card with mana value 1 or less... Sacrifice this creature: Your opponents can't cast noncreature spells this turn.") — the ETB was already fully parser-claimable (`author_card.py reuse` confirmed it); the sacrifice ability just wraps the already-standing `cast_prohibition` static (Gaddock Teeg/Lavinia-shaped) in the already-general `GrantUntilEffect`, `target_kind=None` since the prohibition's own `scope="opponents"` param does the scoping (read off `ability.source.controller_id`, which survives the source being sacrificed — `GameEffect.source` keeps its object reference regardless of the object's current zone). **Vexing Shusher** ("This spell can't be countered. {R/G}: Target spell can't be countered.") — the static was already claimed; the activated ability just widens `MarkCantBeCounteredEffect` (built for Mistrise Village's untargeted "the next spell you cast this turn") with an optional `target_kind` param, opting it into a genuine RULE 115 `TargetSpec(kind="spell")` instead of relying on a caller to hand a spell in via `targets[0]`. **Tinder Wall** ("Defender. Sacrifice this creature: Add {R}{R}. {R}, Sacrifice this creature: It deals 2 damage to target creature it's blocking.") needed exactly one new thing: `targeting.py`'s `"creature_source_is_blocking"` target kind, reading `GameObject.blocking`/`additional_blocking` off the ability's own source instead of the whole battlefield (RULE 115.1a's protection/hexproof checks still apply — this narrows the *candidate pool*, it doesn't bypass legality). Defender and the plain sacrifice-for-mana ability needed no catalogue entry at all: `parse_keywords`/`mana_abilities_for` both scan a `GameObject`'s own oracle text directly, entirely independent of whether the card is registered in `ability_catalogue.py` — a registration only turns off `specs_for`'s `AbilitySpec`-effects fallback, not these two sibling systems.
- **Files:** `parser/oracle/catalogue/handlers.py` (`_destroy_mv`'s widened kinds tuple, `_MASS_DESTROY_NOUNS`/`_MASS_DESTROY_NOUNS_SINGULAR`'s new "nonland permanent(s)" entries), `game/effects.py` (`GameContext.permanents_destroyed_this_way` + its `_apply_effects_partitioned`/`resume_deferred_effects` threading, `GameContext.destroy`'s bookkeeping, `AddManaEffect.any_color_choices`/`any_amount_from_context`, `ConditionalEffect`'s new `cards_in_graveyard_at_least` branch, `MarkCantBeCounteredEffect.target_kind`), `parser/oracle/spec.py` (`_ALLOWED_CONDITION_KEYS`'s new key), `game/targeting.py` (`"creature_source_is_blocking"` kind + its `ALLOWED_TARGET_KINDS`/label entries), `game/rules/casting_mixin.py` (`resume_deferred_effects`'s threading), `game/ability_catalogue.py` (Culling Ritual, Cabal Ritual, Ranger-Captain of Eos, Vexing Shusher, Tinder Wall — Abrupt Decay needed no catalogue entry, the parser fix alone closes it).
- **Tests:** `tests/test_mec40_batch1_family.py` (new, 13 tests covering all six cards — Abrupt Decay's mv-capped destroy and its target-offer-time exclusion of an over-cost permanent, Culling Ritual's mass wipe + mana rider (including the zero-destroyed no-op case), Cabal Ritual below/at threshold, Ranger-Captain's ETB search and its sacrifice ability actually shutting off an opponent's noncreature cast (while leaving the controller's own untouched), Vexing Shusher's static + targeted activated marker, Tinder Wall's target restricted to the actual blocked attacker, the damage-and-sacrifice resolution, and its mana ability).

### MEC-40: `cEDH Rocco` done to completion — the remaining 18 gaps, no deferrals

- **What:** The second, no-deferral pass at MEC-40 — every one of `cEDH Rocco`'s remaining 18 gap cards (Academy Rector, Ajani Nacatl Pariah/Avenger, Allosaurus Shepherd, Domri Anarch of Bolas, Eladamri Korvecdal, Elesh Norn Mother of Machines, Flamescroll Celebrant, Food Chain, Gandalf the White, Guardian Project, Guardian Sunmare, Kutzil Malamet Exemplar, Moon-Blessed Cleric, Sigarda Font of Blessings, Squee the Immortal, Sylvan Library, The Jolly Balloon Man, Yasharn Implacable Earth) closed in one batch, taking the deck to 98/98. As with batch 1, most of these turned out smaller than the ticket's own filing assumed once measured. **Food Chain** ("Exile a creature you control: Add X mana of any one color, where X is 1 plus the exiled creature's mana value. Spend this mana only to cast creature spells.") needed *zero* catalogue entry: `game/costs.py` gained an `exile_creature` cost field (`_EXILE_CREATURE_RE`, `ActivationCost.exile_creature`) and `game/mana_abilities.py` a dedicated `_EXILED_CREATURE_MV_ADD_RE` dispatch row producing a real `ManaAbility` — a genuine RULE 605.1a mana ability (no target, so RULE 605.1a doesn't disqualify it), reusing `_resolve_crew_cost`-shaped payment machinery via `_can_pay_activation_cost`/`_pay_activation_cost`'s existing `exile_creature` branch; `GameEngine.tap_for_mana` recomputes the produced amount from the newly-added `GameObject.last_cost_exiled_object_mv` stamp right after payment (mana abilities' own `options` are pre-resolved before a cost is ever paid, so the "1 plus whatever gets exiled" amount can't be known any earlier). The parser's own `segmenter._COST_LOOKS_REAL` sniff was also widened (`exile an? [a-z]+ you control`) so "Exile a creature you control:" is recognized as a real cost at all — the battlefield-zone sibling of the existing "exile this card from your hand" sniff (PARSER_VERSION 95). **Squee, the Immortal** ("You may cast this card from your graveyard or from exile.") is a new `SelfGraveyardOrExileCastPermissionEffect` marker, read directly off the object's own `static_effects` by a new `GameEngine._self_graveyard_or_exile_cast_permission` check wired into `can_cast`'s `in_castable_zone` — deliberately *not* `graveyard_cast.py`'s existing `GraveyardCastPermissionEffect` family, which is scoped to a permission granted by some *other* permanent scanned off the battlefield; this is the card's own standing self-permission, which needed no board scan since the source *is* the card being cast. **Guardian Sunmare** ("Whenever ~ attacks while saddled, search... Saddle 4") is RULE 702.171a Saddle's first real behaviour — until now keyword-recognized only. `ActivationCost.saddle_power` reuses Crew's own `_resolve_crew_cost`/`_crew_pool` pool-selection unchanged (702.171a is worded identically to 702.122a's "tap any number of other untapped creatures... total power N or greater"), landing on a plain `GameObject.saddled_until_turn` stamp (`effects.BecomeSaddledEffect`) rather than a RULE 613 layer effect, since being saddled changes no characteristic; `effect_binder._saddle_activated_ability` mirrors `_crew_activated_ability`'s own keyword-dispatch wiring. The "while saddled" trigger gate is a new `requires_saddled` trigger-condition key, the same "checks the source's own live state" idiom `requires_equipped` already uses. **Kutzil, Malamet Exemplar**'s "creatures you control **each with power greater than its base power**" is the aggregate-event qualifier the original MEC-40 filing had flagged by name: a new `contributor_power_gt_base` field on `EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER` (`GameEngine._apply_combat_damage`, comparing each contributor's live `power` against its own printed `card.power` — "base power" per the card's own Gatherer ruling *does* include counters and static boosts, so the derived-vs-printed comparison is exactly right) plus a matching `effect_binder` trigger-condition predicate, siblings of MEC-29's `contributor_power_at_least`/`contributor_subtype`. Its first static ("opponents can't cast spells during your turn") was already fully parser-claimable via the existing `cast_prohibition`+`active_if: your_turn` combination. **Elesh Norn, Mother of Machines** and **Gandalf the White** share two primitives built together: `TriggerDoublerEffect` gained a `cause_filter` (one or more `EventType`s the firing event must match, mutually exclusive with Roaming Throne's own `chosen_type` gate) and `cause_type_filter` (a closed "legendary"/"artifact" word list checked against the causing object) — Elesh Norn's own doubling is unscoped by type (`cause_filter=[ENTERS_BATTLEFIELD]` only), Gandalf's is scoped to legendary-or-artifact and fires on *either* entering or leaving (`cause_filter=[ENTERS_BATTLEFIELD, LEAVES_BATTLEFIELD]`). Elesh Norn's second clause ("permanents entering don't cause abilities of permanents your opponents control to trigger") needed the standing `trigger_prohibition` static (Tocatli Honor Guard/Torpor Orb-shaped, previously global-only) split into a fast `scope="all"` path (`continuous.trigger_suppressed`, checked once per event) and a new opponent-scoped `continuous.trigger_suppressed_for` sibling checked per candidate object inside `_collect_triggers`'s own per-permanent loop, since "whose ability" can't be answered once for the whole event. Gandalf's flash permission reuses the already-standing `flash_permission` static widened with a `type_filter` param (the same closed-word-list shape). **Allosaurus Shepherd**'s "green spells you control can't be countered" is `GrantCantBeCounteredEffect`'s new `color` param (a `scope="color_spells_you_control"` sibling of the existing `creature_spells_you_control` scope); its activated ability ("each Elf creature you control has base power/toughness 5/5 and becomes a Dinosaur") is `GrantUntilEffect` wrapping `type_change` with the already-general `creatures_you_control_of_type_elf` selector (`continuous.group_selector_objects`'s existing `creatures_you_control_of_type_*` prefix family) — no new selector needed, just a real card finally using it for something other than a static anthem. **Domri, Anarch of Bolas**'s "+1: Add {R} or {G}. Creature spells you cast this turn can't be countered." combines the existing `add_mana`/`colors=["ANY"]` single-choice shape (narrowed to R/G) with `arm_spell_watcher` (RULE 118.3, `card_types=["creature"]`, `repeat=True` — Veil of Summer's own "for the rest of the turn" idiom) feeding `MarkCantBeCounteredEffect` via `then_specs`; its anthem and `-2` fight ability were already parser-claimable. **Eladamri, Korvecdal** and **Sigarda, Font of Blessings** share `TopLibraryPermissionEffect`'s two new filters: `creature_only` (Eladamri's "you may cast **creature** spells from the top of your library" — the direct mirror of the existing `noncreature_only`) and `subtypes` (Sigarda's "**Angel** spells and **Human** spells" — a closed word list, union semantics). Eladamri's reveal-a-card ability is a documented simplification: `SearchLibraryEffect`'s `zones` param has no "just the top card" source (only whole-zone scans), so it's modeled as "reveal a card from your hand" only, dropping the "or the top card of your library" alternative — his own standing "look at the top card any time" permission still lets a player plan around what that card is even though this ability can't reach it directly. **Guardian Project**'s "if it doesn't have the same name as another creature you control or a creature card in your graveyard" is a new `EffectSpec.condition` key, `entering_object_unique_name` — reads the entering object off `GameContext.trigger_event` (the group trigger's own subject, not `self.source`) and scans battlefield + graveyard by name; the printed "**nontoken**" qualifier folded into the same condition rather than the trigger's own `nontoken` flag, since that flag (`effect_binder._build_group_ok`) only ever combines with a `subtypes` filter, never a plain `type` one. **Academy Rector**'s "dies, you may exile it, if you do search for an enchantment onto the battlefield" collapses to the ability's own `optional=True` plus `[exile_self, search]` in sequence — the same "you may X. If you do, Y." idiom Ranger-Captain of Eos's ETB and Necromancy's reanimate already established, since there's no decision point between the exile and the search. **Ajani, Nacatl Pariah**'s transform trigger reuses `ExileReturnTransformedEffect` (RULE 400.7/712.8) completely unchanged; its ETB token was already parser-claimable. **Moon-Blessed Cleric** and **Yasharn, Implacable Earth**'s ETB searches needed no new primitive at all — Yasharn's "a basic Forest card and a basic Plains card" is just two ordinary `SearchLibraryEffect` calls back to back (rules-equivalent to one search for two named criteria, and simpler). Yasharn's second clause ("Players can't pay life or sacrifice nonland permanents to cast spells or activate abilities.") is the new `cost_restriction` static (`continuous.cost_restricted`), checked at both `_can_pay_additional_cast_cost` (a spell's own printed additional cost) and `can_activate`'s own `_can_pay_activation_cost`, ahead of the ordinary payability gates. **The Jolly Balloon Man**'s copy ability reuses `CopyPermanentEffect` widened with `set_power`/`set_toughness` (threaded through `Card.as_copy`/`RulesEngine.copy_permanent`, "except it's a 1/1") and a new `extra_temp_keywords` list (flying, alongside the existing `haste` bool) plus its already-existing `add_subtypes`; the delayed self-sacrifice reuses `create_delayed_trigger`'s `capture="created_objects"` + `sacrifice_specific` exactly as the Marchesa V4.2 batch's Kiki-Jiki primitive already established — no new mechanism there at all. **Documented simplification**: the token doesn't gain the printed extra "red" colour (`Card` has no colour-override field at all — colours are derived from mana cost, which a token has none of to override) — cosmetic only. **Sylvan Library**'s full "may draw two additional, choose two cards drawn this turn, pay 4 life or return each to the library" sequence is one new bespoke `SylvanLibraryEffect`, backed by two new pieces of general state: `GameState.cards_drawn_this_turn_ids` (`life_lost_this_way`'s "which objects", not just "how many", sibling — appended by `RulesEngine._single_draw`) and a new sequential chooser, `RulesEngine.request_pay_life_or_return_to_library`/`resolve_pay_life_or_return_choice` (a new `pay_life_or_return_to_library` pending-choice kind, re-opening for the next card until the queue empties, the same "resolve one, re-open for the rest" shape `request_choose_objects` already uses for a multi-pick). **Documented simplification**: doesn't offer a genuine "choose which two" decision when more than two cards were drawn this turn (a second simultaneous draw effect, rare) — always processes the most recently drawn two, which is always exactly this ability's own pair in the overwhelming common case.
- **Bug found along the way:** `MarkCantBeCounteredEffect.apply()` (built for Mistrise Village's "next spell you cast this turn") guarded its append with a bare `hasattr(target, "spell_effects")` — but `GameObject.spell_effects` is only ever *set* by `effect_binder.bind_from_catalogue` when a card has a genuine `"spell_effect"`-kind body; the overwhelming majority of creature/artifact/enchantment spells have none (only triggered/static/activated abilities), so the marker was silently dropped for any of them. Domri's own printed wording ("**creature spells** you cast this turn can't be countered") exercises exactly this gap directly, not as an edge case — found while writing its test, not a pre-existing regression. Fixed by initializing the list on first use instead of requiring pre-existence.
- **Files:** `game/costs.py` (`exile_creature`, `saddle_power`, their `is_free`/`label()` entries, `_EXILE_CREATURE_RE`), `game/mana_abilities.py` (`_EXILED_CREATURE_MV_ADD_RE` dispatch), `parser/oracle/segmenter.py` (`_COST_LOOKS_REAL` widened), `parser/oracle/gate.py` (`PARSER_VERSION` → 95), `game/engine/mana_mixin.py` (`tap_for_mana`'s exile-creature amount override), `game/engine/activation_mixin.py` (`_exile_creature_candidate`, `saddle_power` cost payment, the `cost_restriction` checks in `_can_pay_activation_cost`), `game/engine/casting_mixin.py` (the `cost_restriction` check in `_can_pay_additional_cast_cost`), `game/engine/lands_mixin.py` (`_self_graveyard_or_exile_cast_permission`), `game/effect_binder.py` (`_saddle_activated_ability`, `requires_saddled` trigger condition), `game/effects.py` (`SelfGraveyardOrExileCastPermissionEffect`, `BecomeSaddledEffect`, `SylvanLibraryEffect`, `TriggerDoublerEffect.cause_filter`/`cause_type_filter`, `GrantCantBeCounteredEffect.color`, `TopLibraryPermissionEffect.creature_only`/`subtypes`, `CopyPermanentEffect.set_power`/`set_toughness`/`extra_temp_keywords`, `MarkCantBeCounteredEffect`'s bug fix, the new `entering_object_unique_name`/`cost_exiled_creature_mv_plus_one`-adjacent condition branch, `cost_restriction` static registration), `game/continuous.py` (`cost_restricted`, `trigger_suppressed_for`, `trigger_doubler_bonus`'s `event` param, `has_standing_flash_permission`'s `type_filter`), `game/top_library.py` (`_grant_permits_cast`'s new filters), `game/engine/combat_mixin.py` (`contributor_power_gt_base` event field), `game/rules/draw_discard_mixin.py` (`cards_drawn_this_turn_ids`), `game/engine/turn_loop_mixin.py` (its reset, the new pending-choice dispatch), `game/rules/misc_mixin.py` (`request_pay_life_or_return_to_library`/`resolve_pay_life_or_return_choice`), `models/game_object.py` (`last_cost_exiled_object_mv`, `saddled_until_turn`), `models/game_state.py` (`cards_drawn_this_turn_ids`), `models/card.py` (`as_copy`'s `set_power`/`set_toughness`), `game/rules/copies_mixin.py` (`copy_permanent`'s new params), `parser/oracle/spec.py` (`entering_object_unique_name` in `_ALLOWED_CONDITION_KEYS`), `game/ability_catalogue.py` (all 18 cards).
- **Tests:** `tests/test_mec40_batch2_family.py` (new, 26 tests — one execute test per primitive/clause across all 18 cards).

### MEC-41: `[cEDH] Glarb Bloomsday` done to completion — the remaining 8 gaps, no deferrals

- **What:** All 8 of `[cEDH] Glarb Bloomsday`'s remaining gap cards (Ad
  Nauseam, Autumn's Veil, Bring to Light, Counterbalance, Lazotep Quarry,
  Nissa Steward of Elements, Valley Floodcaller, Gifts Ungiven) closed in
  one batch, taking the deck to 100/100. As with MEC-40, the ticket's own
  filing had assumed most of these needed new mechanisms; measured
  against the real engine, each turned out to be a real but modest
  extension of something already shipped. **Ad Nauseam** ("Reveal the top
  card of your library and put that card into your hand. You lose life
  equal to its mana value. You may repeat this process any number of
  times.") is a new `RevealTopHandLoseLifeLoopEffect`/`RulesEngine.
  request_reveal_top_hand_lose_life_loop` — the engine's *second*
  open-ended, self-re-opening loop (Lim-Dûl's Vault's `look_top_pay_
  life_loop` being the first), deliberately not a parameterization of
  that one: the life lost varies per revealed card instead of a flat
  cost, the destination is hand rather than back into the library, and
  RULE 118.4 (which bars paying more life than you have) simply doesn't
  apply to a life-*loss* effect the way it does the Vault's life
  *payment* — nothing here stops the loop once life would go to 0 or
  below, matching the real card's own well-known behaviour (SBAs aren't
  checked mid-resolution). **Autumn's Veil**'s second clause ("creatures
  you control can't be the targets of blue or black spells this turn") is
  a new, genuinely reusable RULE 115 targeting-restriction primitive —
  `GrantCantBeTargetOfSpellColorEffect` stamping a turn-scoped
  `GameObject.temp_cant_be_target_of_spell_colors` set, checked by
  `targeting._targetable_by` — deliberately narrower than both hexproof
  (which also blocks *abilities*, and which this engine has no
  colour-qualified form of at all — Veil of Summer's own entry documents
  that exact gap) and full protection (which also blocks damage/
  blocking/enchanting); distinguishing "is this source a spell" from "an
  ability" reuses the existing `source.zone != BATTLEFIELD` proxy rather
  than threading a new flag through `legal_targets`' several dozen call
  sites. **Documented simplification**: the first clause ("can't be
  countered by blue or black spells") is modeled as unconditional "can't
  be countered this turn" (Veil of Summer's own `mark_your_spells_on_
  stack_cant_be_countered`/`arm_spell_watcher(repeat=True)` shape) —
  `RulesEngine._is_cant_be_countered`'s RULE 118 check has no notion of
  *what* is doing the countering at all, and this is a strict widening
  (protects against every counterspell, not just blue/black ones), not a
  wrongly-narrower one; qualifying it by the countering spell's own
  colour is a real, disproportionate build for how rare non-blue/black
  counterspells are. **Bring to Light**'s Converge ("...mana value less
  than or equal to the number of colors of mana spent to cast this
  spell...") needed RULE 702.108a's own count for the first time:
  `GameObject.colors_spent_to_cast`, diffed off the payer's `ManaPool`
  before vs. after payment in `RulesEngine.cast_spell` (deliberately not
  touching `ManaPool.pay()`'s own payment solver, which only tracks
  colours spent on *constrained* pips, never the ones that happened to
  cover the generic portion — a snapshot diff sidesteps needing to). It
  reaches `SearchLibraryEffect`'s criteria through the *already-existing*
  `RulesEngine._substitute_x` — the same per-resolving-stack-item pass
  that already substitutes `"x"`/`"source_x_paid"` sentinels into a
  criteria dict's `max_mana_value` (Green Sun's Zenith, Invasion of
  Ikoria) — which just gained a third sentinel, `"colors_spent_to_cast"`,
  rather than building a parallel dynamic-criteria mechanism next to it.
  `SearchLibraryEffect` also gained a new destination, `"exile_free_
  cast"` — exiling the found card with a *standing* (never turn-swept)
  free-cast permission, combining `GameState.exile_cast_condition`'s
  existing empty-condition-always-holds idiom (`ExileEffect.grant_owner_
  play_permission`'s own precedent) with `GameState.free_cast_instance_
  ids`, distinct from the already-shipped `"cast_free"` (which casts
  immediately, Sunforger-shaped, rather than parking the card until the
  caster chooses to use it). **Counterbalance** ("Whenever an opponent
  casts a spell, you may reveal the top card of your library. If you do,
  counter that spell if it has the same mana value as the revealed
  card.") is `RevealTopThenCounterIfMVMatchEffect`, the counter-target
  sibling of Powerbalance's own `reveal_top_then_free_cast_if_mv_match`
  (Vivi B4 batch) — same reveal-is-informational/"you may" simplification
  and the same `GameContext.trigger_event`-sourced mana value, resolving
  into `CounterSpellEffect`'s own `target_from_trigger_event="instance_
  id"` idiom through `context.counter` (rather than a free cast) so RULE
  118 "can't be countered" stays honoured. **Lazotep Quarry**'s third
  ability ("{X}{2}, {T}, Sacrifice a Desert: Exile target creature card
  with mana value X from your graveyard. Create a token that's a copy of
  it, except it's a 4/4 black Zombie.") is the first card in this engine
  to combine an activated ability's own announced `{X}` with a
  graveyard-mana-value-linked target: `GameEngine.activate_ability` now
  stamps `source.x_paid = x` the same way `RulesEngine.cast_spell`
  already stamps a spell's own `x_paid`, which for free makes every
  existing X-reading effect (`AddCountersEffect.x_multiplier`, etc.) work
  for an ability's own source too. New `ExileOwnGraveyardCardManaValueX
  Effect` (a `request_choose_objects` pick among mana-value-X graveyard
  creatures) chained via `then_specs` into `CreateTokenCopyOfLinkedExile
  Effect` (the true-copy sibling of `CreateTokenForLinkedExileEffect`,
  reusing `RulesEngine.copy_permanent`'s existing `set_power`/
  `set_toughness`/`add_subtypes` overrides instead of a synthesized X/X).
  **Documented simplifications**: RULE 115's "target" is read as this
  resolve-time pick instead of a genuine announce-time target — a real
  RULE 115 target here would need X threaded into `legal_targets` *before*
  targets are gathered (RULE 601.2b announces X ahead of RULE 602.2b's
  targets), which no activated ability in this engine does yet, and
  building that sequencing for one card's own graveyard-only pick (where
  hexproof/protection/an opponent's response don't apply regardless) is
  disproportionate; colour ("black") is dropped, the same simplification
  The Jolly Balloon Man's own entry already accepts (`Card.as_copy` has
  no colour override). The two mana abilities needed no hand-authoring at
  all — `game/mana_abilities.py`'s `parse_mana_abilities` reads a card's
  printed text unconditionally, independent of `ability_catalogue`
  registration. **Nissa, Steward of Elements**'s 0 ability ("Look at the
  top card of your library. If it's a land card or a creature card with
  mana value less than or equal to the number of loyalty counters on
  Nissa, you may put that card onto the battlefield.") is a new
  `RevealTopThenMaybeBattlefieldIfLandOrCheapCreatureEffect` — a genuine
  "you may" (unlike the deterministic `RevealTopThenLandBattlefieldOr
  DrawEffect` Thrasios already uses), opened only when the top card
  qualifies, routed through a new `request_choose_objects` action,
  `"library_to_battlefield"` (general enough for any future "look at the
  top card, you may put it onto the battlefield" template). Its −6
  ("Untap up to two target lands you control. They become 5/5 Elemental
  creatures with flying and haste until end of turn. They're still
  lands.") needed no new primitive at all: it's Kamahl, Heart of Krosa's
  own "target land becomes a creature until end of turn, still a land"
  `grant_until`/`type_change`+`grant_keyword` chain (MEC-12), just
  widened from Kamahl's single target to "up to two" via `TapEffect`'s
  own pre-existing "untap up to two target lands" shape (Snap-shaped,
  ENG-30) for the untap half. **Valley Floodcaller**'s trigger ("Whenever
  you cast a noncreature spell, Birds, Frogs, Otters, and Rats you
  control get +1/+1 until end of turn. Untap them.") needed `PumpEffect`/
  `TapEffect`'s own new `subtypes` param — a `selector`-group narrowed by
  a subtype-name list, the sibling `AddCountersEffect.subtypes` already
  had and neither of these two previously did (mirroring
  `AddCountersEffect`'s exact type-line-parsing check). Its Flash and
  standing flash-permission clauses were already parser-`MODELED`
  (`flash_permission`'s `noncreature_only` param, built with this very
  card named in its own registry comment already). **Gifts Ungiven**
  ("Search your library for up to four cards with different names and
  reveal them. Target opponent chooses two of those cards. Put the chosen
  cards into your graveyard and the rest into your hand. Then shuffle.")
  generalizes Intuition's own two-phase `intuition_search`/`RulesEngine.
  request_intuition` shape rather than building a parallel one: new
  `search_optional` (RULE 701.19's "up to `<N>`", a decline option that
  stops the search early), `distinct_names` (excludes, each round, any
  library card sharing a name with one already found), and
  `chosen_count`/`chosen_destination`/`rest_destination` (letting the
  *chooser's own* pick move more than one card, and swapping which pile
  is which — Gifts Ungiven's opponent pick sends the chosen pair to the
  graveyard and the rest to the searcher's hand, the mirror image of
  Intuition's "chosen → hand, rest → graveyard"). Intuition's own
  existing behaviour is unchanged (every new param defaults to its
  original fixed shape), confirmed by a regression test.
- **Files:** `models/game_object.py` (`colors_spent_to_cast`, `temp_cant_
  be_target_of_spell_colors`), `game/rules/casting_mixin.py`
  (`colors_spent_to_cast` diff in `cast_spell`, `_substitute_x`'s new
  `"colors_spent_to_cast"` sentinel), `game/rules/search_mixin.py`
  (`request_reveal_top_hand_lose_life_loop`/`resolve_reveal_top_hand_
  lose_life_loop_choice`, `_put_searched_card`'s new `"exile_free_cast"`
  destination, `request_intuition`'s new params threaded through its
  whole two-phase choice-building/resolving chain), `game/rules/misc_
  mixin.py` (`CHOOSE_OBJECT_ACTIONS`'s new `"library_to_battlefield"` +
  its `_apply_chosen_object` branch), `game/engine/activation_mixin.py`
  (`activate_ability`'s `source.x_paid = x` stamp), `game/engine/turn_
  loop_mixin.py` (the new `reveal_top_hand_lose_life_loop` pending-choice
  dispatch, `intuition_search`'s dispatch now passing through a real
  decline), `game/targeting.py` (`_targetable_by`'s new colour-restriction
  check), `game/effects.py` (`GrantCantBeTargetOfSpellColorEffect`,
  `RevealTopThenCounterIfMVMatchEffect`, `RevealTopHandLoseLifeLoopEffect`,
  `RevealTopThenMaybeBattlefieldIfLandOrCheapCreatureEffect`,
  `ExileOwnGraveyardCardManaValueXEffect`, `CreateTokenCopyOfLinkedExile
  Effect`, `PumpEffect.subtypes`, `TapEffect.subtypes`, `IntuitionEffect`'s
  new params, all matching `EffectRegistry` entries), `game/ability_
  catalogue.py` (all 8 cards).
- **Tests:** `tests/test_mec41_family.py` (new, 16 tests — one or two
  execute tests per card, plus a regression test confirming Intuition's
  own unchanged behaviour under the generalized code).

### MEC-42: `cEDH staples` done to completion — all 12 named gaps

- **What:** Ashling, the Limitless; Dauthi Voidwalker; Derevi, Empyrial
  Tactician; Mana Crypt; March of Swirling Mist; Orcish Bowmasters;
  Praetor's Grasp; Sevinne's Reclamation; Teferi, Time Raveler; Touch the
  Spirit Realm; Tymna the Weaver, plus — closed in a follow-up pass the
  same day once RULE 702.62 Suspend existed as a real primitive — Delay.

  **Evoke (RULE 702.74)** had never been built at all (Solitude's own
  catalogue entry explicitly flagged it unmodeled) — this batch built the
  real mana-cost half: a new `evoke` param threaded through `can_cast`/
  `effective_cast_cost`/`cast_spell` exactly like Mutate's own cost
  substitution (`GameEngine._evoke_cost`, `GameObject.cast_via_evoke`),
  plus a genuinely new "sacrifice it when it enters" consequence (not a
  replacement — its own ETB trigger fires first) wired right after
  `_resolve_permanent_spell`'s ENTERS_BATTLEFIELD event. This closes the
  whole *mana-cost* Evoke family for free (Mulldrifter/Shriekmaw-shaped)
  — but not Solitude/Endurance/Fury/Subtlety/Grief's, whose Evoke cost is
  "exile a `<color>` card from your hand" (RULE 118.9's alternative-cost
  shape, never even parsed into `parametric_keywords` since the
  segmenter's cost-run regex only matches mana symbols); those five keep
  their own "not modeled" notes, unchanged. Ashling's own *grant*
  ("Elemental permanent spells you cast from your hand gain evoke {4}")
  is a new `grant_evoke` static (`continuous.granted_evoke_cost_for`, the
  hand-cast-cost sibling of `has_standing_flash_permission`'s "permission
  static outside the layer engine" idiom, since a card still in hand has
  nothing for RULE 613's layer engine to have stamped). Ashling's second
  ability ("whenever you sacrifice a nontoken Elemental, create a token
  copy with haste, sacrifice it at the next end step unless you pay
  {W}{U}{B}{R}{G}") needed two more small primitives: `CopyPermanentEffect`'s
  new `referent="trigger_event"` (reads the firing SACRIFICE event's own
  `instance_id` via `GameState.find_object`, which searches every zone —
  the sacrificed creature is already in the graveyard by the time the
  trigger resolves, so neither the existing `"source"` nor `"previous"`
  referent could name it), and `SacrificeUnlessPayEffect`'s new `target`
  override so the existing Kiki-Jiki/Puppeteer Clique `create_delayed_
  trigger(capture="created_objects")` primitive can bake the *token*, not
  Ashling herself, into the delayed sacrifice.

  **Dauthi Voidwalker**'s "if a card would be put into an opponent's
  graveyard from anywhere, instead exile it with a void counter on it" is
  a new standing `void_counter_redirect` static (`continuous.void_
  counter_redirect_controller_for`, the same battlefield-static-scan
  idiom Opposition Agent's `search_redirect` already uses), checked from
  `RulesEngine._move_to_graveyard` — the one choke point every
  graveyard-bound move funnels through — right alongside the existing
  Lurrus/Yawgmoth's Will redirects; `GameState.void_counter_holder`
  (`instance_id -> holder player_id`) is the marker, never swept. The
  activated ability's own `ChooseVoidCounterCardEffect` gathers the live
  candidate pool (every opponent's exile zone, filtered to that marker)
  and reuses MEC-20's already-general `"grant_free_cast"` chooser action
  — a same-turn free-cast window, exactly what "you may play it this
  turn without paying its mana cost" asks for.

  **Derevi, Empyrial Tactician**'s "you may tap or untap target
  permanent" needed a genuine new choice — `TapEffect`'s existing
  `untap` bool is fixed at bind time, but this is a real decision at
  resolution — so `TapEffect.choose_tap_or_untap` opens a new, small
  `RulesEngine.request_tap_or_untap_choice`/`resolve_tap_or_untap_choice`
  `pending_choice` instead of applying a fixed tap/untap directly. Two
  `AbilitySpec`s (ETB self, and the already-general RULE 603.1
  group-subject "a creature you control deals combat damage to a player"
  shape Bident of Thassa/Rapacious Guest already use) share the effect
  *shape*, each its own fresh `EffectSpec`. Its own third ability — a
  flat-cost "put Derevi onto the battlefield from the command zone" bare
  battlefield-entry, no stack, activated from a zone no activated ability
  in this engine can be offered from — is a documented, deliberate
  non-goal: RULE 903's ordinary command-zone *casting* (already fully
  supported, tax and all) reaches the identical outcome.

  **Mana Crypt** is `CoinFlipEffect`'s already-established "damage with
  `selector='controller'`" shape (Mana Vault's own "deals 1 damage to
  you") at its own printed amount; the mana ability needs no catalogue
  entry at all (`game/mana_abilities.py` reads plain "{T}: Add …" text
  unconditionally, independent of registration).

  **March of Swirling Mist**'s additional cost ("you may exile any
  number of blue cards from your hand. This spell costs {2} less to
  cast for each card exiled this way") is a genuinely new RULE 601.2b
  "announce a value, adjust cost, then pay it" shape — a new `exile_
  discount` param threaded through the same `can_cast`/`effective_cast_
  cost`/`cast_spell` chain evoke uses, gated by a new `exile_discount_
  cost` static (`continuous.exile_discount_spec_for`, read off the
  spell's own `static_effects` in hand, the same way Delve/Affinity's
  own "costs less" static already is) so the mechanism stays generic
  rather than hardcoded to blue/{2}. Found and fixed a real, general
  gap on the way: `ManaCost.reduce_generic` only ever matches a printed
  `GENERIC` symbol, silently doing nothing for a cost (like March's own
  `{X}{U}`) whose only generic component is `{X}` itself — new `ManaCost.
  reduce_generic_and_x` spills the remainder onto the `VARIABLE` symbol's
  own amount after generic is exhausted (RULE 107.3f: `{X}` becomes real
  generic mana once announced, so RULE 601.2f reductions do apply to it).
  "Up to X target creatures phase out" needed `PhaseOutEffect` widened
  from a single fixed target to a real multi-target count (`TargetSpec.
  count_selector`'s new `"source_x_paid"` entry, reading `GameObject.
  x_paid` fresh at target-gathering time, the same "live count, not a
  printed one" idiom Goad's own count-selector already established for a
  different source).

  **Orcish Bowmasters**'s "except the first one they draw in each of
  their draw steps" reuses MEC-32's own `EventType.DRAW` `first_in_draw_
  step` flag — via a plain `filter` exact-match, the *first* trigger
  consumer of it. Found and fixed a real, previously-invisible bug on
  the way: `RulesEngine._single_draw` computed `first_in_draw_step`
  correctly but only ever threaded it into the *input* event `apply_
  replacements` reads (MEC-32's own Notion Thief/Chains of Mephistopheles
  consumers); the event actually broadcast to trigger-collection (`_finish`'s
  own `state.fire_event` call) never carried the field at all, so no
  trigger's own "except the first ... draw step" condition could ever
  have worked, on any card, until now. Amass (RULE 701.48) had no
  primitive at all — new `AmassEffect` (create a 0/0 black Army `<Type>`
  token if you don't already control one, else put N counters on one you
  do, auto-picking among multiple exactly like every other untargeted
  "no chooser for an equally-valid pick" idiom in this engine).

  **Praetor's Grasp**'s "search **target opponent's** library" needed
  `SearchLibraryEffect`'s own controller (who actually picks) to differ
  from the library it searches/shuffles (the RULE 115 target) — new
  `player_from_target` resolving `player` to the targeted opponent, and a
  new `chooser` param threading a real "who answers" identity through
  `RulesEngine.request_search` down to `_search_choice`/`_finish_search`/
  `_put_searched_card` (`pending_choice["player_id"]` becomes "who
  answers", a new `library_owner_id` carries "whose library" — reusable
  by any future Bribery/Mind's Desire-shaped card). The new `"exile_face_
  down_standing_cast"` destination combines the existing face-down-in-
  exile marker (Beseech the Mirror) with a standing (never-swept)
  `GameState.exile_cast_condition` grant to the *chooser*, not the
  searched player — the ordinary-cost sibling of Bring to Light's own
  same-player `"exile_free_cast"` (MEC-41). Also fixed a real, general
  gap found on the way: `can_play_land` never checked `_has_conditional_
  exile_permission` at all, so this permission (or Lukka's own) could
  never actually offer a land, on any card.

  **Sevinne's Reclamation**'s reanimation half is `ReturnFromGraveyardEffect`'s
  already-general `target_kind="graveyard_permanent"`/`max_mana_value`
  (RULE 701.3 family). "If this spell was cast from a graveyard, you may
  copy this spell..." needed a genuine new self-copy primitive — new
  `RulesEngine.copy_self_spell`, `copy_spell`'s sibling that builds the
  copy `StackItem` directly off this spell's own `GameObject` rather than
  looking up a live stack entry (by the time this trailing clause
  resolves, the original has already been popped off `GameState.stack`
  for resolution). Reads `GameObject.cast_via_flashback` directly (still
  true at this point — the "exile instead of graveyard" clearing happens
  only after every effect, this one included, has resolved). Documented
  simplification: the copy keeps the original's own already-gathered
  target by default (RULE 707.10c's default outcome), the same "no real
  new-targeting yet" simplification `CopySpellEffect` already documents
  for every other copy-a-spell card.

  **Teferi, Time Raveler**'s static ("each opponent can cast spells only
  any time they could cast a sorcery") is a new `sorcery_speed_only`
  static (`continuous.forced_sorcery_speed_only`, consulted directly in
  `GameEngine.can_cast`'s own timing computation, forcing sorcery-speed
  even over an instant/Flash spell for a restricted opponent) — the
  mirror image of `flash_permission`'s existing "permission static
  outside the layer engine" treatment. The +1 reuses that same `flash_
  permission` static with a widened `type_filter` (a new `"sorcery"`
  word, `continuous.has_standing_flash_permission`'s own list check)
  wrapped in `GrantUntilEffect` at the already-supported `"your_next_
  turn"` duration. The −3 was already fully `MODELED` by the oracle-text
  parser; reused as-is via the `hand-author-card` skill's own `reuse`
  command.

  **Touch the Spirit Realm**'s ETB is the established O-Ring shape
  (`ExileEffect(remember=True)` + `ReturnLinkedExileEffect` on LEAVES_
  BATTLEFIELD, Shire Shirriff/Leonin Relic-Warder-shaped), just a new
  union target kind — `targeting`'s new `"artifact_or_creature"`, the
  same "two single-type kinds getting their own combined kind" idiom
  `artifact_or_enchantment` already established. Channel (RULE 702.29)
  needed no new primitive: its "Discard this card:" cost is already
  `ActivationCost.discard_self`, already fully wired for a hand-zone
  activation (`GameEngine.can_activate`'s own documented Channel/Cycling
  branch) — just never bound to a real card doing anything but Cycling
  before. Its own return clause reuses `ReturnLinkedExileEffect` again,
  fired from a plain `create_delayed_trigger` (`step="end", scope="any"`)
  instead of a LEAVES_BATTLEFIELD trigger.

  **Tymna the Weaver**'s trigger needed a genuine new count selector —
  `continuous.count_selector`'s new `"opponents_dealt_combat_damage_
  this_turn"`, aggregating `GameState.combat_damage_to_players_this_turn`
  (RULE 120.3, previously only ever read per-source) across every source
  that hit this turn, unlike that field's own keyed-by-source shape. The
  pay-X-draw-X body is the new `PayLifeEqualToOpponentsCombatDamagedDraw
  ThatManyEffect` — computes X once, then opens the already-general
  `RulesEngine.request_pay_cost_then` choice with a dynamically built
  `ActivationCost(pay_life=X)`/draw-X-cards pair, since `PayCostThenEffect`'s
  own fixed cost-text shape has no way to plug in a live board count.

  **Delay** ("Counter target spell. If the spell is countered this way,
  exile it with three time counters on it instead of putting it into its
  owner's graveyard. If it doesn't have suspend, it gains suspend.") was
  left open past this batch's first pass — `parser_probe.py blocked`
  confirms the countering clause is a genuine singleton (SOLO on 1), but
  it can't resolve correctly without RULE 702.62 Suspend's own time-
  counter/cast-on-zero mechanism, which had never been built at all (only
  keyword-recognized, per CLAUDE.md). A same-day follow-up pass built
  that as a real, general primitive rather than special-casing Delay
  alone: `RulesEngine.counter_spell`'s new `suspend_time_counters` param
  (threaded through `counter_unless_pays`, `CounterSpellEffect.
  suspend_instead`, `GameContext.counter`) redirects a countered spell to
  exile with N time counters instead of the graveyard, stamping
  `GameObject.granted_suspend` when the card has no printed Suspend of
  its own. RULE 702.62a's second and third abilities — "at the beginning
  of your upkeep, remove a time counter" and "when the last is removed,
  you may cast it without paying its mana cost" — are collected fresh
  every owner's upkeep by a new `_collect_suspend_triggers`
  (`game/rules/triggers_mixin.py`) rather than bound once at load time: a
  suspended card sits in exile, never a permanent, so `_collect_
  triggers`'s battlefield-only scan can never see it, and Suspend can be
  *granted* mid-game with nothing printed on the card to have pre-
  attached a bound `TriggeredAbility` to — the same "no permanent to hang
  an ability off" shape `_collect_inherent_triggers` already uses for
  Monarch/Initiative. `SuspendUpkeepEffect` (`game/effects.py`) is the
  combined atomic action (remove one counter; at zero, open the free-cast
  window), the same "remove, then branch on empty" shape Vanishing's own
  upkeep pair (`RemoveCounterOrSacrificeEffect`) already established. The
  free-cast offer itself reuses `RulesEngine.grant_free_cast_window_from_
  exile` — the same same-turn-only standing permission Rebound's own
  delayed half already grants (`ReboundFreeCastWindowEffect`), a
  documented fidelity trade-off for "no synchronous mid-resolution
  yes/no chooser" rather than a new one invented for Suspend. "If you
  cast a creature spell this way, it gains haste" is `GameObject.
  granted_suspend_haste`, stamped alongside the window and consumed once
  at resolution in `RulesEngine._resolve_permanent_spell` exactly like
  `cast_via_evoke`. Deliberately *not* built: RULE 702.62a's own first
  ability (paying the Suspend cost from hand as a special action, rather
  than a spell redirecting a countered card into it) — Delay's own path
  never needs it, and no other card in these seven cEDH decks prints a
  bare "Suspend N—cost" yet; left as a real, separately-scoped gap (see
  `BACKLOG.md`'s `MEC-43`) rather than silently assumed done.

- **Files:** `game/engine/casting_mixin.py` (`_evoke_cost`, the `evoke`/
  `exile_discount` params through `can_cast`/`effective_cast_cost`/
  `cast_spell`/`_cast_current_face`/`_auto_tap_for_cast_if_needed`, the
  `sorcery_speed` override), `game/rules/casting_mixin.py` (the
  post-ENTERS_BATTLEFIELD evoke-sacrifice check), `game/rules/copies_
  mixin.py` (`copy_self_spell`), `game/rules/damage_death_mixin.py` (the
  void-counter redirect check in `_move_to_graveyard`), `game/rules/draw_
  discard_mixin.py` (the `first_in_draw_step` broadcast fix), `game/rules/
  misc_mixin.py` (`request_tap_or_untap_choice`/`resolve_tap_or_untap_
  choice`, `CHOOSE_OBJECT_ACTIONS`, the `counter_spell`/`counter_unless_
  pays`/`resolve_counter_unless_pays_choice` `suspend_time_counters`
  threading), `game/rules/search_mixin.py`
  (`request_search`/`_search_choice`/`_finish_search`/`_put_searched_
  card`'s `chooser`/`library_owner_id` threading, the new `"exile_face_
  down_standing_cast"` destination), `game/rules/triggers_mixin.py`
  (`_has_suspend`, `_collect_suspend_triggers`), `game/engine/lands_
  mixin.py`/`legal_actions_mixin.py` (the `_has_conditional_exile_
  permission` land gap fix), `game/engine/turn_loop_mixin.py` (the
  `tap_or_untap` pending-choice dispatch), `game/continuous.py`
  (`granted_evoke_cost_for`, `void_counter_redirect_controller_for`,
  `exile_discount_spec_for`, `forced_sorcery_speed_only`, the new
  `"opponents_dealt_combat_damage_this_turn"`/`"sorcery"` selector
  entries), `game/targeting.py` (`"artifact_or_creature"`, `TargetSpec`'s
  new `"source_x_paid"` count selector), `game/effects.py` (`AmassEffect`,
  `ChooseVoidCounterCardEffect`, `CopySelfIfCastFromGraveyardEffect`,
  `PayLifeEqualToOpponentsCombatDamagedDrawThatManyEffect`,
  `PhaseOutEffect`'s multi-target widening, `TapEffect.choose_tap_or_
  untap`, `SacrificeUnlessPayEffect.target`, `CopyPermanentEffect`'s
  `referent="trigger_event"`, `SuspendUpkeepEffect`, `CounterSpellEffect.
  suspend_instead`, `GameContext.counter`'s `suspend_instead` param, all
  matching `EffectRegistry` entries), `models/mana_cost.py`
  (`reduce_generic_and_x`), `models/game_object.py` (`cast_via_evoke`,
  `granted_suspend`, `granted_suspend_haste`), `models/game_state.py`
  (`void_counter_holder`), `game/ability_catalogue.py` (all 12 cards).
- **Tests:** `tests/test_mec42_family.py` (21 tests covering every card's
  real in-engine behaviour, including the general Evoke primitive off a
  real cached evoke creature independent of Ashling's own grant, and
  Delay's full RULE 702.62 cycle — counter-into-exile-with-suspend, three
  owner's upkeeps counting down, the free-cast window opening, and haste
  on the eventual free cast).

### MEC-43: `cEDH staples 2` — first batch, 9 near-free reuses

- **What:** Contamination, Leveler, Natural Order, Magda Brazen Outlaw,
  Unmarked Grave, Unsubstantiate, Starting Town, Teferi Master of Time,
  March of Otherworldly Light — the first slice of `cEDH staples 2`'s
  45-card remainder, all near-free reuses of primitives shipped for
  entirely different cards, plus a handful of small, genuinely reusable
  additions found along the way.

  **Contamination**'s upkeep clause is already `MODELED` by the parser;
  its mana-override clause is an exact param match for `mana_type_
  override` (Damping Sphere) with `min_amount=1`/`to="B"` instead of
  Damping Sphere's `2`/`"C"`. **Leveler** is `ExileLibraryEffect`
  (registered for Paradigm Shift, never actually used by a card before
  now). **Natural Order**'s search half is parser-`MODELED`; its "sacrifice
  a green creature" additional cost needed a new `"<color>_creature"`
  compound sacrifice-cost sentinel (`_matches_sacrifice_type`'s new
  branch + `_SACRIFICE_COLOR_WORDS`, and the matching whitelist entry in
  `AbilitySpec._validate_additional_cost`). **Magda**'s anthem and
  tap-trigger are already parser-`MODELED` (reused via the `hand-author-
  card` skill's own `reuse` command rather than re-derived by hand); its
  activated ability is `ActivationCost.sacrifice_count`'s already-shipped
  `(count, subtype)` shape at `(5, "treasure")`. **Unmarked Grave** needed
  a new `"nonlegendary": True` search-criteria key (`models/card_query.py`),
  the negation of the already-recognized "legendary" type-line word.

  **Unsubstantiate** ("return target spell or creature") reuses
  `RulesEngine.bounce_spell_or_permanent` (Sink into Stupor/Hullbreaker
  Horror, MEC-12 M-K) almost unchanged — that method was already fully
  generic (falls back to ordinary `return_to_hand` whenever the target
  isn't currently a spell on the stack), so only a new, narrower
  `targeting` union kind (`"spell_or_creature"`) was needed, not a new
  resolve-time mechanism. **Starting Town**'s "enters tapped unless it's
  your first, second, or third turn of the game" needed a genuinely new
  RULE 614.1 conditional-enters-tapped gate — `parser/oracle/catalogue/
  lands.py`'s new `_UNLESS_TURN_AT_MOST_RE`/`"unless_turn_at_most"` kind
  (`PARSER_VERSION` bumped to 96), consumed at both existing dispatch
  sites in `game/rules/casting_mixin.py`. Since `land_tap_condition`
  reads a card's own oracle text directly (independent of catalogue
  registration, exactly like a mana ability), this closed the card with
  **no catalogue entry needed at all** once the parser recognized the
  clause — confirmed via `MODELED` coverage. **Documented simplification**:
  "your Nth turn" (RULE 500.1, a player's own turn count) has no tracker
  in this engine; `GameState.round_number` ("how often the turn has come
  back to whoever started") is used as the proxy — exact for the
  overwhelming common case, wrong only if a player's own turn count ever
  diverges from the table's shared round count (joining/leaving mid-game).

  **Teferi, Master of Time**'s instant-speed loyalty-activation clause
  reuses The Wandering Emperor's own `conditional_flash` mechanism
  (`GameEngine._can_activate_loyalty`) with MEC-44's already-shipped
  `"unconditional": True` member (Necromancy's own "as though it had
  flash" with no gate) instead of Emperor's "entered this turn" gate — no
  new primitive. Its −3/+1 are already parser-`MODELED`; its −10 is
  `TakeExtraTurnEffect` listed twice (no `count` param exists, so "two
  extra turns" is just two queued turns). **March of Otherworldly
  Light**'s additional cost is an exact recolor of March of Swirling
  Mist's own `exile_discount_cost` static (MEC-42) — white instead of
  blue. Its exile clause ("with mana value X or less") surfaced a real,
  general gap: `_substitute_x`'s existing `"x"` sentinel only ever
  resolves a *resolve-time* `filter`/`criteria` dict (a search/mass-
  effect shape) or, new this batch, a `TargetSpec.max_mana_value` at
  *resolution* — but a genuine RULE 115 **target** bound by `{X}` has to
  be gathered/offered at *cast* time, before resolution, when the announced
  X is known but not yet stamped anywhere reachable. Fixed generally:
  `GameEngine._cast_current_face` now stamps `GameObject.x_paid` early
  (right after entering `_mode_effects_applied`, before `has_legal_
  targets` runs) — harmless, since the real post-resolution stamp
  overwrites it with the identical value — and `targeting.legal_targets`
  resolves a `spec.max_mana_value` of `"x"`/`"-x"` off that same field
  before dispatching to any per-kind branch, so every existing and future
  "target `<X>` with mana value X or less" card benefits, not just this
  one. (March of Swirling Mist's own "up to X target creatures phase out"
  count, MEC-42, likely had the identical latent gap through the
  interactive board path — this fix closes that too, not just a new card.)

- **Files:** `game/engine/activation_mixin.py` (`_matches_sacrifice_type`'s
  new `"<color>_creature"` branch, `_SACRIFICE_COLOR_WORDS`),
  `parser/oracle/spec.py` (`_ADDITIONAL_COST_SACRIFICE_TYPES` widened,
  `PARSER_VERSION` implicitly unaffected — that bump lives in `gate.py`),
  `parser/oracle/gate.py` (`PARSER_VERSION` 95 → 96),
  `parser/oracle/catalogue/lands.py` (`_UNLESS_TURN_AT_MOST_RE`/
  `"unless_turn_at_most"`), `game/rules/casting_mixin.py` (the new kind's
  two dispatch sites), `game/engine/casting_mixin.py` (the early
  `x_paid` stamp in `_cast_current_face`), `game/targeting.py`
  (`legal_targets`'s new `"x"`/`"-x"` `max_mana_value` resolution, the new
  `"artifact_creature_or_enchantment"`/`"spell_or_creature"` union kinds),
  `models/card_query.py` (`"nonlegendary"`), `game/ability_catalogue.py`
  (all 9 cards).
- **Tests:** `tests/test_mec43_family.py` (new, 13 tests).

### MEC-43: `cEDH staples 2` — second batch, two shared-primitive clusters (+ MEC-45)

- **What:** Gaddock Teeg, Sanctum Prelate, Chalice of the Void, Ethersworn
  Canonist, Birthing Pod, Oswald Fiddlebender — the two "worth building
  once, not per-card" clusters `BACKLOG.md` had flagged in the first
  batch's own diagnosis — plus Chandra's Incinerator, closing MEC-45
  (`Ojer cEDH`'s last real engine gap; the deck's only remaining item is
  now the unrelated Balin's Tomb `flavor_name` import gap).

  **Cluster 1 — `cast_prohibition`'s literal/eq mana-value threshold.**
  Every prior `cast_prohibition` card read its mana-value bound off a
  dynamic `max_mana_value_selector` (a `count_selector` name evaluated
  against the board); nothing let a static carry a bare *literal*
  threshold. Added `max_mana_value` (an int, or the new `"chosen_number"`
  sentinel) and `cmp` (`"gt"` default / `"eq"`) to both the `cast_
  prohibition` `EffectSpec` factory and `continuous.cast_prohibited`.
  Gaddock Teeg's "mana value 4 or greater can't be cast" turned out to
  need no `cmp="eq"` at all — the pre-existing `mv <= allowed` check
  already reads as "prohibited above `allowed`", so a literal `3` was the
  whole fix; its second, independent clause ("spells with {X} in their
  mana costs can't be cast") is a wholly unrelated flat check
  (`has_x_cost`, a substring test on `mana_cost_string`), not a second
  mana-value comparison, so it's its own separate `cast_prohibition`
  static rather than a combined one. Sanctum Prelate needed the real
  `cmp="eq"` case plus a genuinely new RULE 601.2b pick this engine had
  never built: "as this enters, choose a **number**" (every prior
  enter-choice — creature type/color/named-mode/card-name — picks from
  either a small enumerable set or, for card name, free text; a number is
  the second free-text case). `ChooseNumberReplacement` — a fifth
  `enter_choice_effects` sibling of `ChooseCreatureTypeReplacement`/
  `ChooseColorReplacement`/`ChooseNamedModeReplacement`/
  `ChooseCardNameReplacement` — reuses `ChooseCardNameReplacement`'s own
  free-text `pending_choice` shape (`kind="choose_number"`, `free_text:
  True`) and stamps the parsed int onto the new `GameObject.chosen_
  number`, read back live by `max_mana_value="chosen_number"`. Ethersworn
  Canonist ("each player who has cast a nonartifact spell this turn can't
  cast additional nonartifact spells") turned out not to be a mana-value
  restriction at all — a boolean-flag family instead, so `cast_prohibited`
  gained a second, independent knob: `nonartifact` (the `noncreature`
  check's mirror, scoped to *not artifact* rather than *not creature*) and
  `min_count_selector` (prohibited once a named `count_selector`, read
  **for the casting player**, is >= 1 — checked before the current cast's
  own increment lands, the same "already reflects the very spell" ordering
  `spells_cast_this_turn`'s whole family relies on, so a player's own
  *first* nonartifact spell is never wrongly caught). Backing tracker:
  `GameState.nonartifact_spells_cast_this_turn`, the nonartifact-scoped
  sibling of `noncreature_spells_cast_this_turn`, incremented in lockstep
  by the same `RulesEngine._track_spell_cast` subscriber and reset the
  same game-wide-every-player way.

  Chalice of the Void turned out **not** to be a third `cast_prohibition`
  static at all, despite `BACKLOG.md`'s own framing as this cluster's
  "counter-trigger sibling" — its printed effect is "**counter that
  spell**" (RULE 701.5), not a prohibition on casting it in the first
  place. Its first clause ("enters with X charge counters") needed no
  code at all: `ability_catalogue.entry_counters` already recognizes
  "enters with X `<kind>` counters" (`is_x: True`) directly off a card's
  *raw* oracle text at every battlefield-entry site, independent of
  catalogue registration — confirmed live against the cached text. The
  trigger reuses `CounterSpellEffect.target_from_trigger_event`
  (Vexing Bauble's pre-existing "if no mana was spent to cast it, counter
  that spell" shape — "counter *that* spell" names the very spell whose
  cast fired the ability, not a chosen target) with one new predicate,
  `mana_value_equals_source_counters` (`effect_binder._trigger_condition`)
  — the firing `SPELL_CAST` event's `mana_value` against a live count off
  the ability's own source, since nothing previously compared an event
  field to a counter kind on the source itself.

  **Cluster 2 — activation-cost sacrifice-value stamping.**
  `GameObject.sacrificed_cost_mana_value` (Eldritch Evolution/Neoform, the
  original state-tracking batch) was only ever stamped for a **spell's**
  RULE 601.2b additional sacrifice cost (`_pay_additional_cast_cost`); the
  equivalent **activated-ability** sacrifice-cost path
  (`_pay_activation_cost`) sacrificed the victim and stamped nothing —
  confirmed via `sacrificed_cost_mana_value`'s own grep, a real gap, not
  a misreading. Mirrored the stamp there (right after the victim reaches
  the graveyard), plus the same unconditional per-payment reset the
  cast-cost site already does (so a stale value from an *earlier*
  activation that sacrificed something can't leak into a later one that
  doesn't). `SearchLibraryEffect.mana_value_from` needed no changes at
  all — it already reads generically off whatever `GameObject` an
  effect's own `source` resolves to, an activated ability's own permanent
  here exactly as it was a spell's own object before. Birthing Pod and
  Oswald Fiddlebender are both the identical Neoform-shaped "search for a
  card with mana value equal to 1 plus the sacrificed X's mana value, put
  it onto the battlefield" template — one card, one artifact — so both
  closed from the existing search machinery with no further engine work.

  **Latent bug found and fixed along the way (unrelated card, same
  function):** Void Winnower's own `cast_prohibition` clause ("…spells
  with even mana values") had shipped in the MEC-12 Kinnan/M-K batch
  carrying an `even_mana_value` param that the `cast_prohibition`
  `EffectSpec` factory never actually captured (not in the params dict,
  not in `_selectors`' whitelist) — so it silently fell through, and
  `cast_prohibited` had nothing to compare mana value against at all,
  meaning the clause prohibited **every** opponent spell unconditionally
  regardless of mana value (no test had ever exercised it). Found while
  widening this exact factory for `max_mana_value`/`cmp`; fixed by adding
  `even_mana_value` as its own independent flat check, the same shape
  `has_x_cost` uses.

  **MEC-45 (Chandra's Incinerator).** "This spell costs {X} less…where X
  is the total amount of noncombat damage dealt to your opponents this
  turn" reuses `self_cost_reduction_for`/`_cost_static_amount`'s existing
  `per`-count_selector multiply unchanged — the only new piece is
  `GameState.noncombat_damage_to_opponents_this_turn`, a running
  per-player *amount* total (unlike `combat_damage_to_players_this_turn`'s
  own per-source hit-*set*, since RULE 120.3 only ever asks "was this
  player hit", never "how much"), incremented directly in `RulesEngine.
  deal_damage`'s existing player-damage branch and registered as an
  ordinary `count_selector` value. The trigger ("whenever a source you
  control deals noncombat damage to an opponent, ~ deals that much damage
  to target creature or planeswalker that player controls") needed two
  genuinely new pieces on the *target* side (the amount side was already
  general — `DealDamageEffect.amount_from_trigger_event`, Imodane's own
  primitive): a `requires_damage_to_opponent` trigger-condition predicate
  (the DAMAGE event's recipient must be some player other than this
  ability's own controller — the existing `"group"`/`"controller": "you"`
  check only ever scopes the *source*, never who was hit; combined with
  the DAMAGE event's own already-general `"filter": {"combat": False}`
  for "noncombat"), and a wholly new `targeting.py` kind, `creature_or_
  planeswalker_that_player_controls` — "that player" is whichever
  opponent the *firing* trigger event actually named, not a fixed
  "opponent" role, so `legal_targets` gained a new `trigger_event`
  parameter (threaded from `triggers_mixin.py`'s two target-gathering
  call sites, both of which already had the firing event in scope but
  had never passed it through).

- **Files:** `game/continuous.py` (`cast_prohibited`'s `max_mana_value`/
  `cmp`/`has_x_cost`/`nonartifact`/`min_count_selector`/`even_mana_value`,
  two new `count_selector` entries), `game/effects.py` (the matching
  `cast_prohibition` factory params, `ChooseNumberReplacement` +
  `choose_number_on_enter` registration), `game/engine/activation_
  mixin.py` (the sacrifice-cost stamp + its reset), `game/engine/turn_
  loop_mixin.py` (two new per-turn resets), `game/rules/misc_mixin.py`
  (`_track_spell_cast`'s new nonartifact tally), `game/rules/damage_
  death_mixin.py` (the noncombat-damage-to-opponents increment),
  `game/rules/casting_mixin.py` (`_offer_enter_choices`/`resolve_enter_
  choice`'s new `choose_number` kind), `game/effect_binder.py`
  (`mana_value_equals_source_counters`/`requires_damage_to_opponent`
  predicates, `ChooseNumberReplacement` wired into `enter_choice_effects`),
  `game/targeting.py` (`creature_or_planeswalker_that_player_controls`,
  `legal_targets`'s new `trigger_event` param), `game/rules/triggers_
  mixin.py` (threading `trigger_event` through both target-gathering call
  sites), `models/game_object.py` (`chosen_number`), `models/game_state.py`
  (`nonartifact_spells_cast_this_turn`, `noncombat_damage_to_opponents_
  this_turn`), `game/ability_catalogue.py` (all 7 cards).
- **Tests:** `tests/test_mec43_cast_prohibition_family.py` (new, 17
  tests) — a separate file from the first batch's own `tests/test_mec43_
  family.py`, since that name was already taken.

### MEC-43: `cEDH staples 2` — third batch, 22 "near-free reuses"

Closed the ticket's own "near-free reuses" cluster — all 22 named cards,
Jeweled Amulet included (closed in an immediate follow-up pass rather
than risking a third deferral of its own "note the type of mana spent"
tracker, per this repo's own no-half-implementations rule). Each card
needed only a small param-widening of an existing primitive, but the
batch touched a lot of surface area because "small" was spread across
~20 different primitives rather than one shared one, unlike the first two
MEC-43 batches. New/widened primitives, grouped by what they closed:

- **Sacrifice-cost magnitude**: `GameObject.sacrificed_cost_power` (the
  power sibling of `sacrificed_cost_mana_value`, stamped by `GameEngine.
  _pay_ability_cost` alongside it) plus two new `continuous.count_selector`
  entries (`"sacrificed_cost_mana_value"`/`"sacrificed_cost_power"`) reading
  either field generically — `MillEffect` gained a `count_selector` param
  (Altar of Dementia: "mills cards equal to the sacrificed creature's
  power") and `AddManaEffect`'s `colors=["ANY"]` branch gained an
  `amount_selector` fallback (Burnt Offering's "any combination of {B}
  and/or {R}" reusing the same selector Sacrifice's fixed-colour form
  already read).
- **`graveyard_redirect`** (Leyline of the Void/Rest in Peace): the
  plain-exile sibling of Dauthi Voidwalker's `void_counter_redirect` (no
  counter/holder tracking), `scope="opponent"`/`"any"`, checked in
  `RulesEngine._move_to_graveyard` right alongside it.
- **`cast_prohibition` widened three ways**: `color`+`creature_only`
  (Llawan's "opponents can't cast blue creature spells" — the first card
  needing both a colour and a card-type restriction at once) and `zones`
  (Soulless Jailer's "can't cast … from graveyards or exile", the
  allowlist sibling of the existing `hand_only` single-zone exemption).
- **`grant_borrowed_activated_ability`'s new `source_mode="top_of_
  library"`** (Conspicuous Snoop): a library card is never bound the way
  every other donor mode's card already is, so this builds a scratch,
  off-zone `GameObject` purely to read its `.activated_abilities`,
  rebuilt fresh every recompute pass (an accepted simplification: a
  borrowed ability's own "once per turn" state doesn't survive a pass
  where the top card changes). `donor_subtype` narrows the donor filter.
- **`dig_until`'s new `rest_destination="graveyard"`** (Hermit Druid): a
  plain library→graveyard move for the dig's non-hit cards, mirroring
  `mill`'s own direct zone move rather than `_move_to_graveyard`'s full
  battlefield-leave machinery (these cards are library cards being
  discarded past, not permanents dying).
- **A new `defending_player_id` field on `EventType.ATTACKS`** (Kogla,
  the Titan Ape) plus `targeting.py`'s matching `"artifact_or_enchantment_
  defending_player_controls"` kind — the already-resolved RULE 508.1a
  defender, threaded onto the event so a per-attacker trigger's own target
  can reach it without re-deriving it from `combat_defender`.
- **`EachPlayerPayOrEffect`/`request_each_player_pay_or` widened with
  `scope`** (`"each_player"` default, `"each_opponent"` excludes the
  ability's own controller from the sweep) **and `effect_targets`**
  (`"decliner"` default, `"controller"` routes the "if they don't pay"
  effect to the ability's own controller instead) — Acererak the
  Archlich's "for each opponent, you create a token unless that player
  sacrifices a creature" needed both knobs at once, the first card to.
- **A new `not_completed_dungeon` trigger predicate** (`effect_binder.
  _trigger_condition`, reading `Player.completed_dungeons`) for Acererak's
  ETB "if you haven't completed Tomb of Annihilation" — RULE 309.7's
  completion record had never been read by a trigger condition before.
- **A new `not_controllers_turn` trigger predicate** (already-shipped
  actually — Tataru Taru's "if it isn't that player's turn" just reused
  it against the firing `DRAW` event's own actor) plus ordinary
  `TriggeredAbility.once_per_turn` (via the trigger dict's `"limit"` key,
  not a top-level `AbilitySpec` kwarg — the one wiring mistake this batch
  actually hit).
- **Five one-off `GameEffect` subclasses**, each backing exactly one
  card's own shape: `BounceOwnLandFromTriggerEffect` (Mana Breach — "that
  player returns a land they control", the triggering player read off
  `SPELL_CAST`'s `player_id`, not the ability's controller);
  `DrawIfTriggerObjectGreatestPowerEffect` (Selvala — a strict "greater
  than **each** other creature" comparison against the firing
  `ENTERS_BATTLEFIELD` event's own object); `CopySelfControlledByPrevious
  TargetEffect` (Chain of Smog — the copier is the preceding discard
  clause's own target, read off `GameContext.previous_targets`, not the
  caster); `_draw_exile_face_up_replacement` (Uba Mask — a genuine
  `ReplacementEffect` on `EventType.DRAW`, the first to ever rewrite what
  a draw *becomes* rather than just its count; grants `GameState.
  temp_play_permissions` on the exiled card in the same step, so the
  card's own second line — "may play … from among cards exiled with ~" —
  falls out for free); `GrantCantBeCounteredEffect`'s new
  `"creature_or_enchantment_spells_you_control"` scope (Destiny Spinner —
  its land-animation half is deliberately left unbound, the recurring
  "animate a noncreature permanent" gap `BACKLOG.md` tracks separately).
- **`ReturnToHandEffect` gained `creature_filter`** (Kogla's "target
  Human you control", reusing `TargetSpec.creature_filter` rather than a
  new fixed kind — `BlinkEffect`/`CounterUntapGrantKeywordEffect` already
  threaded it through, `ReturnToHandEffect` just hadn't yet) **and a new
  `"opponents_creatures"` mass selector** (Llawan's ETB bounce, the
  opponent-scoped sibling of `"all_creatures"`) **plus a `color` key on
  `_mass_selector_objects`' own `filt`** (shared by `DestroyEffect`/
  `ExileEffect`/`ReturnToHandEffect` alike, though only Llawan uses it
  today). A new `"basic_land"` target kind (Earthcraft) mirrors the
  existing `"nonbasic_land"`.
- **`ManaPool.last_payment_types`** (Jeweled Amulet — "note the type of
  mana spent to pay this activation cost"): `_spend_generic` now returns
  which type(s) it actually drained instead of `None`, and `pay()` folds
  that together with any fixed colour pips into a new `last_payment_
  types` dict any caller can read right after paying, without changing
  `pay()`'s own return signature (still just `life_spent`) or touching
  any of its many existing callers. This engine has no interactive
  "which color pays a generic pip" choice — `_spend_generic`'s own
  colorless-first `MANA_TYPES` order decides it deterministically, so
  what gets noted isn't always a genuine player pick, the same
  simplification tier every other "spend from the pool" caller already
  accepts. `ActivationCost.note_spent_color` stamps the result onto the
  new `GameObject.noted_mana_color` (`GameEngine._pay_ability_cost`);
  `AddManaEffect`'s new `color_from_source_noted_color` reads it back,
  the exact sibling of the already-shipped `color_from_source_chosen_
  color` (Utopia Sprawl-shaped RULE 601.2b colour choices). "Activate
  only if there are no charge counters" is `ActivationCost.activation_
  condition` reusing the existing `source_counters` `static_conditions`
  kind (`{"kind": "source_counters", "counter": "charge", "max": 0}`),
  the same shape Frodo, Sauron's Bane already established.

Two latent-bug-shaped findings along the way, both fixed: `AbilitySpec`
has no top-level `once_per_turn` kwarg (it lives inside the `trigger`
dict's `"limit"` key) — caught immediately by `bind_from_catalogue`
raising on Tataru Taru rather than silently no-opping. And this session's
own dev venv turned out to be a stray macOS `backend/venv` synced in via
OneDrive (`pyvenv.cfg` pointing at `/Library/Frameworks/...`); per
CLAUDE.md's own venv/venv_win convention this project already expects
`venv_win` on Windows, so `python setup/install.py` was re-run to build
the correct one rather than fighting the wrong one.

**Files:** `game/effects.py` (all the new/widened effect classes and
registry factories above), `game/continuous.py` (`graveyard_redirect_
active`, `cast_prohibited`'s three new knobs, `count_selector`'s two new
entries, `graveyard_library_entry_prohibited`'s `"permanent"` filter,
`_apply_borrowed_activated_abilities`'s `"top_of_library"` mode),
`game/effect_binder.py` (`not_completed_dungeon`, `min_opponent_
creatures`), `game/rules/misc_mixin.py` (`request_each_player_pay_or`'s
`scope`/`effect_targets`, `GrantCantBeCounteredEffect`'s new scope check),
`game/rules/search_mixin.py` (`dig_until`'s `"graveyard"` destination),
`game/rules/damage_death_mixin.py` (`graveyard_redirect` wired into
`_move_to_graveyard`), `game/engine/activation_mixin.py`
(`sacrificed_cost_power` stamp), `game/engine/combat_mixin.py`
(`ATTACKS`'s new `defending_player_id`), `game/targeting.py`
(`"basic_land"`, `"artifact_or_enchantment_defending_player_controls"`),
`models/game_object.py` (`sacrificed_cost_power`, `noted_mana_color`),
`models/mana_pool.py` (`last_payment_types`, `_spend_generic`'s new
return value), `game/costs.py` (`note_spent_color`), `game/ability_
catalogue.py` (all 22 cards).
**Tests:** `tests/test_mec43_near_free_reuses.py` (new, 16 tests).

### MEC-43: round 2, 17 more near-free reuses (`cEDH staples 2`/`K'rrik cEDH`)

A fresh 2026-08-24 diagnosis (built on the newly-shipped `scripts/deck_
coverage.py`, MEC-44 below) found 74 more uncovered names across the two
decks' now-verified coverage numbers; 17 closed the same day, each again
a small param-widening rather than a new subsystem. 5 closed purely
through the *parser*, no hand-authoring:

- **`graveyard_library_cast_prohibition`/`_entry_prohibition` gained a
  `zones` param** (Kunoros, Hound of Athreos — "Players can't cast spells
  from **graveyards**"/"Creature cards in **graveyards** can't enter the
  battlefield", no "or/and libraries" on either clause, unlike every
  prior card on this static): `continuous.graveyard_library_cast_
  prohibited`/`_entry_prohibited` both gained an optional `zone` param
  (the mover's own current zone name), checked against the static's
  `zones` list when set; the three real call sites (`GameEngine.can_
  cast`, `SearchLibraryEffect`'s battlefield placement,
  `ReturnFromGraveyardEffect._apply_one`) now pass the object's actual
  zone. The parser regexes widened to make the "or/and libraries" tail
  optional, emitting `zones=["graveyard"]` when it's absent.
- **`trigger_prohibition` gained a DIES sibling via a second `EffectSpec`**
  (Hushbringer — "Creatures entering **or dying** don't cause abilities
  to trigger"): the parser regex's "or dying" tail, when present, emits
  a second `trigger_prohibition` spec with `event="DIES"` alongside the
  existing `ENTERS_BATTLEFIELD` one — no engine change at all, since the
  static already took an arbitrary `event` string.
- **`enters_tapped_static`'s `nonbasic` flag moved from clause-wide to
  per-word** (Thalia, Heretic Cathar — "Creatures **and nonbasic lands**
  your opponents control enter tapped": creatures aren't nonbasic-
  restricted, only the lands are, a mix the old single-flag grammar
  couldn't express). The parser regex now captures each `and`-joined part
  with its own optional "nonbasic " prefix and emits one spec per part —
  Blind Obedience's older two-type case and every single-type case still
  parse identically.
- **`reveal_hand_choose_discard` gained `max_mana_value`** (Inquisition
  of Kozilek's "…a nonland card from it **with mana value 3 or less**")
  **and the parser regex gained an optional trailing `lose_life` rider**
  (Thoughtseize's "…That player discards that card. **You lose 2
  life.**") — the two riders this effect's own docstring had flagged as
  deliberately out of scope when it first shipped (MEC-43 round 1).

12 more closed hand-authored, needing a mix of genuinely new and widened
primitives:

- **The reanimation family's own wrinkles**: `targeting._GRAVEYARD_TYPE_
  FILTERS` gained `"artifact_or_creature"` (Beacon of Unrest's "artifact
  or creature card"), closing it together with the already-shipped
  `shuffle_self_into_library` (Green Sun's Zenith). Rise from the
  Grave/Chainer, Dementia Master's own "that creature is a black
  `<type>` in addition to its other colors and types" needed a *standing*
  type/colour grant on a specific reanimated object — `GrantUntilEffect`'s
  existing `previous_subject`/`duration` combo turned out to already
  cover it exactly: `duration="rest_of_game"` (RULE 611.2c's "no stated
  duration = indefinite", already a real `durations.py` value, just never
  paired with `previous_subject` before) reading back the just-reanimated
  creature the same way "It fights…" reads a prior clause's target — RULE
  400.7 keeps the object's `instance_id` stable across the graveyard-to-
  battlefield move, so `GameContext.previous_targets` still resolves to
  it. Tenacious Dead's "when ~ dies, you may pay `<cost>`. If you do,
  return **it** to the battlefield tapped" needed two small additions to
  `ReturnFromGraveyardEffect`: a `tapped` param (stamped alongside the
  existing `haste`), and a `trigger_subject_key="remembered"` mode
  (mirroring `AddCountersEffect`'s own, reading `GameObject.remembered_
  instance_id` instead of taking a RULE 115 target) — since `context.
  trigger_event` is only live for `PayCostThenEffect`'s first, synchronous
  `apply()` call, `remember_trigger_subject=True` stamps the dying
  creature's own id before the interactive pay-or-decline choice opens,
  and the deferred "if you do" branch reads it back once answered.
  Chainer's own repeatable activated reanimation reuses all of the above
  plus a plain anthem ("All Nightmares get +1/+1") and its "when Chainer
  leaves the battlefield, exile all Nightmares" trigger needed one more
  small addition — `_mass_selector_objects` (the `DestroyEffect`/
  `ExileEffect`/`ReturnToHandEffect` mass-wipe helper) gained a `subtype`
  filter key, delegating to `combat.matches_object_filter` rather than a
  bare type-line read since the Nightmare subtype here is *granted*
  (Chainer's own reanimation), not printed.
- **Sanctifier en-Vec**: `ExileAllGraveyardsEffect` (Farewell-shaped mass
  exile) gained a `colors` filter for its ETB sweep, and `graveyard_
  redirect` (Leyline of the Void/Rest in Peace's static, round 1) gained
  its own independent `colors` param alongside `scope` — Sanctifier's
  "if a black or red permanent/spell/card would be put into a graveyard"
  is colour-scoped, not owner-scoped, so it always passes `scope="any"`
  with the colour filter doing the real work.
  `continuous.graveyard_redirect_active` now checks `colors` (an OR set
  against `GameObject.colors`) before falling through to the `scope` gate.
- **Kenrith's Transformation, the "Elk" template**: "loses all abilities
  and is a green Elk creature with base power and toughness 3/3" is
  `remove_all_abilities` + `type_change` (`add_types=["creature"]`,
  `set_subtypes=["Elk"]`, `power`/`toughness`) + `color_change`
  (`colors=["G"], set=True`), all three composed on `affects="attached_
  permanent"` — no new primitive at all, just three already-shipped
  statics on one Aura. **Documented simplification**: only the creature
  type is *added*, the permanent's other printed card types (artifact,
  etc.) aren't stripped, since `Card.is_artifact`/`is_enchantment` read
  the printed card directly rather than a layer-4-`_removed_types`-aware
  property the way `GameObject.is_land`/`is_creature` already do — low
  practical impact, since the Elk has no abilities left to use any type
  distinction. Oko, Thief of Crowns' +1 shares the same clause but needs
  its own resolve-time `grant_until` wiring plus Oko's other two loyalty
  abilities — left open (`BACKLOG.md`).
- **Conqueror's Flail/Faeburrow Elder's shared anthem**: `continuous.
  count_selector` gained `"colors_among_permanents_you_control"` (the
  P/T-anthem sibling of ENG-27's same-named `ManaAbility.color_selector`
  entry, Bloom Tender) — no change needed to the `"anthem"` static itself,
  which already supported a `power_count`/`toughness_count` selector.
  Conqueror's Flail's second clause — "As long as this Equipment is
  attached to a creature, your opponents can't cast spells during your
  turn" — needed two conditions ANDed at once (`source_attached` +
  `your_turn`), which no single `static_conditions` `kind` could express;
  `static_conditions.condition_holds` gained a genuinely new `"all"`
  combinator kind (`{"kind": "all", "conditions": [...]}`, recursing over
  each sub-condition) — general, reusable infrastructure for any future
  "as long as X and Y" clause, not a one-off for this card.
- **Delney, Streetwise Lookout**: its first clause ("creatures you
  control with power 2 or less can't be blocked by creatures with power
  3 or greater") is the already-shipped qualified `combat_restriction`
  shape (Challenger Troll/Flopsie's own group `min_power`/`max_power`
  scoping), just on the *restricted* side with a blocker-power `filter`
  instead of a same-side P/T qualifier — no new primitive. Its second
  ("if a triggered ability of a creature you control with power 2 or
  less triggers, it triggers an additional time") needed
  `TriggerDoublerEffect` widened with `min_power`/`max_power` — a third,
  independent scoping axis alongside `chosen_type` (Roaming Throne) and
  `cause_filter` (Elesh Norn, Mother of Machines). Unlike those two,
  Delney's own clause names no "another", so `continuous.trigger_
  doubler_bonus`'s new branch doesn't exclude the doubling permanent's
  own triggers — a separate code path from the existing `chosen_type`/
  `cause_filter` branches (which still skip self, unchanged) rather than
  a shared one, to avoid any risk of regressing Roaming Throne/Elesh
  Norn's own tested behaviour.
- **Runic Armasaur**: "whenever an opponent activates an ability of a
  creature or land that isn't a mana ability" turned out to need no new
  engine primitive at all — `EventType.ACTIVATED_ABILITY` already fires
  for every non-mana activated ability (RULE 605.1a mana abilities never
  use the stack, so "isn't a mana ability" is automatically true) with
  `controller_id`/`object_types` already matching `_group_ok`'s default
  keys for that event. The one real gap: `_group_ok`'s `type` filter only
  ever took one word before this batch, and "creature or land" needs two
  ORed together — widened to accept a list (`type=["creature","land"]`),
  OR semantics, with every existing single-string caller unchanged
  (iterates a one-element tuple). Hand-authored directly onto the event
  rather than taught to the parser's own trigger-verb grammar
  (`segmenter._TRIGGER_VERBS`), since "activates" is a new verb that
  grammar has never needed and one singleton card doesn't justify adding
  it there. **Documented simplification**: "you may draw" is read as
  unconditional, the same accepted convention Selvala, Heart of the
  Wilds's own entry already established.
- **Peer into the Abyss**: "target player draws cards equal to half the
  number of cards in their library and loses half their life" needed two
  *targeted* siblings of MEC-37's Doomsday "half your own life" shapes:
  `DrawCardEffect` gained `count_selector="half_target_library_round_up"`
  (read off the resolved drawing player's own library, not the
  controller's), and `LoseLifeEffect` gained `amount_from_half_target_
  life` (same idea for life) plus a `previous_subject` param — the
  targeted player is chosen once, by the draw clause, and the life-loss
  clause reads that same choice back via `GameContext.previous_targets`
  rather than declaring a second RULE 115 target of its own (which would
  have opened a second, spurious targeting round for what the real card
  targets only once).
- **Soul Conduit**: "two target players exchange life totals" is a
  genuinely new one-shot, `ExchangeLifeTotalsEffect` — every other life
  effect in this engine is a single-player delta (`GainLifeEffect`/
  `LoseLifeEffect`), none can express a simultaneous two-player swap.
  Deliberately not modeled as a gain/loss for either player (no `GAIN_
  LIFE`/`LOSE_LIFE` event fires) — an exchange is its own RULE 119
  category, matching the real ruling that it isn't a life-total change
  for triggered-ability purposes.

One latent-bug-shaped finding: the round-2 diagnosis's own "likely
entirely free" call on Ojer Axonil, Deepest Might turned out to already
be shipped (MEC-30, well before this round) — the diagnosis script that
produced the "still uncovered" list had the same DFC-name-canonicalization
bug the MEC-44 tool below was built to stop repeating, so it mis-reported
an already-covered card as open. No engine work was needed; the entry was
simply removed from the open list once `scripts/deck_coverage.py`
confirmed it.

**Files:** `game/effects.py` (`ExchangeLifeTotalsEffect`,
`ExileAllGraveyardsEffect.colors`, `RevealHandChooseDiscardEffect.max_
mana_value`, `ReturnFromGraveyardEffect.tapped`/`trigger_subject_key`,
`DrawCardEffect`'s `"half_target_library_round_up"`, `LoseLifeEffect.
amount_from_half_target_life`/`previous_subject`, `TriggerDoublerEffect.
min_power`/`max_power`, `_mass_selector_objects`'s `subtype` filter,
`graveyard_library_cast_prohibition`/`_entry_prohibition`'s `zones`,
`graveyard_redirect`'s `colors`), `game/continuous.py`
(`graveyard_library_cast_prohibited`/`_entry_prohibited`'s `zone` param,
`graveyard_redirect_active`'s `colors`, `count_selector`'s
`"colors_among_permanents_you_control"`, `trigger_doubler_bonus`'s
power-filter branch), `game/static_conditions.py` (the `"all"`
combinator, + its `describe()` label), `game/effect_binder.py`
(`_group_ok`'s list-`type` support), `game/targeting.py`
(`"artifact_or_creature"` graveyard filter), `game/engine/casting_mixin.py`
+ `game/rules/search_mixin.py` (the two zone-aware call sites),
`parser/oracle/catalogue/static_handlers.py` (the four regex widenings),
`parser/oracle/catalogue/handlers.py` (`_HAND_DISRUPTION_RE`'s two new
riders), `game/ability_catalogue.py` (all 12 hand-authored cards).
**Tests:** `tests/test_mec43_round2_near_free_reuses.py` (new, 21 tests).
**Tooling (MEC-44):** `scripts/deck_coverage.py` (new) — a checked-in,
reusable replacement for the one-off diagnosis script this ticket kept
hand-rolling; parses a saved deck's `mainboard_text`/`commander_text`
the same way `parser/deckliste_parser.py` does, then measures each
unique card via `is_registered`/`parse_oracle` exactly like
`coverage_report.py` does cache-wide, keyed off the resolved `Card.
name`'s canonical form rather than the decklist's own text.

### MEC-43: round 3, `SearchLibraryEffect` widenings (`cEDH staples 2`/`K'rrik cEDH`)

The round-2 diagnosis had clustered four cards as "already-general
`SearchLibraryEffect` criteria/gate widenings" — a fair first read of the
constructor signature, but only two of the four actually turned out to be
free once checked against the effect's real code, confirming this file's
own "verify, don't assume" rule for this ticket.

- **Beseech the Queen** ("mana value less than or equal to the number of
  lands you control"): `SearchLibraryEffect.mana_value_from` already
  supported a *dynamic* bound (Eldritch Evolution/Neoform's
  `"sacrificed_cost"` source), just not a board-count one. Widened
  `_resolved_criteria` with a new `"count_selector"` source, reading
  `continuous.count_selector(state, controller_id, ..., source=self.
  source)` — `"lands_you_control"` already existed there for an unrelated
  characteristic-defining P/T, so this needed zero new count-selector
  vocabulary, only a new way to *reach* it from a search. A dedicated
  parser regex (`_SEARCH_MV_LANDS_QUALIFIER_RE`) rather than a fourth
  `_SEARCH_MV_QUALIFIER` alternative, since the existing one only ever
  captures a literal digit/`x`.
- **Final Parting** ("Search your library for two cards. Put one into your
  hand and the other into your graveyard. Then shuffle."): a genuinely
  free reuse of the `destinations` split `_search_split_destination`
  already builds for Cultivate/Kodama's Reach — the only real gap was
  recognition. Its own bare "N cards" (no criteria, no "up to", no
  "reveal") and three-sentence-with-periods phrasing didn't fit
  `_SEARCH_CRITERIA`/`_SEARCH_SPLIT_DESTINATION_RE`'s comma-joined
  single-clause shape, so it got its own regex
  (`_SEARCH_TWO_CARDS_SPLIT_RE`) with literal `\.\s*` sentence
  boundaries — the same "whole span, not a connector split" idiom
  `_SEARCH_EXILE_REST_RE` (Doomsday) already established, confirmed by
  checking `segmenter.py`'s `parse_effect_body`: the *whole* un-split
  body is tried against the handler registry (`match_clause`) before the
  `_CONNECTORS` period/semicolon/"then"/"and" fallback ever splits it.
- **Search for Glory** ("Search your library for a snow permanent card, a
  legendary card, or a Saga card, ... You gain 1 life for each {S} spent
  to cast this spell."): the search half was free — `models.card_query`
  already has a general `"or"` combinator (an unused-until-now feature),
  so the three-way criteria is `{"or": [{"type": "Snow", "without_type":
  ["Instant", "Sorcery"]}, {"type": "Legendary"}, {"type": "Saga"}]}` with
  no engine change at all. The life-gain half needed a wholly new
  primitive: this engine had never tracked snow-*sourced* mana at all
  (`{S}` symbols fell back to "count as generic" in `models/mana_cost.py`,
  and "for each {S} spent" doesn't mean a literal `{S}` pip in the
  printed cost anyway — it means however much of the payment came from a
  snow-typed permanent, regardless of what mana type it produced).
  Modeled as `ManaPool.snow_pool` — a `pool_by_source`-shaped shadow
  tally, but *orthogonal* to `source_kind` rather than reusing it: a
  Snow-Covered Forest is both `source_kind="basic_land"` (PAR-19) *and*
  snow, and `source_kind` only ever holds one value per lot, so folding
  "snow" into it would have silently broken any "spend only mana from
  basic lands" restriction on a snow basic. `ManaPool.add`/`add_many`
  gained an `is_snow` flag (set at the tap site,
  `mana_abilities.is_snow_source_for` — a plain type-line "snow" check,
  wired into both of `game/engine/mana_mixin.py`'s `add_many` calls
  alongside the existing `mana_source_kind_for`); `_consume` drains it in
  lockstep with `pool`, snow-first (an arbitrary but harmless
  deterministic order credit, the same simplification tier
  `_spend_generic`'s own colorless-first order already is — this engine
  has no interactive "which mana pays which pip" choice to consult
  instead). `GameObject.mana_spent_to_cast_snow` is the `colors_spent_
  to_cast`/RULE 702.108a-Converge-shaped before/after diff at cast time
  (`game/rules/casting_mixin.py`'s `cast_spell`), read via `continuous.
  count_selector`'s new self-referential `"snow_mana_spent_to_cast"`
  entry — the same idiom `sacrificed_cost_mana_value`/`sacrificed_cost_
  power` already use. Along the way this surfaced a real, general,
  previously-dormant bug: `GainLifeEffect.apply()`'s `count_selector`
  branch never passed `source=self.source` to `continuous.count_
  selector` (unlike `MillEffect`'s identical call, which does) — every
  self-referential count-selector kind silently evaluated to 0 on a
  life-gain effect, not just this new one, since `source` defaulted to
  `None` and every self-referential entry reads it via `getattr`.
- **Myriad Landscape** ("Search your library for up to two basic land
  cards **that share a land type**, put them onto the battlefield
  tapped, then shuffle."): the real gap — a cross-pick constraint no
  existing criteria shape could express, since `card_query.matches`
  judges exactly one candidate at a time with no visibility into what a
  multi-pick search has already found. `SearchLibraryEffect.
  share_land_type` threads a new bool through `GameContext.
  request_search`/`RulesEngine.request_search` down to both places a
  round's eligible pool is computed (`request_search`'s own first-round
  `eligible`, and `resolve_search_choice`/`_search_choice`'s later
  rounds) — `_shares_land_type` (new, `game/rules/search_mixin.py`) is
  vacuously true for the first pick (nothing found yet to share with),
  then checks the candidate's basic land type word(s) against every
  already-found card's. A dedicated regex
  (`_SEARCH_PUT_THEN_SHUFFLE_SHARE_TYPE_RE`, tried before the plain
  `_SEARCH_PUT_THEN_SHUFFLE_RE` row since it's a strict superset) rather
  than an optional group spliced into the shared `_SEARCH_CRITERIA`
  machinery, since only this one shape needs the new param.

**Files:** `game/effects.py` (`SearchLibraryEffect.mana_value_from`'s
`"count_selector"` source, `SearchLibraryEffect.share_land_type`,
`GameContext.request_search`'s matching param, `GainLifeEffect`'s
`source=self.source` fix), `game/continuous.py`
(`count_selector`'s new `"snow_mana_spent_to_cast"` entry),
`models/mana_pool.py` (`snow_pool`, `add`/`add_many`'s `is_snow`,
`_consume`'s snow-first drain, `empty`/`clone`), `models/game_object.py`
(`mana_spent_to_cast_snow`), `game/mana_abilities.py`
(`is_snow_source_for`), `game/engine/mana_mixin.py` (both `add_many` call
sites), `game/rules/casting_mixin.py` (the snow before/after diff,
alongside the existing Converge one; `request_search`/`_search_choice`/
`resolve_search_choice`'s `share_land_type` threading, `_shares_land_
type`/`_land_types_of` helpers), `parser/oracle/catalogue/handlers.py`
(`_SEARCH_MV_LANDS_QUALIFIER_RE`, `_SEARCH_TWO_CARDS_SPLIT_RE`,
`_SEARCH_SNOW_LEGENDARY_SAGA_RE`, `_GAIN_LIFE_PER_SNOW_SPENT_RE`,
`_SEARCH_PUT_THEN_SHUFFLE_SHARE_TYPE_RE`, and their handler functions).
**Tests:** `tests/test_mec43_round3_search_widenings.py` (new, 6 tests).
Coverage: `cEDH staples 2` 572→573/606, `K'rrik cEDH` 50→53/71.

### MEC-43: round 3, "small, self-contained" (Vilis Broker of Blood, Volatile Stormdrake)

Two more cards from the same round-3 diagnosis, both confirmed near-free
before building (`Done_Backend.md`'s own fail-closed rule for this
ticket) — one turned out to be a pure oracle-text recognition gap, the
other needed one genuinely new composite effect plus a real fix to a
shared, previously-unexercised primitive.

- **Vilis, Broker of Blood** ("Whenever you lose life, draw that many
  cards."): `EventType.LIFE_LOST` already exists as `RulesEngine.
  lose_life`'s single choke point for every cause of life loss — damage
  (RULE 120.3, `deal_damage` itself routes through `lose_life`), a cost
  paid with life, or a direct effect — so the card's own reminder text
  ("Damage causes loss of life.") needed no engine work at all. Only two
  small gaps: `segmenter.py`'s `_PLAYER_TRIGGER_CONDITIONS` had no "you
  lose life" entry (mirroring the existing "you gain life" →
  `LIFE_GAINED` row, plus the matching `effect_binder._GROUP_CONTROLLER_
  EVENT_KEYS["LIFE_LOST"] = "player_id"`), and `DrawCardEffect` had no way
  to read "that many" off the firing event — `count_from_trigger_event`
  (mirroring `ImpulsiveDrawEffect`/`CreateTokenEffect`'s own identical
  field) closes that. The trigger-condition addition alone incidentally
  finished two more cache-wide cards for free, since both already print
  the pre-existing "for the first time each turn" suffix (stripped before
  condition dispatch, so it composes automatically): Gonti's Machinations
  ("...you get {E}.") and Vengeful Warchief ("...put a +1/+1 counter on
  ~."). The "during your turn" variant (the four-card Shadowheart cycle)
  is a different, unbuilt gate — noted but deliberately not built this
  round, since it needs a genuine new trigger-condition suffix (whether
  the controller is the active player), not just a bare event mapping.
- **Volatile Stormdrake** ("When this creature enters, exchange control
  of this creature and target creature an opponent controls. If you do,
  you get {E}{E}{E}{E}, then sacrifice that creature unless you pay an
  amount of {E} equal to its mana value."): the exchange half (RULE
  701.10) was already shipped for Gilded Drake (`ExchangeControlEffect`),
  and "you get {E}{E}{E}{E}" is the already-shipped `add_player_counters`
  (kind `"energy"`). The real gap is RULE 608.2b's "if you do" gating on
  whether the *exchange itself* succeeded — a condition no generic
  `EffectSpec.condition` key covers and `_apply_effects_partitioned` has
  no channel to signal between separate effect instances, so — following
  this engine's own established convention for that exact shape (Temur
  Sabertooth's `ReturnCreatureGrantIndestructibleEffect`, Akiri's
  analogous effect) — it's one new bespoke composite effect,
  `ExchangeControlThenEnergySacrificeEffect`, rather than two effects and
  a cross-effect flag. One subtlety it gets right that a naive port of
  `ExchangeControlEffect` wouldn't: RULE 112.7a means this ability's
  controller is fixed as of when it triggered, so "you" in "you get
  {E}{E}{E}{E}" is captured *before* the swap, not read off the
  permanent's new (post-exchange) controller. Building this surfaced a
  real, general, previously-dormant bug: the shared pay-or-lose-it
  machinery (`_can_pay_player_cost`/`_pay_player_cost`, shared by
  ward/`sacrifice_unless_pay`/`counter_unless_pays`) had never gained
  `ActivationCost.pay_energy` support at all — every prior card printing
  that shared machinery's "unless you pay `<cost>`" used mana/life/
  discard/sacrifice, never energy, so an energy-costed "unless" clause
  would previously have been silently free to pay and never actually
  deducted. Fixed by adding the same affordability/payment branches
  `GameEngine._can_pay_activation_cost`/`_pay_activation_cost` already
  have for an activated ability's own `pay_energy` component.

**Files:** `game/effects.py` (`DrawCardEffect.count_from_trigger_event`,
`ExchangeControlThenEnergySacrificeEffect`, its `EffectRegistry`
registration), `game/effect_binder.py`
(`_GROUP_CONTROLLER_EVENT_KEYS["LIFE_LOST"]`), `game/rules/misc_mixin.py`
(`_can_pay_player_cost`/`_pay_player_cost`'s new `pay_energy` branches),
`parser/oracle/segmenter.py` (`_PLAYER_TRIGGER_CONDITIONS`'s new "you
lose life" row), `parser/oracle/catalogue/handlers.py`
(`_DRAW_THAT_MANY_RE`/`_draw_that_many`), `game/ability_catalogue.py`
(Volatile Stormdrake).
**Tests:** `tests/test_mec43_round3_small_self_contained.py` (new, 7 tests).
Coverage: `cEDH staples 2` 573→574/606, `K'rrik cEDH` 53→54/71.

### MEC-43: round 4 — the last two decks closed (`cEDH staples 2`, `K'rrik cEDH`)

Closed every remaining uncovered card in `cEDH staples 2` (574/606 →
602/602 resolved) and `K'rrik cEDH` (54/71 → 71/71) in one sitting —
**MEC-43 is closed**: all eight "cEDH"-named saved decks/cubes are now
fully playable. 48 cards, split across seven independent clusters worked
in parallel (each its own git worktree off the same base commit, merged
back afterward — the only cross-cluster conflicts were git's own textual
diff3 confusion over multiple branches each purely *appending* new
catalogue entries/registry rows at the same file tail; nothing required
resolving competing logic except two effects two different clusters both
happened to widen — `ExileTopOfLibraryEffect` gained both `keep_bottom`
(Doomsday Excruciator) and `track_exiled_with` (Knowledge Pool) as
independent params, and `PayCostThenEffect` gained both a `target`/
`sacrifice_or_discard`/`prompt` trio (Tergrid's Lantern) and
`remember_trigger_stack_id` (Rings of Brighthearth) the same way).

**Cluster A — combat/equipment/damage** (Grim Hireling, Ikra Shidiqi the
Usurper, Sword of Feast and Famine, Umezawa's Jitte, Commander's Plate,
Legolas's Quick Reflexes, Final Punishment, Drain Life): the one real new
primitive was RULE 700.2 modal choice for an *activated* ability
(`ActivatedAbility.modes`, widened `AbilitySpec._validate_modes`,
`GameEngine.activate_ability`'s new `mode` param) — modal spells and
modal triggered abilities already existed, but nothing let a plain
`{cost}: Choose one —` activation itself branch, which is what Umezawa's
Jitte's three-mode removal ability needed. Also: RULE 702.61 Split Second
went from parser-recognized to real behaviour (`continuous.
split_second_active`, wired into `can_cast`/`can_activate`) for Legolas's
Quick Reflexes; `continuous.commander_color_identity` +
`grant_protection_static`'s new `protection_from_colors_not_in_
commanders_identity` for Commander's Plate; `GameState.damage_dealt_to_
players_this_turn` (an amount tracker, distinct from the existing hit-set/
opponent-scoped trackers) for Final Punishment; `ManaCost.with_x_colored`
(RULE 605.3a scoped to just `{X}`) for Drain Life. Found and fixed two
real bugs: the "equip" keyword regex was capturing "Equip commander {3}"
as the card's plain Equip cost instead of the real `{5}` (Commander's
Plate prints both), and `targeting.legal_targets`'s "any target" excluded
planeswalkers/battles (RULE 115.4) — a stale gap that silently
under-targeted every other "any target" card in the cache, not just Drain
Life.

**Cluster B — trigger composition** (Bontu's Monument, Korvold Fae-Cursed
King, Kozilek Butcher of Truth, Jin-Gitaxias Core Augur, Sheoldred
Whispering One, Ledger Shredder, Talion the Kindly Lord, Crypt Ghast):
mostly pure composition of already-shipped primitives (cost-reduction's
`spell_type`+`spell_color` filters together, `EventType.SACRIFICE`,
`PayCostThenEffect` for Extort). New: `RulesEngine._collect_self_cast_
triggers` + `TriggeredAbility.functions_from_stack` (RULE 601.2i,
"when you cast this spell" firing off the stack rather than the
battlefield); `continuous.hand_size_modifier_for` (the numeric sibling of
`has_no_maximum_hand_size`) for Jin-Gitaxias; `ConniveEffect` (RULE
701.47) for Ledger Shredder; `ChooseNumberReplacement` (Sanctum Prelate)
reused plus a new `spell_characteristic_equals_chosen_number` predicate
for Talion. Found and fixed a real bug the new self-cast-trigger primitive
itself introduced before shipping: Crypt Ghast's own Extort static was
wrongly firing off casting Crypt Ghast itself (while still a spell, not
yet a permanent) — fixed with `functions_from_stack`, inferred at bind
time only for a genuine `{"subject": "self"}` SPELL_CAST trigger, and
locked in with a regression test. Kozilek's trailing "graveyard from
anywhere" clause is a documented simplification (RULE 400.7's uniform
graveyard-entry event would need touching 12+ independent call sites this
engine's graveyard-bound moves go through — genuinely disproportionate for
one clause), matching Hostility's own prior identical deferral.

**Cluster C — library/graveyard/search/tokens** (Syphon Mind, Spoils of
Blood, Dark Petition, Demonic Bargain, Doomsday Excruciator, Mizzix's
Mastery, Poison the Cup, Hoarding Broodlord): almost entirely composition
of `SearchLibraryEffect`, `ExileTopOfLibraryEffect` (widened with a flat
`count` for Demonic Bargain's "top thirteen", `each_player`+`keep_bottom`
for Doomsday Excruciator's "all but the bottom six"), and the existing
face-down-exile/free-cast machinery (Hoarding Broodlord reuses
`destination="exile_face_down_standing_cast"` verbatim from Praetor's
Grasp). New: `DiscardEffect.draw_per_discard` (a follow-up effect fired
per real discard, not double-counted against an already-empty hand) for
Syphon Mind; `CreateTokenEffect.pt_from_count_selector` + a new
`"creatures_died_this_turn"` count-selector key for Spoils of Blood;
`ExileEffect.grant_free_cast_window` for Mizzix's Mastery. Overload
(Mizzix's Mastery), Foretell (Poison the Cup), and Convoke-granted-to-
exile-casts (Hoarding Broodlord) are documented simplifications —
keyword-recognized but not built to full behaviour, following the same
precedent already in the catalogue (Selfless Safewright, City on Fire).
Found and fixed a real bug: `ExileEffect`'s `target_kind=None` self-exile
branch was reading a stray leftover `targets[0]` from an earlier
targeting effect in the same resolution instead of always exiling
`self.source` — latent until Mizzix's Mastery combined a real target with
a trailing "Exile ~." clause.

**Cluster D — control/zone changes/entry-choice statics** (Homeward Path,
Heliod Sun-Crowned, Containment Priest, Archon of Valor's Reach, Command
Beacon, Worldgorger Dragon, Jodah the Unifier, Kodama of the East Tree):
new `RegainControlOfOwnedCreaturesEffect` (RULE 108.4/110.2) for Homeward
Path; a new `"uncast_creature_entry_exile"` replacement (`continuous.
uncast_creature_entry_exiled`) for Containment Priest, checked at the same
choke points `graveyard_library_entry_prohibited` (Grafdigger's Cage)
already uses; `ChooseNamedModeReplacement` (RULE 601.2b) reused for
Archon of Valor's Reach's card-type pick, plus a `type_from_source_mode`
gate on `cast_prohibition`; `PutCommanderIntoHandEffect` (RULE 903.7's
reverse direction) for Command Beacon; a mandatory `"other_permanents_
you_control"` mass-exile selector + `track_exiled_with` for Worldgorger
Dragon (its return half reuses `ReturnAllExiledWithEffect`, built for
Parallax Wave, unchanged); `LegendarySpellFreeDigEffect` (riding
`RulesEngine.dig_until`) for Jodah; `PutEqualOrLesserManaValueFromHand
Effect` + a new `"hand_to_battlefield"` `request_choose_objects` action +
`GameObject.entered_via_ability_id`/`not_entered_via_self` (the
Panharmonicon-shaped self-recursion guard) for Kodama. Found and fixed
three real bugs: `cast_prohibition`'s `type_from_source_mode` param wasn't
threaded through its own `EffectRegistry` factory at all; the anthem
family's `power_count`/`toughness_count` docstring didn't match what the
code actually required (an explicit `power=1, toughness=1` per-unit
coefficient); and `_put_searched_card`'s `ENTERS_BATTLEFIELD` event fires
synchronously, so Kodama's own `entered_via_ability_id` stamp had to move
*before* that call, not after, or the self-recursion guard would never
see it.

**Cluster E — harder mechanics** (Tergrid God of Fright, Swift
Reconfiguration, Angel's Grace, Mesmeric Orb, Smokestack, Oko Thief of
Crowns): the batch's headline primitive is **Mesmeric Orb's own gap**,
open since this doc's own "trigger-verb table" note first called out
"becomes untapped" as deliberately excluded — `RulesEngine.set_tapped`
now fires a real per-permanent `EventType.UNTAPPED`, every untap route
(untap step, `{Q}` costs) migrated onto it, and `segmenter._TRIGGER_
VERBS` finally gained the row, closing the gap cache-wide rather than just
for this one card. Tergrid's front face needed a new `ActivationCost.
sacrifice_or_discard` compound cost + `PayCostThenEffect.payer="target"`
for the back face (Tergrid's Lantern); Swift Reconfiguration is a standing
Aura static combining the already-shipped Crew (MEC-29) and type-change
machinery — surfaced and fixed three real, previously-dormant layer-engine
bugs along the way (a granted-ability effect never got `.source` stamped;
RULE 613.7b layer ordering used the wrong timestamp for resolve-time
grants, fixed with a new `GameState.next_timestamp()`; and the layer-4
type pass let a "removed" type outlive a later "added" of the same word
regardless of real ordering). Angel's Grace is a turn-scoped RULE 104.3a
damage floor (`grant_cant_lose_this_turn` + `cap_damage_life_floor`).
Smokestack extends the RULE 608.2 per-player-sequenced sacrifice idiom
(`SacrificePermanentsPerCounterEffect`, Tangle Wire's tap-per-counter
shape swapped to sacrifice). Oko's −5 needed `ExchangeControlEffect`
widened to a genuine two-independent-targets mode.

**Cluster F — new small subsystems** (K'rrik Son of Yawgmoth, Maralen of
the Mornsong, Keen Duelist, Scroll Rack, Dance of the Dead): K'rrik's "for
each {B} in a cost, you may pay 2 life rather than pay that mana" is a
standing, unscoped alternative-payment permission broader than every
existing wildcard-*color* mechanism — `ManaPool.can_pay`/`pay` gained
`extra_life_color`, the same life-payment option a printed Phyrexian pip
already has, consulted via `continuous.life_for_mana_pip_color` at all
three real cost-payment sites plus a new `grant_life_for_mana_pip` static.
Maralen's "players can't draw cards" turned out nearly free —
`draw_limit` at `max_per_turn=0` (Omen Machine's own template). Keen
Duelist needed a genuinely new primitive, `MutualRevealCompareManaValue
Effect` (a simultaneous two-player reveal-and-compare — each player's loss
reads the *other's* reveal, no existing shape for that). Scroll Rack
extended the scry/surveil "order the rest back on top" `_LOOK_TOP_KINDS`
machinery with a new `"scroll_rack"` kind (source zone = exile, not
library). Dance of the Dead reused Animate Dead's reanimate-Aura core
wholesale plus a new `phase_relation="attached_permanent"`/
`PayCostThenEffect.payer="attached_permanent"` pair (both resolving
`GameObject.attached_to` live) for its "enchanted creature's controller"
clauses.

**Cluster G — free-cast permissions and ability copying** (The Tabernacle
at Pendrell Vale, Rings of Brighthearth, Isochron Scepter, Aluren,
Knowledge Pool): Tabernacle turned out fully parser-**MODELED** with no
hand-authoring at all — the `all_creatures` group scope for a quoted
ability grant already existed; the only new piece was a
`"destroy_unless_pay"` verb (`DestroyUnlessPayEffect`) alongside the
existing `sacrifice_unless_pay`, since RULE 701.16 destruction (unlike
sacrifice) must stay regenerable. Rings of Brighthearth needed the
ability-item sibling of the existing spell-copy machinery —
`CopyAbilityEffect`/`RulesEngine.copy_ability`, naming "that ability" via
ENG-26's `StackItem.stack_id` remembered onto a new `GameObject.
remembered_stack_id` field. Isochron Scepter widened `ImprintEffect` with
`include_card_type`/`max_mana_value` and added `CopyImprintedCardEffect`
(found and fixed a real latent bug along the way: `_remove_stranded_
tokens` would have swept the exiled copy before it could be cast — now
exempted while `free_cast_instance_ids` covers it). Aluren is the batch's
hardest primitive: a standing, *not-controller-scoped* `"free_cast_
permission"` static (`continuous.has_standing_free_cast_permission`/
`standing_free_cast_grants_flash`), the first free-cast grant not scoped
to one controller, wired into `can_cast`'s existing `free=True` branch —
confirmed no measurable `legal_actions` performance regression. Knowledge
Pool widened `ExileTopOfLibraryEffect` (`each_player`/`count`/
`track_exiled_with`) and added `ExileCastSpellIntoImprintPoolEffect`,
reusing `move_spell_off_stack` (Possibility Storm) and `exiled_with_ids`
(MEC-21) — found and fixed a second real bug: `legal_actions` only ever
scanned the *acting* player's own exile zone for a temp-play-permission
grant, which silently failed Knowledge Pool's whole premise (a shared pool
that can hand a free cast of a card sitting in someone else's exile) —
widened to scan every player's exile.

**Merge:** all seven clusters were built in isolated git worktrees off the
same base commit and merged back sequentially; six of seven merges needed
manual conflict resolution, always in `ability_catalogue.py` (multiple
branches purely appending new entries at the same tail — resolved by
concatenating both sides, verified with a duplicate-`register()` scan
across every card name) and, in the seven-way merge, three further spots
in `effects.py`/`turn_loop_mixin.py` where two clusters had independently
widened the same effect/registry factory or `pending_choice` dispatch —
each resolved by keeping both sides' new params/branches, verified by
re-parsing every touched file and re-running `deck_coverage.py`.

**Tests:** `test_mec43_round4_a.py` through `test_mec43_round4_g.py` (new,
~70 tests total across the seven files), plus each cluster's own broad
targeted regression sweep (thousands of pre-existing tests across the
files it touched) before merging. **0 new failures** against this
session's actual pre-existing baseline (`test_cedh_cube_bespoke_tail.py`'s
two `test_jeskas_zero_*` tests, unrelated to this batch).
Coverage: `cEDH staples 2` 574/606 → 602/602 resolved (the 5 remaining
unresolved names — Balamb Garden, Dol Amroth, Seymour Guado, Zidane
Tribal, Thrum of the Vestige — are crossover/non-real-card import gaps,
not parser coverage ones, same category as `Ojer cEDH`'s Balin's Tomb
above); `K'rrik cEDH` 54/71 → **71/71**. **MEC-43 is closed**: all eight
"cEDH"-named saved decks/cubes are fully playable.

### MEC-40/41/42/43 coverage note

Every card above closed against its own named deck (`cEDH Rocco` — all 18,
now 98/98; `[cEDH] Glarb Bloomsday` — all 8, now 100/100; `cEDH staples` —
all 12, now 215/215 including Delay's own same-day follow-up pass;
`Ojer cEDH` — Chandra's Incinerator, now 76/77, its only residual item
the unrelated Balin's Tomb import gap), plus whichever of the other
decks' own residual lists happened to share the same card names
(`cEDH staples 2` — now 563/602 after MEC-43's own first and second
batches on top of the shared cards above). `BACKLOG.md`'s `MEC-12` (the
original umbrella ticket for all seven "cEDH"-named decks) was folded
into `MEC-43` and retired once `MEC-42` closed — by 2026-08-20 `MEC-43`'s
own diagnosis was the only one of the three still carrying open scope;
see `BACKLOG.md`'s `MEC-43` entry for the current per-deck coverage
table, re-measured after each batch.

## Player Assets & Identity

### Favorite decks + multiplayer default settings (PLR-13)

- **What:** A third `player_assets.py` table, `favorite_decks` (same player-name-keyed shape as sleeves/token art, since decks aren't owned by a player in this app's one shared `DeckDatabase`), with `GET/POST/DELETE /api/players/{name}/favorite-decks`; the goldfish/multiplayer deck pickers list favorites first. Multiplayer default settings (format, mulligan style, takebacks, seating randomization) are purely client-side cookies, applied via the same host-only `setMultiplayerOptions` call right after table creation.
- **Files:** `services/player_assets.py`, `api/player_assets.py`

## Database Maintenance

### Ban-List Live Sync (DB-2)

- **What:** `scripts/update_ban_lists.py` re-derives the live "banned" set for a format from `RawCardStore.iter_raw()`'s already-cached Scryfall `legalities` data, diffs it against the hand-maintained `BANNED_COMMANDER_CARDS` constant, and rewrites it in place with a round-trip check.
- **Files:** `backend/mtg_analyzer/scripts/update_ban_lists.py`, `services/commander_legality.py`, `services/raw_card_store.py`.
- **Why:** Reads the source with `ast` rather than importing the module, so it has no dependency on the rest of `mtg_analyzer` being importable; `BANNED_COMMANDER_CARDS` stays a frozen constant read at legality-check time (not a live per-call lookup) for the same cache-primary reasoning as `SCRYFALL_PRIMARY`.

### Stale Pre-`mana_cost_string` Cache Audit (DB-1)

- **What:** Closed as structurally impossible rather than by a code change — `services/schema_version.py`'s `_clear_on_schema_change` wipes the entire card cache on any `models/card.py` hash mismatch, so no row predating the `mana_cost_string` field can survive in today's cache. No code changed.
- **Files:** `backend/mtg_analyzer/services/schema_version.py`, `models/card.py`.

### Commander-Legal Coverage Measurement

- **What:** Nothing previously scoped `coverage_report.py`'s coverage measurement to just the Commander-legal pool — it always ran over the whole ~35k-card cache, which includes un-set/joke/silver-border cards that can never be Commander-legal and drag the denominator down for no reason relevant to a "complete modelling for Commander" goal. New `coverage_db.commander_legal_names(store)` reads `RawCardStore.iter_raw()`'s own `legalities.commander` field (the same field `scripts/update_ban_lists.py`'s `live_banned_names` already reads, "legal"/"restricted" counting as in-pool) and `coverage_report.py --commander-legal-only` filters the card list through it before measuring, printing a separate "Commander-legal coverage" line alongside the existing whole-cache one.
- **Files:** `services/coverage_db.py`, `scripts/coverage_report.py`.
- **Why not reuse `commander_legality.py`:** that module is a deck-level *validator* (ban list + colour identity + Partner pairing), not a queryable card-pool filter, and correctly has no notion of "every card that's ever legal" — this is a different, measurement-only concern, kept in `coverage_db.py` rather than mixed into the legality module.
- **Tests:** `tests/test_coverage_db.py` (`TestCommanderLegalNames`)

## Deck Analysis

### Dynamic (simulated) deck analysis (ANA-4)

- **What:** New `services/dynamic_analysis.py`: runs N solo goldfish matches headlessly against a `Bot`, aggregating turn-by-turn stats (lands drawn, mana potential, card advantage, tutors resolved, commander ETB turn, mana produced) as mean ± population stddev, via a background job polled through `POST`/`GET /api/analysis/dynamic[/{id}]`.
- **Files:** `services/dynamic_analysis.py`, `api/dynamic_analysis.py`

### Bot-driven goldfish match loop via `advance_to_decision` (ANA-4)

- **What:** `Bot` had only ever driven a multiplayer seat (interactive priority on); a goldfish session runs with that off, so the bot's "nothing to do" fallback (`pass_priority`) spun forever on an empty stack — confirmed empirically before any fix. `run_one_match`'s drive loop falls back to `advance_to_decision` instead (the same primitive behind the goldfish UI's "Nächste Entscheidung" button), which fast-forwards through steps until the active player has a real decision.
- **Files:** `services/dynamic_analysis.py`

### Infinite-mana guard for simulated matches (ANA-4)

- **What:** A `GreedyBot` against a real infinite-mana combo would tap forever without the turn ending. `run_one_match` checks `GameState.mana_produced_this_turn` after every action and aborts the match once it crosses a named `INFINITE_MANA_THRESHOLD` (1000), dropping only that turn's snapshot and counting the match separately (`matches_aborted_infinite_mana`) rather than silently lowering the sample count.
- **Files:** `services/dynamic_analysis.py`

### Bounded worker pool for background analysis jobs (ANA-4 follow-up)

- **What:** Each analysis job originally got its own bare `threading.Thread`, risking an unbounded burst of CPU-bound threads. `DynamicAnalysisJobs` now owns a fixed `_JobWorkerPool` (default 4 workers, `MTG_DYNAMIC_ANALYSIS_WORKERS`) pulling jobs off a queue; an over-capacity job sits as a new `"queued"` status until a worker frees up.
- **Files:** `services/dynamic_analysis.py`, `mtg_analyzer/config.py`

### Survivorship-bias fix in dynamic analysis (ANA-4 follow-up)

- **What:** The dummy opponent shared the real player's starting life, so a `GreedyBot` killed it within a handful of turns for any aggressive deck — later turns' means were then dragged down because only slower-developing matches survived to contribute data. Fixed by decoupling the dummy's life via `build_goldfish_engine`'s new `dummy_starting_life` param, set to a fixed `DUMMY_ANALYSIS_LIFE = 100_000` constant in the analysis harness only.
- **Files:** `services/dynamic_analysis.py`, `services/game_session.py`

## Auth & Persistence

### Deck persistence (save/load)

- **What:** `models/deck.py`'s `Deck` (server-generated UUID identity, name is just a label) and `services/deck_database.py`'s `DeckDatabase` (SQLite, same JSON-blob-per-row pattern as `CardDatabase`) store raw decklist text only, re-parsed on demand, rather than derived data that could drift.
- **Files:** `models/deck.py`, `services/deck_database.py`, `api/saved_decks.py`

### Cached color identity / commanders on a saved deck

- **What:** `color_identity`/`commanders` are computed once (needs resolved `Card` data, too costly per list render) and persisted, filled in lazily on first GET and reset only when the decklist text itself changed (not on a sleeve-only re-save).
- **Files:** `services/deck_validation.py` (`compute_deck_identity`), `api/saved_decks.py`

### `Deck.is_cube` flag

- **What:** Marks a saved decklist as a curated card pool rather than a legal Commander deck; parser and legality validation both gained an `is_cube` param that skips structural (100-card/singleton/commander-count) and semantic (ban list/color identity/Partner) checks entirely rather than reporting a cube's inherent "violations."
- **Files:** `parser/deckliste_parser.py`, `services/deck_validation.py`, `api/saved_decks.py`
