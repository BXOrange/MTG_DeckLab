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

### Commander Spellbook combo snapshot

- **What:** A lazy `CommanderSpellbookDatabase` downloads Spellbook's compressed full variants/aliases export only when the first combo match needs it (or via explicit update), streams it into staging SQLite, then transactionally syncs full JSON records, indexed card uses, checksums, version and source timestamp. Refresh reports added/changed/removed variant and alias counts; failed download/import leaves the old snapshot intact. `GET /api/combos/status` never initializes it, `POST /api/combos/matches` initializes only if needed, and `POST /api/combos/update` forces refresh.
- **Files:** `services/commander_spellbook_database.py`, `api/combos.py`, `api/dependencies.py`, `config.py`, `api/schemas.py`
- **Why:** The upstream OpenAPI documentation explicitly says not to paginate through the whole `/variants/` API; use the compressed bulk snapshot with a named User-Agent. The durable local SQLite copy avoids repeated upstream calls and exposes source diffs. Full implementation and contract limits: [COMMANDER_SPELLBOOK.md](../Reference/COMMANDER_SPELLBOOK.md).

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

### Mana-ability source counters (RULE 605.3b)

The mana grammar recognizes a single named counter placed on the source after
ordinary mana production. `ManaAbility.source_counters` survives runtime option
resolution and applies through the counter-replacement path without a stack item.
The World Shaper regression checks the counter immediately after activation.

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

### Mox Opal: conditional mana activation

- Mana abilities now parse “Activate only if …” through the shared activation-condition vocabulary. Both available production options and cost validation check the condition against the current controller's board, so manual activation, legal actions and auto-tap potential respect Metalcraft. Unrecognized conditions fail closed.
- Mox Opal counts itself; opponents' artifacts do not count. Losing control of the third artifact immediately disables production. Covered by `tests/test_mox_opal_mana_condition.py`.

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

### Counter-scaled mana: "plus an additional {C} for each `<counter>`" and "X mana … where X is the counters" (PAR-135)

- **What:** a mana ability is claimed by `segmenter._MANA_EFFECT_RE` on its leading "Add", and `game/mana_abilities.py` models it *fail-soft* — a shape it doesn't read falls back to the base clause. Famous Museum ("{T}: Add {C}, plus an additional {C} for each art counter on ~") therefore produced a flat {C}, and Lotus Blossom ("{T}, Sacrifice: Add X mana of any one color, where X is the number of petal counters") one mana of any colour — both only visible once their *other* clause (the named counter) started parsing and they turned MODELED. `_SUBJECT_COUNTER_RE` now takes a named counter kind on "this artifact/creature/…/~" (the card's own name folded to "~"), and `_PLUS_ADDITIONAL_FOR_EACH_RE` makes the amount `1 + count` (`amount_selector["plus"]`, read in `resolve_options`) when the extra pip equals the single-pip base. Amounts resolve before the sacrifice cost, so Lotus Blossom pays out its three.
- **Still true, and worth knowing:** the blanket "Add …" claim means any *other* unrecognised mana shape is wrong-but-MODELED; a newly covered card with a mana ability should be tapped in the engine, not trusted.
- **Files:** `game/mana_abilities.py`. Tests: `tests/test_par135_named_counters.py`.

## Rules Engine Core Loop

### Cast-time keyword grants and scoped cascade

`grant_keyword` supports `spells_you_cast`, a required `mana_source_kind`
and `first_matching_each_turn`. Cast events snapshot actual mana by source
kind, including restricted lots, and stack mana value including announced
X. The shared grant evaluator also serves existing instant/sorcery storm
grants. Each granted cascade queues a separate spell-owned trigger, with
its caster and threshold captured independently of the granting permanent.
Earlier matching casts count even if the grant was not yet present.

Cascade uses the immediate-play path for ordinary target, face, mode and
additional-cost choices. Its scoped permission permits spells only and
enforces the resulting spell's lesser mana value under RULE 702.85a.
Uncast exiled cards are randomized onto the library bottom after either
casting or declining, before priority is offered. The cast spell remains
on the stack for responses.

### Revealed-card payments inside player iterations

`reveal_top` resets its referent for an empty library and emits a public
REVEAL event. `put_revealed_card` supports exile through the ordinary zone
move and hand placement without a draw. Optional payment continuations keep
the revealed card and acting controller through their answer; their frame
now belongs to GameState so rewind preserves both the payment and its card.
Player iterations preserve that controller across each suspended body.

Resolution drains outstanding choices and deferred bodies before checking
state-based actions, allowing a player to pay their entire life total during
a multi-player process before the enclosing ability finishes. Phase-relation
predicates consult the source's current controller at triggering time.
State clones retain earlier turn/attack events for permissions based on an
opponent's most recent turn.

### Mixed-zone choices and delayed attached returns

`choose_objects` accepts an owned-card pool across hand and command zones,
with `mana_value_less_than_trigger` using the DIES event's last-known mana
value. The shared measurement handles face-down, transformed and melded
creatures. `zone_to_battlefield` resets the selected card before entry and
retains it as the follow-up referent without invoking library-search rules.

`create_delayed_trigger` captures the original host and source incarnations
for `return_self_from_graveyard` with `attach_to_previous`. An invalid host,
protection or a host that left and returned prevents Aura entry under
RULE 303.4i / 603.7c. Successful entry establishes the attachment before
the entry event. Object choices and delayed effects preserve the resolving
ability's controller when the source changes zones or has another owner.

### Conditional defender permission (RULE 702.3b / 508.4)

`attacks_as_though_no_defender` supports a defender kind and a combat
condition. Attack offers, declaration validation and goad checks apply the
same permission to the actual defender. Removing defender independently
still permits ordinary attacks. `opponent_attacked_you_last_turn` reads
declared attacks during each opponent's own most recent turn; attacks on
planeswalkers or battles and creatures put onto the battlefield attacking
do not qualify. Declared attack events retain their defender kind, while
solo goldfish attacks remain valid without a defender object.

### Hideaway entry trigger (RULE 702.75a / 406.3)

The existing `Hideaway N` keyword spec now binds an ordinary entry trigger.
It inspects the top N cards, requires one selection, exiles it face down and
randomizes the rest onto the library bottom. Linked cards and visibility
permissions survive separate trigger firings. New source controllers gain
permission to look; previous viewers retain it after control changes or source
removal. A source incarnation captured by the trigger prevents attaching an
old selection to a returned permanent. Mandatory object choices reject declines
without discarding the pending choice.
Activated stack items capture `hideaway_exile_ids` in their event context when
the source has links, preserving the original association after source removal
or new links on a returned incarnation (RULE 607.2a / 400.7).
The snapshot also records each linked card's incarnation before activation
costs are paid. Leaving exile invalidates that incarnation and the card's
source link, so an older activation cannot play a later exile of the same card.

`play_hideaway_card` checks a shared state predicate at resolution and offers
the captured linked cards through the ordinary immediate-play path. Under
RULE 607.3, multiple cards from duplicated entry triggers may each be played
in the same activation, with choices and targets preserved for each.
The shared state predicate `opponent_was_dealt_damage_this_turn` reads actual
damage events per opponent, including infect, independently of life loss or
subsequent life gain. It supports the numeric bounds needed by Spinerock Knoll.

### Playing an exile card during resolution (RULE 608.2g / 305.2–3)

`GameContext.offer_play_during_resolution` opens a scoped optional play choice;
`GameEngine.play_resolution_card` uses the ordinary casting/land path with
targets, modes and additional costs. Casting another player's card transfers
spell control to its caster. Alternative costs cannot be combined, and mana-cost
X must be zero. Lands still require the player's turn and an available land
play, but do not require an empty stack or main phase. Declining or playing
revokes the scoped permission. Deferred outer effects finish before the nested
spell resolves; the active player receives priority afterward.

Game sessions expose ordinary cast/land actions to the choice's player and
validate the acting seat independently of priority. The board reuses its
target/modal cast controls inside the choice. The primitive is tested in
`tests/test_resolution_play.py`. Repeated offers wait for a played land's own
entry choice before offering the remaining cards; no nested spell resolves
between those choices.

### Choices representing different card types (RULE 205.2a–b)

`distinct_card_types` accepts selected cards whenever each can represent a
different card type. Earlier multi-type assignments can change as later cards
are chosen; shared types alone no longer exclude a legal pick. The chooser
captures each pick's types before its zone move and includes Kindred and the
other official card types. Integration tests cover both selection orders and
reject an extra card while keeping the choice open.

`choose_objects` can use the defending player's graveyard as its pool while
the ability controller chooses. The attacking event preserves that player's
identity after source removal. Serialized follow-up effects retain their
conditions, so a departed source does not receive battlefield-only counters.

### Measured choices and battlefield exit state

`choose_objects.then_that_many` measures a chosen creature's power before
returning it to hand, or its mana value before sacrificing it. The mana-value
measurement uses the front face for transformed permanents, sums meld components,
and treats face-down permanents as zero (RULE 202.3). It can supply the count
for a subsequent optional top-library selection without re-reading the card
after the zone change. Battlefield-to-hand moves clear counters and temporary
modifications, restore the front face and owner's control (RULE 400.7).
Control-dependent riders can branch before that move to preserve the relevant
information. Queued triggers capture their source's controller at the triggering
event, including after a control change (RULE 603.3a).

`choose_player_objects` also supports all living players, permanent filters,
and simultaneous decline effects while retaining APNAP choice order.

### Quoted abilities on created tokens (PARSER_VERSION 598)

The parser attaches a fully supported quoted ability in “They/Those tokens
have …” to each created token's Oracle text (RULE 111.3). Each token receives
its own bound ability; unsupported or partially claimed quotes fail closed.
Integration tests cover controlled Devil death triggers and the complete
two-stage Ooze death chain.

### Multi-player selections and simultaneous actions (RULE 101.4 / 608.2e)

`choose_player_objects` collects choices in APNAP order, including optional
declines, before discarding hand cards or sacrificing permanents simultaneously.
Its serialized continuation preserves the selected objects and remaining seats;
measured follow-ups count only nontoken cards that actually reach the graveyard.
`choose_objects` can filter by shared card types and capture the sacrificed
permanent's last-known types before subsequent players choose. Both discard
paths now honor graveyard redirection through the shared zone-move handler.

### Additional costs on standing casting permissions

Standing graveyard permissions can require a sacrifice in addition to the
spell's other costs. Explicit choices are validated, and automatic selection
finds distinct objects for both sacrifices. Payment occurs during casting;
overlapping permissions without this cost remain available. Additional land
play grants now honor their live conditions, including charge-counter thresholds.

### Composed graveyard recovery and linked casting permissions

`MillEffect.capture_milled` and `ReturnFromGraveyardEffect.previous_pool` restrict
a subsequent recovery choice to the cards from that mill, including across an
optional payment. `each_player_pick` can return the selected cards under the
ability controller's control. Living Death uses separate simultaneous exile,
sacrifice and return stages; targeted sacrifice-to-return effects preserve their
announced targets across the sacrifice choice.

Single-card graveyard grants can authorize normal-cost casting without
flashback's exile replacement. They survive removal of the granting permanent,
expire at cleanup, and are consumed when the card leaves the graveyard.
Conditional exile permissions can cover lands and spells linked to an active
source; turn and event-history gates are checked when a card is played or cast.

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

### Impulsive Draw from every library; contested-land control; "dealt combat damage this turn" gate (PLAY-ALL, Riveteer Rampage)

- **What:** `impulsive_draw` gained `each_player` (one exile per living player, every permission held by the controller) and `mana_wildcard` (RULE 605.1a), reused by Mezzio Mugger. A new condition kind `dealt_combat_damage_to_player_this_turn` (`static_conditions.py`) reads the event-derived `GameState.combat_damage_to_players_this_turn` by the subject's stable `instance_id`, so a dying creature still answers it (Wave of Rats' intervening-if). `take_contested_land` (`ContestedLandControlEffect`) plus the `gain_control_and_untap` choose-object action lets the damaging creature's controller pick one of the damaged player's `contested` lands (Turf War); its "controls such a land" intervening-if is checked at resolution only. Blitz itself is the existing `game/blitz.py`, bound from the printed cost.
- **Files:** `game/effects/library.py`, `game/effects/core.py`, `game/effects/exile_control.py`, `game/effects/registry.py`, `game/isa.py`, `game/static_conditions.py`, `game/rules/misc_mixin.py`, `tests/game/catalogue/cards/test_riveteer_rampage_deck.py`.

### Demonstrate, look-and-cast-free, counter-then-exile, uncounterable spells, standing flashback (PLAY-ALL, Jeskai Striker)

- **What:** **Demonstrate** (RULE 702.144a) is now an engine cast trigger (`RulesEngine._collect_demonstrate_triggers` → an `optional` node around `demonstrate_copy`/`DemonstrateCopyEffect`: the controller's copy plus the next living opponent's copy; opponent auto-picked, new targets keep the originals) — Creative Technique and Transforming Flourish get it from the keyword. `look_top_cast_free` (`LookTopCastFreeEffect`) exiles the top N, offers matching spells through RULE 608.2g's resolution play (≤ the source's power for Velomachus Lorehold) and bottoms the rest randomly. `counter` gained `exile_then_cast_free` (`counter_spell(exile_instead=True)`, Transcendent Dragon). `grant_cant_be_countered` gained the `all_spells` scope (Lier); `graveyard_cast_permission` gained `instant_sorcery_only` (Lier's standing flashback at mana cost). `dig_until` gained `digger="previous_target_controller"` (Transforming Flourish). `copy_spell` gained a `max_mana_value` spell-target ceiling (Expansion // Explosion, via `targeting._spell_matches_filter`). `free_cast_from_hand` gained `shares_type_with_trigger` / `strictly_less_than_trigger`, and triggers gained `is_nth_instant_or_sorcery_cast_this_turn` (Baral and Kari Zev). `AttackedCurseGoldEffect` + `create_token creators="trigger_attacking_player"` serve Curse of Opulence (the Curse's controller's Gold is once per turn via `curse_gold_turn`, the attacking opponent's once per `PLAYER_ATTACKED` group). Parser: "counter target activated or triggered ability" is its own clause (PARSER_VERSION 607), which made Sublime Epiphany `MODELED`.
- **Engine bug found and fixed:** `RulesEngine.destroy` ignored indestructible (RULE 702.12b) — only the lethal-damage SBA honoured it, so every destroy effect killed indestructible permanents. It now returns early (no shield counter or regeneration is spent). `test_par92_residue_batch.py` had been pinning the old behaviour with Blightsteel Colossus and now uses Legacy Weapon.
- **Files:** `game/effects/{exile_control,stack,library,counters_tokens,core,registry}.py`, `game/rules/{misc_mixin,triggers_mixin,damage_death_mixin}.py`, `game/{targeting,static_conditions,isa}.py`, `game/binding/core.py`, `parser/oracle/catalogue/handlers.py`, `tests/game/catalogue/cards/test_jeskai_striker_deck.py`.

### Offspring, power-gated discounts, granted-ability grantor, hideaway from triggers (PLAY-ALL, Animated Army)

- **What:** **Offspring** (RULE 702.175) is engine-backed: it is an optional additional cost, so `GameEngine._kicker_cost` falls back to the printed offspring cost and shares Kicker's announcement (`kicked`, `GameObject.kicker_count`; the cast action carries `kicker_keyword: "offspring"` and the board titles the field "Offspring"); `_kw_offspring` binds the ETB "if its offspring cost was paid, create a 1/1 token copy of it" (`copy_permanent`, untargeted, `set_power/set_toughness`). `cost_reduction` gained `spell_min_power`; spell-keyword grants (`grant_keyword` on `spells_you_cast`, read by `granted_cast_keyword_instances`) gained `card_types` and `from_hand` (Wildsear); the "greatest `<metric>` among `<scope>` you control" reader gained an `artifacts` scope. New trigger gates: `spell_mana_source_kind` (a Treasure paid for the spell, off `SPELL_CAST.mana_spent_by_source`). New condition: `controls_greatest_power_creature`. A granted ability can now name its **granting permanent**: a `$grantor` param value in `grant_effects` resolves to that permanent's instance id (`continuous._build_grant_effect`), used by `fight` with the new `other_instance_id` (Grothama). `play_hideaway_card` works from a *triggered* ability (links read off the source) and needs no condition (Evercoat Ursine; hideaway printed twice is two authored keyword specs). `draw_per_damage_dealt_to_source` sums this turn's DAMAGE events aimed at the source per source controller (Grothama).
- **Files:** `game/engine/{casting_mixin,legal_actions_mixin}.py`, `game/binding/core.py`, `game/continuous.py`, `game/static_conditions.py`, `game/effects/{registry,library,returns_graveyards}.py`, `game/isa.py`, `frontend/src/js/gameBoardView.js`, `tests/game/catalogue/cards/test_animated_army_deck.py`.

### Attack redirect, linked-exile characteristics, mass-effect filters, monarch/step conditions (PLAY-ALL, Keen Engineering)

- **What:** `reselect_attack` (`ReselectAttackEffect` + the `reselect_attack` choice, `RulesEngine._attack_defender_specs`) lets an effect's controller re-pick which player/planeswalker/battle an attacking creature attacks (Misleading Signpost). `type_change` gained `from_linked_exile` (layer 4: base P/T and creature types of the source's Imprinted creature card while it is still exiled — Duplicant). Mass-effect vocabulary: the `_mass_selector_objects` filter gained `attacking` and `controller_dealt_combat_damage_by_source`; `sacrifice` gained `what="colored"`, `what="subtype:<word>"` and `count="all"`; `damage` gained the `attacked_object` selector (the player *or planeswalker* an attacker was declared against). New conditions: `controlled_by_monarch` (of a subject), `controls_greatest_mana_value_artifact`, `during_step`; new trigger gate `mana_produced_includes` (a `TAPPED_FOR_MANA` whose `produced` contains the type — Forsaken Monument). `play_hideaway_card`/`choose_objects` now serve triggered "tap X untapped Myr" bodies (`then_that_many`, Myr Battlesphere).
- **Files:** `game/effects/{library,damage_draw,registry}.py`, `game/rules/{misc_mixin,damage_death_mixin}.py`, `game/continuous.py`, `game/static_conditions.py`, `game/binding/core.py`, `parser/oracle/spec.py` (the `step` condition field), `tests/game/catalogue/cards/test_keen_engineering_deck.py`.

### Attackers-aimed-at-you counts, tapped dig hits, divided computed damage, fight-each (PLAY-ALL, Tramplesaurus Rex)

- **What:** the `count_selector` vocabulary gained `creatures_attacking_you` (attackers whose declared defender is that player — Arachnogenesis, with `prevent_all_combat_damage`'s `exclude_subtype`); `dig_until` hits may enter `battlefield_tapped` (Clifftop Lookout); `flash_permission` gained a `color` filter (Yeva); `cost_reduction` ∧ `spell_color` serves Rhonas's Monument; divided `damage` now splits its *resolved* amount, so a computed X divides too (Monstrous Onslaught — it reads the greatest power at resolution, not at cast); `inspect_top_choose` criteria accept `max_mana_value: "lands_you_control"` (Loot, Exuberant Explorer). `FightEachOpposingCreatureEffect` (`fight_each_opposing_creature`) makes a token per opposing creature and pairs them (Ezuri's Predation; the pairing is battlefield order, not a controller choice), sharing `FightEffect._fight`.
- **Files:** `game/effects/{library,damage_draw,returns_graveyards,registry}.py`, `game/rules/search_mixin.py`, `game/continuous.py`, `game/isa.py`, `tests/game/catalogue/cards/test_tramplesaurus_rex_deck.py`.

### Mana retention, red-only X payments, discover limits, conditional keywords (PLAY-ALL, Reign of Dragons)

- **What:** `retain_mana` is a standing permission read by `continuous.empty_mana_pool` as each step ends (Leyline Tyrant keeps red; no colours listed = all) — both step-end sites now go through it. `pay_cost_then` gained `x_color` ("pay any amount of {R}": the announced X is paid in that colour, `_cost_with_x`/`_max_payable_x`), used with a reflexive `then_trigger` for the dies-payoff. `discover` gained `cast_limit` (Breaching Dragonstorm: a hit above 8 can only go to the hand) and `treasures_below` (Hit the Mother Lode: tapped Treasures equal to the difference, applied after the cast-or-take choice). `behold_then` (`BeholdThenEffect`) is "you may behold a `<type>`. If you do, …" (Sarkhan). **Conditional keywords:** `register(..., suppress_keywords=(...))` stops Scryfall's `keywords` array granting a keyword the card only has conditionally (Goddric's celebration flying) — `card_registry.core.suppressed_keywords_for` stamps `GameObject.suppressed_keywords` at bind time and `combat._obj_keywords` subtracts them from the card-level part. New conditions: `nonland_permanents_entered_this_turn` (celebration). `damage_equal_to_power` gained `each_other_creature_and_opponent` (Chandra's Ignition); damage effects gained `distinct_from_others` ("other targets", Drakuseth); `cost_reduction` gained `spell_subtype_from_source` and `inspect_top_choose` criteria the `chosen_type` sentinel (Herald's Horn); `inspect_top_choose` criteria also accept `max_mana_value: "lands_you_control"` (Loot). `ExileTopPlayThenBurnEffect` + `StillExiledDamageEffect` (Dragonhawk) pair the exile-and-play window with a delayed end-step burn per card still exiled.
- **Files:** `game/continuous.py`, `game/card_registry/core.py`, `game/binding/core.py`, `game/combat.py`, `game/effects/{exile_control,library,returns_graveyards,choices_actions,game_status,damage_draw,registry}.py`, `game/rules/{misc_mixin,search_mixin}.py`, `game/engine/{turn_loop_mixin,misc_mixin}.py`, `game/static_conditions.py`, `game/isa.py`, `tests/game/catalogue/cards/test_reign_of_dragons_deck.py`.

### Ravenous/evolve, granted offspring, mass reanimate-as-Spirits, attacking-copy defenders (PLAY-ALL, Family Matters)

- **What:** `ravenous` (RULE 702.156: X counters at entry via `_apply_entry_counters`, draw at X≥5, `RAVENOUS_DRAW_THRESHOLD`) and `evolve` keyword builders; `enters_with_counters_count` static; trigger gate `spell_mana_value_less_than_source_power`; `return_to_hand` `exact_mana_value`; creature filter `attacking_trigger_defender` plus `CopyPermanentEffect` entering attacking the *copied* creature's defender (Echoing Assault); affinity for tokens (`_AFFINITY_SELECTORS["token"]`, Junk Winder); new static condition `cast_spell_this_turn` (Fortune Teller's Talent's level-2 top-of-library permission, `min_level` + `active_if`; level 3 is a `cost_reduction` with `not_from_hand`). Storm of Souls is `return_from_graveyard players="you"` + one `grant_until previous_subject` (it falls back to the mass return's `created_objects`; `pt_set` 1/1 + Spirit subtype + flying, `rest_of_game`) + untargeted self `exile`. Zinnia: a self `anthem` whose per-unit count is a structured selector (`base_power` filter, `not_reference`), and the new `grant_offspring` static (`continuous.granted_offspring_cost_for`) — `GameEngine._kicker_cost` became an instance method so Offspring's shared kicker announcement can fall back to it, and the cast binds the Offspring ETB trigger onto the spell once its cost was paid.
- **Files:** `game/binding/core.py`, `game/rules/casting_mixin.py`, `game/engine/casting_mixin.py`, `game/continuous.py`, `game/static_conditions.py`, `game/targeting.py`, `game/isa.py`, `game/effects/{registry,returns_graveyards,counters_tokens}.py`, `game/card_catalogue/{j,b,p,r,t,c,s,m,e,f,z}/…`, `tests/game/catalogue/cards/test_family_matters_deck.py`.

### Tempting offers, chosen opponent, class token upgrades, Curse-style Aura on an opponent (PLAY-ALL, Peace Offering)

- **What:** the "each opponent may …, for each who does you …" shape is a `for_each` over opponents whose body is a free `pay_cost_then` (``payer="target"``; Ja/Nein labels when the cost is empty) — the opponent's side reads the iterated player as the target (`draw` ``target_kind``, `create_token` ``creators="target"``, `search` ``player={"of": "target"}``), your bonus is the untargeted default; two interactive effects in one branch need a `seq` wrapper so the second waits (Tempt with Bunnies/Discovery, Kwain). `reveal_top` ``whose="target"`` reveals a `for_each` item's own library (Selvala). "Choose an opponent" is `_request_choose_player` ``opponents_only`` + ``then_effects`` (a lone opponent is taken without a prompt) with the new ``chosen_player`` referent, `tap` ``selector_player="chosen"``, and `_object_by_instance_id` now also finds a spell parked in `deferred_effects` (Intellectual Offering). `draw` gained ``target_count``/``target_optional`` (any number of target opponents, with the new ``targets_count`` amount and a player-aware `_span_picks` so one opponent can't be picked twice — Communal Brewing, whose cast-time counters are `extra_etb_counter` with a structured count selector). `pt_set` takes ``power_count``/``toughness_count`` (Jolrael), `add_player_counters` takes a player operand (Bloodroot Apothecary's sacrifice poison), the amount modifier ``minus`` accepts an amount (Mr. Foxglove). `substitute_token` is a Class-level-gated token-creation replacement that chains (Fisher's Talent: Fish → Shark → Octopus), with `peek_top_land_or_hand` ``reveal_then`` for its "you may reveal it if it's a land" upkeep. Tenuous Truce: "Enchant opponent" Auras (`_attachment_legal`, `spell_target_specs`), ``phase_relation="enchanted_player"``, the ``enchanted_player`` referent and an `ATTACKERS_DECLARED` predicate ``attack_between_controller_and_enchanted`` (the event now carries ``defended_player_ids`` incl. planeswalker controllers). Coveted Jewel: `gain_control_by_source` ``recipient="event_player"`` and the ``first_unblocked_attacker_at_you`` trigger predicate. Perch Protection is Teferi's Protection's phase-out behind ``gift_promised``. Tamiyo, Field Researcher: `grant_until` ``your_next_turn`` of a granted combat-damage trigger drawing for the grantor's controller (`GRANTOR_SENTINEL` as `draw`'s player), and an emblem `free_cast_permission` limited ``from_hand``. Illusionist's Gambit: a new ``cast_timing_restriction`` shape (declare blockers on an opponent's turn), `tap` ``remove_from_combat``, `extra_combat_phase`, a temporary ``attacks_if_able`` and the ``reversed`` no-attack pair.
- **Files:** `game/effects/{registry,damage_draw,counters_tokens,library,life_sacrifice,exile_control,game_status,attachments_transforms,replacements}.py`, `game/{continuous,effect_amounts,effect_conditions,targeting,isa}.py`, `game/binding/core.py`, `game/rules/{misc_mixin,casting_mixin,triggers_mixin,search_mixin}.py`, `game/engine/{casting_mixin,combat_mixin,legal_actions_mixin}.py`, `parser/oracle/spec.py` (+ `PARSER_VERSION.lock`), `game/card_catalogue/…` (19 cards), `tests/game/catalogue/cards/test_peace_offering_deck.py`.

### Omen, reveal-or-control lands, command-zone loans, forced-defender attacks (PLAY-ALL, Temur Roar)

- **What:** **Omen (RULE 720.3d):** the cache stores Omen cards with the Adventure layout, so they cast through the Adventure path; on resolution `RulesEngine._is_omen_card` (back type line "… — Omen") routes the card to `shuffle_into_library` instead of exile + `adventure_castable` (a fizzled Omen still goes to the graveyard). **Reveal-or-control lands** (Temple of the Dragon Queen, Fortified Beachhead; PARSER_VERSION 608): `land_tap_condition` `reveal_types` gained `or_control` — controlling a permanent of the type skips the reveal question (`_controls_permanent_of_types`, also used by `predict_land_tapped`). **Target ceilings read off the firing spell:** `max_mana_value: "trigger_spell_mana_value"` (`legal_targets`, beside Skyfire Kirin's `exact_mana_value`) and `return_to_hand` now accepts `max_mana_value`; `put_from_hand_onto_battlefield` takes `max_mana_value_from_trigger` (a firing-event field, e.g. the contributor batch's `matching_amount`, Broodcaller Scourge). `enter_as_copy` takes a `creature_filter` (Deceptive Frostkite's power ≥ 4) and the become-copy effects a `set_name`. `flash_permission`'s `type_filter` also accepts a printed subtype word (Whirlwing Stormbrood). New `nontoken_creatures_died_this_turn` count selector (`turn_history.nontoken_creatures_died`, off the DIES event's `is_token`). New target kind `human_or_artifact_you_dont_control`. A granted `cant_attack`/`cant_block` flag survives "loses all abilities" (`combat._obj_keywords`: it is a rules effect, not an ability — Opportunistic Dragon). **Command-zone loan:** `return_specific_to_command_zone` (the `return_specific_to_hand` sibling) closes Hellkite Courser's `choose_objects` (`zone_to_battlefield`, `pool_zones: ["command"]`) + haste + delayed return. **Forced defender:** `GameObject.must_attack_player_id` / `last_combat_attacked_ids` (recorded per combat in `CombatMixin._record_last_combat`), `force_attack_unattacked_opponent` and `_enforce_must_attack_player` (Territorial Hellkite: random opponent it didn't attack last combat, else tap). "Dragon Egg" is registered as a card (the token Nesting Dragon creates shares its name and so binds the dies-trigger by name — the parser cannot claim a created token whose granted ability is itself a quoted ability). Fifteen cards in all; the individually modelled ones live in `game/card_catalogue/` and their tests.
- **Files:** `game/rules/casting_mixin.py`, `game/targeting.py`, `game/continuous.py`, `game/combat.py`, `game/engine/{combat_mixin,turn_loop_mixin}.py`, `game/effects/{registry,returns_graveyards,library,counters_tokens,choices_actions}.py`, `models/game/{game_object,game_state,turn_history}.py`, `parser/oracle/catalogue/lands.py`, `parser/oracle/gate.py` (PARSER_VERSION 608), `game/card_catalogue/…`, `tests/game/catalogue/cards/test_temur_roar_deck.py`.

### Zombie amounts, graveyard-zombie targets, regenerate-by-type, embalmed copy clause (PLAY-ALL, Eternal Might)

- **What:** new `effect_amounts` kinds `moved_count` (cards a preceding mill/move shifted, optionally by ``card_type`` — nested compositions scope `moved_objects`, so the count must sit in the same `seq` as the mill, e.g. Dread Summons per player) and `greater_of` (``left``/``right`` amounts — "A or B, whichever is greater", Prophet of the Scarab); `AmassEffect.count` now coerces lazily so a `bind`-measured "amass X" works. New count selector `creatures_you_controlled_died_this_turn` (per-controller sibling of `creatures_died_this_turn`, Priest of the Crossing). New static condition `subtype_dealt_combat_damage_to_player_this_turn` (Lost Monarch's intervening-if, dealers looked up in any zone). New graveyard target kind `graveyard_zombie_card` (Unholy Grotto, Rot Hulk with `count_selector: "opponents"`). `enter_as_copy` takes `token_add_subtypes`/`token_set_colors` (the embalmed-token "except" clause; `copy_mechanics.become_copy` gained `set_colors`). Reused unchanged: `regenerate` + a `subtype_any` filter (Accursed Duneyard), group `pump` over ``of: "any"`` (Lord of the Accursed), `choose_targets` + `previous_player` (Corpse Augur, Gempalm Polluter), `any_of` selector filters (On Wings of Gold), parametric `afflict` grants. PARSER_VERSION 609/610 (amount-spec fields).
- **Files:** `game/{effect_amounts,static_conditions,continuous,targeting,copy_mechanics}.py`, `game/effects/{counters_tokens,registry}.py`, `game/rules/casting_mixin.py`, `parser/oracle/{spec,gate}.py` (+ `PARSER_VERSION.lock`), `game/card_catalogue/…` (17 cards), `tests/game/catalogue/cards/test_eternal_might_deck.py`.

### Dies-replacement token riders, opponent-count conditions, structured entry counters (PLAY-ALL, Wretched Ranks)

- **What:** `die_to_exile` (RULE 616.1) gained `nontoken_only` and a `create_token` rider the source's controller receives (Kalitas, Traitor of Ghet: opponents' nontoken creatures are exiled and leave you a Zombie; a token is not "that card" and just dies). New static condition `opponent_controls_at_least` (``min`` + a `matches_object_filter` ``filter``, some one opponent) read by a cost's `dynamic_reduction.active_if` for Razorlash Transmogrant's "{4} less if an opponent controls four or more nonbasic lands". `enters_with_counters_count` accepts a structured ``{zone, of, filter}`` selector (Diregraf Colossus: Zombie cards in your graveyard; the entry-counter reader no longer stringifies it). A tapped-entry land trigger uses a RULE 603.4 intervening-if (`trigger["active_if"]` = ``source_untapped``) instead of a resolve-time condition, so Witch's Cottage never asks for a target when it entered tapped. Reused: `choose_player_objects` + `then_that_many` ("x" = creatures actually sacrificed; Syphon Flesh), `may_exile_source_then` (Undead Butler), `grant_flashback_to_target` ``as_permission`` (Zul Ashur), `any_of`/`without_subtype` selectors (Death Baron), `enters_with_counters_count`, `kicked` effect condition (Josu Vess).
- **Files:** `game/effects/replacements.py`, `game/static_conditions.py`, `game/effects/registry.py`, `game/rules/casting_mixin.py`, `game/card_catalogue/…` (16 cards), `tests/game/catalogue/cards/test_wretched_ranks_deck.py`.

### Convoke records, "this way" pools, per-player graveyard targets, paired sacrifice costs (PLAY-ALL, Sultai Arisen)

- **What:** `GameObject.convoked_by_ids` (stamped by `_consume_cast_help`, RULE 702.51c) feeds `connive` with ``convoked`` ("each creature that convoked this spell connives", Lethal Scheme). `GameContext.destroy` now appends what it destroyed to `moved_objects`, and `return_from_graveyard` gained ``moved_pool`` (a pick limited to cards moved "this way", Necromantic Selection), ``previous_subject`` (put "those cards" the earlier clause chose onto the battlefield, Afterlife from the Loam), ``then_effects`` (serialized follow-ups run with the picked card as `previous_targets` — `_apply_choose_objects_tail` now sets that referent for every chooser's `then_specs`) and ``chooser="chosen_player"`` (an opponent picks, Tasigur). New graveyard target filters `creature_or_land`, `nonland_card`, `nonlegendary_card`, `non_dragon_creature` and a `that_player_graveyard` scope (`per_player` rounds target each player's own graveyard). `reveal_until` takes ``scope="each_opponent"`` and a graveyard hit destination (Consuming Aberration); `DiscardEffect`'s ``scope`` now asks each player one at a time through `deferred_effects` (before, a 3+ player "each opponent discards" silently kept only the last player's prompt — Junji). `turn_history.cards_put_into_graveyard_from_hand_or_library` + selector (Welcome the Dead); `mana_value` condition ``max_selector`` (a live count — Meren's experience counters); `cast_graveyard_instant_sorcery_free_exile` ``pick``/``max_mana_value`` (untargeted, Diviner of Mist) with a new ``free_cast_exile`` choose-objects action; `grant_flashback_to_target` ``lock_casting`` (`GameState.cast_lock_instance_ids`/`no_more_spells_this_turn`, checked in `can_cast`, cleared at cleanup — Conduit of Worlds); `GraveyardCastPermissionEffect.exile_graveyard_cards` (an additional cost of casting through a standing permission — Kotis; the engine takes the oldest other cards), `GameObject.cast_from_zone` + the ENTERS event's ``cast_from_zone`` and the trigger key ``from_zone_or_cast_from``. **Paired sacrifice cost** "Sacrifice a Swamp and a Forest" is `ActivationCost.sacrifice_also` (`cost_text._SACRIFICE_PAIR_RE`, `ActivationMixin._sacrifice_pair` — two distinct permanents, so a Swamp Forest pays one half only; PARSER_VERSION 611).
- **Bug fixed on the way:** a `lands_only` graveyard permission (Conduit of Worlds, Szarel, Genesis Shepherd) also let you *cast* nonland cards from the graveyard — `graveyard_cast_grant_for` now skips it.
- **Files:** `game/{static_conditions,continuous,targeting,graveyard_cast}.py`, `game/effects/{core,registry,returns_graveyards,damage_draw,choices_actions,game_status}.py`, `game/engine/{casting_mixin,activation_mixin,turn_loop_mixin}.py`, `game/rules/{misc_mixin,search_mixin,casting_mixin}.py`, `game/binding/core.py`, `game/costs.py`, `models/game/{game_object,game_state,turn_history}.py`, `parser/oracle/catalogue/cost_text.py`, `parser/oracle/gate.py` (+ `PARSER_VERSION.lock`), `game/card_catalogue/…` (18 cards), `tests/game/catalogue/cards/test_sultai_arisen_deck.py`.

### Creature-token substitution, turn-scoped token doubling, "that player's library", standing free casts (PLAY-ALL, Mardu Surge)

- **What:** `substitute_token` takes ``from_creature_tokens`` (any creature token, not one named token — Divine Visitation's Angels; the `CREATE_TOKENS` event now carries ``is_creature``, and a substitute is not replaced again by the same effect). New `double_tokens_this_turn` (`DoubleTokensThisTurnEffect`): a `ReplacementEffect` on `Player.player_effects` that ends itself once the turn it was made in is over, so it needs no cleanup hook (Kaya, Geist Hunter's −2); classified in `isa._REPLACEMENT_TYPES`. New count selector `tokens_you_created_this_turn` (`turn_history.tokens_entered`, a token's creation is its entry — Thalisse). New object filter ``is_reference`` (the positive sibling of ``not_reference``, for `any_of` unions such as Ainok Strike Leader's "this creature and/or your commander" `ATTACKERS_DECLARED` head). `immoral_bargain` takes ``destroy_kind`` (``"creature"`` — Eliminate the Competition); its destroy tail no longer counts the spell itself, which already sits in the graveyard when the last sacrifice pick is answered (it made X one too large — the older `sacrifice_count_draw_lose` tail, used by Plumb the Forbidden, has the same snapshot and is untouched). `impulsive_draw` takes ``library_of="that_player"`` (the damaged player of a `DAMAGE` trigger via `targeting.trigger_player_antecedent`, permission stays with the controller — Grenzo, Havoc Raiser); `exile_top_of_library` takes an `effect_amounts` ``count`` (Neriv: differently named tokens, a structured selector with ``distinct: "name"``) and a ``target_kind`` (Gix: "target opponent's library"); `grant_conditional_cast_from_exile` takes ``cost_override`` (``"{0}"``, Airbend's `exile_cast_cost_override`) for a standing "play lands and cast spells … without paying their mana costs"; `pay_cost_then` takes ``payer="trigger_subject_controller"`` (the controller of the creature that satisfied a group trigger) and runs its paid branch as that player (`acting_player_id`). Reused unchanged: `ATTACKERS_DECLARED` for "whenever you attack" (one trigger per declaration, unlike the per-defender `PLAYER_ATTACKED`), `create_token` ``per_opponent`` + tapped-and-attacking, `commander_casts_this_game`, `creatures_died_this_turn`, `creatures_attacked_this_turn` through a `control_count` condition (Windbrisk Heights' hideaway payoff), the opponents-batch combat-damage head (Mindblade Render), Tempt with Bunnies' `for_each`/`pay_cost_then` offer with ``x_paid`` counts, `creature_that_player_controls` goad targets, Evendo Brushrazer's `event_this_turn` permission. Infantry Shield authors Mobilize X as the Equipment's own attack trigger (the keyword row is still recognition only).
- **Files:** `game/{combat,continuous,isa}.py`, `game/effects/{registry,replacements,life_sacrifice,returns_graveyards,library,exile_control,counters_tokens,choices_actions}.py`, `game/rules/misc_mixin.py`, `models/game/turn_history.py`, `game/card_catalogue/…` (18 cards), `tests/game/catalogue/cards/test_mardu_surge_deck.py` (the Mentor tests in `test_par24_triggered_keywords.py` no longer borrow the name "Legion Warboss", which now has a catalogue entry).

### Block tax, can't-lose/win statics, starting life, own-turn counts, entry-counter filters (PLAY-ALL, Calling All Angels)

- **What:** New `block_tax` static (RULE 509.1c, `continuous.block_tax_per_creature`, paid with an auto-tap in `GameEngine.declare_blockers` before the block locks in — Archangel of Tithes while attacking); `attack_tax` now honours its `active_if` gate (the registry factory used to drop it, so a tapped Archangel still taxed attackers). `cant_lose_game` / `opponents_cant_win` statics (RULE 104.3b, `continuous.player_cant_lose/_cant_win`) read by `RulesEngine._loss_prevented`, `_player_loses` (an effect-driven loss is stopped, a concession is not — RULE 104.3a) and `player_wins` (Herald of Eternal Dawn). `Player.starting_life` (+ condition `life_over_starting_at_least`) and `Player.turns_taken` (bumped in `begin_turn`, floored by `GameState.sync_turn_nr` for Replay) with the cast-gate key `own_turn_after` ("can't cast during your first three turns", Serra Avenger). `extra_etb_counter` filters: ``colorless``, ``subtype_from_source`` (Metallic Mimic's chosen type), a structured angel count (Giada). `cost_reduction` takes a ``spell_subtype`` *list* and passes its source to a ``per`` selector (Herald of War: one less per +1/+1 counter on it). Count selector `opponents_with_more_cards_in_hand` (Wojek Investigator), condition `control_same_name_at_least` (Endless Atlas), `parity` bound on `power` (Kianne's even/odd flash).
- **Files:** `game/{continuous,static_conditions,condition_query,isa}.py`, `game/effects/registry.py`, `game/engine/{combat_mixin,turn_loop_mixin}.py`, `game/rules/sba_mixin.py`, `models/game/{player,game_state}.py`, `parser/oracle/spec.py`, `game/card_catalogue/…` (18 cards), `tests/game/catalogue/cards/test_calling_all_angels_deck.py`.

### Face-down land returns, manifest from hand, turn-face-up triggers, resolution-time choices (PLAY-ALL, Jump Scare!)

- **What:** `return_from_graveyard` takes ``face_down_as`` (a `face_down.LAND_KINDS` entry — Yedora's "face down … It's a Forest land", turned face down *before* it enters, RULE 708.3; a kind with no turn-up route) and `return_self_from_graveyard` takes ``face_choice`` (Deathmist Raptor: `_request_return_face_choice`, a `return_face_choice` continuation); the trigger-subject return now requires the card to still be in a graveyard. `choose_objects` gained the actions ``manifest_from_hand`` (Scroll of Fate) and ``exile_face_down_for_play`` (Primordial Mist: exiled face up, then a same-turn play permission) plus ``count_amount`` (an `effect_amounts` operand — Shriekwood Devourer reads the new captured ``matching_attacker_greatest_power``), ``what: face_down``. `counter` takes ``exile_standing_free_cast`` (Kheru Spellsnatcher: `exile_cast_condition` + `free_cast_instance_ids`, never expiring). New `disorienting_choice` (a three-stage choose/exile/search continuation, one pending choice at a time — the cards are chosen on resolution, not targeted at cast). `cant_attack_defender` filters on ``keyword`` (Sandwurm Convergence); object filter ``face_up``. Reused: `manifest_dread` + `previous_subject` (the manifested creature is the next clause's "that creature", also across the look-at-two pause — Experimental Lab), `grant_until` + `grant_triggered_ability` with ``lock_group`` (Whisperwood Elemental), `TURNED_FACE_UP` group triggers (Growing Dread), `flash_permission` (Kianne). **Simplification:** Rooms have no door state — casting Experimental Lab is its door unlocking (the cache holds only the front half).
- **Files:** `game/{face_down,combat,continuous,trigger_quantities,isa}.py`, `game/effects/{registry,returns_graveyards,attachments_transforms,choices_actions,stack,core}.py`, `game/rules/{damage_death_mixin,misc_mixin}.py`, `game/rules_engine.py`, `game/card_catalogue/…` (17 cards), `tests/game/catalogue/cards/test_jump_scare_deck.py`.

### Defender permissions, power-budget choices, resolution-time numbers, per-recipient counters (PLAY-ALL, Abzan Armor)

- **What:** Reused `combat_restriction` ``attacks_as_though_no_defender`` as a static (Felothar) and, until end of turn, through `combat_restriction_this_turn` over a target or a structured group (Assault Formation, Wakestone Gargoyle, Walking Bulwark with ``damage_uses_toughness``). `_request_choose_objects` gained ``total_power_budget`` (the power sibling of the mana-value budget; a graveyard card counts its printed power): Slaughter the Strong (`slaughter_the_strong`, each player in turn order keeps creatures within 4 total power, then every other creature is sacrificed together) and Reunion of the House (`return_creatures_total_mana_value` ``measure: power``, ``own_graveyard``). New `choose_number_then` (a `choose_number_resolve` continuation whose answer binds the ``"x"`` sentinel of its body — Expel the Interlopers). `add_counters` takes ``per_recipient_stat`` (Canopy Gargantuan: each other creature gets its own toughness in counters, measured before any is placed); `gain_life` takes ``life_from_target_creature`` (Wall of Reverence); `exchange_life_total_with_toughness` takes ``player: you`` (Tree of Redemption, Tree of Perdition's effect); `ExileEffect`'s trigger-subject branch honours ``track_exiled_with`` (Colfenor's Urn). New amount kind `abs_diff` (Jaws of Defeat), count selectors `cards_in_your_hand` / `total_toughness_other_creatures_you_control`, mana-value bound sentinel ``life_lost_this_turn`` (Betor), object filter ``without_keyword`` as a list (Sidar Kondo of Jamuraa's "without flying or reach"). Betor's two targets are two end-step triggers (an ability carries one targeting effect); Baldin measures X once for all targets.
- **Files:** `game/{combat,continuous,targeting,effect_amounts,isa}.py`, `game/effects/{registry,choices_actions,returns_graveyards,counters_tokens,life_sacrifice,exile_control}.py`, `game/rules/misc_mixin.py`, `game/card_catalogue/…` (19 cards), `tests/game/catalogue/cards/test_abzan_armor_deck.py`, `tests/test_isa_inventory.py` (continuation bound 92 → 95).

### Variable energy payments, vehicle tokens, granted alternative costs, ETB X (PLAY-ALL, Living Energy)

- **What:** `pay_energy_then` gained ``variable`` ("you may pay one or more {E}": one ``pay_x:<n>`` option per affordable amount, the paid n binds the branch's ``"x"``; `owns_x_sentinel` keeps the enclosing ability's X out of it — Pia Nalaar, Rampaging Aetherhood, Territorial Aetherkite) and ``target_kind`` + ``amount_from_target_mana_value`` (the spell's target prices the payment and is handed to the "if you do" body — Confiscation Coup). `granted_alt_cast_cost` gained ``pay_energy`` and ``permanent_only`` (Nissa, Worldsoul Speaker; the alt-cost check/payment now handle energy). `double_counters_on_target` ``mode="player"`` doubles the controller's energy/experience/poison (Aetheric Amplifier). `free_cast_from_hand` ``arm_all`` arms every nonland hand card for the turn (Aetherflux Conduit). `synthesize_token_card`/`create_token` ``vehicle`` ("an X/X colorless Vehicle artifact token": the P/T is the Vehicle's printed one; Crew needs the ``Crew`` keyword in the keyword list). `additional_creature_tokens` gained ``only_artifact`` + ``fixed_amount`` (Stridehangar Automaton: one extra Thopter per artifact-token creation; the CREATE_TOKENS event now carries ``is_artifact``). `combat_restriction` kind ``must_block_if_able`` (RULE 509.1c, enforced in `_enforce_block_requirements`) via `combat_restriction_this_turn` (Peema Aether-Seer). `choose_player_objects` action ``destroy_not_yours`` (Druid of Purification: every player picks an artifact/enchantment the controller doesn't control, all destroyed at once). `damage` ``amount`` accepts an `effect_amounts` operand (Combustible Gearhulk: milled mana value via `moved_sum`). `look_top_cast_free` ``prompt``. **Engine bug fixed on the way:** an enters-the-battlefield ability that names X read 0 — a trigger's stack item only carried X for SPELL_CAST events; `_place_trigger` now gives a permanent's own ETB trigger the X it was cast with (RULE 107.3m: Champions from Beyond made no Heroes).
- **Files:** `game/effects/{choices_actions,counters_tokens,exile_control,registry,replacements,attachments_transforms,damage_draw,returns_graveyards}.py`, `game/{continuous,combat,isa}.py`, `game/engine/{casting_mixin,combat_mixin}.py`, `game/rules/{misc_mixin,triggers_mixin}.py`, `services/token_database.py`, `game/card_catalogue/…` (20 cards), `tests/game/catalogue/cards/test_living_energy_deck.py`.

### Job select, delayed copies, two-target copies, "once each turn" targets (PLAY-ALL, Scions & Spellcraft)

- **What:** **Job select (RULE 702.182a):** `_kw_job_select` builds the enters trigger from `LivingWeaponEffect` (now parameterised by token) — a 1/1 colorless Hero, then the Equipment attaches (Blue Mage's Cane, Dancer's Chakrams, Reaper's Scythe; the keyword was recognised but inert). `become_copy_of_target_until_eot` (`BecomeCopyOfTargetUntilEndOfTurnEffect`, ``extra_target_specs``: the copier and "another" artifact or creature to copy — Saheeli, Sublime Artificer). `pay_cost_then` ``x_from_trigger_event`` + ``pay_life_x`` + the ``"$x"`` sentinel (X = the cast spell's mana value prices a life payment and the counters — G'raha Tia; a plain ``"x"`` is rewritten with the ability's own X by the composition layer first). **Engine bug fixed:** `ConditionalEffect` hid the targets of a gated `seq`, so every "…target … Do this only once each turn." trigger (PAR-135 shape) resolved with no target; it now announces its inner effect's specs (Krile Baldesion). `GrantSelfAdventureCastFromGraveyardEffect` + `GameState.temp_play_adventure_only` (Hildibrand: a `temp_play_permissions` entry that only covers the Adventure half from the graveyard until the end of your next turn). `PlayCardsExiledWithSourceEffect` + `turn_cost_reductions` ``object_ids`` (Urianger Augurelt: linked-exile play permission with a {2} discount only for those cards). `RemoveFromCombatEffect` (RULE 506.4), structured-selector scope ``attached_controller``, count selectors ``opponents_dealt_combat_damage_by_self_or_<subtype>_this_turn`` and ``players_who_lost_life_this_turn``, `sacrifice` selector ``each_opponent_who_lost_life_this_turn``, target kinds ``another_legendary_permanent_you_control`` and ``graveyard_instant``, `GameContext.exiled_objects` (``exiled_this_way`` for `grant_conditional_cast_from_exile`, Cane's {3} cast), `add_counters` ``group`` must be a structured selector (a bare string is silently dropped).
- **Files:** `game/binding/core.py`, `game/effects/{counters_tokens,choices_actions,game_status,attachments_transforms,life_sacrifice,registry,core}.py`, `game/{continuous,targeting,isa}.py`, `game/engine/{casting_mixin,legal_actions_mixin,turn_loop_mixin}.py`, `models/game/game_state.py`, `game/card_catalogue/…` (19 cards), `tests/game/catalogue/cards/test_scions_spellcraft_deck.py`.

### Granted Miracle, once-per-turn standing casts, type-slot free casts, stun lock (PLAY-ALL, Miracle Worker)

- **What:** `grant_miracle` static + `continuous.granted_miracle_cost_for` (`_arm_miracle` gives a drawn enchantment card Miracle at its mana cost minus {4}; the grant lapses at cleanup — Aminatou, Veil Piercer). "Once during each of your turns" for standing casts: `GameState.once_per_turn_grants_used`, ``once_per_turn`` on `granted_alt_cast_cost` (now also ``card_type`` and ``pay_life_equal_mv`` — Demon of Fate's Design) and on `free_cast_permission` (now also ``zones`` — One with the Multiverse). `aminatous_augury` (`AminatousAuguryEffect`) with `GameState.free_cast_type_pools` and `RulesEngine._consume_free_cast_type_slot`: one free cast per nonland card type from the exiled eight. `stun_counters_cant_be_removed` + `continuous.stun_counters_locked` (read by `set_tapped` before an untap spends a stun counter — Fear of Sleep Paralysis). `exile_top_of_library` ``position="bottom"`` and ``player_selector="each_opponent"`` with `grant_conditional_cast_from_exile` ``permanent_only``/``any_color`` (Arvinox: the standing exile permission keeps its `mana_wildcard_permission` past cleanup). `sacrifice_shared_type_to_return` (`SacrificeSharedTypeToReturnEffect`) and `return_remembered_graveyard_cards` ``exile_instead_of_leaving`` (Spirit-Sister's Call). `look_top_select` rest destination ``library_top_bottom`` (Telling Time), `grant_escape` ``card_type`` (The Master of Keys), `create_token` ``is_enchantment`` (Phenomenon Investigators' Horror), `control_count` over the ``not_owned_by_you`` filter for Arvinox's creature gate. Rooms keep the Experimental Lab simplification (casting is the single door unlocking; only the front half's text is cached).
- **Files:** `game/{continuous,isa}.py`, `game/effects/{registry,exile_control,returns_graveyards,game_status,counters_tokens}.py`, `game/rules/{casting_mixin,draw_discard_mixin,mana_counters_mixin,search_mixin}.py`, `game/engine/{casting_mixin,turn_loop_mixin}.py`, `models/game/game_state.py`, `services/token_database.py`, `game/card_catalogue/…` (20 cards), `tests/game/catalogue/cards/test_miracle_worker_deck.py`, `tests/test_isa_inventory.py` (continuation bound 95 → 97).

### Random graveyard returns, finality counters, graveyard-set choices, top-of-library sacrifice (PLAY-ALL, Death Toll)

- **What:** `return_from_graveyard` ``at_random`` (+ ``else_destination``): RULE 706 draws N matching cards from your graveyard with `random_choice` (Moldgraf Monstrosity, Deadbridge Chant). **Finality counters (RULE 122.1h):** `_move_to_graveyard` exiles a permanent with a ``finality`` counter instead. `repeat_process` ``repeat_while`` also takes an `effect_conditions` dict (Grist's +1); context conditions ``milled_cards_share_all_types`` and ``milled_subtype_this_way`` (``name: source`` also counts the source's own card). `trigger_quantities.matching_attackers` ``defender: "player"`` ("attack a player"), trigger predicate ``min_card_types`` ("a card with two or more card types", Rendmaw, over `SPELL_CAST` and `LAND_PLAYED`), `force_attack_unattacked_opponent` ``avoid_last_attacked=False``. **Winter, Cynical Opportunist:** `choose_objects` ``select_only`` selects a graveyard set, `exile_selected_then_return_one` judges "four or more card types among them", exiles it and offers `return_from_exile_finality`. `TopLibraryPermissionEffect` ``sacrifice_type`` (Into the Pit: the cast also sacrifices a nonland permanent, `GameEngine._top_library_sacrifice_victim`), `graveyard_cast_permission` ``plays_lands`` on the standing form (Titania). `destroy` ``optional`` targets compose with `moved_sum` (`pt_amount`) for Convert to Slime; ``distinct: card_type`` selectors and ``aggregate: max`` serve Carrion Grub/Deluge of Doom/Ursine Monstrosity. `ActivationCost`-style choices untouched.
- **Files:** `game/effects/{returns_graveyards,game_status,choices_actions,registry}.py`, `game/{effect_conditions,trigger_quantities,targeting}.py`, `game/rules/{damage_death_mixin,misc_mixin}.py`, `game/binding/core.py`, `game/engine/{casting_mixin,lands_mixin}.py`, `game/{top_library,isa}.py`, `game/card_catalogue/…` (19 cards), `tests/game/catalogue/cards/test_death_toll_deck.py`, `tests/test_isa_inventory.py` (continuation bound 97 → 98).

### Vehicles, Pilots, imprint-copies, exile costs (PLAY-ALL, Shorikai Vehicles)

- **What:** "Crews Vehicles as though its power were N greater" (`GameEngine._crew_power_of`, read off the creature's rules text; Saddle excluded), the `CREWED` event fired by every Crew ability (`CrewedEventEffect`, RULE 702.122e — Mobilizer Mech), target kinds ``vehicle``/``other_vehicle_you_control`` and `type_change` ``pt_selector: vehicle`` (the chosen Vehicle's own printed P/T — Mech Hangar, Peacewalker Colossus, Kotori's granted Crew 2 via `grant_activated_ability`). `_shared/pilot.py` (the Pilot token) and `_shared/vehicle_animation.py`. `ActivationCost.exile_others` ("Exile ~ and four other artifact creatures and/or Vehicles", `sacrifice_count`'s pool, recorded in `exiled_with_ids`), `return_all_exiled_with` ``tapped`` and `transfer_exiled_with_to_created` (Mechtitan Core; the token's leave trigger is the registered "Mechtitan" entry). `imprint` ``pool: graveyards`` and `become_copy_of_imprinted_until_eot` (Dermotaxi). The `UNTAP` event carries ``permanents_untapped`` (The Millennium Calendar). Protection from mana values (``protection_from_mana_values_among_artifacts``, ``mv:N`` qualities in `combat._quality_matches_type` — Rebbec). `of: attacked_player` land comparison, `no_untap` over ``all_creatures`` and `untap_each_untap_step` over ``artifacts_you_control`` (Intruder Alarm, Unwinding Clock).
- **Files:** `game/{costs,combat,continuous,targeting,isa}.py`, `game/engine/{activation_mixin,turn_loop_mixin}.py`, `game/binding/core.py`, `game/effects/{attachments_transforms,exile_control,registry}.py`, `models/game/events.py`, `game/card_catalogue/{_shared,…}` (21 cards), `tests/game/catalogue/cards/test_shorikai_vehicles_deck.py`, `tests/test_isa_inventory.py` (one-card residue 59 → 61).

### "If they don't", dealer subjects, life-lost-this-turn totals, suspend-from-resolution (PLAY-ALL, Endless Punishment)

- **What:** `optional` ``else_effects`` ("…may sacrifice it. If they don't, ~ deals 5 damage to that player" — Star Athlete, Enchanter's Bane), `damage` ``dealer_subject: previous_target`` (the targeted permanent deals the damage) and ``selector: random_opponent``. Count selector ``opponents_life_lost_this_turn`` (Florian, Rakdos), `cast_condition` key ``opponent_lost_life_this_turn`` (a `spec.py` whitelist key — behaviour-neutral, `PARSER_VERSION.lock` re-pinned), trigger predicate ``controllers_turn`` (the mirror of ``not_controllers_turn`` — Valgavoth). `impulsive_draw` ``rest_to_bottom`` (look at the top X, exile one, bury the rest), target kind ``player_other_than_event_player`` (The Lord of Pain), `choose_player_objects` ``start_with_next_opponent`` (Sadistic Shell Game), `GameObject.discarded_cost_card_types` + context condition ``discarded_cost_card_is`` (Grab the Prize), `exile_self_with_counters` (the resolving spell exiles itself with time counters — Suspended Sentence's own Suspend then runs).
- **Files:** `game/effects/{composition,damage_draw,library,exile_control,choices_actions,registry}.py`, `game/{effect_conditions,condition_query,continuous,targeting,isa}.py`, `game/rules/casting_mixin.py`, `game/engine/casting_mixin.py`, `game/binding/core.py`, `parser/oracle/spec.py`, `models/game/game_object.py`, `game/card_catalogue/…` (21 cards), `tests/game/catalogue/cards/test_endless_punishment_deck.py`, `tests/test_isa_inventory.py` (one-card residue 61 → 62).

### Mill replacement, Tiered, two-colour choice, capped X payment (PLAY-ALL, Hope to the last)

- **What:** `mill_replacement` (RULE 614.1/701.13 — "if an opponent would mill N, they mill N plus 4 instead", The Water Crystal) on a new pre-event `EventType.WOULD_MILL` that `RulesEngine.mill` now routes through `apply_replacements` (like `gain_life`; `_mill` is the old body). Tiered (RULE 702.183) is a Spree-shaped modal spell with exactly one mode: `modes["tiered"]` lets `mode_costs` sit on a plain "choose one" block (`spec.py`) and `GameEngine._modal_extra_cost` prices a single chosen (int) mode. `choose_color_on_enter` takes ``count`` (two prompts, the second excluding the first; `GameObject.chosen_colors`), read by the spell-filter key ``color_from_source_chosen_colors`` and the amount kind ``chosen_colors_shared_with_trigger_spell`` (Tablet of the Guilds). `pay_cost_then` ``x_cap_from_trigger_event`` caps the offered `{X}` by an event field (Well of Lost Dreams). Smaller primitives: `exile_all_graveyards` ``card_type``, `gain_life` ``selector: event_damaged_player`` (Angel of Destiny), `lose_game` ``players: attacked_by_source_this_turn``, `tap` ``untap_if_yours`` (untap what you control, tap the rest — Teferi), affects ``legendary_permanents_you_control`` (Thopteryx's ward grant) and the count selector ``creatures_you_attacked_with_this_turn`` (Minas Tirith); the "tapped unless you control a `<type>`" check (`_controls_check_type`, both `play_land` and its preview) now also reads card-type phrases ("a legendary creature" — Minas Tirith) over every permanent instead of treating the phrase as a land subtype, which had left it always tapped.
- **Files:** `game/effects/{replacements,registry,exile_control,life_sacrifice,choices_actions,counters_tokens,attachments_transforms}.py`, `game/rules/{draw_discard_mixin,casting_mixin,misc_mixin}.py`, `game/engine/casting_mixin.py`, `game/{continuous,combat,effect_amounts}.py`, `parser/oracle/spec.py`, `models/game/{events,game_object}.py`, `game/card_catalogue/…` (21 cards), `tests/game/catalogue/cards/test_hope_to_the_last_deck.py`.

### ENG-1: Re-Validate Attachment Legality Every SBA Pass

- **What:** RULE 704.5m/n (an illegally-attached Aura/Equipment) had only ever been checked when a host *left* the battlefield.
- **Files:** `game/rules/sba_mixin.py`, `game/combat.py`
- **Control is not part of legality (PAR-135):** the first version re-checked "a creature you control" every pass, so an Equipment fell off the moment its host changed controller — and a Magnetic-Theft-shaped attach to an opponent's creature would have been undone by the next SBA pass. CR 301.5b/301.5d say control matters only when the equip ability is activated and when it resolves. `_attachment_legal(check_control=…)`: the equip activation keeps `True`; `_revalidate_attachments` and a spell/ability that attaches pass `False`. `test_equipment_stays_attached_when_the_host_changes_control` replaces the test that pinned the old behaviour.

### Sacrifice a Chosen Number, Then "That Many" (MEC-103)

- **What:** "[you may] sacrifice up to N / any number of `<type>`. When you sacrifice one or more this way, `<payoff>`" (Ravenous Rotbelly, Nyssa of Traken) — new `sacrifice_chosen_then` effect (`SacrificeChosenThenEffect`, `game/effects/life_sacrifice.py`). The controller picks through the ordinary `choose_objects` chooser (untargeted, `continuous.matches_permanent_word` so a subtype word like "zombie" never falls through to "any permanent"); `RulesEngine._request_choose_objects` gained `then_that_many` (`{"effects", "trigger"}`), carried on the choice so it survives the undo `clone()`. When something was picked, `_apply_choose_objects_tail` binds the picked count into those specs' `"x"` sentinel — `_substitute_x_specs`, the same ENG-48 binder a paid `{X}` uses, no second sentinel — and queues `trigger` as a real RULE 603.12 reflexive trigger (`enqueue_reflexive_trigger`), so the payoff may itself target ("tap up to that many target creatures"). Nothing fires when nothing was sacrificed.
- **Parser:** `handlers._sacrifice_chosen_then` (`_SACRIFICE_CHOSEN_THEN_RE`). The payoff body is parsed by the ordinary `parse_effect_body` after "that many" is rewritten to a placeholder count, then mapped back to `"x"` (`_bind_that_many`); a payoff containing any other digit fails closed. PARSER_VERSION 517.
- **Radiant Lotus (hand-authored, `card_catalogue/r/radiant_lotus.py`):** "sacrifice one or more artifacts" is Grim Hireling's announced-X sacrifice cost (`costs.SACRIFICE_COUNT_X`), so "each artifact sacrificed" is X. `AddManaEffect` gained `any_amount_multiplier` (3 × X of one chosen colour) and `recipient="target_player"`; `"any_amount"` joined `casting_mixin._X_MAGNITUDE_ATTRS` (both substitution loops now read that one tuple). Simplification: X = 0 is not refused (the printed "one or more" minimum) — it only lets the Lotus be tapped for nothing.
- **Files:** `game/effects/life_sacrifice.py`, `game/effects/registry.py`, `game/effects/choices_actions.py`, `game/rules/misc_mixin.py`, `game/rules/casting_mixin.py`, `game/isa.py`, `parser/oracle/catalogue/handlers.py`, `parser/oracle/gate.py`; test `test_mec103_sacrifice_that_many.py`.

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

### "Target creature or planeswalker" keeps its planeswalker half (PAR-127, PARSER_VERSION 501)

- **What:** The shared TARGET rows mapped "target creature or planeswalker [you don't
  control | an opponent controls]" to `creature` / `creature_you_dont_control`, so 83
  parser-MODELED cards (Hero's Downfall, Dreadbore, Eliminate, Bite Down, the Charms …)
  could never target a planeswalker. They now resolve to `creature_or_planeswalker` and a
  new `creature_or_planeswalker_you_dont_control` frame; both apply the mana-value bound the
  plain `creature` branch did (Eliminate, Long Goodbye). For the verb whitelists the union
  is a narrowing of `permanent` (`subgrammars.SCOPED_TARGET_BASE`, the idiom
  `artifact_or_creature` uses) and the scoped kind is in `NOT_YOU_TARGET_KINDS`;
  `_DAMAGE_RECIPIENT_KINDS` admits it for the "bite" family.
- **Why:** A whole-cache spec diff showed 74 changed cards, every one a pure `target_kind`
  swap, and no coverage change — the first cut lost 38 cards to per-verb whitelists, which
  is why the base mapping matters. The 71 "SOLO" cards `parser_probe.py blocked "target
  creature or planeswalker"` reports were never blocked by the target phrase, only by
  riders in the same sentence.
- **Files:** `parser/oracle/catalogue/subgrammars.py`, `parser/oracle/catalogue/handlers.py`,
  `game/targeting.py`, `tests/test_par127_creature_or_planeswalker.py`

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
- **Generalised and parser-reachable (PAR-135, PARSER_VERSION 564):** `AttachChosenEffect` was hand-authored for Brass Squire/Halvar/Ardenn only. Its halves are now independent: `what_optional`/`what_count` ("up to one"/"any number of target Equipment"), `to_optional`, a destination `creature_filter` ("…to target attacking creature"), and `to_subject` for a destination that is not a target — `source` ("to ~"), `trigger_subject` ("to that creature" under a group trigger), `previous_target`, `attached_permanent` — the vocabulary `FightEffect` reads. The destination is the *last* pick, so a declined optional Equipment can't shift which pick is which. Oracle rows: `attach_chosen_to_target` plus a `_subject_handlers` table. "Target Equipment" became target kinds `equipment` and `equipment_you_dont_control` (frames, German labels, grammar rows, `NOT_YOU`/`THAT_PLAYER` scopes; deliberately *not* source-excluded). Magnetic Theft, Auriok Windwalker, Kor Outfitter, Iron Hills Stalwart, Kazuul's Toll Collector, Raubahn, Sokka and Suki, Armory Automaton, Super-Soldier Serum.

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

- **Parser extension (v598):** Divided damage accepts contiguous target-count
  lists, including “one, two, or three,” and preserves creature, flying,
  attacking, and attacking-or-blocking restrictions. Invalid lists fail closed.
  Integration tests cover spell casting and both entry and attack triggers.
  The existing automatic equal division remains a gameplay simplification.
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

### Storm triggers and cast-time spell counts (RULE 702.40)

Native storm and grants to instant/sorcery spells queue independent cast
triggers. Each captures the preceding spell count when the spell is cast;
responses and removal of the granting permanent do not change its copy count.
Copies use the existing spell-copy primitive and do not count as casts.

### Expend (RULE 700.14, MEC-107; PARSER_VERSION 553)

- **What:** Every `SPELL_CAST.mana_spent` payment contributes to a per-player total derived from
  the current turn's event log. A cast fires one `EXPEND` event for every threshold crossed by that
  payment; "Whenever you expend N" is a composed player-event head filtered to exactly N. Free
  casts contribute zero, totals reset naturally with the turn-event window, and thresholds are not
  capped to today's printed 4/8 values.
- **Why:** Deriving the total from the authoritative cast events avoids a second mutable counter and
  makes rewind/history behavior automatic. Tests: `tests/test_mec107_expend.py`.
- **Files:** `models/game/events.py`, `models/game/turn_history.py`, `models/game/game_state.py`,
  `game/rules/casting_mixin.py`, `game/binding/core.py`,
  `parser/oracle/catalogue/player_event_head.py`

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

### Intervening-if of a multi-sentence phase trigger gates the whole ability (RULE 603.4, PARSER_VERSION 501)

- **What:** "At the beginning of `<step>`, if `<state>`, A. Then B." used to carry the
  condition on A alone (the per-effect gate path), so B ran when the condition was false.
  When a phase trigger's body runs past its first sentence, a leading "if `<state>`," that
  `static_condition` reads now becomes the trigger's own ``active_if``; a one-sentence body
  keeps its per-effect gate (same outcome, no churn). 17 already-MODELED cards changed, each
  checked: e.g. Wary Zone Guard's "~ perpetually gets +1/+1" was ungated, Loyal Apprentice's
  haste grant, Marit Lage's Slumber, Planar Collapse, Tallyman of Nurgle, Ocelot Pride.
- **Files:** `parser/oracle/segmenter.py` (`_NEXT_SENTENCE_RE`),
  `tests/test_par112_for_each_object_copy.py`, `tests/test_par120_instead_override.py`

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

### One Damage Trigger Per Step Across All Opponents (MEC-104)

- **What:** "… deal(s) [combat] damage to **one or more of your opponents**" is one trigger for the whole simultaneous batch, whereas "to an opponent" fires once per opponent (RULE 603.2c). `_apply_combat_damage` still fires the MEC-29 aggregate once per (contributors' controller, player hit) pair but now stamps each with `hits` — `{target_id, ids, amounts}` for *every* player that controller damaged. A trigger head carrying `opponents_batch` (`object_trigger_head._damage_recipient`'s new "1 or more of your opponents" phrase) makes `binding.core._contributor_members` count the contributors across every opponent of the ability's controller, and `_contributor_condition` passes only the pair naming the first matching opponent, so the step's other pairs (and hits on the controller) don't refire. The per-ability capture also stamps `matching_opponents` — "the number of opponents dealt damage this way", exact even when a non-matching creature hit a different opponent.
- **Non-combat form (Molten Lavamancer):** a plain per-hit `DAMAGE` event has no batch to dedupe, so the phrase is only sound with "this ability triggers only once each turn" — `gate._opponents_batch_ok` fails closed for the `DAMAGE` form without the `limit` marker.
- **Cards:** Hordewing Skaab (`handlers._draw_opponents_damaged_discard`: `draw`/`discard` with `count_from_trigger_event="matching_opponents"`), Molten Lavamancer (parser), Nelly Borca (hand-authored `card_catalogue/n/nelly_borca_impulsive_accuser.py`; `GoadEffect` `selector="suspected_creatures"` for "goad all suspected creatures", `DrawCardEffect` `selector="event_player"` for "the controller of those creatures"). Per-creature "to an opponent" wording is unchanged.
- **Files:** `game/engine/combat_mixin.py`, `game/binding/core.py`, `game/effects/counters_tokens.py`, `game/effects/damage_draw.py`, `parser/oracle/catalogue/object_trigger_head.py`, `parser/oracle/catalogue/handlers.py`, `parser/oracle/gate.py`; tests `test_mec104_opponents_damage_batch.py`, `test_par119_combat_damage_batch.py`.

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

### Temporary Layer-6 Keyword Removal (MEC-105, RULE 613.1f / 514.2; PARSER_VERSION 554)

- **What:** `PumpEffect.removed_keywords` is the resolve-time mirror of a temporary keyword grant. It stamps `GameObject.temp_removed_keywords`; combat subtracts that set after printed, intrinsic, and granted keywords are combined, `continuous.recompute` preserves and traces it as an end-of-turn layer-6 change, and cleanup/new-object reset clears it. The pump path deliberately carries gains, P/T changes, and losses together, so “gains flying and loses trample” or “gets -2/+2 and loses flying” resolves against one recipient. Keyword loss is harmful target polarity for bot selection. The parser recognizes target/self/group-trigger/previous-subject forms plus attached-permanent standing “gets +N/+N and loses `<keyword>`”/bare loss through the existing `remove_keyword` static. Cache diff from v553: **+32 modeled, 0 regressed** (including Gravity Well, Barbed Foliage, Canopy Claws, Downdraft, Adarkar Windform, Canopy Dragon, and Starforged Sword).
- **Files:** `models/game/game_object.py`, `game/combat.py`, `game/continuous.py`, `game/engine/turn_loop_mixin.py`, `game/effects/counters_tokens.py`, `game/effects/registry.py`, `parser/oracle/catalogue/handlers.py`, `parser/oracle/catalogue/static_handlers.py`, `tests/test_mec105_temporary_keyword_loss.py`
- **Why:** A separate temporary removal set matches the existing `temp_keywords` lifetime and lets every established `PumpEffect` addressing mode work unchanged; mutating printed keywords would violate object identity and lose the change on a layer recompute.

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

### Scope adjectives are filters, not creature subtypes (PAR-134, PARSER_VERSION 555)

- **What:** `static_handlers._scope` turned any word before "creatures you control" into `subtype: "<Word>"`, so "Tapped / Untapped / Legendary / Nonlegendary / Nontoken / Multicolored / Commander creatures you control have/get …" granted to creatures of a subtype nobody has (38 wrong-but-MODELED cards; a scan of the whole MODELED set found 59 incl. the same word read as a subtype in "target legendary creature" pump/grant phrases and in coordinated lists). `subgrammars.scope_adjective` is now the one adjective vocabulary (`SCOPE_ADJECTIVES`: tapped/untapped/legendary/nonlegendary/nontoken/multicolored/colorless/snow/modified/nonattacking/commander/historic + `non<colour|type|subtype>` negations) and returns a `combat.matches_object_filter` fragment. `_scope` collects the fragments into `_Scope.filt`; `_scope_params` ships them as a static's `object_filter` param, `object_filter()` (target/blocker filters) merges them, and `resolve_target_creature_state_filter` — already the "target `<state>` creature" resolver — accepts the same words, which fixes `_pump_subtype_target`/`_grant_subtype_target` (Okina, Plaza of Heroes, Psychotic Fury, Ruthless Instincts, Ohran Yeti, Forerunner of Slaughter …) without touching them. A coordinated list ("Ninja and Rogue creatures", "snow and Zombie creatures", "green creatures and white creatures", "Saproling creatures and other Treefolk creatures") is an `any_of` of its parts (`_coordinated_scope`; a per-part "other" is `not_reference`); a list with a controller phrase inside fails closed (Rukarumel, Biologist — was wrong-but-MODELED, now honestly UNMODELED). "Commanders you control" is every *permanent* of the designation (`permanents_you_control`), since a planeswalker can be a commander.
- **Engine:** `continuous.group_selector_objects` applies `object_filter` through `combat.matches_object_filter(…, reference=src, state=state)` (`object_filter` is one more `registry._SELECTOR_KEYS` entry — every static factory that goes through `_selectors` keeps it; a factory that dropped it would *broaden* the effect, so a test pins anthem/grant_keyword/grant_protection_static). New filter keys: `modified` (RULE 700.9 — `continuous.is_modified`, which the `modified_creatures_you_control` count selector now shares; an Equipment counts whoever controls it, an Aura only under the permanent's controller) and a negative `attacking` (`False` = nonattacking, same idiom as `tapped`).
- **Why this shape:** one filter dict in the engine's existing object-characteristic vocabulary, instead of a new flat param per adjective (tapped/legendary/… each needing its own selector-key and factory plumbing); the negations and lists compose for free. Bonus: General's Enforcer and Kashi-Tribe Elite ("Legendary Humans/Snakes you control have …") newly MODELED correctly.
- **Files:** `parser/oracle/catalogue/static_handlers.py`, `parser/oracle/catalogue/subgrammars.py`, `game/continuous.py`, `game/combat.py`, `game/effects/registry.py`; tests `tests/test_par134_scope_adjectives.py`.

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

### MEC-109: Blitz (RULE 702.152, PARSER_VERSION 605)

- **What:** Printed and granted Blitz costs are separate cast choices, including mana, life and discard payments, commander taxes, additional costs and Henzie's commander-cast discount. Henzie's mana-value threshold includes announced X. Sabin and Tenacious Underdog can use Blitz from the graveyard; Blitz itself does not exile them.
- **Lifetime:** Paying Blitz grants haste and a dies/draw trigger to the resulting permanent, plus a respondable sacrifice trigger at the next end step. Zone changes clear the payment; the delayed sacrifice tracks that incarnation and cannot sacrifice an opponent's permanent. Spell copies retain the payment decision. Riveteers Provocateur uses the object chooser to grant perpetual Blitz.
- **Integration:** Parser handlers, executable IR, legal actions and the session API carry the selected Blitz instance. The board exposes distinct Blitz actions and preserves the choice through X, target and discard selection. `game/blitz.py` owns the mechanic; `tests/test_blitz.py` covers payments, grants, copies, ability loss and zone transitions.


### PAR-99: the targeted-spell tax — "Spells `<you|your opponents>` cast that target `<X>` cost …" (PARSER_VERSION 572, +5, 0 regressed)

- **What:** Monastery Siege's Dragons mode, Esior, Kasmina, Terror of the Peaks, Elderwood Scion's "spells you cast that target ~ cost {2} less". The ticket began as the Khans/Dragons Siege cycle; Batch 6 closed that cycle (and a lot besides), which left this tax as the only residue. One row (`static_handlers._SPELL_COST_TAX_THAT_TARGET_RE`) replaces the old opponents-only "that target ~" row with the same output for it, over two axes: **who** (you / your opponents → `affects`) and **what the tax is** (`{N}` more/less, or "an additional N life").
- **Target slot:** `~` stays `targets_source`. Anything else is an `if_targets` OR-list read by `continuous._spell_targets_hit` against the caster's chosen targets (RULE 601.2c precedes 601.2f): `{"player": "controller"}` ("you"), or a `_obj_matches_target_criteria` dict — `permanent: True` (battlefield only; a creature *spell* on the stack is not "a creature you control"), `card_type`, `is_commander`, and `controller: "source_controller"`, which is the *static's* controller, not the caster's (the existing `"you"` is caster-relative, for a discount printed on the spell). Vocabulary: "you", a card type, "commander(s)", "1 or more …", a trailing "you control" scoping every permanent alternative; any other word (a subtype, "enchanted creature", a bare "a permanent") fails the row closed. As with every mana tax here, the offer-time probe (no targets yet) leaves a tax off and a discount on.
- **Life tax:** `cost_reduction.life` is its own number, not generic mana — `cost_reduction_for` skips it, `continuous.cast_life_tax_for` sums it (same `affects`, target filters and `active_if`), `GameEngine._can_pay_cast_life_tax` gates `can_cast` at the common tail (so it covers alternative and free casts too; Yasharn forbids it, and life must cover it) and `_pay_cast_life_tax` pays it inside the additional-cost payment, so it stays paid if the spell is countered.
- **Named-choice gate:** `cost_reduction` joined `gate._NAMED_MODE_STATIC_EFFECTS` (it reads `active_if`), which is what lets Monastery Siege's Dragons bullet be claimed under its `chosen_mode` label.
- **Left open, per card:** Callaphe (a quoted static *granted* to a group: "creatures and enchantments you control have "spells your opponents cast that target this permanent cost {1} more""), Kopala ("abilities your opponents activate that target a merfolk you control cost {2} more to activate" — activation costs never see a target; `activation_cost_reduction_for` has no `targets`, and the spell half needs a subtype slot), Strong Back (same activation half, plus "enchanted creature" as a target). **Found, not fixed:** the segmenter claims a line that starts with "Equip" as a keyword line (`keyword_line=True`), so Strong Back's "Equip abilities you activate that target enchanted creature cost {3} less to activate." is silently swallowed rather than unclaimed — confirmed on the cache (PV 572): Bureau Headmaster, Bladehold War-Whip, Cloud Planet's Champion, Dwarven Mauler, Helitrooper, Plate Armor / A-Plate Armor and Warrior's Blades are `MODELED` with their Equip-cost discount line emitting no spec at all (Bureau Headmaster's only spec is the unrelated Equipment *spell* discount). Ticketed as BUG-1.
- **Files:** `parser/oracle/catalogue/static_handlers.py`, `gate.py` (PARSER_VERSION 572), `game/continuous.py`, `game/effects/registry.py`, `game/engine/casting_mixin.py`. Tests: `tests/test_par99_targeted_spell_tax.py` (parse, refusals, the five real cards modeled, executes: Kasmina scopes, a stack spell is not a permanent, Esior's commanders, the Siege under each label, Scion's discount, Terror's life payment / unaffordable / controller spared).

### Surge (RULE 702.117) — alternative cast cost after another spell (PARSER_VERSION 585, +3)

- **What:** "Surge {cost}" is a real cast option: `legal_actions` offers a second `cast_spell` entry (`surge: true`, `surge_cost_label`) next to the plain one, only while `spells_cast_this_turn` is above zero for the caster — read before the surge spell itself is cast, so it counts *other* spells. The surge cost replaces the mana cost (RULE 118.9, still subject to reductions and tax) and `GameEngine.cast_spell` stamps `GameObject.surge_cost_paid`, reassigned on every cast so a plain recast clears it. The flag is a `surge_cost_paid` condition beside `madness_cost_paid` (`effect_conditions`, `static_conditions`, `spec._ALLOWED_CONDITION_KEYS`, an announced flag). Parser: "When ~ enters, if its surge cost was paid, …" is the madness intervening-if row widened to `(madness|surge)`, and "if its / this spell's surge cost was paid" is a static-condition row (Reckless Bushwhacker, Tyrant of Valakut, Crush of Tentacles). Teammates (RULE 810) don't exist in the engine, so only the caster's own spells count.
- **Shape:** `surge` is threaded through `can_cast` / `effective_cast_cost` / `cast_spell` / `_cast_action` exactly like `evoke`; `services/game_session.py` round-trips the flag and `gameBoardView.js` carries it through every cast path (plain, X, targeted, discard-choice) with a ⚡ Surge label (`bd.cast.surge*`).
- **Left open:** Fall of the Titans (`x` damage "to each of up to 2 targets" is a separate gap). The UI still does not show the surge cost in the button label (`surge_cost_label` is on the action but unused).
- **Files:** `game/engine/casting_mixin.py` (`_surge_cost`, `_surge_enabled`), `game/engine/legal_actions_mixin.py`, `models/game/game_object.py`, `parser/oracle/segmenter.py`, `parser/oracle/catalogue/static_handlers.py`, `tests/test_surge.py`

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

### Gift (RULE 702.174, MEC-106; PARSER_VERSION 553)

- **What:** Casting a Gift spell now offers the ordinary cast plus one "promise a gift" cast per
  opponent. The chosen recipient and promised flag are stamped before targets are announced, so
  RULE 702.174m condition-only targets exist only on the promised branch. Instants/sorceries give
  the gift first as they resolve; permanents use a real intervening-if ETB trigger. Card, Food,
  Treasure, tapped Fish, extra-turn and Octopus gifts are implemented, and a successful gift emits
  `GIFT_GIVEN` for "Whenever you give a gift". Unknown joke-card qualities fail closed.
- **Parser/UI:** Prefix, suffix and `instead` promised-gift clauses share the normal condition/
  composition machinery; cast-decided conditions can select branch-specific target requirements.
  The board carries `gift_opponent_id` through X, discard-cost and multi-target flows and labels the
  recipient. The parser batch additionally covered the real Dewdrop Cure, Longstalk Brawl and
  Wildfire Howl clause shapes; the old hand-authored Into the Flood Maw simplification was removed.
- **Why:** Promise state belongs to the spell object beside Bargain/Kicker state, while giving the
  gift belongs at resolution/ETB; this preserves the countered-spell rule and keeps the keyword out
  of card-specific code. Tests: `tests/test_mec106_gift.py`,
  `tests/test_mec106_gift_real_cards.py`.
- **Files:** `game/engine/casting_mixin.py`, `game/engine/legal_actions_mixin.py`,
  `game/rules/casting_mixin.py`, `game/effect_conditions.py`, `game/effects/composition.py`,
  `game/binding/core.py`, `models/game/game_object.py`, `models/game/events.py`,
  `parser/oracle/`, `services/game_session.py`, `frontend/src/js/gameBoardView.js`

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
  - **War Room (PLAY-ALL Step 0):** "Pay life equal to the number of colors in your commanders' color identity" — `costs.PAY_LIFE_COMMANDER_COLORS` (-3), the third payment-time `pay_life` sentinel beside `PAY_LIFE_X`/`PAY_LIFE_HALF_UP`; the catalogue spec writes `"pay_life": "commander_colors"`. `activation_mixin._life_cost` is now an instance method (it reads `continuous.commander_color_identity`) and `can_activate` checks the *resolved* amount, not the raw sentinel. `mana_potential` now fails closed on any negative `pay_life` (it used to subtract a sentinel, i.e. *add* life, for half-life). Hand-authored `card_catalogue/w/war_room.py` (the `{T}: Add {C}` stays derived from the oracle text); tests `tests/test_war_room.py`. Not parser-reachable yet: the cost grammar (`cost_text.py`) has no matching row.
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

### Keyword counters (MEC-108, RULE 122.1b, PARSER_VERSION 556, +52 covered, 0 regressed)

- **What:** a `flying`/`first strike`/`double strike`/`deathtouch`/`haste`/`hexproof`/`indestructible`/`lifelink`/`menace`/`reach`/`shadow`/`trample`/`vigilance` counter makes its permanent gain that keyword. The reader is one layer-6 pass in `continuous.recompute` (`KEYWORD_COUNTER_SLUGS`, kind as printed → the underscore slug every other grant uses) that re-derives the grant from `obj.counters` each pass, so taking the last counter off takes the keyword straight back with no cleanup, and a `static_trace` line names "Keyword counter". `decayed`/`exalted` (also in 122.1b) are left out on purpose: nothing reads them as a combat keyword, so they stay fail-closed in the parser too. The parser's own copy of the list (`counters.KEYWORD_COUNTER_KINDS`; `parser/` may not import `game/`) is pinned to the engine's by a test.
- **Parser rows:** the thirteen kinds join `_NAMED_COUNTER_KINDS` (single, group and `remove all` forms for free); a compound list ("a +1/+1 counter and a lifelink counter on target creature", 2+ items) is one `add_counters` per kind — the first carries the recipient, later ones read it back (`previous_subject`), so one RULE 115 target serves the list, and `segmenter._stamp_counters_on_referent` now stamps a whole list of "…on it"; "remove a menace counter from ~" is `remove_counters` with a new exact-`count` (every other mode strips all); "enters with …" accepts a two-word kind and a compound (`extra_counters` on `entry_counters_condition`, placed in `_apply_entry_counters`); "return … to the battlefield with a `<keyword>`/+1/+1 counter on it" widens the old `-1/-1` rider onto the existing `return_from_graveyard.extra_counters`.
- **"Your choice of …":** two shapes, two mechanisms. *At resolution* (Assaultron Dominator, Inspirit): `AddCountersEffect.kind_options` (`[{kind, count}]` — options carry their own amount, "a +1/+1 counter or 2 charge counters") opens a `counter_kind` choice (`RulesEngine._request_counter_kind_choice`/`_resume_counter_kind`), which parks the effect, its gathered targets and the RULE 608.2 `previous_targets`, then runs a copy with the picked kind/amount — subject and target handling stay `AddCountersEffect`'s own. *As it enters* (Boot Nipper, Helica Glider, Wingfold Pteron, …): `ChooseEnterCounterReplacement` (`choose_enter_counter`, a sixth `enter_choice_effects` sibling next to choose-color/-type/…) is offered by `_offer_enter_choices` before the permanent joins the battlefield, so the counter is there when ENTERS_BATTLEFIELD fires. Like every entry in that family it is offered only on the hard-cast path (`_resolve_permanent_spell`); a card put onto the battlefield some other way (reanimated, flickered) enters without the pick — the same documented limit as "as ~ enters, choose a color". Both choices are mandatory (a bad answer takes the first option); the ISA continuation ceiling went 82 → 83 for `choose_enter_counter`.
- **Follow-up:** the residue this turned up (a non-targeted pick, negated counter conditions, the type-addition rider, remove-a-counter-then) is closed by PAR-140 below.
- **Files:** `game/continuous.py`, `game/effects/counters_tokens.py` (`AddCountersEffect.kind_options`, `RemoveCountersEffect.count`, `ChooseEnterCounterReplacement`), `game/effects/registry.py`, `game/binding/core.py`, `game/rules/casting_mixin.py`, `game/rules/mana_counters_mixin.py`, `game/rules_engine.py`, `game/isa.py`, `parser/oracle/catalogue/counters.py`, `handlers.py`, `static_handlers.py`, `parser/oracle/segmenter.py`, `frontend/src/js/gameBoardView.js` (choice icon). Tests: `tests/test_mec108_keyword_counters.py`.

### Counter-placement residue (PAR-140, PARSER_VERSION 557, +24 covered, 0 regressed)

- **A counter on "a creature you control"** (Blood Curdle, Ajani Fells the Godsire, Choking Miasma): not a RULE 115 target, so `AddCountersEffect` gained `choose_one` over the structured `group` selector the count-phrase grammar already produces ("another" is its `not_reference`). The controller picks at resolution (`RulesEngine._request_counter_recipient_choice` → `counter_recipient` choice, the `counter_kind` choice's sibling); exactly one eligible permanent is taken without asking, none does nothing, an opponent's creature is never offered. Own-side only ("you control") — "an opponent controls" stays unclaimed. Additional-cost and activation-cost spellings ("as an additional cost, put a -1/-1 counter on a creature you control", Wandering Mage) are *costs*, not this effect, and stay open.
- **Negated counter presence:** `static_conditions.source_counters` already had `max`; only the parser rows for "if ~/it doesn't have a `<kind>` counter on it" / "has no `<kind>` counters on it" (leading-if and "as long as" alike) were missing. The filter twin is `combat.matches_object_filter`'s new `without_counter_kind` (next to `has_counter_kind`/`no_counters`), read by `characteristic_phrase`'s "without …" tail; the mass destroy/exile/return rows' group character class had no `+`/digits, so no "+1/+1" qualifier could ever reach the shared noun-phrase grammar (Wave Goodbye; it also unlocked Granulate and the threshold-power exile wipes). A **targeted** spelling ("target creature you control that doesn't have a +1/+1 counter on it") has no quality slot in `TARGET` — open.
- **"It becomes a `<type>` in addition to its other types"** (Butch DeLoria, Beorn the Fierce, Origin of Spider-Man; also Memnarch, Myr Landshaper, Liquimetal Coating, Sealock Monster): one `grant_until` over a layer-4 `type_change` (`add_types`/`add_subtypes`/`legendary`), duration "until end of turn" → `end_of_turn`, none → `rest_of_game` (RULE 611.2a, the same permanent-animation idiom Earthbend uses, with the same limit: the effect names the object by id and lapses when the permanent leaves). Subtype words come from the full generated vocabulary (`subtype_vocabulary.SUBTYPES`), card types from a four-word set; an unknown word fails the clause closed. The pronoun row is `previous_subject_only`; "~"/"target …" name their subject and need no gate. A clause that also sets P/T or adds abilities is the animation family (see PAR-142), not this row.
- **"You may remove a `<kind>` counter from ~/it. When/If you do, …"** (Kappa Tech-Wrecker, Forgehammer Centurion, Lattice-Blade Mantis, Sun Droplet, Purestrain Genestealer): a new cost alternative in `_MAY_COST_THEN_CLAUSE`, so the existing `pay_cost_then` machinery runs it; `_can_pay_player_cost`/`_pay_player_cost` take an optional `source` and charge `ActivationCost.remove_counters` off it (`_source_counter_removal`: fixed count only; the X/any-number sentinels stay unpayable; "a counter" of no kind takes the source's first kind — documented simplification). Ward and the other pay-or-else callers pass no source and behave as before. Under a group trigger "it" is the firing object, so that spelling is refused.
- **Files:** `game/effects/counters_tokens.py`, `game/effects/registry.py`, `game/rules/mana_counters_mixin.py`, `game/rules/misc_mixin.py`, `game/rules_engine.py`, `game/combat.py`, `parser/oracle/catalogue/handlers.py`, `static_handlers.py`, `characteristic_phrase.py`. Tests: `tests/test_par140_counter_placement_residue.py`.

### Target quality and adjective slots (PAR-141, PARSER_VERSION 558–560)

- **Two slots on `subgrammars.TARGET`, not a row per phrase.** A *quality* after the noun ("target creature **without flying**", "…you control **that doesn't have a +1/+1 counter on it**", "…**that's attacking you**") and an *adjective* before it ("target **nontoken** creature", "**legendary**", "**non-Human**", "**Zombie**", "**black**", "**artifact** creature", "**nonattacking**"). The vocabulary is shared: `characteristic_phrase.parse_absent_quality` (keyword words, counter kinds), `SCOPE_ADJECTIVES`/`scope_adjective` (moved above `_TARGET_ROWS`), colours, card types and the generated subtype list; one slot of each kind per phrase, either side of a scope tail ("without flying you don't control"). `resolve_target_kind` drops the slot and only for the creature pools whose `TargetFrame` applies `creature_filter`; `resolve_target_creature_state_filter` reads it back as a `combat.matches_object_filter` fragment, so every handler that already merged the combat-state adjective gets it for free (~93 cards: Coiling Stalker, Defenestrate, Roast, Cast Down, Hero's Demise, Glorybringer, Kiki-Jiki, Snow Fortress …).
- **Fail-closed in one place.** v409's lesson — a qualifier `resolve_target_kind` discards silently widens a clause to every creature — is enforced by `handlers.EffectHandler.match` (`_target_qualities_kept`): a row whose matched `target`/`target_*` group carries a slot no spec's `creature_filter` holds is refused, for all `{TARGET}` handlers at once. An adjective with no filter reading ("nonbasic" — a supertype negation that `scope_adjective` would make a bogus subtype) makes `resolve_target_kind` return ``None`` rather than drop it. The adjective slot exposed two latent defects, both fixed: "nonsnow" became a *subtype* filter (snow is a supertype — new `without_snow` key) and `attacking: False` ("nonattacking", Alarum) was never enforced by the target pool (`targeting._creature_matches_filter` now treats the key structurally). "that's attacking you" is `attacking_you`: the creature's `combat_defender` is the ability controller (RULE 506.2). "Exile ~ and target …" (Hunting Kavu, Giant Trap Door Spider, Mangara) is its own two-spec row.
- **Conditions.** A conjunction of state predicates ("if you haven't cast a spell from your hand this turn **and** ~ doesn't have a flying counter on it") is the AND twin of the existing "or" split in `static_condition` — both halves must resolve (Inventive Wingsmith, Creakwood Safewright, Incisor Steed). "~ isn't a creature" is the `not` combinator over `is_card_type` (Emergent Haunting, Answered Prayers); a phase trigger's intervening-if that names `~` gives a bare "it" in its body that antecedent. A host pronoun in an Aura's "as long as it's blocking and …" now reads the *enchanted creature*, not the Aura (`_pronoun_attached_condition`, Snow Devil — the old reading would never have held). The trigger head "whenever combat damage is dealt to you" is the passive spelling of "you're dealt combat damage" (Risona).
- **Olivia-shaped compounds.** A comma before a pronoun-led effect clause is a sentence boundary (`_PRONOUN_COMMA_CONNECTOR`) — never across an "if you do" gate, where it would leave the later clauses outside it; `_remembered_group_referent` now also rewrites the granted-haste effect so all three clauses run inside the payment.
- **Last-known information of a dying object (RULE 603.10a/608.2h, PARSER_VERSION 561).** "When ~ dies, if it was a creature / wasn't a Demon, …" (Weatherseed Totem, Infernal Vessel) read `previous_target` — a pick no clause had made — so the gate never held and the card silently never acted (wrong-but-MODELED; first failed closed in v560). The engine side: the DIES event's ``subtypes`` snapshot is now the *derived* set (`continuous.derived_subtype_words`: printed plus layer-added, or the RULE 613.5 overwrite), the LEAVES_BATTLEFIELD event gained ``subtypes``/``colors``, and a new condition kind `trigger_event_object` (``card_type``/``subtype``/``color``, `effect_conditions`) reads ``object_types``/``subtypes``/``colors`` off the firing event — unanswerable without a snapshot, so it fails closed. The parser side: `segmenter._rescope_self_pronoun_condition` turns a pronoun gate under a *self-subject* trigger into the source itself (present tense) or the snapshot (past tense "was/wasn't"). Execution-tested: Infernal Vessel returns once with two counters as a Demon and stays dead the second time; the Totem returns to hand only if it died animated.
- **Files:** `parser/oracle/catalogue/subgrammars.py`, `characteristic_phrase.py`, `handlers.py`, `static_handlers.py`, `player_event_head.py`, `segmenter.py`, `game/targeting.py`, `game/combat.py`. Tests: `tests/test_par141_target_quality.py`, `tests/test_par141_142_residue.py`.

### Type-addition family (PAR-142, PARSER_VERSION 558–560)

- **Attached permanents** (Dub, Call to Serve, Raven Wings, Samurai's Katana, Ninja's Blades, Silverskin Armor, Ensoul Artifact, Mightstone's Animation, Angelic Armaments, Blade of the Oni, Draconic Destiny): `static_handlers._ATTACHED_TYPE_ADDITION_RE` composes the parts those cards recombine — base P/T, anthem, keyword grant, added colours (layer 5, "…other colors and types"), a layer-4 `type_change` (RULE 205.1b, with a base P/T, RULE 613.4b/7b) and a quoted-ability grant; a second sentence that only adds a type ("It's a Dragon in addition …") rides the first. `type_addition_params` is the single reader of the type words (card types, "legendary", the subtype vocabulary; an unknown word fails the clause closed) and is shared by every row below. "enchanted artifact" joined `_ATTACHED_SUBJECTS`. **Group statics** ("creature tokens you control are Squirrels …", "nontoken creatures you control are Forest lands …") are the literal-word sibling of the chosen-type row; `_chosen_type_group_affects` now forwards `tokens`/`color`/`card_type` (it used to drop them, widening the grant to every creature) and fails closed for an attacking/permanent scope.
- **One-shot "becomes / it's".** `becomes_in_addition` takes a base P/T ("a 4/4 Illusion creature"), "with `<keywords>`" and "and gains `<keyword>`", on "~", "it" (after a counter on the source — `_puts_counter_on_source` — or a pick), "that land/creature/permanent" and the "it's a Spirit in addition" rider after a put/return (Call a Surprise Witness). `ReturnSelfToBattlefieldEffect` hands the returned permanent to the next clause and takes "with 2 +1/+1 counters on it".
- **"… for as long as it has a `<counter>` counter on it"** (Aquitect's Will, Minas Morgul): not a clause of its own — `segmenter._for_as_long_as_counter_specs` re-times the `grant_until` its body parsed to (RULE 611.2b, `game/durations.py`, condition read off the locked permanent via `of="affected"`); anything that isn't a duration effect fails closed. New bodies: the bare lockdown ("it doesn't untap during its controller's untap step") and a previous-pick base P/T ("that creature has base power and toughness 3/1 and has flying").
- **Copy riders.** *Token copies* (`create a token that's a copy of …, except …`): `CopyPermanentEffect` gained `creature_filter` (Kiki-Jiki's "nonlegendary"), `legendary`, and the tail vocabulary now reads enchantment/land additions, "it's legendary", dropped-subject pieces ("…and is a mutant in addition"), an optional comma before "except", and the granted end-step clause ('it has haste and "at the beginning of the end step, sacrifice ~"' → haste plus the same delayed trigger the sentence form emits — Minion Reflector, Kindle the Inner Flame, Electroduplicate, Heat Shimmer). *Enter as a copy* (`static_handlers.enter_as_copy_specs`): "you may have ~ enter as a copy of any creature/artifact/land/permanent … on the battlefield[, except …]" onto the engine's `EnterAsCopyReplacement` (Clone, Copy Land, Glasspool/Mirrorhall Mimic …), which gained `not_legendary` (threaded through `become_copy` → `Card.as_copy`; `card.py` untouched). *Becomes a copy* ("~ becomes a copy of [another] target creature/permanent[ until end of turn][, except it has this ability …]"): `BecomeCopy*Effect` gained the exception params and `keep_own_abilities` (RULE 707.2 would erase the ability that does the copying; Cryptoplasm, Artisan of Forms).
- **Left as plain long-tail (each needs a different primitive, none a ticket):** a granted *quoted* ability under a counter duration (Obsidian Fireheart, Makeshift Mannequin, Mathas, Olinda — `PAR-102`'s quoted-tail grant is the shared gap); "perpetually" (Alchemy — a permanent, zone-surviving modification); the plural rider after a group return ("they're Zombies in addition …", Afterlife from the Loam, Ghouls' Night Out — the returned set is not a target list); copy tails naming a *quoted* ability, a name override ("his name is ~"), a counter duration ("until your next turn") or `toxic 1` (Kinzu); a graveyard pool for the copy (Activated Sleeper, Echoing Deeps); "it becomes a copy of that card" after an exile (Dimir Doppelganger); Xira's persistent "when that creature dies, if it has an egg counter on it" watcher; Vengeful Pharaoh's two-headed graveyard trigger; Abuelo's Awakening ("artifact or non-Aura enchantment card" + "X additional counters" + the rider); Aven Mimeomancer ("feather" counters on a creature).
- **Files:** `parser/oracle/catalogue/static_handlers.py`, `handlers.py`, `segmenter.py`, `game/effects/counters_tokens.py`, `registry.py`, `core.py`, `game/rules/copies_mixin.py`, `casting_mixin.py`, `game/copy_mechanics.py`. Tests: `tests/test_par141_142_residue.py`, `tests/test_par141_target_quality.py`.

### Graveyard returns: tapped / attacking, the untargeted pick, the typed mass (PAR-143, PARSER_VERSION 559, +52 covered, 0 regressed)

- **Enters tapped [and attacking]:** "return … from your graveyard to the battlefield tapped [and attacking]" on the targeted row, the self row ("this card"/"~", Narfi, Chronosavant, Interceptor) and the new rows below. `ReturnFromGraveyardEffect` now passes ``battlefield_tapped`` to `return_from_graveyard` instead of tapping afterwards (RULE 110.5b — an enters-the-battlefield trigger sees it tapped), and ``attacking`` reuses `put_onto_battlefield_attacking` (RULE 508.4, the tapped-and-attacking token primitive). The self effect also takes the "with N +1/+1 counters on it" rider (Retrofitted Transmogrant, Phoenix Chick).
- **Untargeted pick** ("[you may] return a land card from your graveyard to the battlefield tapped / your hand", "put a land card from a graveyard onto the battlefield tapped under your control" — Blossoming Tortoise, Deeproot Wayfinder, Soul of Windgrace): `ReturnFromGraveyardEffect.pick`. The pool is `targeting.legal_targets` over the effect's own private spec, offered through `_request_choose_objects` (two new chooser actions, `return_from_graveyard_tapped`/`return_from_graveyard_to_hand`); one candidate is taken without asking, none does nothing. A pick or a mass return announces **no** target spec, so the spell can be cast with nothing in the graveyard — the targeted spelling needs a legal target, this one does not.
- **Typed mass** ("return all land cards from your graveyard to the battlefield tapped", Aftermath Analyst, Lumra): the mass row took the graveyard type vocabulary instead of "creature" only, filtered by `targeting.graveyard_card_matches`.
- **Power cap:** "with power 2 or less" (Alesha) rides the same slot as the mana-value cap, as a `creature_filter` the graveyard branch of `legal_targets` now honours.
- **Still unclaimed (each needs something else, not this modifier):** a finality counter (39 cards cache-wide — the counter and its "exile instead of dying" replacement are not modelled), "lesser mana value" (Havi, Riveteers Ascendancy), a granted quoted ability or perpetual rider on the returned card, a subtype-worded target ("phoenix card"), and "up to two … then up to two …" compounds.
- **Files:** `game/effects/returns_graveyards.py`, `attachments_transforms.py`, `registry.py`, `game/targeting.py`, `game/rules/misc_mixin.py`, `parser/oracle/catalogue/handlers.py`. Tests: `tests/test_par143_graveyard_return_tapped.py`.

### Counter/Token-Creation Count-Amount Resolver Wiring (MEC-27)

- **What:** `AddCountersEffect` gained `amount_from_count_selector` (mirroring `DealDamageEffect`) with a new `add_counters_devotion` parser row for "put X counters on `<ta…
- **Files:** `game/effects/core.py`, `parser/oracle/catalogue/handlers.py`.

### Named counters as an open axis, shield counters, asymmetric P/T counters (PAR-135, PARSER_VERSION 564)

- **What:** `_NAMED_COUNTER_KINDS` was a closed list of the tracker words printed so far, so every set's next counter ("stun", "shield", "feather", "bloodstain", "globe") was a new row and "put a stun counter on target creature" — or three of them — was unclaimed. The kind is now `_NAMED_COUNTER_KIND`: any word minus `_RESERVED_COUNTER_KINDS` (the names the engine itself keys off — `time`/`age`/`fade`/`level`/`loyalty`/`lore`/`defense`, the player counters `rad`/`energy`/`experience`/`poison`, the unread keyword counters `decayed`/`exalted`, `finality`, `ticket`). Every row that shared the old vocabulary (single, group, "a creature you control", compound list, "your choice of", `remove`) reads it, and `tests/test_par135_named_counters.py` scans `game/` for counter-kind literals so a *new* engine reader fails the suite until it is reserved or declared generically fed.
- **Shield counters (RULE 122.1c) are now enforced** — claiming a counter the engine ignores would have been a card that parses and does nothing. `deal_damage`'s resolved-recipient step removes one counter and prevents the whole damage event (before infect/wither, loyalty/defense loss or the DAMAGE event); `RulesEngine.destroy(by_effect=True)` replaces destruction "as the result of an effect" and sits ahead of the "can't be regenerated" opt-out, while the RULE 704.5g lethal-damage SBA passes `by_effect=False` because a shield counter doesn't guard that. Stun already had its replacement (`set_tapped`); the tap-and-stun handler had only the singular, targetless spelling, so "put 3 stun counters on it", "…on that creature" and the targeted form were the gap.
- **Asymmetric P/T counters:** the shared "±N/±N" counter token matched "+0/+1" and read it as a +1/+1 counter (Coral Reef, Shield Sphere, Armor Thrull, Spirit Shackle were wrong-but-MODELED — the creature gained power it never had). The token is now `_PT_COUNTER_TOKEN`; a symmetric "+2/+2" stays N × ±1/±1, an asymmetric one is its own counter kind spelled "+0/+1", and layer 7c (`continuous.py`, `_PT_COUNTER_KIND_RE`) adds each such counter's own delta.
- **Two bugs the newly parsed cards exposed:** "has two **or fewer** judgment counters" was read as a counter *named* "or fewer judgment" with a lower bound of 2 (Faithbound Judge), and the kindless "has four **or more** counters on it" as a counter named "or more" — a condition that never held (Gavel of the Righteous and Warden of the Inner Sky had been MODELED with a dead static). Both are now `source_counters` `max`/`min` (the kindless form counts every kind). And Shackle Slinger's "if it's tapped" after a targeting clause gated on the *source's* tapped state; `segmenter._peel_condition` now rescopes a pronoun condition after a pick to `of: previous_target`.
- **Kitnap:** "tap enchanted creature … put three stun counters on **it**" — a tap of the Aura's host now leaves it in `previous_targets` (`TapEffect` attached mode) and `_announces_creature_target` counts it, so the counters land on the creature, not the Aura.
- **Files:** `parser/oracle/catalogue/handlers.py` (`_NAMED_COUNTER_KIND`, `_RESERVED_COUNTER_KINDS`, `_PT_COUNTER_TOKEN`, `_counter_kind_and_multiplier`), `static_handlers.py`, `segmenter.py`, `game/rules/damage_death_mixin.py`, `sba_mixin.py`, `game/continuous.py`, `game/effects/attachments_transforms.py`. Tests: `tests/test_par135_named_counters.py`.
- **Still unclaimed, and why:** Lulu's "choose target creature attacking you. Put a stun counter on **that creature**" (a pronoun after a *choose* clause), Protection Magic's "on each of up to N target creatures" (a multi-target named counter), Shield Broker's control-for-as-long-as-it-has-a-counter — each needs a different grammar than a counter kind.

## Card Types & Structures

### Choices and counters before entry; legendary spell casting

The entry-player chooser can include the entering permanent's controller;
the choice is made before characteristic-defining abilities and state-based
actions inspect the permanent. Conditional creature-entry bonus counters are
applied before the entry event, after entry-copy choices. RULE 205.4e's casting
restriction applies to all legendary instant and sorcery spells, independently
of their reminder text or catalogue entry.

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

### MEC-110: Empower Jace (RULE 701.71)

- **What:** `empower_jace` creates the nonlegendary blue Jace planeswalker token at zero loyalty if no Jace planeswalker token is controlled, then places N loyalty counters on one chosen token. Token copies of other Jaces qualify; printed Jaces, nonplaneswalker tokens and opponents' tokens do not. Token/counter replacements and an interactive choice between multiple tokens run within the same resolution, before SBAs. The token's −1 surveil and −3 draw are ordinary bound loyalty abilities, including timing, costs and the once-per-turn limit. Numeric and X quantities use the shared parser and amount grammar (PARSER_VERSION 593; +18 covered cards, no parser regressions).
- **Files / tests:** `game/effects/counters_tokens.py`, `game/rules/misc_mixin.py`, `services/token_database.py`, `services/deck_tokens.py`, `parser/oracle/catalogue/handlers.py`, `tests/test_empower_jace.py`. Token art follows the existing art library/player-upload fallback; deck preloading includes Jace. Replay preserves the token's text, characteristics and loyalty.
- **Related correction:** `game/rules/casting_mixin.py` now skips the whole resolving item when all announced targets have left their required zones, so Academic Ascent cannot empower after its only target leaves. Stack targets and graveyard targets use their respective zones. This zone check does not expand characteristic-based target revalidation.
- **Rule source:** The repository's August 2026 CR predates Empower; [Reality Fracture release notes](https://magic.wizards.com/en/news/feature/reality-fracture-release-notes) and [update bulletin](https://www.magic.wizards.com/en/news/announcements/reality-fracture-update-bulletin) define the action and assign RULE 701.71.
- **Validation:** Full backend suite with `--full-cache`: 11,088 passed; expanded Empower/token-art tests: 32 passed. Ledger coverage at v593: 20,305 / 35,046 overall; 19,539 / 32,068 Commander-legal.

### PAR-111: Exploit as a real mechanic, and the small ETB residue (PARSER_VERSION 573, +27, 0 regressed)

- **Exploit (RULE 702.110):** the keyword was parser-recognised only — no ETB sacrifice happened, and 26 cards were blocked on "when ~ exploits a creature". Now `_kw_exploit` (`binding/core._KEYWORD_TRIGGERED_BUILDERS`) binds its own ETB trigger → `ExploitEffect` → the generic chooser with a new `exploit` action (an optional pick among *your* creatures, the exploiter included). The action sacrifices and fires **`EventType.EXPLOITS`** (RULE 702.110b: ``instance_id`` = the exploiter, ``related_ids`` = the sacrificed creature); a creature that sacrifices *itself* fires it first, so its own trigger still goes on the stack. The trigger head is `object_trigger_head._parse_exploit_head` ("~ / a creature you control exploits a `<kind>` creature"; the kind rides as the same ``related_filter`` the block-relation head uses, "any creature" adds nothing). **A grant of exploit ("have exploit") stays unclaimed on purpose** (`keywords.UNGRANTABLE_FLAG_KEYWORDS`, both flag-keyword grant paths): a granted flag keyword adds the slug and none of the trigger. ISA: `exploit` is one new instruction (RULE 702.110).
- **"you may have that player lose N life"** (Blood Seeker, Suture Priest): `_peel_optional` takes the "you may" off, so it is the group-subject `lose_life` row with the entering creature's controller (`_ENTERING_CONTROLLER`) as the player; the answer is "do"/"decline".
- **"attach it to target legendary creature you control"** (Mithril Coat; also Rosethorn Halberd's non-Human): the destination's qualifier rides on `attach` as `creature_filter`, the same field Equip-restricted-to-commanders already used.
- **"manifest dread, then attach ~ to that creature"** (Conductive Machete, Cursed Windbreaker, Dissection Tools, Killer's Mask): `manifest_dread` + `attach(target_kind="created")`. The look-at-two choice suspends the resolution, so `_resume_manifest_dread` hands the manifested permanent to the *parked remainder* (`deferred_depth` on the choice → that frame's `created_objects`); a one-card library manifests at once and `ManifestDreadEffect` records it directly.
- **Dropped from the ticket:** Enduring Friendship's Double team is an Alchemy keyword (conjure) — a permanent non-goal. Mjölnir's second ability ("deals damage to each opponent equal to the number of tapped creatures that opponent controls") is a per-opponent count-damage cluster of its own (Stormbreath Dragon, Treacherous Terrain, Typhoon + Mjölnir), not a trigger-head gap.
- **Left open, per card (exploit):** Colonel Autumn and Henry Wu (a *granted* exploit — needs a granted-trigger path for a flag keyword; Henry's "if the exploited creature had power 3 or greater" also needs the sacrificed creature's last-known power on the event), Profaner of the Dead (the exploited creature's toughness), Silumgar Scavenger ("if it exploited that creature"), Diver Skaab, Graf Reaver, Overcharged Amalgam (their own bodies).
- **Found, not fixed:** "target player draws N cards **and loses N life**" in a *triggered* ability makes the controller lose the life (the `lose_life` carries no player and the trigger hands its targets only to the effect that declared one; as a spell the shared target list hides it) — Fell Stinger is newly `MODELED` with it; Vault Plunderer, Bloodgift Demon, Unscrupulous Contractor already were. Ticketed as BUG-2.
- **Files:** `models/game/events.py` (`EXPLOITS`), `game/rules/misc_mixin.py` (the `exploit` action), `game/rules/copies_mixin.py`, `game/effects/{counters_tokens,core,registry}.py`, `game/binding/core.py`, `game/isa.py`, `parser/oracle/catalogue/{object_trigger_head,handlers,static_handlers,keywords}.py`, `gate.py` (PARSER_VERSION 573). Tests: `tests/test_par111_residue.py` (heads and refusals, a grant stays unclaimed, execute: sacrifice → trigger, decline, self-sacrifice, only your creatures offered, a group trigger reading the victim's type, the event payload; Blood Seeker yes/no/own creature; Mithril Coat and Halberd offer only legal destinations; manifest dread then attach with and without the pause).

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
- **Fail-closed on an unmodeled body (PAR-129, PARSER_VERSION 555):** `_segment_keyword_labeled_ability` used to fall back, for a comma-free `<keyword> — <body>` line whose body didn't parse, to `is_keyword_line`'s greedy `_KEYWORD_TOKEN_RE` — an inert keyword-line claim, so the card was MODELED with the whole labelled ability missing (23 cards across Exhaust/Power-up/Boast/Max speed: Mai, Liliana the Repentant, Redshift, Captain Marvel, Kang, …). The ticket blamed the card-level keyword pass and said the lines "segment correctly alone"; measured, that held only for bodies that parse (Audacious Knuckleblade's two other lines) — the listed cards' bodies were unmodeled, and the inert claim hid it. The fallback is gone: such a line is unclaimed, the card UNMODELED, and its body is an ordinary clause the ranking sees (keyword-counter bodies — "put a flying counter on …", no layer reader — are the biggest such cluster, 124 cards).
- **Exhaust mana ability:** "Exhaust — {G}, {T}: Add three mana of any one color." (Loot, the Pathfinder) went through `mana_abilities.py` with no once-per-game cap. `ActivationCost.once_per_game` (set by the "Exhaust —"/"Power-up —" label in `_parse_mana_ability_lines`), tracked like `once_per_turn` by ability index on `GameObject.mana_abilities_used_this_game`; `mana_abilities_for` blanks a spent ability's `options` (index-stable, so every consumer — legal actions, auto-tap planning — stops offering it). `reset_as_new_object` (RULE 400.7) now also clears it and `used_once_per_game_abilities`. Tests: `tests/test_par129_labeled_keyword_fail_closed.py`.


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

### Ophidian Eye: stale attachment predicates after rollback

- Attachment trigger predicates previously captured an Aura/Equipment object directly. `GameState.clone()` deep-copies objects but retains callback functions, so after rollback the callback could still read an old Aura with no attachment while the live Aura was correctly attached. Predicates for attached and self-or-attached subjects now look up their source by instance ID in the current context state.
- Regression coverage reproduces the missing Ophidian Eye trigger after both direct state cloning and the real failed-action rollback path (`tests/test_ophidian_eye_trigger.py`).

### Replay attachment round-trip

- Exported object descriptors now include their original `instance_id`. Import rebuilds every object, then remaps numeric Aura/Equipment attachment references to the new IDs. Player-targeting Auras retain their player IDs. Legacy exports without object IDs cannot recover their original attachment mapping. Covered by `tests/test_replay.py`, including duplicate creature names and Ophidian Eye triggering after import.

### Malcolm: noncombat Pirate damage, including Kediss

- Malcolm's previous combat-only approximation now also handles noncombat damage. The existing combat contributor path remains; a `DAMAGE` batch handles noncombat damage and captures the number of distinct opponents hit by controlled Pirates. `DealDamageEffect` groups one instruction's recipients into a simultaneous batch.
- Regression coverage includes multiple Pirates hitting the same opponent, Kediss preserving the commander's damage source, and both commanders attacking with Ophidian Eye on Kediss: three Treasures and three optional draws against three opponents (`tests/test_malcolm_noncombat_damage.py`).


### Cleanup discard selection (RULE 514.1)

- End-of-turn hand-size enforcement now uses the existing discard chooser instead of automatically removing the last hand cards. Cleanup waits for every required pick before clearing damage and effects that last until end of turn. The suspension survives undo through `GameState.cleanup_discard_pending`.
- Goldfish decision advancement and shared-game priority advancement stop for the choice; shared games continue to the next priority window after the final pick. Maximum hand sizes below zero are treated as zero.
- Regression coverage: `tests/services/test_game_session.py` and `tests/test_batch8_permission_statics_family.py`.

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

### Session table feed (VIS-4)

- **What:** `TableFeed` retains the latest 200 emotes and public action announcements in session views, including reconnects. Emotes use a fixed server-validated allowlist and canonical seat identity, leave game state/history unchanged and broadcast without driving bots. Announcements derive from accepted engine events, including automatic mana payments and free casts during resolution, while preserving face-down identities. Hand mana abilities emit a separate event because they resolve without the stack (RULE 605.3b). Undo removes announcements for undone moves while retaining emotes; restart clears the feed.
- **Files:** `services/table_feed.py`, `services/game_session.py`, `api/multiplayer.py`, `models/game/events.py`, `game/engine/mana_mixin.py`.
- **Validation:** Service/API regressions cover emote validation, shared views, observer restrictions, undo, concealed spells and mana/free-cast announcements; full-cache backend suite and Chromium board interaction passed.

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

- Opening-hand permissions (RULE 103.6) are accepted by every bot policy. Gemstone Caverns' mandatory hand-card exile completes through legal choice offers; Smart/AI preserve higher-value cards and combo pieces. AI handles pregame choices without an LLM call. Regression coverage exercises all five policies through Solo polling and verifies human choices remain visible and unanswered by bots.
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

### Smart Bot — deck-aware play and combo assembly

- **What:** Additional `smart` seat policy available through the existing Solo/Multiplayer catalogue. Detects own-deck colour identity, commander themes and archetype, prioritizes WinCons and visible combo progress, tutors missing ingredients, fixes mana, handles bounded mulligans and evaluates combat/interaction. Uses installed Spellbook matches without triggering downloads; ignores unresolved template matches. Oracle + Demonic Consultation has an engine-tested UU+B/trigger-response/name-card winning sequence. Other combos receive assembly heuristics rather than generic combo execution.
- **Boundary:** Only own setup deck definitions as prior knowledge; live decisions use the perspective-redacted view and validated legal offers. Free-text naming is now an explicit parameterized `choose` offer. Repeatable abilities require visible progress and stop at 64 uses per ability/turn; session memory survives bot reconstruction and resets on restart.
- **Files:** `services/bots.py`, `services/bot_strategy.py`, `services/game_session.py`; reference and upstream research in `docs/Reference/SMART_BOT.md`.
- **Mana and entry choices (BUG-3):** the engine offers `cast_spell` only when auto-tap can pay, and auto-tap never spends sacrifice/hand-exile sources (Lotus Petal, Treasures, Spirit Guides), although the view's mana potential counts them — so a commander/combo permanent payable only with them (Kinnan with Springs + Petal) was never offered and Smart Bot, unlike Greedy, had no manual-tap fallback. `SmartBot._unlock_tap` now puts the scarcest missing colour into the pool first (once per card and turn; commander tax from the new public `commander_casts` on the player view, RULE 903.8). Also fixed: shock lands were always declined (now paid when something is castable and life > `SHOCK_LIFE_FLOOR`), "reveal a card" lands always reveal, Mox Diamond is cast only with a spare land and discards the least-needed one, the mulligan counts cheap mana rocks as sources, lands no longer carry the `tutor` role (a fetch land earned +30), and a land's own mana ability is no longer activated as a candidate. A fetch-land crack deliberately stays ahead of spells: the fetched land is what makes them payable. Detector campaign (bot vs bot, end of main 2 with a payable piece/commander still uncast): Kinnan 7/258 → 1/270 bot turns, M-K 4/139 → 0; mulligans roughly halved; K'rrik, Rocco and Wretched Ranks unchanged at 0.
- **Tests:** `tests/services/test_smart_bot.py` (13 new, 10 red against the previous code).

### Individual bot policies and AI Bot

- **What:** Each bot class now lives in its own `services/bot_policies` module; `services/bots.py` retains registry/driver and compatible exports. The new `ai` policy shares Smart Bot's detected deck/commander/combo profile, asks a configured LLM to select offered actions, validates parameters, then uses the ordinary engine action path. Bounded background workers preserve priority while waiting; stale results are discarded. Unconfigured/failed/over-budget requests fall back to Smart. Solo polls pending jobs; lobby rebuilds preserve session context; restart clears it.
- **Files:** `services/bot_policies/`, `services/bots.py`, `api/solo.py`, `services/game_session.py`; configuration/transport in `services/llm_settings.py`, `services/llm_client.py`, `api/llm.py`. See [LLM integration](../Reference/LLM_INTEGRATION.md).

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

### Leading object "for each" — the loop item as "it" (PAR-112, PARSER_VERSION 501)

- **What:** "For each `<count phrase>`, `<body>`" at the *front* of a clause now iterates
  battlefield objects (`segmenter._leading_for_each_object_specs`, after the player-subject
  slot): the group is the shared `count_phrase` grammar, the body is parsed with the pronoun
  reading on, and every effect that names its object through ``referent: "previous"`` is
  re-pointed at ``referent: "iteration"`` — `GameContext.iteration_item`, which `for_each`
  already set but nothing read. `CopyPermanentEffect` is the first reader. `count_phrase`
  gained the "that entered [the battlefield] this turn" tail (`entered_this_turn`, already
  in `combat.matches_object_filter`). Closed PAR-112's last item: Ocelot Pride (+ Alchemy),
  plus Chief Magistrate of Mercadia and Renewed Solidarity.
- **Why:** The trailing "`<effect>` for each `<group>`" connective hands each item over as a
  *target*, which is wrong for a pronoun ("a copy of it" is no target). A body that targets,
  or uses a pronoun no effect reads through ``referent``, fails closed, so the connective
  cannot claim a clause it would run wrongly. `CopyPermanentEffect`'s referent whitelist
  silently maps an unknown value to ``"source"`` — the first run copied Ocelot Pride itself
  per item until ``"iteration"`` was added there; a new referent must be whitelisted in the
  effect, not only emitted by the parser. Still open on the same shape: Saheeli, the Gifted
  and Red Sun's Twilight (a trailing "those tokens gain haste. exile them …"), March of
  Progress and Battle for Bretagard ("for each creature chosen this way" / "for each of them").
- **Files:** `parser/oracle/segmenter.py`, `parser/oracle/catalogue/count_phrase.py`,
  `game/effects/counters_tokens.py`, `tests/test_par112_for_each_object_copy.py`

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

### Case solve conditions based on instant/sorcery casts (PARSER_VERSION 597)

“You've cast N or more instant and sorcery spells this turn” maps to the existing
cast-history selector and intervening-if solve trigger. Tests exercise configurable
thresholds, reject a different cast filter, and verify the parsed Case against real
spell casts: a creature cast does not contribute to solving it.

### Optional discard followed by drawing the discarded count (PARSER_VERSION 595–596)

The effect grammar recognizes “discard up to N cards, then draw that many cards”
and its optional “if you do” form using the existing discard chooser. Its parser
regressions cover trigger bodies and reject additional draw riders. The full
cache comparison added five covered cards and regressed none. Version 596 also
recognizes the standing storm grant to instant and sorcery spells.

### Player-scoped phase bodies and additional draws (PAR-100, PARSER_VERSION 592)

"That player" in a phase-trigger body runs the shared second-person grammar as the active
player (`trigger_subject_referent.acting="active_player"`), including linked instructions
and optional choices; an explicit second player referent is refused. Deferred effect tails
now preserve and restore `acting_player_id`. "Draw an / N additional cards" accepts fixed
plural counts, and "each other player's" phase scope uses `phase_relation="not_you"`.

The original eleven cards are fully parser-modeled: Academy Loremaster, Anvil of Bogardan,
Dictate of Kruphix, Font of Mythos, Howling Mine, Kami of the Crescent Moon, Nekusar, Rites of
Flourishing, Spiteful Visions, Teferi's Puzzle Box, and Mornsong Aria. Well of Ideas closes
through the plural-count and other-player scope extensions. Howling Mine's intervening-if
is checked both at trigger time and resolution. Academy Loremaster's optional body asks
the active player and applies a turn-long spell tax (`reduce_spell_costs_this_turn.increase`)
only on acceptance; the tax survives its source and expires at cleanup. Mornsong Aria reuses
`draw_limit.max_per_turn=0`, `prevent_all_life_gain`, life loss, and the existing search.

Puzzle Box uses `bind` to save hand size, `put_hand_on_bottom` (a `move_object` alias) to
order the whole hand through the existing library-ordering chooser, and an ordinary draw
of the saved count after that choice. Partner commanders' command-zone choices pause each
move before the draw, using ordinary deferred effect tails. This also models Arjun and Mindmoil. Cache-wide probe:
**20 newly covered, zero coverage regressions**; the other gains are Braids, Conjurer Adept,
Collapsing Borders, Manic Scribe, Seizan, Perverter of Truth, Walking Archive, and Worry Beads.
The related-card search found five fixed two-additional-card cases (Font, Curse of Obsession,
Well of Ideas, Sylvan Library, Sarkhan's emblem), no larger fixed count in the cached pool.
Curse's enchanted-player trigger head and Sarkhan's transformation/emblem remain separate
unmodeled shapes; Sylvan Library already has a hand-authored implementation.

Validation: `tests/test_par100_draw_steps.py` exercises three-player draw ownership,
plural counts, Howling Mine's two condition checks, Anvil's active-player discard,
Loremaster's accept/decline and tax lifecycle, Puzzle Box's ordering/paused draw, Mornsong's
prohibitions/search, and full-cache parse/bind checks for all twelve cards. The full-cache
backend suite passed 11,058 tests; its sole Windows-default-decoding failure in the existing
PAR-119 source scanner passed when its module was rerun with `python -X utf8`. The 504
focused phase/continuation/ISA/parser-lock tests also passed, including the twelve real cards.

### PAR-104: the Mutagen token and what the TMNT cards around it needed (PARSER_VERSION 576, +34, 0 regressed)

- **The token:** a `data/tokens.json` entry ("{1}, {T}, Sacrifice this token: Put a +1/+1 counter on target creature. Activate only as a sorcery.", set `ttmt`, art from `token_art.json`) and `handlers._NAMED_TOKEN_WORDS["mutagen"]` — that alone unlocked ten ETB/attack/leave makers (Crustacean Commando, Michelangelo, Ray Fillet, Slithering Cryptid, Genghis Frog, Roadkill Rodney, Splinter, Zoo Escapees, Mona Lisa, Ooze Spill). Executed: the token is an artifact that can be sacrificed for a +1/+1 counter at sorcery speed only.
- **Cast trigger over a comma list of types** (`segmenter._CAST_TRIGGER_COMPOSED_RE`: the phrase may be "x, y, or z spell"): April O'Neil, and — unrelated to Mutagen — Rockslide Sorcerer, Umara Mystic / Wizard ("an instant, sorcery, or Wizard spell"), God-Pharaoh's Faithful, Guru Pathik, Lucky the Pizza Dog. The subtype member is read off the cast spell's own type line (a stale pin that said such a list "stays unclaimed" was replaced by one that casts a Wizard and a Bear).
- **Donatello's replacement:** "if 1 or more tokens would be created under your control, those tokens plus a `<named>` token are created instead" is a parser row onto the existing `additional_named_token` (Peregrin Took's hand-authored original), over the closed named-token set.
- **"create a `<named>` token for each +1/+1 counter on it"** (The Ooze) under a group trigger: `create_token.count` is the `counters` amount of the trigger subject — live counters, or the leave event's RULE 603.10a snapshot once it is gone. Group-subject only: with no firing creature "it" would count nothing.
- **"target artifact, enchantment, or creature [with flying / power N or greater]"** (13 cards: Mutant Chain Reaction, Spider Food, Storm, Broken Wings, Return to the Earth, Shoot Down, Exorcise, Make Your Move, Airship Crash, Shattered Wings, Shower of Arrows, Vivien Reid's −3, …) is one shared axis: the three-type union in any printed order resolves to the dedicated `artifact_creature_or_enchantment` pool instead of the broad "permanent" (which also offered lands), a destroy/exile row carries the quality as `creature_filter`, and `TargetFrame.creature_filter_creatures_only` applies it to the creature members only (an artifact or enchantment needs no flying). The opponent-scoped pool (`…_you_dont_control`) and the library-put / exile-until-leaves rows that had taken "permanent" for it follow (Banishing Stroke, Banishment Decree, Trapped in the Screen).
- **Two latent bugs found by reading the newly covered cards' specs and binding them:** (1) `binding.core._subject_event_key` hashed a *list* event ("a Detective you control **enters or is turned face up**, put a +1/+1 counter on it") — a TypeError at deck load that no covered card had reached; (2) "Solved —" / "Max speed —" on a **replacement** appended an activation-condition marker the replacement binder cannot build (a `BindError` for Case of the Pilfered Proof); it is now the replacement's `active_if`, which `build_replacements` already reads. Executed: the Case's extra Clue appears only once solved.
- **Left open, per card:** Return to the Sewers ("target creature's owner puts it on their choice of the top or bottom of their library" — a 21-card cluster of its own, 17 of them SOLO: Aether Gust, Aetherspouts, Desynchronize, Diver Skaab, Misleading Motes, Run Behind, Trip Up, …; needs the owner's interactive top-or-bottom pick), Shellshock (already in `singletons.md`: damage "to each of those creatures" plus a count of the creatures actually hit), Mutagen Man ("create X Mutagen tokens" and "activated abilities of artifact tokens you control cost {1} less"), Michelangelo Mutant BFF ("can't be blocked by more than 1 creature" for creatures with counters), Raphael the Muscle ("double all damage that creatures you control with counters on them would deal"), Carnivorous Canopy ("if that permanent's mana value was 3 or less, proliferate").
- **Files:** `data/tokens.json`, `parser/oracle/catalogue/{handlers,subgrammars,replacements}.py`, `segmenter.py`, `gate.py` (PARSER_VERSION 576), `game/targeting.py`, `game/binding/core.py`. Tests: `tests/test_par104_mutagen.py` (the token's ability and sorcery timing, the type-list cast trigger and its refusal, Donatello for its controller only, The Ooze's per-counter count, the three-type pool's creature-only quality in both scopes, the Case's solved gate and the two-event bind).

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


### PAR-119: attack leftovers, entry origin, player-event and cast leftovers, "otherwise" (commit `d2967b79`, PARSER_VERSION 501)

- **What:** Axis (b) — "you attack with your commander", "~ and another legendary
  creature", "creatures with total power N or greater", "creatures with counters on them"
  and "that many" off an attack batch: `game/trigger_quantities.py` captures each
  ability's own matching attackers when it triggers (RULE 603.2, so a later change to the
  attackers can't alter the count); Arthur's end-of-combat return. Axis (c) — "enters from
  a graveyard / exile" (every ENTERS emitter supplies an origin, `from_zone`). Axis (d) —
  "you're dealt damage", the opponent combat-damage head, proliferate, "taps a land for
  mana" on the existing mana event, "except the first N … in each draw step". Axis (e) —
  ordinals ("your first spell during each opponent's turn", from cast history), magecraft
  "or copies", "that has an adventure"; "during an opponent's turn" on a cast trigger is
  now controller-relative (RULE 102.2), the migration's named defect. The "otherwise"
  residue: Insatiable Appetite / Pippin's Bravery (a targeted then-branch with an else) and
  Lorehold Excavation (branches on what was actually milled).
- **Why:** Shipped as an intermediate commit without ticket or worklog update; recorded
  here from its tests (`test_par119_attack_batch_head.py`, `test_par119_zone_origin.py`,
  `test_par119_player_event_head.py`, `test_par119_cast_trigger_grammar.py`,
  `test_par119_otherwise.py`). That gap is what `workingOn.md` now exists to prevent.
  Its one red pin (`~ enters` "must fail closed") was stale: a bare "~ `<verb>`" is a legal
  object-head subject, with the same spec as the legacy self row plus an origin.

### PAR-119 (a): RULE 603.2c object batches — `EVENT_BATCH` and the quantity head (PARSER_VERSION 502–508)

- **What:** "Whenever one / N or more `<objects>` enter / die / leave the battlefield" is
  one trigger per *simultaneous* batch. `GameState.simultaneous()` is a nesting scope:
  batched per-object events (`BATCHED_EVENT_TYPES` — enters, leaves, dies, discard) fired
  inside it are re-announced when the outermost scope closes as one `EventType.EVENT_BATCH`
  per type, ``{"batch_of", "members": [the original events]}``; an event outside every
  scope is its own one-member batch. The scope wraps each instruction's `apply`
  (`effects/core._apply_effects_partitioned`) — so "create two tokens" / "destroy all
  creatures" is one batch and two separate "create a token" sentences are two — and each
  SBA sweep (RULE 704.3). A batch trigger is ``{"event": "EVENT_BATCH", "batch": {"of",
  "min"}, "condition": <the ordinary per-object condition>}``: `binding.core._batch_members`
  runs the normal per-object `_trigger_condition` for ``of`` over the members and counts;
  the batch `capture_event` stamps ``matching_count`` / ``matching_ids`` per ability.
  Parser: `object_trigger_head._parse_batch_quantity_head` (plural noun phrase + the head's
  shared tail loop, `_consume_tails`); "that many/much" on a counting head is read as X and
  bound to the head's count (`_bind_x`), not one row per verb; typed "one or more
  `<type>` cards leave your graveyard" (snapshots now carry `object_types`). +29 cards
  (Great Fierce Bee, Vengeful Townsfolk, Welcoming Vampire, Woodland Champion, Elvish
  Warmaster, Chalk Outline, Cyan, Desecrated Tomb, …), no regression.
- **Why:** The legacy rows modelled a batch as per-object events: `_BATCH_ENTER_TRIGGER_RE`
  made Frantic Scapegoat trigger once per entering creature, and `_BATCH_DIES_TRIGGER_RE`
  claimed only cards whose "triggers only once each turn" hid the over-firing. Both rows
  are deleted; the six once-per-turn DIES cards keep their `limit` on the real batch.
  Merging pending triggers instead was rejected: two instructions of one resolution are two
  events (RULE 608.2c) and must not merge, which only an emission-side scope can tell. A
  batch has no single firing object, so its body gets no "it = the firing object" reading;
  Frantic Scapegoat's "suspect one of the other creatures" reads the batch's
  ``matching_ids`` in `SuspectEffect`. MEC-78's graveyard-only `graveyard_exit_batch`
  was folded into this scope under PAR-131 (see that entry).
- **Discard batches and the multi-pick hold (PARSER_VERSION 503):** "you discard `<n>` or
  more [`<type>`] cards" is the actor head's quantity form over DISCARD_CARD (+10: Mishra,
  Rielle, Cryptcaller Chariot, Tinybones, …). Discards happen outside effect resolution
  too, so `draw_discard_mixin._one_event` scopes `discard` / `discard_random` /
  `discard_matching` (costs, "discard your hand", the RULE 514.1 cleanup discard) and the
  discard-cost loops are scoped. An interactive multi-pick (`choose_objects`, count > 1)
  applies each pick as it is answered, so `GameState.hold_batches` keeps the batch open
  until `_resume_choose_objects` completes the choice (`release_batches`) — without it an
  interactive "discard two cards" or "sacrifice two creatures" was two batches (the tests
  check both fail without the hold).
- **Sacrifice batches (PARSER_VERSION 507):** "`<you | 1 or more players>` sacrifice(s) 1
  or more [other] `<permanents>`" (Forge Boss, Blood Hypnotist, Evin, Hostile Investigator;
  +5). SACRIFICE joined `BATCHED_EVENT_TYPES`, and the whole cost payment is one scope —
  `activate_ability` around `_pay_activation_cost`, the cast around `_pay_additional_cast_
  cost` (RULE 601.2h / 602.2b pay the total cost in one step) — so "Sacrifice two
  creatures: …" is one batch (the test checks it is two without the scope). The slice-2
  fail-closed pin on "you sacrifice 2 or more creatures" moved to the positive table.
- **"For each of them" (PARSER_VERSION 508):** under a batch head, "for each of them,
  `<body>`" is `for_each` over ``{"batch_members": true}`` — the captured ``matching_ids``
  (`ForEachEffect._items`), the body parsed with the pronoun reading like the leading
  object `for_each` (Kambal, Profiteering Mayor). Off a batch head it fails closed.
- **Combat-damage batches (PARSER_VERSION 504):** "whenever `<n>` or more `<creatures>`
  deal combat damage to `<a player | an opponent | you | 1 or more players>`" is
  `object_trigger_head._parse_combat_damage_batch_head` over the existing
  `CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER` aggregate, which already fires once per
  (contributors' controller, damaged player) — the RULE 510.2 batch, so no new event. The
  trigger is ``{"contributors": {"min": N}, "condition": <per-creature condition>}``;
  `binding.core._contributor_members` re-reads each ``contributor_ids`` entry as the
  per-creature combat `DAMAGE` event it stands for and runs the ordinary `_trigger_
  condition` over it, so every subject filter and recipient scope the singular damage head
  knows applies unchanged (the contributors are still on the battlefield: the aggregate
  fires before SBAs). `_apply_combat_damage` now also stamps ``contributor_amounts``; the
  capture adds ``matching_ids``/``matching_count``/``matching_amount`` for "those
  creatures" / "that damage" bodies. The old per-flag hand rows (``contributor_subtype``
  etc.) and the two bare segmenter rows stay: player-event rows run first, so no modelled
  spec changes. Also `characteristic_phrase._alternation` shares a trailing type noun
  across subtypes ("ninja or rogue creatures"; subtypes only — "red or blue creatures"
  stays ambiguous). +9 (Alela, Cunning Conqueror, Automated Assembly Line, Haliya,
  Invasion Tactics, Keeper of Fables, Olivia, Opulent Outlaw, Prosperous Thief ×2, Thopter
  Spy Network), whole-cache spec diff: 0 lost, 0 changed. Of the head's 28 remaining SOLO
  cards most are body gaps — chiefly "target `<X>` that player controls" (PAR-130).
  Tests: `tests/test_par119_combat_damage_batch.py`. The subject grammar later gained
  "goaded", "face-down" and "that entered this turn" (see the next entry). "To 1 or more
  of your opponents" stays closed on purpose: it triggers once per step, the aggregate
  once per damaged player.
- **Files:** `models/game/events.py`, `models/game/game_state.py`, `game/effects/core.py`,
  `game/rules/sba_mixin.py`, `game/binding/core.py`, `game/rules/casting_mixin.py`,
  `game/effects/counters_tokens.py`, `parser/oracle/catalogue/object_trigger_head.py`,
  `parser/oracle/segmenter.py`, `parser/oracle/catalogue/handlers.py`,
  `game/rules/draw_discard_mixin.py`, `game/rules/misc_mixin.py`,
  `game/engine/activation_mixin.py`, `game/engine/casting_mixin.py`,
  `game/engine/combat_mixin.py`, `parser/oracle/catalogue/characteristic_phrase.py`,
  `tests/test_par119_batch_quantity.py`, `tests/test_strixhaven_secrets_wave7.py`,
  `tests/test_par119_combat_damage_batch.py`, `tests/test_par119_sacrifice_batch.py`,
  `game/effects/composition.py`

### PAR-119 (c/d): graveyard arrivals, land-tap mana bodies, zone tails, subject qualifiers (PARSER_VERSION 505–510)

- **What — graveyard arrivals (505, +16):** "`<a card>` is put into `<a | your | an
  opponent's>` graveyard [from anywhere | a library | your hand | anywhere other than the
  battlefield]" and the batch form "`<n>` or more `<cards>` are put into …" (The Gitrog
  Monster, Profane Memento, Serra Avatar, Worldspine Wurm, Skola Grovedancer, Patron of the
  Nezumi, …). New `EventType.PUT_INTO_GRAVEYARD`, batched. The engine writes graveyards in
  ~17 places with no choke point, so `GameState.announce_graveyard_arrivals` diffs the zone
  map when the outermost `simultaneous` scope closes — every instruction and every SBA
  sweep, i.e. before anyone gets priority (RULE 603.3) — and fires one event per new
  arrival with ``from_zone`` (where it was at the previous check). `resync_graveyard_watch`
  re-baselines without firing: at `new_game`, after `build_replay_engine`, and after every
  `edit_*` action. Measured cost: none (suite time unchanged).
- **Why those choices:** RULE 603.6c — "from anywhere" is never a leaves-the-battlefield
  ability, so it needs no look-back; RULE 113.6k — "when ~ is put into a graveyard" can't
  trigger from the battlefield, so the binder sets `functions_from_graveyard` for that self
  trigger. A "card" subject adds ``nontoken`` (RULE 111.1); a non-card subject ("a
  permanent is put into …") has no other origin than the battlefield (RULE 110.1). RULE
  108.4a: an arriving card's ``controller_id`` becomes its owner (a stolen creature that
  died kept the thief as controller, so "that player" hit the wrong player). A token that
  died and ceased to exist (RULE 704.5d) still names its player: `effect_operands.
  players_for` falls back to the event's last-known controller/owner for the ``entering``
  referent (RULE 608.2h). `test_par30_exchange_control_bespoke`'s Confusion in the Ranks
  test used 0-toughness creatures that died after the exchange; given real toughness.
- **Land-tap mana bodies (506, +9):** "[that player] add(s) one mana of any type that land
  produced" is `mirror_produced_mana` (Kinnan's effect) with a new ``player`` operand
  (Mana Flare, Heartbeat of Spring, Mirari's Wake, Zendikar Resurgent, Lavaleaper, …). A
  `TAPPED_FOR_MANA` trigger whose body only adds mana (`_MANA_ADDING_EFFECTS`) is a RULE
  605.1b mana ability on the composed head too. "That land doesn't untap …" with no
  earlier referent is the firing event's land (`skip_next_untap_event_object`; Vorinclex,
  Winter's Night).
- **Zone tails (509, +3):** LEAVES_BATTLEFIELD stamps ``to_zone`` on its five emitters, so
  "leave(s) the battlefield without dying" is ``to_zone_not: graveyard`` (Dour Port-Mage,
  Imperial Cosmographer, Three Tree Scribe); `play_land`'s ENTERS stamps ``played``
  (RULE 305.1), so "enter … without being played" is ``not_played``; "under an opponent's
  control" joined the tails.
- **Subject qualifiers (510, +7):** "goaded" and "face-down" are flag words over new
  `matches_object_filter` keys, "that entered [the battlefield] this turn" a phrase tail
  (Goro-Goro and Satoru, Glitch Interpreter, Primal Whisperer, Threats Around Every
  Corner, …).
- **Files:** `models/game/events.py`, `models/game/game_state.py`, `game/binding/core.py`,
  `game/effect_operands.py`, `game/effects/library.py`, `game/effects/registry.py`,
  `game/combat.py`, `game/rules/damage_death_mixin.py`, `game/engine/lands_mixin.py`,
  `game/engine/turn_loop_mixin.py`, `services/replay.py`, `services/game_session.py`,
  `parser/oracle/catalogue/object_trigger_head.py`, `parser/oracle/catalogue/
  characteristic_phrase.py`, `parser/oracle/catalogue/handlers.py`, `parser/oracle/
  segmenter.py`; tests `test_par119_graveyard_arrival.py`, `test_par119_land_mana_
  triggers.py`, `test_par119_zone_tails.py`.

### PAR-119 closing: the per-adjective group rows onto the composed head (PARSER_VERSION 511)

- **What:** `_GROUP_SUBJECT_RE`, `_GROUP_SUBTYPE_SUBJECT_RE`, `_SELF_OR_GROUP_SUBJECT_RE`
  and `_SELF_OR_GROUP_SUBTYPE_RE` are deleted. `_trigger_condition` asks
  `object_trigger_head.legacy_group_condition` instead: the composed head, translated by
  `legacy_condition` back into the flat keys those rows printed (``type`` / ``subtypes`` /
  ``color`` / ``min_power`` / ``excluded_subtypes`` / ``nonland`` / counters). The head
  gained the object verbs only those rows named (turned face up, becomes blocked / tapped /
  untapped, mutates, becomes monstrous, specializes, "is put into your graveyard from the
  battlefield"), "attacks 1 of your opponents", and a leading "nontoken" over an
  alternation. +4 (Lifeblood, Lifetap, Thoughtleech, Prowess of the Fair).
- **Why translate instead of switching to ``filter``:** the flat keys read the event's
  last-known snapshot, the ``filter`` path looks the object up live and gives up if it is
  gone — rewriting them would change behaviour, not spelling. Every spec the rows claimed
  is unchanged except two intended fixes: the old row dropped "your" in "put into your
  graveyard from the battlefield", so Scrapheap and Nether Traitor counted opponents'
  permanents; they now carry ``owner: you``. 21 cards the rows had missed ("another elf",
  "creature or artifact" in the "~ or another" form) moved from the composed ``filter`` to
  the flat keys. The remaining rows are PAR-131.
- **Files:** `parser/oracle/segmenter.py`, `parser/oracle/catalogue/object_trigger_head.py`,
  `parser/oracle/catalogue/characteristic_phrase.py`; tests `test_par119_zone_tails.py`,
  `test_par117_group_subject_blocks_this_turn.py` (stale "this turn" pin — PAR-124 moved
  that tail onto the turn-trigger wrapper).

### PAR-131: the remaining legacy trigger rows retired onto the composed heads (PARSER_VERSION 515–516)

- **What:** every per-phrase trigger row PAR-119 left behind is deleted from
  `segmenter.py` (−1,180 lines): the nine cast rows (`_CAST_SPELL_TRIGGER_RE`, `_NEG_`,
  `_PLAIN_`, `_MV_`, `_MV_AT_LEAST_`, `_X_`, `_FIRST_X_`, `_HISTORIC_`, `_NTH_`),
  `_DAMAGE_TRIGGER_RE`, `_DAMAGE_RECIPIENT_TRIGGER_RE`, `_BECOMES_TARGET_TRIGGER_RE`,
  `_BATCH_ATTACK_TRIGGER_RE` and the `_PLAYER_TRIGGER_CONDITIONS` table (also the trigger
  doublers' cause path, `trigger_condition_dict`). Their shapes now come from
  `object_trigger_head.py` (new recipient "is dealt damage", "becomes the target of …" and
  "one or more `<creatures>` attack" heads), `player_event_head.py` (scry/surveil, clash,
  forage, collect evidence, dice, "the Ring tempts you", the compound "cycle or discard"
  / "scry or surveil" as one event list) and `spell_phrase.py` ("with {X} in its mana
  cost", "your first spell with {X} …"). +16 cards (Thunderbreak Regent, Scalelord
  Reckoner, Diffusion Sliver, Blood Hound, Kavu Predator, Presence of the Master, …),
  each executed in a real engine.
- **Spec shape:** flat cast keys became the composed ``spell_filter`` (a
  `matches_object_filter` dict read off the spell on the stack) and ``spell_from_exile``
  became ``spell_cast_from``; group subjects on DAMAGE / BECOMES_TARGET / the combat-damage
  aggregate moved from flat keys to ``condition.filter``. Unlike PAR-119's dies/leaves rows
  this is safe to rewrite: none of those events is a departure, so the acting object is
  still there when the condition is read. Proven with a whole-cache spec diff against the
  pre-change tree: 0 lost; every changed spec is a rename or one of the fixes below.
- **Fixes the migration surfaced:** (1) a re-granted trigger dropped its spell filter —
  Black Mage's Rod / Red Mage's Rapier fired on creature spells, since the registry never
  passed ``spell_exclude_card_types`` through — now `binding/core.spell_filter_predicate`
  / `spell_cast_from_predicate` are shared by printed and re-granted triggers. (2) The old
  player-event row rebuilt effects without their ``condition``, so Karlach's "if it's
  the first combat phase" gate was silently lost; kept now, which needed
  `_apply_effects_partitioned` to see the selector through a `ConditionalEffect` for "they".
  (3) A self/attached DAMAGE subject's recipient ("to an opponent", "to you", "to a
  creature") used to widen to "a player"/"not a player"; it is a trigger-level
  ``recipient_relation`` / ``recipient_filter`` gate now (printed and re-granted —
  Curiosity, Hypnotic Specter, Kaldra Compleat; 40 cards). (4) `BECOMES_TARGET` stamps
  its acting player as ``player_id``, so "that player" resolves (Thunderbreak Regent).
  (5) "This ability triggers only once each turn" on a composed cast head is ``limit``,
  not a stray marker (Basim, Glóin, Sarah Jane).
- **The aggregate combat-damage flags:** the hand-authored ``contributor_power_at_least``
  / ``contributor_subtype`` / ``contributor_is_commander`` / ``contributor_power_gt_base``
  / ``contributor_base_power_zero`` trigger keys (and the event fields only they read)
  are gone. Tifa, Malcolm, Kutzil and Primo use the composed batch head's shape
  (``contributors`` + ``condition.filter``), which reads each contributor as its own
  per-creature damage event; `matches_object_filter` gained ``base_power`` and
  ``power_gt_base`` (RULE 707.2's printed/copied power). Kediss's entry is deleted — the
  parser already modeled it per commander hit, which is also more correct: the old
  aggregate summed every contributor's damage once any commander was among them.
- **MEC-78's graveyard-exit batch folded into `GameState.simultaneous`:** the engine's
  private `graveyard_exit_batch` depth/list is gone; `GameState.note_graveyard_exit`
  buffers exits while a RULE 603.2c scope (or an interactive `hold_batches` multi-pick) is
  open and `_flush_batches` announces them as one ``CARDS_LEFT_GRAVEYARD``. The event
  keeps its ``cards`` shape, so its consumers (Quintorius, Spirit of Resilience, Advanced
  Reconstruction, the parser's "cards leave your graveyard" row) are unchanged; every
  instruction and SBA sweep now batches exits without an explicit scope, and a held
  multi-pick batches them for the first time.
- **Head gaps (PARSER_VERSION 516, +8):** a compound "`<A>` or `<B>`" condition the heads
  can't read whole is split (`segmenter._compound_trigger_heads`) into two heads that each
  parse — two whole heads (Dreadhound) or one subject with a second verb (Psychomancer's
  "dies or is put into exile from the battlefield") — and re-segmented as one ability per
  head sharing the body. Only when no single event satisfies both: different events that
  never co-fire (`_CO_FIRING_EVENTS` names DIES with PUT_INTO_GRAVEYARD / LEAVES_BATTLEFIELD,
  allowed only with a separating zone), or "~" against "another …". New: the verb "is put
  into exile from the battlefield" (LEAVES_BATTLEFIELD + ``to_zone``); "`<phrase>` or a
  `<phrase>`" noun unions → ``any_of`` (Shipwreck Sifters, and for free Kumena's Speaker and
  Long Feng); "with disturb" read off the printed card like flashback
  (`combat._PRINTED_ONLY_KEYWORDS`); "~ or another …" on the DAMAGE head (Millicent, Tyranid
  Harridan) — which needed the binder's ``self_or_group`` self half to read the event's own
  subject field (it read ``instance_id`` for every event, so "~ or another" never fired for
  "~" on DAMAGE). Split out as their own tickets: MEC-103 (sacrifice a chosen number, then
  "that many"), MEC-104 (one damage trigger per step across all opponents), PAR-133
  (Powerstone tokens, found blocking Slagstone Refinery's body).
- **Files:** `parser/oracle/segmenter.py`, `catalogue/object_trigger_head.py`,
  `catalogue/player_event_head.py`, `catalogue/spell_phrase.py`,
  `catalogue/static_handlers.py`, `game/binding/core.py`, `game/continuous.py`,
  `game/effects/core.py`, `game/effects/registry.py`, `game/rules/misc_mixin.py`; tests
  `test_par131_legacy_row_retirement.py` plus ~30 shape pins re-pointed at the composed
  keys. `tests/api/test_game_ws.py`'s broadcast test now shares one TestClient portal —
  two portals put the sockets on two event loops, and a cross-loop send does not wake a
  receiver that is already waiting (an intermittent 20 s hang, ~1 run in 4).

### PAR-123 closes: the firing object of a group trigger, for every effect (PARSER_VERSION 552)

- **What:** under a RULE 603.1 group trigger ("whenever a creature you control enters …") a bare "it" / "that creature" / "that `<subtype>`" is the object that fired it — an object nothing chose. Until now each effect had to grow its own trigger-event read (`tap`, `exile`, `return_to_hand`, the pump, `add_counters`, …), so any verb without one left the clause unclaimed, or worse, claimed as the *source* (see below). One mechanism now serves every effect: **`trigger_subject_referent`** (`game/effects/composition.py`), which seeds `GameContext.previous_targets` with the firing object, optionally runs a body *against* it (as its `targets`), optionally runs that body **as its controller** (`acting: "controller"` → `GameContext.acting_player_id`, read by `_controller_of` / `effect_conditions._controller_id` / `CreateTokenEffect` / `TapEffect`), and — for a payment's deferred "if you do" — reads the object `PayCostThenEffect(remember_trigger_subject)` stamped on the source (`event_key: "remembered"`). Cards: +154 (53.2 %), 0 regressed; e.g. Ogre Battledriver, Black Widow, Path of Discovery, Dread, Caltrops, the attach-to-it Equipment cycle (Cloak and Dagger …), Durable Handicraft/Anointer of Valor (paid branches), Seed the Land/Burning Sands/Fecundity (its controller), Marcus/Zurgo/Tribute (gates), Archon/Hamletback Goliath/Necropolis Regent (amounts), Shared Animosity/Marhault (counts), Hellrider, Boxing Ring, Teferi's Veil.
- **How a clause reaches it** (`catalogue/handlers.match_clause`, only after every row written for the group subject declined, so nothing they claim changes reading): (1) the clause retried as a *previous-subject* clause — every row with a "that creature" reading (explore, endure, fight, phase out, connive, goad, keyword/pump, copy …) works unchanged; (2) `_group_pronoun_as_target` — the pronoun spelled as a target ("destroy it" → "destroy target permanent", then "target artifact", "card from a graveyard"), the result wrapped so it acts on the firing object; refused when a second "target" would be hidden or when a nested body runs later (`_runs_against_targets`); (3) `_group_controller_as_you` — "its controller creates a token" as "you create a token" run as that player, offered only for effect types verified to read "you" through the acting player (`_ACTING_AS_CONTROLLER_TYPES`, pinned per type by `test_par123_referent.py`). `that <subtype>` normalises to `that creature` (unless a second "that creature" is in the clause); `that X's` to `its`; `that card` to `it` on a dies-shaped body with no earlier card-introducing verb. `segmenter._hoist_referent_seed` puts one seed first, because a gate is evaluated before the gated effect runs.
- **Operand positions:** conditions — `catalogue/referent_condition.py` reads "it has flying / was attacking / has a +1/+1 counter / is 1/1 / entered this turn / was cast / its power is 3 or greater / has greater power or toughness than ~ / is an instant or sorcery card" into the shared vocabulary (new engine kinds `toughness`, `mana_value`, `has_keyword`, `entered_this_turn`), and `_rescope_to_trigger_subject` points *every* gate on "it" at the firing object (a bare `is_card_type` used to read the source — Temur War Shaman); the suffix "`<A>` if `<C>`. Otherwise, `<B>`." / "If it doesn't, `<B>`" is an `if_else`. Amounts — `_referent_characteristic_specs` binds "where X is its power" / "equal to that creature's toughness" / "put a number of counters on ~ equal to …" to `{"kind": "characteristic", "of": "trigger_subject"}`; "that many" after a damage head is the event's `amount`. Counts — `count_selector` amounts gain a `reference` ("for each creature blocking **it**", "each **other** … that **shares a creature type with it**": new filter `shares_creature_type_with_reference`; a static evaluates it for the affected object, Alpha Status). Target filters — `TargetSpec.exact_mana_value: "trigger_subject_mana_value"` (Boxing Ring; the `creature_you_dont_control` frame now applies it), `excluding_trigger_subject` (Pawpatch Recruit, stamped by `build_effects`). Boxing Ring's Treasure gate needed a `FIGHTS` event (fired per fighter by `FightEffect`) and the history grammar's "you control a creature that fought this turn". "The player or planeswalker it's attacking" is `DealDamageEffect.recipient_subject="trigger_subject_defender"`; "that archer deals that much damage to that creature's controller" reads `damage_recipient_controller`.
- **Wrong-but-modeled claims this removed:** "put a +1/+1 counter on ~. It gains flying" under a group trigger flew the entering land (Fearless Fledgling; a pronoun in a later clause than an explicit "~" is now the source, `_pronoun_continues_source`); a bare `is_card_type` gate read the source; `_add_counters`'s `_SELF_SUBJECT` "it" put the counters on the source for any counter that was not a printed P/T (`_GROUP_CLAUSE` context var); a payment's "if you do, it gets …" pumped the Enchantment; `_announces_creature_target` and the previous-subject amount read a *player* target as a creature (Devour Flesh's subject-less "then gains life" is refused). The audit is recorded in `PARSER_LONG_TAIL.md`'s lessons.
- **Composed heads:** "~ or another creature you control enters, **that creature** …" is now read (Ambuscade Shaman, Ardoz, Archon of Redemption); a bare "it" there stays refused — it could as well be "~". Aggregate heads (`contributors`, Vulture) and batches give no single-object pronoun.
- **Also:** copy-"except" pieces accept "the token" / "they" as the subject (Miirym); `Ashroot Animist`'s "gains trample and gets +X/+X, where X is ~'s power"; delayed "it phases out at end of combat" (`PhaseOutEffect` reads a captured object).
- **Not closed here, and not pronoun gaps** (each fails in its *targeted* spelling too): temporary keyword loss ("loses flying until end of turn", Gravity Well/Barbed Foliage — 36 SOLO cards), named counters on a target ("put a stun/globe/flying counter on …"), "target Equipment" as a target kind (Sokka and Suki, Kemba, Swordsman), power-only doubling ("double its power", Death Kiss), "any target that isn't a `<subtype>`" (the Wrathful pair), additive-colour copy exceptions ("… in addition to its other colors and types", Ratadrabik), "gain control … for as long as you control ~" (Willbreaker), the once-per-turn *action* limit "Do this only once each turn" (Ondu Spiritdancer — not a trigger limit when the effect is optional). Look-at-the-top / reveal-until families that merely mention "that creature" are their own grammar.
- **Tests:** `tests/test_par123_referent.py` (70) — parse shapes, refusals, and execution for every family above (each acting type; a paid branch after the event is gone; an optional attach; a spell's LKI power; Boxing Ring's offer/fight/gate; Hellrider's declared defender). Three stale pins rewritten (`test_par117_group_subject_power`, `test_par123_pump_for_each`, `test_lifegain_dynamic_amount_family`); `test_target_frames` now inspects `_legal_targets_for`. Full-cache tier green (one unrelated randomised Planechase-deck test flaked once).

### PAR-123: a pump that scales "for each `<quantity>`" (PARSER_VERSION 527)

- **What:** "`~`/it gets +N/+M until end of turn for each `<quantity>`" (Goblin Piledriver, Angelic Captain, Kavu Mauler, Spider-Mobile, Growth Cycle's "additional +2/+2 …", the "for each elf you control" cycle — +21 cards, 0 regressed). The amount path (`segmenter._bound_for_each_amount`) accepted only a single `amount`/`count` magnitude, so a `pump` (power/toughness) had nowhere to put the measured number; `_bound_pump_for_each` now hands it to each nonzero printed half (`$n`, with `multiply` for a unit above 1). Two different nonzero halves ("+2/+1 for each"), negative halves and non-literal halves are refused rather than guessed.
- **Why "other" is refused under a group trigger:** the count's ``not_reference`` excludes the ability's own source, but under "whenever a creature you control attacks, it gets … for each other …" the counted-against object is the firing creature, which a count selector can't name yet (Shared Animosity's "…that shares a creature type with it" is the same gap). Self-subject triggers, where source and "it" coincide, take it.
- **Tests:** `test_par123_pump_for_each.py` (parse, execute through the engine, real cards).
- **Follow-up (v528/v529): the dealer under a group trigger, and a latent unresolved-placeholder bug.**
  - "it deals damage equal to its power to `<target>`" under a group trigger gets two rows (`damage_equal_to_power_group_pronoun[_selector]`) with `dealer_kind="trigger_subject"`, the dealer `fight` already reads (Stalking Vengeance, Warstorm Surge, Be'lakor).
  - "it deals N damage to `<target>`" under a group trigger is dealt by the firing object, not the carrying permanent (Dragon Tempest was a wrong-but-modeled claim: lifelink/deathtouch/protection would have read the Enchantment). `segmenter._stamp_group_pronoun` stamps `dealer_event_key` (the group sentinel) onto each `damage`, including one inside a `bind`; `DealDamageEffect.apply` swaps `self.source` to that object for the one resolution and restores it (an effect instance serves every future firing).
  - **Bug found on the way:** the binder resolved the group-subject sentinel only on a spec's *top-level* params, so any pump/damage nested in a composition node (`bind`, `for_each`) under a group trigger kept `"__group_subject__"`, matched no event and did nothing — modeled but inert ("it gets +X/+X, where X …", every v527 for-each pump under a group trigger). `binding/core._resolve_group_sentinel` now rewrites it at any depth. `test_par123_group_pronoun.py` executes both.
- **"it gets +X/+X …, where X is the number of `<quantity>`" (PARSER_VERSION 541, +5, 0 regressed).** `_where_x_specs` already bound a literal X, but no row read "it gets +x/+x" for *any* pronoun subject, so the phrase was unclaimed everywhere. `_PUMP_IT_X_RE` is one regex with three subject flavours (`pump_group_subject_x`: the firing object of a RULE 603.1 group trigger, `pump_self_subject_x`, `pump_previous_subject_x`), each emitting the `"x"` power/toughness sentinel the where-X wrapper rewrites to `$n`. Angelic Exaltation, Thoughtweft Imbuer, Imaryll, Team Avatar, Vile Deacon; the executed test caught that "attacks alone" needs `_fire_attacks_alone_event()` (a separate aggregate event) in a harness.

### PAR-124's own residue: "copy that spell X times" and a delayed trigger's own group pronoun (PARSER_VERSION 460)

### PAR-124 closes completely: the mana-tap/life-gain player-event pair, X-token creation, a for-each pump variant, a targeted delayed DIES trigger, an optional targeted-antecedent composition, a hand-zone spell duplicate, and the controller-binding fix that makes the targeted variant generally safe (PARSER_VERSION 463)

### PAR-124's own residue, second batch: the "must be blocked this turn if able" cluster, the animate-land/flash/tap-selector family, and a group-subject copy (PARSER_VERSION 462)

### PAR-123 / PAR-124: two wrong-but-modeled families closed (PARSER_VERSION 455)

### PAR-136 / 137 / 138 / 139: one batch of four ticket-sized axes (PARSER_VERSION 566, +99 over v565, 0 regressed)

- **PAR-136 — flicker with a delayed return** ("Exile target creature. Return that card to the battlefield under its owner's control at the beginning of the next end step.", ~22 cards: Flickerwisp, Turn to Mist, Liberate, Aetherling and the self-blink activations, Ghostway/Sudden Disappearance's mass form). The ticket's "decide row-over-composition vs. a `BlinkEffect` param" resolved as **composition**: `exile` + the existing RULE 603.7 `create_delayed_trigger` (`capture="previous_or_self"`) + one new inner effect, `return_specific_to_battlefield` (`ReturnSpecificToBattlefieldEffect`; returns only a card *still in exile*, as a new object under its owner's control, so a stale capture — "up to one target" with none chosen falls back to the source — returns nothing). The return row is **gated** (`previous_subject_only` / `self_subject_only` / `previous_selector_only`, `handlers._DELAYED_RETURN_BATTLEFIELD_RE`): ungated it also claimed Resurrection Orb's "when equipped creature dies, return it …", where nothing is in exile — a wrong-but-MODELED claim the probe's spec read caught. A mass exile (`group`/`selector`) now leaves what it exiled in `previous_targets` and `_announces_group_selector` knows an `exile` selector. **Unclaimed, each its own axis:** target phrases the shared grammar lacks ("exile target permanent other than ~", "up to 1 other target creature or artifact you control", "nonland, nontoken permanent", "nonenchantment permanent"); "you may exile … if you do, return that card …" (Astral Slide, Sentinel of the Pearl Trident); riders after the return (Teferi's Time Twist's counter, Silver Surfer's tapped land); a *dies* return ("when ~ dies, return it …", Ivory Gargoyle, Resurrection Orb) — nothing is in exile there.
- **PAR-137 — impulse draw.** The ticket's premise ("no parser row emits `impulsive_draw`") was stale: `exile_top_play` existed. What was missing were variants: the window word "until end of turn", and *a choice of one* of the exiled cards ("choose 1 of them. You may play that card …", "you may play 1 of those cards …"), which keeps the permission on the pick alone (`ImpulsiveDrawEffect.choose_one`, `exile_with_play_permission(grant=False)`, the `grant_temp_play_same_turn/next_turn` choose-object actions). Two **general** parser fixes came with it, both measured at 0 regressions: a clause row written for several sentences is now tried over a window of 2–4 consecutive sentences when a body is split on periods (`segmenter._MAX_SENTENCE_WINDOW`) — it is what lets "<anything>. Exile the top 2 cards of your library. Until the end of your next turn, you may play those cards." parse at all — and "…, where x is `<phrase>`. `<more sentences>`" (the definition mid-body) reads like the definition-last form (`_WHERE_X_MID_BODY_RE`). A bare `x` count is still refused for the reason given under PAR-144. **Unclaimed:** the "cast … from among them" family (a different mechanic, PAR-105's), riders per exiled card ("if you exiled a land this way, create …"), piles, "choose a card name/artist" reveal-until forms, "where x is ~'s power" (a self-characteristic X).
- **PAR-138 — "whenever 1 or more +1/+1 counters are put on `<subject>`".** The engine already fired `EventType.COUNTER` *after* the counters landed (Flourishing Defenses, Hapatra, Danny Pink consume it); only the head was missing (`object_trigger_head._parse_counters_put_head`: `~`, or a group phrase with its controller scope; the kind is an exact event filter; "for the first time each turn" is the existing once-per-turn limit). One engine fix: `_GROUP_CONTROLLER_EVENT_KEYS["COUNTER"] = "recipient_controller_id"` — a group head read the causer's controller key and never fired for "a creature you control". Unclaimed: the ordinal state trigger ("when the fourth plan counter is put on ~"), "investigate that many times", an intervening-if on the graveyard ("if ~ is in your graveyard").
- **PAR-139 — the small residue batch (closed completely, v566–567):** (1) `extra_etb_counter` gained a `filter`/`other` pair — "each [other] `<kind>` you control enters with an additional +1/+1 counter on it" (`static_handlers._extra_etb_counter_specs`, `continuous.extra_etb_counters_for`; Grumgully, Bramblewood Paragon, Dragonstorm Globe, Sage of Fables, Renata, Slinza, Oona's Blackguard); (2) a trigger *condition* may contain a list comma ("whenever you discard a noncreature, nonland card, …", "an island, pirate, or vehicle card, …" — `segmenter._TRIGGER_RE`; Bone Miser, Mary Read and Anne Bonny, Surly Badgersaur, Waste Not); (3) "~ deals 2 damage to any target. If you're the monarch, it deals 7 damage instead." — a replacement naming no recipient hits the base's own (`_resolve_override_referents`; Court of Ire, Frost Bite, Summary Judgment); (4) "its owner shuffles their graveyard into their library" (`shuffle_graveyard_into_library(owner_of_source)`; Emrakul, the Aeons Torn, Ulamog, the Infinite Gyre — the trigger from a graveyard already worked); (5) RULE 702.35 "if its madness cost was paid" — the `madness_cost_paid` flag stamped at cast (both cast paths, in `ANNOUNCED_FLAGS`), parsed for an ETB intervening-if (Grave Scrabbler); **madness overrides that read the madness `{X}`** ride the generic "instead" path once the replacement's "X of those tokens"/"among those permanents and/or players" is spelled as the base's own (From Under the Floorboards, Avacyn's Judgment; the same rewrite also claimed the kicker "create 12 of those tokens instead" family, Conqueror's Pledge/Saproling Migration), and Welcome to the Fold is hand-authored (`effect_conditions._evaluate` binds a `toughness`/`power`/`mana_value` bound of `"x"` to the spell's announced X); (6) a standing `prevent_damage` with a `combat` source filter, a `requires_counter` gate ("while it has a +1/+1 counter on it") and the rider kinds `add_scaled_counters` (`on: self|recipient`), `add_self_counter`, scaled/clamped `remove_self_counter`, `mill` with a factor, `exile_top_of_library_scaled`, `gain_life` and `reflexive_damage` (a fresh RULE 603.11 trigger sized by the amount prevented) — Phyrexian Hydra, Stormwild Capridor, Vigor, Purity, Vindicator, Oathsworn Knight, Undergrowth Champion, Ugin's Conjurant, Angel of Suffering, Gloom Surgeon, Ironscale Hydra, Panther Habit; the **one-shot** form "Prevent the next N [X] damage … to target creature. For each 1 damage prevented this way, put a +1/+1 counter …" / "you gain life equal to the damage prevented" (`_PREVENT_SHIELD_THEN_RIDER_RE`; Test of Faith, Temper, Candles' Glow) — plus the missing base row "prevent the next N damage that would be dealt to target creature this turn", which alone unlocked ~14 cards (Alms, Anoint, Kei Takahashi, …); a *targeted* one-shot shield had silently dropped its `rider` (fixed, with the spell controller as the rider's "you"); (7) corpse-counter reanimation: `exile_instead_of_leaving` (a `WOULD_DIE` → exile replacement shared with Unearth, `_exile_instead_of_dying`; the same simplification — a bounce/blink that keeps the card is not modeled), `exact_mana_value` on graveyard targets with `"x"` bound by a preceding "pay {X}" (Isareth), the named `corpse` counter on the reanimate rows, and take-the-initiative/become-the-monarch as referent-transparent interstitials (`_REFERENT_TRANSPARENT_TYPES`). **Still unclaimed from the ticket's scope:** Magma Pummeler/Sekki (a shield with a *second* reflexive/token rider), Callous Giant ("3 or less damage"), Sacred Boon/Scars of the Veteran (a delayed counter rider), Gatta and Luzzu, Impulsive Maneuvers, The Mindskinner.
- **Files:** `parser/oracle/catalogue/{handlers,object_trigger_head,static_handlers,replacements}.py`, `segmenter.py`, `spec.py`, `gate.py` (PARSER_VERSION 566), `game/effects/{choices_actions,exile_control,library,registry,replacements,core}.py`, `game/{continuous,effect_conditions,static_conditions,isa}.py`, `game/rules/{damage_death_mixin,casting_mixin,search_mixin,misc_mixin}.py`, `game/binding/core.py`, `models/game/game_object.py`. Tests: `tests/test_par136_delayed_blink.py`, `test_par137_impulse_draw.py`, `test_par138_counters_put_trigger.py`, `test_par139_residue_batch.py` (each parses *and* executes against a real engine; the execute tests found two real bugs — a missing function-scoped `combat` import in the entry-counter path and the group-trigger controller key above).

### PAR-109: the small residue batch for static/activated abilities and mana (PARSER_VERSION 567, +131 over v566 with PAR-139, 0 regressed)

- **"Creatures you control with `<qualifier>` get/have …"** (~36 cards): the anthem, keyword-grant and quoted-grant rows (`static_handlers._ANTHEM_RE`/`_GRANT_RE`/`_QUOTED_GRANT_RE`) gained an optional qualifier tail (`_QUAL_TAIL`), read back through the shared `object_filter` grammar (`_qualifier_params`, fail-closed): keywords (the closed `_FILTER_KEYWORD_WORDS`, widened to vigilance/trample/deathtouch/lifelink/infect/flanking/double strike/indestructible/hexproof), "+1/+1 / `<kind>` counters on them", "that are enchanted/equipped" (new `combat.matches_object_filter` keys `enchanted`/`equipped`, a battlefield scan), "that entered this turn", "power N or greater" and "with the chosen name" (`card_name_from_source`). The plural-subtype **group pump** ("Dragons you control get +1/+0 until end of turn", Lathliss, Ran and Shaw) came from one generic alternative in `handlers._GROUP`, failing closed through `parse_count_phrase`'s vocabulary — +48 cards, the biggest single yield; every emitted selector was read back for the cards it claimed.
- **Counters:** "if 1 or more counters would be put on `<a permanent you control | an artifact or creature you control | a permanent your team controls>`, that many plus 1 of each of those kinds" and "if you would put … / get …" (`double_counters` with `plus` and no `kind`; Winding Constrictor, Doc Samson, Pir, Lae'zel — recipient modes `artifact_or_creature_you_control`, `you_player`, `creature_planeswalker_or_you`; a permanent-scoped recipient no longer matches a *player* counter event). **"Team" is read as "you"** — no teams exist in this engine.
- **Engine statics, each its own marker layer:** `untap_each_untap_step` ("Untap ~ during each other player's untap step", `GameEngine._step_untap` — Bender's Waterskin, Thousand Moons Infantry), `activate_as_though_haste` (`combat_mixin._summoning_sick_for_tap` is now an instance method — Thousand-Year Elixir, Shang-Chi, Tyvar; attacking still needs real haste), `ALL_CREATURE_TYPES` ("equipped creature gets +N/+N and is every creature type": a `changeling` marker in `_added_subtypes`, honoured by `has_subtype`).
- **"Spend only `<colour>` mana on X"** on an *activated* ability (Crypt Rats, Crimson Hellkite): `X_SPEND_COLOR_MARKER` folded by `bind_ability` into `ActivationCost.x_spend_color`, applied through `ManaCost.with_x_colored` at every X-resolving site (`_activation_mana_with_x`, `_max_x_for_mana`); on a *spell* the same line sets `GameObject.x_spend_color_restriction` (Consume Spirit; Drain Life's hand-authored route).
- **Granted land mana abilities:** "basic lands you control have '{T}: Add …'" (`object_filter {"basic": True}`) and the two spend restrictions a granted ability prints, `contains_x` and `instant_or_sorcery_spell` (Nexos; the parser cannot import `game/`, so the restriction dicts are mirrored).
- **Also:** "permanents your opponents control lose hexproof and indestructible until end of turn" (Shadowspear).
- **Left open, one clause each:** Brad Boimler's until-end-of-turn counter replacement; Worldknit's card-pool condition; "can't be regenerated" leftovers (Bone Shaman's quoted form, Lim-Dûl's Cohort — "that creature" is a block's other side, needing a trigger-related referent); Desolation of Smaug's "spend only to cast Dragon spells"; Luxior's per-counter equipment bonus; Atalya's modal `{X},{T}` body. (Alchemy's `conjure`, which Stormforged Armor / Kari Zev's Alchemy printings use, is a permanent non-goal — see `DEFERRED.md`; the saved decks use the paper printings.)
- **Files:** `parser/oracle/catalogue/{static_handlers,handlers,replacements}.py`, `segmenter.py`, `game/{combat,continuous,effect_conditions}.py`, `game/effects/{replacements,registry}.py`, `game/engine/{turn_loop_mixin,combat_mixin,activation_mixin}.py`, `game/binding/core.py`, `game/costs.py`, `game/rules/{mana_counters_mixin,damage_death_mixin}.py`, `game/isa.py`. Tests: `tests/test_par109_batch.py` (parse and execute for every bullet).

### PAR-102: a pump that also grants — quoted abilities, a choice of keyword, "dies this turn" (PARSER_VERSION 568, +46 over v567, 0 regressed)

The ticket's premise was stale: the plain "gets +N/+N and gains `<keyword>` until end of turn" tail (its part (a)) already parsed. What was left were the *tails* the pump row could not read, each its own axis:

- **A quoted ability after the pump** ("Until end of turn, target creature gets +2/+0 and gains "When this creature dies, return it to the battlefield tapped under its owner's control."" — Abnormal Endurance, Hunter's Prowess, Dreadmaw's Ire, Tower Above, Full Steam Ahead, Dead Before Sunrise, Root Manipulation, Greater Stone Spirit, …): `handlers._pump_and_quoted_grant` emits the ordinary `pump` (it picks the recipient) followed by a `grant_until` over the same `static_handlers._quoted_ability_grant_effects` the Aura/Equipment rows use, replaying the recipient (`previous_subject`; a self subject grants its own source). The duration must be written, at the front or the back, or the clause stays unclaimed (without it the grant would be permanent). `_pump_then_grant` is the shared tail for every "pump and also grant X" row. **A group subject locks its set** — `GrantUntilEffect.lock_group` resolves the static's own `affects` selector once at resolution (RULE 611.2c), so a creature that enters later this turn gets neither the pump nor the grant (it did get the grant before this, as `grant_until`'s group form keeps its selector live; the old "until your next turn" group grants still do).
- **"…and gains all creature types"** (Volatile Claws; the Shields/Blades of Velis Vel forms use a multi-target subject and stay open): the `ALL_CREATURE_TYPES` layer-4 marker through the same tail.
- **"Target `<subtype>` creature gets +2/+2 and has `<keyword>` for as long as ~ remains tapped"** (the five Courier/Cohort creatures — Pearlspear, Frightshroud, Ghosthelm, Flamestick, Everglove): one `grant_until` carrying the `anthem` and the keyword, a RULE 611.2b `for_as_long_as` duration with `source_tapped`, and `GrantUntilEffect.creature_filter` for the subtype target.
- **A parametric `toxic N` in a granted list** (Aspirant's Ascent): `toxic` joined the grantable parametric keywords — it needs no trigger builder, `combat.toxic_value` reads the granted N at damage time — and the pump row's keyword list now goes through `_split_keywords_with_parametric`.
- **"gains your choice of flying, vigilance, or haste until end of turn"** (25 cards: Alchemist's Gift, Argivian Avenger, Steel Seraph, Golem Artisan, Butcher of the Horde, Ezrim, Manifold Mouse, Atraxa's Skitterfang, …): `PumpEffect.keyword_options` + a `keyword_choice` pending choice (`RulesEngine._request_keyword_choice`/`_resume_keyword_choice`, the `counter_kind` pattern: park the effect, targets and `previous_targets`, resume with a copy granting the pick). Flag keywords only; "protection from red", a landwalk of your choice and the like leave the clause unclaimed.
- **"…When `that creature` dies this turn, `<effect>`"** after a clause that chose a creature (A Good Day to Die, Make Your Mark, Otherworldly Outburst, Felonious Rage, Blessed Defiance, Grim Javelineer, …): `CreateTurnTriggerEffect.previous_subject` bakes the preceding clause's chosen creature into the turn-long trigger's condition (the PAR-124 `instance_id_override`), and `segmenter._turn_trigger_segment` reads "that creature" only when a previous clause did choose one.
- **Left open, per card:** the multi-target forms ("any number of target creatures each get +1/+0 and gain "…"", the Velis Vel pair); "choose target creature. When that creature dies this turn, …" and its bodies (earthbend, "its controller gets a poison counter", experience counters, Burn Away's graveyard exile — each a body gap, not the trigger); "if it's a `<type>`, instead/also …" riders on the pump (Fey Steed-shaped); Galuf's Final Act (the quoted body "put a number of +1/+1 counters equal to its power on up to one target creature"); Unnatural Moonrise / Into the Night ("it becomes night", 3 cards, 5 with the day/night restrictions); the static "equipped/enchanted creature gets +N/+N and has "…"" and "`<group>` get … and have `<parametric keyword>`" forms (PAR-109's territory — Biorganic Carapace, ward/afflict/afterlife grants); triggers whose *head* is the gap (another target knight, "target creature you control with toxic").
- **Files:** `parser/oracle/catalogue/handlers.py`, `segmenter.py`, `game/effects/{counters_tokens,choices_actions,registry}.py`, `game/rules/mana_counters_mixin.py`, `game/rules_engine.py`, `gate.py` (PARSER_VERSION 568). Tests: `tests/test_par102_pump_quoted_grant.py` (parse, execute — a granted dies-trigger returning the creature tapped, a locked group, a granted toxic poisoning, the picked keyword, the while-tapped grant ending for good — and adversarial shapes).

### Batch 4: "create a token that's a copy of …" (PARSER_VERSION 569, +31 over v568, 0 regressed)

Not ticketed (PLAY-ALL Step 1). The family was already large (`copy_permanent`, PAR-18/124/142); what still blocked ~150 single-gap cards were four independent axes plus one engine bug:

- **The head takes a count and flags** (`handlers._COPY_HEAD`/`_copy_head_params`, shared by the target, `~`, pronoun and trigger-subject rows): "create 2 tokens that are copies of target token", "create X tokens …" (the `"x"` count sentinel), "create a tapped / tapped-and-attacking token …", "create 2 tapped tokens that are copies of ~" (Cheer, For the Common Good, Sandstorm Crasher, Skyclave Relic, Compy Swarm, Uugguu).
- **Two target vocabularies** (engine and parser in step): `token` / `token_you_control` and a general "you control" slot over `artifact` / `enchantment` / `artifact_or_enchantment` (`subgrammars.YOU_TAIL` + `YOU_TARGET_KINDS`, `targeting.TARGET_FRAMES` + the `token` pool; Esika's Chariot, Three Blind Mice, Caretaker's Talent, Donatello, Chrome Dome, Adagia, Urza Prince of Kroog). The slot is general, so it also claimed "return target artifact you control to its owner's hand" (Ingenuity Engine, Nobody), "exchange control of target artifact you control …" and "up to one other target enchantment you control" — each read back, each a correct narrowing. A pool without a `*_you_control` frame stays unclaimed ("target planeswalker you control"), and a row that already named its own scope ("another target red creature you control") resolves exactly as before.
- **The pronoun row** takes "that creature / permanent / artifact / enchantment / land" after a clause that chose it ("Choose target creature you control. Create a token that's a copy of that creature." — `copy_permanent_previous`, still `previous_subject_only`).
- **The bare "It gains haste."** after a copy / token / reanimation clause (Cogwork Assembler, Chrome Dome, Grave Upheaval, Kami of Industry, Momo's Heist, Felhide Spiritbinder, Flameshadow Conjuring, …) is an **indefinite** grant — `grant_until(rest_of_game, previous_subject)` — which is what the text says; the earlier draft read it as until end of turn, which is wrong for Grave Upheaval (no sacrifice follows). `GrantUntilEffect.previous_subject` falls back to `created_objects` like `PumpEffect` does. "the token" joined the singular-pronoun list.
- **Engine bug, fixed:** after "create a token that's a copy of **target** X" the next clause's "it"/"that token" read the *original* permanent, because `_apply_effects_partitioned` hands an effect's own targets on as `previous_targets` and a targeted copy made its token only in `created_objects` — so "…It gains haste." (and the pump rows that already existed, e.g. Tempestra, Kiki-Jiki-style tails) granted the original, not the copy. `CopyPermanentEffect.created_objects_are_referent` makes the loop hand the copies on instead.
- **Tried and dropped:** a self-subject "create a token that's a copy of **it**" row (Sphinx of False Conclusions, Vaultborn Tyrant, Watchful Radstag, Skitterbeam Battalion) — `self_subject_only` is also true for a player-event trigger, so Welcome to Mini-apolis ("whenever an opponent casts a creature spell, create a token that's a copy of it") would have copied the *source*. It needs the trigger's subject kind at handler level.
- **Left open, per card (each its own body):** "of a creature card exiled with ~" / "the exiled card" (Gut ×5 specialize, Dollhouse of Horrors, Dino DNA, Mardu Siegebreaker — a linked-exile referent); "for each opponent / each creature target player controls" player-scoped copies (Clone Legion, Face Yourself, Elminster's Simulacrum, "its controller creates …" — Bramble Sovereign, Dual Nature, Parallel Evolution, Fractured Identity); random or named pools (Pool of Vigorous Growth, The Wizardly Barge, the Mox Painter, Disciple of Vess); "choose a nonlegendary creature that saddled it" and the other Calamity/Echoing-Assault attack shapes; except-tails with a rewritten name, loss of all other types, "half that creature's power", a quoted ability naming the token (`~` in a granted ability), "it enters with an additional +1/+1 counter"; the trigger-subject "it" row above.
- **Files:** `parser/oracle/catalogue/{handlers,subgrammars}.py`, `game/targeting.py`, `game/effects/{counters_tokens,core}.py`, `gate.py` (PARSER_VERSION 569). Tests: `tests/test_batch4_token_copy.py` (vocabulary sync, parse, execute: a counted X-copy of a token you control with the legal-target pool checked, the artifact pool excluding the opponent's, the copy — not the original — keeping its haste).

### PAR-107…114 residue batches: the sacrificed-creature amount, "or pay {N}" costs, kept mana, edicts by mana value (PARSER_VERSION 577, +221 over v576, 0 regressed)

The ticket lists were stale (several clusters had drifted to one card), so the batch was sized with a scan-once multi-regex probe and built as *axes*; most of the +221 came from axes the listed cards only touched. Tests: `tests/test_par107_114_{graveyard_library,misc,costs}_family.py`.

- **Library and graveyard.** `return_to_library` takes `depth` (RULE 401.7, "Nth from the top"), a self form ("put ~ / it …", Fell Horseman, God-Eternals, Bookwurm), `group` ("put all creatures on the bottom …", Terminus) and `search` the `library_third` destination (Long-Term Plans); the "… into its owner's library second/third from the top" targeted row was the same axis (Oust, Chronostutter). `exile_hand_card` gained `zone="graveyard"` (the targeted player chooses), `TargetSpec.min_mana_value` ("or greater", exile and destroy), graveyard type words "artifact and enchantment" / "artifact or creature". "Look at the top N … put them back in any order" is now `look_reorder_top` (own or target library, X through a `, where x is …, then …` rewrite, optional `shuffle_offer`) instead of `scry`, which had wrongly offered the bottom. `look_at_hand` is an informational `look_hand` choice (only its decider ever sees it — `game_session._redact`). Blink takes plural targets, "tapped" and the owner form (Displace, Gandalf, Brago). Search criteria "an instant card or a card with flash" and "a land card with a basic land type".
- **Amounts.** "The sacrificed creature's power / toughness / mana value" is one amount term (`count_phrase.SACRIFICED_TERM`) read from stamps `RulesEngine.note_sacrificed` writes for a cost *and* for an effect's own sacrifice, so Fling, Altar-style and "you may sacrifice … when you do" shapes agree. `where x is the greatest/total …`, `… minus N` (floored), `-X/-X` bound as `-$n`, `greatest_commander_mana_value`, "…destroyed/exiled this way" tallies (`this_way`), `this spell costs {X} less, where X is <amount>` (this also unlocked the devotion and total-power discounts), `scry/surveil x`.
- **Triggers and mana.** `is tapped for mana` as a trigger verb (Wild Growth family, "an additional" wording, "2 mana in any combination of colors" = two single picks); `add N {R}`, `add that much {G}`, "you get that many {E}". `ManaPool.kept`: a trailing "Until end of turn, you don't lose this mana as steps and phases end." tags the preceding `add_mana` (`keep_until`); kept mana survives step ends, expires at end of combat / cleanup, and is spent last.
- **Costs.** `additional_cost["or_mana"]` generalizes `sacrifice_or_mana` to any single cost (discard, sacrifice a `<type>`, exile N cards from the graveyard, reveal a `<type>` card from hand) — mana is the default cast, the other cost the `pay_additional` variant; `legal_actions` now offers the paid variant when only it is castable, and `ActivationCost.label` leaves the mana half out of it. "During turns other than yours, spells you cast cost {1} less" (`not_your_turn`).
- **Misc.** `counter` target kind `spell_or_ability` (Disallow) and `mana_value: x` (Spell Blast); `you win the game`; edicts by greatest power / mana value as sacrifice or exile with the tied leaders as the chosen player's pick (`SacrificeEffect.greatest/action`); `mill half their library`; a turn tally of cards played from exile.
- **Bugs found on the way.** An ability `StackItem` was read as a player by `effect_operands._is_player` and as nobody by `effect_conditions._object_or_none`, so "counter target … ability. Its controller loses …" did nothing.
- **Left open, per card** (also in `workingOn.md`): see the PAR-107/108/110/113/114 points in `BACKLOG.md`; Visions of Phyrexia waits on a Powerstone token (not in `data/tokens.json`) and the "can't be spent to cast nonartifact spells" restriction.
- **Files:** `parser/oracle/{segmenter,spec,gate}.py`, `catalogue/{handlers,static_handlers,count_phrase,history_phrase,subgrammars}.py`, `game/{costs,targeting,continuous,effect_operands,effect_conditions,static_conditions}.py`, `game/effects/{core,registry,stack,life_sacrifice,damage_draw,counters_tokens,returns_graveyards,choices_actions,composition}.py`, `game/rules/{damage_death,search,draw_discard,mana_counters,misc}_mixin.py`, `game/engine/{casting,activation,legal_actions,turn_loop,misc,lands}_mixin.py`, `models/mana/mana_pool.py`, `models/game/{game_state,turn_history}.py`, `frontend/src/js/gameBoardView.js`.

### PAR-107…114 residue batches, run 2: either/or additional costs, "look at their hand and choose", "turns other than yours", the Visions discount, mass-damage riders (PARSER_VERSION 578–581, +59 over v577, 0 regressed)

Same method as run 1 (probe the listed cards, build the axis, execute-test). Tests: `tests/test_par107_114_{costs,hand_pick,other_turns,mass_damage}_family.py`.

- **Either/or additional cast costs with no mana half.** `additional_cost["either"]` = `[A, B]` (two single-component branches from the `or_mana` vocabulary); `ActivationCost.either_alt` holds B. A is the plain cast, B the `pay_additional` variant — the same two-variant shape `or_mana` uses — so `legal_actions` offers a variant per payable branch and `_can_pay_additional_cast_cost`/`_pay_additional_cast_cost` swap to the alternative. The split point is the first " or " leaving two valid single costs ("pay 5 life or sacrifice a creature or enchantment" splits after "life"); a compound sacrifice type ("a creature or enchantment", "a creature or land", "a permanent") is one cost, not two branches. `tap_others` is now payable as a cast cost ("tap an untapped artifact you control or pay {1}", Disruption Protocol). Closed: Bone Shards, Minion Missile, Bitter Triumph, Demand Answers, Souls of the Lost, Final Payment, Disruption Protocol, Final Flare, Final Vengeance, Heartfire, Merciless Resolve.
- **"Look at target player's hand and choose N cards".** `reveal_hand_choose_discard` gained `count` (an int or X), `up_to` and `destination` (`discard` / `library_top` / `library_third`, the new `hand_to_library_*` choose-object actions, RULE 401.7); the chooser is still the caster, the card goes to its owner's library. Mind Warp, Abandon Hope, Extortion, Agonizing/Painful Memories, Lost Hours, Discordant Dirge (X = verse counters via `bind`), Thrull Surgeon. Picks go on top in the caster's pick order (later picks end higher) — the "in any order" choice is the pick order.
- **"During turns other than yours, `<static>`".** The existing "During your turn" leading row now takes either polarity (`not_your_turn`); a gated "~ is a 2/3 Gargoyle artifact creature with flying" / "~ is an artifact creature" is a layer-4 `type_change` (with the base P/T when printed) plus a keyword grant, reachable only under the gate (ungated it stays unclaimed). Mesa Lynx, Glory of Warfare, Vibrating Sphere, Oak Street Innkeeper, Warden of the Wall, Midnight Mangler.
- **The Visions flashback cycle.** "Flashback {8}{G}{G}. This spell costs {X} less to cast this way, where X is the greatest mana value of a commander you own …": the gate hands the keyword half to `parse_keywords` and the sentence to the existing self `cost_reduction` row, gated by the new `source_in_graveyard` static condition. Visions of Dominance/Duplicity/Glory (Dread and Ruin wait on their own bodies).
- **Mass damage.** `…without flying and each planeswalker` (Magmaquake; `each_creature_and_planeswalker` with the keyword filter on the creatures only), `damaged_this_turn` as a `matches_object_filter` key (Inflame), and `amount_if_kicked` on a mass hit (Cinderclasm).
- **Kept mana, part 2 (v579).** `add_mana` with the `"ANY"` offer narrowed to named colours: "add X / that much / N mana in any combination of colors or {R} and/or {G}", "add that much mana of any 1 color" (`any_amount_from_trigger_event`), and "add {R} or {G}". A fixed N is N independent single picks (exactly RULE 106.1); a variable amount keeps the one-colour-for-all simplification Culling Ritual already documents. Closed: Manamorphose, Cosmic Crucible, Realm-Scorcher Hellkite, Klothys, Kessig Naturalist, Photon, Grand Warlord Radha. **Latent bug fixed on the way:** "that much/many" under "whenever one or more creatures you control attack" read `PLAYER_ATTACKED`, which carries no amount, so the effect saw 0 ("gain that much life" gained nothing); the segmenter now retargets such a body to `ATTACKERS_DECLARED` with the measured `bind`, and a group-filtered head of that kind fails closed. Test: `tests/test_par107_114_any_mana_family.py`.
- **"Whenever a player attacks" (v580).** `player_event_head` reads "a player / an opponent attacks [with N or more creatures]" as `ATTACKERS_DECLARED` with the actor scope — once per declaration, where `PLAYER_ATTACKED` would fire once per defender — and "each of your opponents" is the `each_opponent` damage selector. Avatar Roku, Aurelia. The other heads of that cluster (the Curses' "attacks enchanted player", Ellie, Mirkwood Trapper, Suppressor Skyguard, Total War) need their bodies' "that player"/"they" referents and stay open.
- **Singletons one row away (v581, +19).** Prison Break ("with an **additional** +1/+1 counter" — the same counter, which also closed Evil Reawakened, Generous Revival, Rakdos Joins Up); Sister of Silence (the `spell_or_ability` pool now honours a `spell_filter` on its spell half); Terisian Mindbreaker (`MillEffect` `defending_player` selector); Open the Vaults ("from all graveyards … under their owners' control" = `each_player`); Shattered Ego (`ReturnToLibraryEffect` `attached_permanent`); Aligned Hedron Network, Consulate Crackdown, Temporary Lockdown (a mass "exile all/each `<group>` until ~ leaves the battlefield": the plain mass-exile reading plus `remember`, which now links every exiled card in `linked_exile_ids` for the companion return). **A gate on the pick's mana value:** "If its / that permanent's mana value was N or less, …" after a targeting clause reads the printed mana value (zone-independent) as `of: previous_target`; power, toughness and keywords stay refused because they are last-known information the engine does not keep (RULE 608.2h). It closed Carnivorous Canopy, Fading Hope, Extinguish the Light, Tainted Treats, Raze to the Ground, Containment Breach, Perilous Voyage and Vindictive Triumph — whose "return it to the battlefield" first resolved to the *spell* (a wrong-but-MODELED reading caught by the execute test); `ReturnSelfToBattlefieldEffect` now takes `target_kind="previous_target"`. Test: `tests/test_par107_114_singletons_family.py`.
- **Left open, per card** (also in `workingOn.md`): see the PAR-107/108/110/113/114 points in `BACKLOG.md`.
- **Files:** `parser/oracle/{segmenter,spec,gate}.py`, `catalogue/{handlers,static_handlers,player_event_head}.py`, `game/{costs,combat,static_conditions}.py`, `game/effects/{damage_draw,registry}.py`, `game/engine/{casting,legal_actions,activation}_mixin.py`, `game/rules/misc_mixin.py` (PARSER_VERSION 578).

### PAR-107…114 residue batches, run 3 (closed): "that attacking player" bodies, the adventure filter, two mass hits, "lose X life", the hybrid "if {w} was spent" cycle, "skips their next …" (PARSER_VERSION 582–584, +84 over v581, 0 regressed)

Same method (probe the listed cards, build the axis, execute-test). Tests: `tests/test_par107_114_{attacking_player,adventure_filter,mass_damage_pairs,skip_step}_family.py` (40). Full pytest incl. `--full-cache` 10,811 passed.

- **A body that speaks of "that attacking player" / "they" runs *as* that player.** `trigger_subject_referent` gained `acting="event_player"` (no firing object is looked up; the acting player is the event's `player_id` / `attacking_player_id`, RULE 109.5). The acting player has to survive a pause, so `OptionalEffect`'s choice and `pay_cost_then`'s pending dict now carry `acting_player_id` and restore it when the answer arrives (before this, "that attacking player may discard a card. If they do, they draw a card" asked the right player and then drew for the Curse's controller). The segmenter rewrites the body to its second-person form (`_event_player_body`) and refuses when the body also says "you"/"target" or holds an effect outside the whitelisted set (`_ACTING_EVENT_PLAYER_TYPES`). **Heads** (`player_event_head`): "attacks you / enchanted player / 1 of your opponents [with N or more creatures]" are `PLAYER_ATTACKED` with `defender_is_you` / `defender_is_enchanted_player` / `defender_is_opponent` (+ `attackers_at_least`); "1 or more of your opponents" is `ATTACKERS_DECLARED`, whose event now lists `defending_player_ids` so those predicates read both events (`binding/core._attacked_player_ids`). "…creates a tapped `<token>` that's attacking that opponent" is the existing `attacker_creates_attacking_token` (Combat Calligrapher's primitive) with the token read by the ordinary create-token grammar and "named X" folded in. Closed: Curse of Chaos, Curse of Shallow Graves, Everett K. Ross, Ellie Brick Master, Jolene, Xorn, Tippy-Toe.
- **"Instead create those tokens plus an additional Treasure token"** is `additional_named_token` (Peregrin Took's primitive) with `only_token` narrowing it to one named kind (Xorn, Jolene), or none (Tippy-Toe).
- **"A card that has an adventure".** The `has_adventure` filter key existed; it is now reachable from the graveyard-return row (Edgewall Inn), the count grammar (`that has an adventure`, and `you own …` for a non-battlefield zone: Howling Galefang's "as long as you own a card in exile that has an adventure", Dreadlight Monstrosity's "activate only if you own a card in exile") and the group enters-with-counter row (Mysterious Pathlighter).
- **Two mass hits in one sentence.** "~ deals 1 damage to each nonblack creature and an additional 1 damage to each green creature" / "…and 1 additional damage to each blue creature" is two ordinary mass-damage effects (Kaervek's Hex, Tropical Storm). "…where X is the number of colors of mana spent to cast this spell" is the existing `converge` selector (Radiant Flames). "…where X is `<count>` plus the number of `<count>`" reads as a sum (Calamitous Cave-In). "~ deals N damage to `<A>` and M damage to you" and the other **elided second conjunct** that repeats only the amount noun (`_ELIDED_AMOUNT_VERBS`) now parse; a second target reading "any other target" / "another …" / "player or planeswalker" is refused because the target-kind resolver drops the distinctness / the planeswalker half (a latent inaccuracy of the single-sentence forms, which this does not extend; now **ENG-52**).
- **"Lose X life".** The `lose_life` row accepts `x` (the announced {X}, or the one a "where X is …" binds), which unlocked the whole "you lose life equal to …" family: Vendetta, Devour in Shadow, Castle Locthwain, Starlit Sanctum, Maga, Shaman of the Pack, Filthy Cur, Cut of the Profits, Skeletal Scrying, Damnable Pact, Monumental Corruption, Exotic Disease, Fell Beast of Mordor and others. **Two latent bugs surfaced on the way and are fixed.** (1) In "target player gains 3 life **and draws a card**" the second verb has no subject and used to parse to a bare `draw`/`gain_life`/`lose_life`/`discard` acting on the *controller* (Sign in Blood is hand-authored and was the only correct one): the connector loop now stamps `previous_subject` / `player: {"of": "previous_player"}` on a subject-less third-person verb after a "target player/opponent" clause (`_stamp_previous_player`), and a verb with no such reading (mill) refuses the sentence — this fixes BUG-2's direct-trigger shapes (Vault Plunderer, Bloodgift Demon), the reflexive/exploit ones are still open in BACKLOG. (2) A shared "where X is the greatest power / the sacrificed creature's power" over "target player loses X life and you gain X life" bound only the second half (`_WHERE_X_AMOUNT_RE` was not tried for the shared-X path), leaving the first on the spell's own X.
- **The hybrid cycle: "if {w} was spent to cast this spell".** One state predicate (`mana_color_spent_to_cast_at_least`, Adamant's fact, amount 1) in the shared condition vocabulary, reached through the generic if-prefix / if-suffix rows; a trailing comma before "and" is stripped so "…if {g} was spent, and … if {u} was spent" splits. Closed: Firespout, Dawnglow Infusion, Invert the Skies, Unnerving Assault, Revenant Patriarch, whose "if {W} was spent to cast it" is a true RULE 603.4 intervening-if (`_etb_intervening_if`: the trigger-level `active_if`, so there is no stack object and no target prompt when white was not spent). What was spent to cast is history, so the resolution re-check is dropped for this kind: read off a source that has left the battlefield (a new object, RULE 400.7) it would disagree with last-known information. Other leading-if conditions of an enters trigger (kicked, "you control a Forest") still keep the resolution check alone.
- **"You may have target creature get +N/+N / gain K".** "have … get" is only how the optional wording carries the verb; it reads as "you may target creature gets …" (14 cards: Blightcaster, Battle-Rattle Shaman, Painsmith, the cycling trio, Kinsbaile Balloonist, …).
- **"Creatures target player controls get +N/+N [and gain K]"** is `PumpEffect.group_player`: the group is written for "you" and evaluated for the player the spell targets (Arms of Hadar, How to Start a Riot, Torrent of Souls, Neutralize the Guards, Shields of Velis Vel, the modal Commands).
- **"`<player>` skips their next untap step / draw step / combat phase".** `skip_next_step` takes a player target, `each_opponent` or the firing event's player (a damage event names it `target_id`); a skipped phase marks its `GamePhase.skipped` when its first step opens and every step of it is passed over (RULE 500.11). Fatigue, Brine Elemental, Blinding Angel, Stonehorn Dignitary, Moment of Silence, Shisato's trigger half. "That player" after a clause that *chose* a player (Dovin) stays unclaimed — only the firing-event reading is built.
- **Left open, per card (cause, not a ticket):**
  - *Needs a mechanic that does not exist:* the Blitz alternative cost (Sabin, Tenacious Underdog's graveyard cast; Henzie, Riveteers Provocateur grant it) — RULE 702.152 is recognition only, now **MEC-109**; casting the Adventure half from the graveyard for a limited time (Hildibrand, Mosswood Dreadknight); the Powerstone token and "can't be spent to cast nonartifact spells" mana (Visions of Phyrexia, Karn Legacy Reforged, PAR-133); mana that is both restricted and kept (Klauth, Karn, Tanuki Transplanter, The Bloodsky Massacre, Shizuko, Neheb ×2, Tundra Fumarole's `{S}`, Sap Sucker); additional upkeep steps (Obeka); copy-"except" (Chameleon, Mercurial Pretender, Aurora Shifter); the Contraption/Planar/Interplanar vocabulary (Planequake, Interplanar Brushwagg, Sap Sucker).
  - *Needs one more clause shape each:* "creatures target player controls …" with a trailing "untap them" (Great Oak Guardian) or a tap rider (Yosei); Flame Sweep's "except for creatures you control with flying" (a negated conjunction the group filter cannot express); Baki's Curse (damage per Aura on each creature); Monsoon / Angel's Trumpet (a tally of what a tap actually tapped); Living Death / Living End / Destined Confrontation / Slaughter the Strong / Blood Money / Deadly Tempest / Singularity Rupture (per-player tallies of what a mass destroy took, or "any number of target players"); "counter up to one target `<kind>`" (Repel Intruders, Repulsive Mutation, Tishana's Tidebinder); the hybrid cycle's remaining bodies (Batwing Brume's per-attacker life loss, Boros Fury-Shield's "damage to that creature's controller equal to its power", Induce Paranoia's mill, Flash Conscription's quoted grant, Moonhold's "can't play lands this turn", Vigor Mortis); the remaining attack bodies (Curse of Inertia's "of their choice" target, Mirkwood Trapper, Suppressor Skyguard, Total War's "didn't attack", Lulu's "choose target creature attacking you", Emberwilde Captain's monarch gate, Cunning Rhetoric/Davriel/Jace's "and/or planeswalkers"); Eldritch Pact / Estinien's X over "their graveyard" / "your opponents who were dealt combat damage"; Bulwark, Spellstutter Sprite, Spy Network, Graveyard Shift's flash gate, Graveyard Shovel / Grave Birthing's "if it's a creature card" rider; Anthropede, Baru, Nahiri's Sacrifice, Dargo, Visions of Dread / Ruin; Sailors' Bane / Memory Theft / Sentinel of Lost Lore (an OR over several card kinds in one count, and exile-zone adventure cards by owner).
- **Files:** `parser/oracle/{segmenter,gate}.py`, `catalogue/{handlers,static_handlers,count_phrase,player_event_head,replacements}.py`, `game/binding/core.py`, `game/effects/{core,composition,counters_tokens,registry,replacements}.py`, `game/rules/{casting,misc}_mixin.py`, `game/engine/{combat,turn_loop}_mixin.py`, `game/phases.py`.

### PAR-105 + batch 5: library/graveyard cast permissions and "counters on each `<group>`" (PARSER_VERSION 570, +84 over v569, 0 regressed)

PAR-105 ("you may cast creature spells from the top of your library") was only the smallest face of a closed-vocabulary problem: `TopLibraryPermissionEffect` knew five printed phrasings and one hand-picked filter flag each (`noncreature_only`, `creature_only`, `subtypes`). It now carries what the text says.

- **Top of the library** (`parser/oracle/catalogue/library_permission.py`, `parse_top_library_permission`; ~16 cards — Elven Chorus, Garruk's Horde, Ranger Class, Korlessa, Nalia de'Arnise, Emperor Mihail II, Hakoda, Madame Web, Traveling Chocobo, Errant and Giada, Crystal Skull, Benjamin Sisko, Assemble the Players, Johann, Augur of Autumn, Summoning Materia): the spell kind is a `card_query` criteria dict built through `dig.parse_criteria` — types and subtypes, lists ("cleric, rogue, warrior, and wizard", "instant and sorcery", where the "and" is an or), "noncreature", "colorless", "historic", keywords ("with flash or flying" → `has_keyword` alternatives), "with power N or less/greater", "with mana value …" — plus a land filter for "play snow/historic lands", and a leading "once each turn,". A rarity ("common spells"), an unknown keyword, an alternative cost or a rider outside the two the old row knew leaves the line unclaimed. The old closed row stays first, so its five phrasings produce byte-identical specs. Engine: `spell_criteria` / `land_criteria` on the effect (`top_library._grant_permits_cast`, `may_play_land_from_top_of_library(card=)`), **`once_each_turn`** (one use per granting permanent per turn, `GameObject.top_library_uses_this_turn`, spent by `record_top_library_use` at the cast / land-play choke points and reset at the controller's untap step), and an **`active_if` gate** — which fixes a latent gap: the effect is not a `StaticAbility`, so the "as long as …" and Class-level (`min_level`/`level_counter`) wrappers the parser already stamped on a `top_library_permission` were silently ignored; `registry._top_library_gate` translates them to one `static_conditions` dict and `active_top_library_grants` evaluates it live.
- **The graveyard sibling** (`parse_graveyard_cast_permission`; Karador, Gisa and Geralf, Danitha, Kess, Gravecrawler, Oathsworn Vampire, The Indomitable, Skaab Ruinator, Lightwheel Enhancements' max-speed grant): "once during each of your turns, you may cast a `<kind>` spell from your graveyard[. If … exile it instead.]" onto `GraveyardCastPermissionEffect` (`spell_criteria`, `active_if`, the existing per-object once-per-turn counter and exile rider), and "you may cast this card from your graveyard [as long as / if `<condition>`]" onto `SelfGraveyardOrExileCastPermissionEffect`, which gained `zones` (graveyard only vs Squee's both) and `active_if` (evaluated for the casting player in `GameEngine._self_graveyard_or_exile_cast_permission`). A condition outside `static_conditions`' vocabulary fails the line closed.
- **"Put a +1/+1 / -1/-1 counter on each [other] `<group>`"** (`handlers._ADD_PT_COUNTER_GROUP_RE`, ~50 cards — Dueling Coach, Edgar, Oran-Rief Ooze, Acid-Spewer/Belltoll/Herdchaser Dragon, Agent Phil Coulson, Camellia, Arcbound Shikari, Drana, Biogenic Ooze, Duskfang/Frillscare/Hornbash Mentor, Choking Fumes, Light of the Legion, Titans' Vanguard, Novijen …): the group is read through the shared `parse_count_phrase` grammar into `AddCountersEffect.group` (the named-counter row had it since PAR-128), now also with `other` → `group_other` ("each **other** Dragon you control" excludes the source, RULE 109.5 — the structured grammar has no spelling for it) and with qualifiers such as "with a +1/+1 counter on it", "attacking", "that entered this turn", "with lifelink". The closed `add_counters_selector` row still goes first, so every phrase it read produces the same spec; a stale pin ("each nonblack creature" must stay unclaimed) was updated to the structured reading it now has.
- **Left open, per card:** top-of-library permissions with a rider or alternative cost (Galea, Mikey & Don, Thundermane Dragon, Falco Spara, Into the Pit, Gwenom, The Belligerent — "if you cast a spell this way …", "by sacrificing …", "pay life …"), "play cards" (Fortune Teller's Talent), Cemetery Illuminator's "shares a card type with a card exiled with ~", the Fourth/Eighth Doctor's "play a historic land or cast a historic spell, once each turn" (a land-or-spell single use with a flavour prefix); graveyard permissions with an alternative or additional cost (Alien Symbiosis, Helbrute, Rona, Squee Dubious Monarch, Demonic Embrace, Wickerfolk Indomitable, Scourge of Nel Toth, Noctis, Exploration Broodship, Maestros Ascendancy), a dynamic mana-value bound (Arcade Gannon), Finale of Promise / Invoke Calamity (free casts of several spells), the Blitz/Mutate/Bestow/Warp "using its … ability" forms (PAR-107's list), Haakon's "but not from anywhere else"; mass counters whose amount reads the recipient ("a number of +1/+1 counters equal to that creature's toughness" — Canopy Gargantuan), the compound "… and a loyalty counter on each other planeswalker" (Ajani, Brokers Ascendancy), "toughness less than the number of basic land types" (Zar Ojanen) and "named ~" groups (Baloth Packhunter, Charmed Stray).
- **Files:** `parser/oracle/catalogue/{library_permission,static_handlers,handlers}.py`, `game/{top_library,graveyard_cast}.py`, `game/effects/{game_status,counters_tokens,registry}.py`, `game/engine/{lands_mixin,casting_mixin,turn_loop_mixin}.py`, `models/game/game_object.py`, `gate.py` (PARSER_VERSION 570). Tests: `tests/test_par105_library_graveyard_permissions.py` (criteria shapes, adversarial phrases, the engine filters / once-each-turn / gate / real cast, the graveyard conditions, the group-counter execution).

### Batch 6: Siege and Enduring cycles, "twice X", the wheel, "equal to the greatest …", damage "to target `<X>` equal to the number of …" (PARSER_VERSION 571, +111 over v570, 1 removed on purpose)

Not ticketed (PLAY-ALL Step 1). The plan called it "cycles through `register_family`"; sizing with `parser_probe.py blocked` showed the cycles were mostly shared *axes*, so the batch closed the axes and the cycle members came with them. Every saved-deck card on the list (Will of the Temur / Mardu / Jeskai / Abzan, Erebos's and Thassa's Intervention, Court of Garenbrig, Disorder in the Court, Frontier / Outpost Siege) is now `MODELED` and executes.

- **"As ~ enters, choose `<A>` or `<B>`." + "• `<A>` — `<ability>`" bullets** (Siege cycle: Barrensteppe, Citadel, Frontier, Frostcliff, Glacierwood, Outpost, Palace, Windcrag): `modal.split_named_choice_block` reads the header and its two labelled bullets, `gate._process_named_choice_block` emits the existing `choose_named_mode` replacement plus each option's ordinary ability gated on `GameObject.chosen_mode` — a trigger by its `named_mode` key, a static by an `active_if` of the new `static_conditions` kind `chosen_mode`. The static gate is a whitelist (`gate._NAMED_MODE_STATIC_EFFECTS`: anthem, grant_keyword, trigger_doubler and the three library/graveyard permissions, each of which reads `active_if`); an option built from any other effect type fails the whole block closed instead of applying unconditionally. "Choose odd or even / a colour" has no bullets and stays unclaimed. Two trigger heads came with it: "at the beginning of **each of your main phases**" (both mains, two triggers through `Segment.extra_specs`; the singular "your main phase" is not a printed template and stays unclaimed) and "at the beginning of **combat on each opponent's turn**" (Citadel Siege, Sentinel of the Eternal Watch).
- **Enduring cycle** ("When ~ dies, if it was a creature, return it to the battlefield under its owner's control. It's an enchantment."): one row onto the existing `dies_return_as_enchantment` (Courage, Curiosity, Innocence, Tenacity; Enduring Vitality is the hand-authored original).
- **"twice X"** (Heliod's / Erebos's Intervention, Drown in Dreams, Procrastinate, Purphoros's and Nylea's amounts): the `"twice_x"` sentinel next to `"x"` / `"half_x_*"` (`RulesEngine._substitute_x`, also inside `create_delayed_trigger`'s nested specs), `COUNT_X` + `count_or_x_of`, and per-row widenings (gain life, "deals twice X damage" to a target and to each creature with a keyword, mill, "pays twice {X}" as `{x}{x}`). "Exile up to twice X target cards from graveyards" is a new multi-target row (`any_graveyard_card`, `TargetSpec.count_selector="source_twice_x_paid"`); the pick count is capped at the shared "any number" cap of 10.
- **Dig with an `x` count** (PAR-144 refused it): allowed for a spell or an activated ability, where the sentinel is the announced X (Flash of Insight, Enshrined Memories, Thassa's Intervention); `gate._dig_x_ok` refuses it under a trigger, and "where X is …" never reached the row. "Put **up to** N of them into your hand" joined the dig grammar.
- **Damage "to target `<X>` equal to the number of `<Y>`"** (`segmenter._DAMAGE_TO_EQUAL_TO_RE`, 44 cards: Earth Tremor, Mob Justice, Fire Dragon, Spire Barrage, the Mountain-count burn spells, Will of the Mardu's second mode, …) — the sibling of the "deals damage equal to the number of `<Y>` to target `<X>`" spelling the where-X pass already read; the count is bound once through `bind`. **"…equal to the greatest `<power|toughness|mana value>` among `<group>`"** (`_EQUAL_TO_AGGREGATE_RE`, ~12 cards: Garruk Primal Hunter, Rishkar's Expertise, Rush of Knowledge, Torrent of Fire, Huatli, Arni Slays the Troll, Will of the Temur's draw) reads the amount through `count_phrase.parse_amount_phrase`; "other" creatures exclude the source because the bind's reference defaults to it.
- **The wheel** (Reforge the Soul, Wheel of Fate, Dragon Mage, Magus of the Wheel, Runehorn Hellkite; Raphael's Technique, Ruin Grinder, Will of the Jeskai): "each player discards their hand, then draws N cards" is the hand-authored Wheel of Fortune's `seq`; "each player **may** discard their hand and draw N cards" is a loop over the players whose body asks that player (`optional` with `player="target"`, the loop item handed in as the target) and then acts on them — each player answers for themselves.
- **Smaller rows:** "draw an additional card" (draw-step trigger; Overbeing of Myth, Heightened Awareness, Monastery Siege's Khans); "each opponent / target opponent sacrifices a creature with the greatest power among creatures they control" (`SacrificeEffect.greatest_power`, Professor Onyx's hand-authored original — Crackling Doom, Consumed by Greed, Extract a Confession); "distribute N counters among **1, 2, or 3** / **up to N** target creatures" (Court of Garenbrig, Biogenic Upgrade, Armament Dragon, Ajani Mentor of Heroes, Glint Weaver, Wurmskin Forger, Defend the Celestus, Storm the Seedcore, Revival of the Ancestors — the split is the documented auto-even one, so a player choosing one target gets the whole pool); "investigate X times" and "return the exiled cards to the battlefield **tapped** under their **owners'** control at the beginning of the next end step" (Disorder in the Court, Hide on the Ceiling; `ReturnSpecificToBattlefieldEffect.tapped`); "any number of target opponents each sacrifice … and lose N life" (Will of the Abzan: a bare `choose_targets` plus a `for_each` over exactly the chosen opponents); "create a number of `<token>`s equal to the number of creatures **target player** controls" (Will of the Mardu: the count taken as that player, `effect_amounts`' `of: "target"`).
- **Wrong-but-MODELED claims found while reading the specs of every newly covered card — fixed, not shipped:**
  - **"Tap X untapped artifacts you control" as a cost** was parsed by `costs.py` as a count of 1, so Secluded Starforge (already `MODELED`) tapped one creature whatever its X, and the dig change would have added Merchant's Dockhand and Belisarius Cawl the same way. `gate._tap_x_cost_ok` now fails such an ability closed (Secluded Starforge drops out of the covered set on purpose). X-sized tap costs need a `tap_others` count sentinel like `SACRIFICE_COUNT_X` — Secluded Starforge, Dockhand, Cawl, Necron Overlord, Resonance Technician, Aryel, Glacian, Myr Battlesphere.
  - **A turn-scoped graveyard flashback grant from a spell** ("Each instant and sorcery card in your graveyard gains flashback until end of turn", Will of the Jeskai, Past in Flames) was appended to the *spell*, which has left the stack by the time anything asks, and `active_graveyard_cast_grants` only scanned permanents — the grant never existed. It now also scans the player's graveyard and exile for grants that carry `expires_turn`.
  - **Pit of Offerings'** "Add one mana of any of the exiled cards' colors": the mana engine claimed the line and produced only {C}. `mana_abilities._IMPRINTED_COLOR_ADD_RE` now takes the plural, the menu reads every id in `linked_exile_ids`, and the gate stamps `remember` on the ETB graveyard exile when the card prints that line.
  - **Bighorner Rancher's** "Add an amount of {G} equal to the greatest power among creatures you control" produced one {G} (`mana_abilities._EQUAL_TO_GREATEST_POWER_RE` onto Selvala's `greatest_power_control`).
  - **"target artifacts and/or enchantments"** (multi-target) resolved to the `permanent` pool and so offered creatures and lands (Heliod's Intervention would have been wrong); it is now `artifact_or_enchantment`, with "artifacts and/or creatures" as its own `artifact_or_creature` row (Hide on the Ceiling, Baral's Expertise, Involuntary Cooldown, Repulsor Bots). Two stale pins (`test_multi_target`, `test_distinct_controllers`) were updated.
- **Left open, per card:** Akroma's Will ("protection from each color"), Kamahl's / Sakashima's / Szat's Will (animate lands, "target opponent chooses a creature they control. You gain control of it", copy-of-chosen, exile graveyards then X tokens); Hollowmurk Siege ("whenever a counter is put on a creature you control"), Battle of Hoover Dam / Mirrodin Besieged / Phenomenon Investigators (bodies of their own); Nylea's Intervention ("search … for up to X land cards"), Purphoros's Intervention (an X/1 token sacrificed at the next end step), Confront the Past, Stargaze, Khaaaaaaaaaaaannn!, Sanguine Sacrament, Lifestream's Blessing; "exile up to N target cards from **a single graveyard**" (Decompose, Rapid Decay, Scarab Feast, Shred Memory, Rats' Feast — needs a same-graveyard constraint); Genesis Wave / Saheeli's Directive (a mana-value `x` bound in a dig); "tap X untapped …" costs (above).
- **Files:** `parser/oracle/catalogue/{handlers,modal,dig,subgrammars}.py`, `segmenter.py`, `gate.py` (PARSER_VERSION 571), `game/{static_conditions,graveyard_cast,mana_abilities,targeting}.py`, `game/effects/{choices_actions,registry}.py`, `game/rules/casting_mixin.py`. Tests: `tests/test_batch6_named_choice_and_enduring.py` (parse and adversarial shapes for every row; executes: the Siege static / permission gates, Heliod's life, Drown in Dreams' mill, Erebos's pick count, Thassa's double-X tax cost, Pit of Offerings' colours, the Rancher's mana, the greatest-power draw, both wheels with per-player answers, the greatest-power edict, distribute-then-double, Disorder in the Court end to end, Will of the Abzan / Mardu / Jeskai).

### PAR-144: the "dig" family — look at/reveal the top N, take a kind, put the rest away (PARSER_VERSION 565, +115 covered, 0 regressed)

- **What:** "Look at/Reveal the top N cards of your library. You may reveal a `<kind>` card from among them and put it into your hand / onto the battlefield. Put the rest on the bottom of your library / into your graveyard." One composed grammar (`parser/oracle/catalogue/dig.py`, one row `dig_top_choose` that owns only the first sentence and hands the rest to `parse_dig`) over four independent axes, so a future card recombining known values needs no new row: **count** (a literal N), **kind + how many** (a / up to N / any number of / all, kind → a `card_query` criteria dict), **destination** (hand, battlefield, battlefield tapped) and **rest** (bottom, graveyard, shuffled back in). It was found by sizing, not by the saved-deck list: 195 cards had this as their only unclaimed clause cache-wide against ~27 in saved decks (PLAY-ALL Step 1, batch 1).
- **Engine:** no new effect type — `inspect_top_choose` (`InspectTopChooseEffect`, MEC-72) widened. `criteria` (a `models/cards/card_query` dict, ANDed with the old `filter` keys; named `criteria` so `_substitute_x` reaches its mana-value bound), `max_picks="all"`, `else_effects` ("if you didn't put a card into your hand this way, …" — rides `_request_choose_objects`' existing `else_specs`, and now also fires when nothing in the top N matched), rest `library_shuffled`, and action `library_to_battlefield_tapped`. `card_query` gained `all_types` (AND: "dragon creature", "legendary artifact") and `has_x_cost`, and its `type` match is now **whole-word** — it was a substring, so "orc" matched "Sorcery" (and "ape" "Shape"); no existing test or card relied on the substring.
- **Parser details worth knowing:** a bare "card" is `{}` (any card); "permanent" expands to the six permanent types, "historic" to artifact/legendary/saga; a comma/"or" list of type words is one OR-list when every item is a single `type`, otherwise `{"or": [...]}`; a bare type word before the item that carries "card" ("an elf, warrior, or tyvar card") belongs to the same list; the verb "reveal" is only accepted with its "and put it" half (without it the put would silently vanish). Trailing sentences go back through `match_clause`, so "create 2 1/1 tokens" / "you gain 3 life" ride along.
- **`x` (batch 6 update):** a count of `x` is now read for a spell or an activated ability (the announced X) and refused under a trigger (`gate._dig_x_ok`); a mana-value bound of `x` is still refused, so Genesis Hydra/Wave, Geometer's Arthropod, Knickknack Ouphe and Vivien's Arkbow stay unclaimed, and Belisarius Cawl / Merchant's Dockhand stay unclaimed behind their "tap X untapped …" cost.
- **Unclaimed in this family (≈95 cards still SOLO-blocked, by cluster):** two separate picks in one sentence ("a creature card **and/or** an enchantment card", "up to 1 land … tapped and up to 1 elf …"); "for each card type, you may put a card of that type" (Atraxa, Grand Unifier); the picked card gets a rider ("it gains …", "if it's legendary, you gain 3 life", "with a shield counter"); the opponent chooses/exiles a card among them (Animal Magnetism, Allure of the Unknown); "cast a spell from among them" (Aetherworks Marvel and the impulse-cast family — a different mechanic); "chosen type"/"shares a creature type with …" kinds; "with a kicker ability". Each is its own axis; none was bundled in here.
- **Files:** `parser/oracle/catalogue/dig.py` (new), `handlers.py`, `gate.py` (PARSER_VERSION 565, `PARSER_VERSION.lock`), `models/cards/card_query.py`, `game/effects/{returns_graveyards,registry}.py`, `game/rules/{search_mixin,misc_mixin}.py`. Tests: `tests/test_par144_dig_family.py` (criteria vocabulary, refusals, whole-word type match, six executes against a real engine incl. else tail, decline, forced "all", tapped lands, shuffled rest).

### PAR-135: the base-grammar residue closed (PARSER_VERSION 564, +82 covered, 0 regressed)

- **What:** the six gaps PAR-123 found were each a *shared axis* with a closed list on it; they closed together with the counter work (the "Named counters" entry under Counters).
  - *"any target that isn't a `<subtype>`"* (Wrathful Raptors/Red Dragon) and "…that isn't a commander" (Lozhan): a quality-tail slot next to "without flying" — `subgrammars._ISNT_A_TAIL`, read back by `isnt_a_filter` (subtype → `without_subtype`, card type → `without_card_type`, commander → `is_commander: False`); a word outside that vocabulary leaves the kind unresolved instead of dropping the filter, and "any" is the one extra pool it may narrow. Engine: `legal_targets`' `any` branch now applies `creature_filter` to creatures only (players, planeswalkers and battles are never a subtype and stay legal); `combat.matches_object_filter` reads `is_commander: False`.
  - *"Do this only once each turn."* (Ondu Spiritdancer, Irreverent Gremlin, Legolas, Leonardo, Deep Gnome Terramancer): an *action* limit, not `trigger["limit"]` — the ability still triggers every time and declining doesn't use the turn's one performance up. The clause is a marker effect (`ACTION_ONCE_PER_TURN_MARKER`); `spec.fold_action_limit` turns it into one `seq` gated by `action_unused_this_turn` (`static_conditions`, reading `GameObject.action_turns[key]`) with an `action_stamp` (`ActionStampEffect`) placed *where the action is accepted* — first in a plain body, first inside the `optional`/`pay_cost_then` node when the "may" is inside (a first version stamped at ability resolution, which spent the limit on a decline). `TriggeredAbility.action_key` lets a repeat firing skip its prompt. The parser nests the marker inside `pay_cost_then.effects`, so detection can't be top-level only; a marker it can't place, or on a non-trigger, fails the card closed (`gate._action_limit_ok`). `action_stamp` is the one new `SPECIAL` row in the ISA inventory (bookkeeping, not a rules action; budget 57 → 58).
  - *Power-only doubling* (Bulk Up, Double Trouble, Mr. Orfeo, Mightform Harmonizer, Devilish Valet, Tifa Lockhart, Rasaad's toughness, Casey Jones, Death Kiss, Two-Handed Axe): a `stat` slot on the four double/triple rows (`PumpEffect.self_multiplier_stat`: both/power/toughness), plus group-trigger and attached-host pronoun rows (`trigger_subject` / `attached_permanent`). Not claimed: "double its power **X times**" (Exponential Growth), "…and it gains first strike" (Legion Leadership), "attacks a battle" (War-Trained Slasher's trigger head).
  - *Additive colours:* "a black Zombie in addition to its other **colors and** types" is a layer-5 `color` static with `set: False` riding the existing PAR-140 `becomes_in_addition` row (colour-only "becomes blue in addition to its other colors" too; `that creature is`/`each of those creatures is` after a pick; "with base power and toughness 4/4" as the other spelling of a base P/T). For a *copy*, `CopyPermanentEffect.add_colors` — expressed through `Card.as_copy(set_colors=copied ∪ added)` in `copy_permanent`, because editing `models/cards/card.py` changes the card-cache schema hash and wipes the production cache. `_parse_copy_except_tail` no longer splits "colors **and** types" at its "and" (Ratadrabik, Dread Slaver, Liliana Death's Majesty, Indigo Faerie, Relic's Roar). Not claimed: the plural "they're black Zombies" (Ghouls' Night Out, Grimoire of the Dead), "that creature is …" after a delayed return (Grave Betrayal), Halsin's "target token you control".
  - *Equipment:* see "Two independently-chosen targets in one clause".
- **Wrong-but-MODELED claims caught by reading the emitted specs of every newly covered card** (this is where the batch's real work was): asymmetric counters, "or fewer/or more" counter conditions, the pronoun-condition scope, Kitnap's counters on the Aura, Famous Museum / Lotus Blossom mana, the action limit's decline path, and an Equipment losing its host on a control change.
- **Unclaimed in this family, with the reason:** Barret ("target Rebel you control" has no bare-subtype target row), Frodo ("target Equipment … with mana value 2 or 3"), Amy Rose/Shagrat (rider clauses of their own), Stolen Uniform/Ogre Geargrabber/Grip of Phyresis (a gain-control prefix), Hidden Blade & the "attach it to target `<subtype>` you control" family.
- **Files:** `parser/oracle/catalogue/handlers.py`, `subgrammars.py`, `static_handlers.py`, `segmenter.py`, `gate.py`, `spec.py`, `game/binding/core.py`, `game/effects/{core,library,counters_tokens,game_status,registry}.py`, `game/{targeting,combat,static_conditions,isa,mana_abilities}.py`, `game/rules/{copies_mixin,casting_mixin,triggers_mixin}.py`, `models/game/game_object.py`. Tests: `tests/test_par135_named_counters.py` (77).


### PAR-121 (first step): one "unless you pay" row over the verb (PARSER_VERSION 454)

- **What:** `_SACRIFICE_/_DESTROY_/_TAP_/_EXILE_UNLESS_PAY_RE` were four registrations of "`<verb>` ~


### PAR-121 closes: the subject slot and the connectives declared once (PARSER_VERSION 564, 0 clause readings changed)

- **What:** the ticket described "a third of the regexes in near-duplicate clusters". An audit first (every one of the 39,639 clause × subject-flag readings the cache reaches, run against all 629 rows in order, recording each clause's first claimant and every later row that also matched) found the clusters are *not* shadowed rows — 33 rows never first-claim a corpus clause, and all but one of those match nothing in the corpus at all (they exist for cards not printed yet, which is not redundancy); the exception is a strict subset: `exile_another_target` (`TARGET` has carried "another" since PAR-128, so the plain `exile` row always won) — deleted. The duplication is *code*, so it was folded where one table can say it once:
  - **verb × subject:** `_subject_handlers(rows)` over `_SUBJECT_FLAGS` (self/previous/group/attached) replaces a row-and-builder per reading. Applied to "its controller `<verb>`" (the 14 group/attached rows and their 14 builders → `_its_controller_spec` + a matrix; the `previous` readings stay separate, they resolve through `previous_targets`), the double/triple-pronoun rows, `pump_*_subject_x`, `gain_life_eq_*` and the new `attach_chosen_*` rows. The remaining repeated-regex pairs are already tables (`_POWER_DAMAGE_ROW_SPECS`, `_FIGHT_ROW_SPECS`) or two rows far apart where order is the point.
  - **connectives:** `segmenter._CERTAIN_ANTECEDENT_ROWS` — sacrifice-of-source, earthbend and bare-discard "…. When/If you do, `<effect>`" were three copy-pasted blocks; each keeps its own connective regex (that is what keeps a *may* antecedent from collapsing) and one loop reads them. Roll-a-die, exile-delayed-return, counter and tap have genuinely different bodies and stay.
  - **targeted damage:** `_targeted_damage` is the one place that merges kind, "up to one" and the creature qualifier; four amount spellings call it (the mana-value one had silently never merged the qualifier).
- **How it was proved:** a fingerprint of every clause reading and every card's full spec list before and after each consolidation — 0 changed in 39,639 readings and 34,811 cards — plus `tests/test_par121_subject_rows.py` pinning the exact specs of the cells no printed card reaches. The 16 `*_DEVOTION_*` rows are *not* folded into `count_phrase`: each carries its own effect's parameter mapping (draw count vs life amount vs counter count), so the shared part is the `{DEVOTION}` fragment, which they already share — the ticket's "32 rows" was stale (16 exist).
- **Files:** `parser/oracle/catalogue/handlers.py`, `segmenter.py`. Tests: `tests/test_par121_subject_rows.py`.

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
- **Land source exclusion (PARSER_VERSION 606).** Ordinary `land` targets include their source, so they cannot be in `SOURCE_EXCLUDED_TARGET_KINDS`. Dedicated `other_land`/`other_land_you_control` frames now preserve land filters and controller scope while excluding the source for "another/other target land". Grammar, verb binding and offered-target regressions cover both ordinary and source-excluded forms.
- **Verb whitelists.** 37 per-verb `kind not in (...)` checks became `target_kind_allowed(kind, allowed)`, which walks `SCOPED_TARGET_BASE` (a scoped kind or type union narrows its base), so "destroy/return/tap/put a counter on target creature an opponent controls" work without each verb listing each scope. The pronoun-antecedent check in the segmenter reads the same way.
- **Union bug.** The N-way "target X, Y, or Z" row also matched "target artifact or enchantment", so Naturalize, Disenchant and ~100 others could target any permanent; the dedicated two-type rows now sit above it (`artifact_or_enchantment`, `artifact_or_creature` in either order). 124 already-covered cards changed kind accordingly.
- **One gate over "A, then B".** "If `<cond>`, A, then B" handed B to the connector split ungated: Canyon Crab, Wistfulness, Statute of Denial, Contaminant Grafter, Scion of Vitu-Ghazi and So Shiny did their second half regardless, and Airbender Ascension's "exile …, then return it" became "return the source". The existing one-gate rule now covers ", then" as well as "and".
- **Player subject.** "each player / each opponent `<verb>`" parses the verb as "target player `<verb>`" and iterates it with `for_each {"players": …}` (every effect must target exactly that player); "target opponent `<verb>`" narrows the target to `opponent`. The token rows' `who` slot takes "target player/opponent" (`creators: target`, the Hunted cycle).
- **Yield** (with batch 6): 17,515 → 17,641 (+126, 0 regressed); Commander-legal 53.3%. Open residue is in PAR-128's `workingOn.md` block.
- **"Another/other" on a graveyard card and an unscoped group (PARSER_VERSION 519, +20, 0 regressed).** `_GRAVEYARD_OTHER` is an optional `another/other` slot before "target" in the five graveyard return/put rows; it is a pure grammar slot because `legal_targets`' graveyard branch already leaves out the ability's own source (`o is not source` — Junk Diver's dies trigger is the case it matters for). `_GROUP` gained "all other creatures", "other attacking creatures" and "each other creature", read through `parse_count_phrase`'s existing `not_reference` filter (`_GROUP_SELECTORS` holds the singular "each other creature" as a structured selector). `damage_selector` takes "each other creature" → `DealDamageEffect`'s new `each_other_creature` selector (`_DAMAGE_OTHER_SELECTORS`, kept off `_DAMAGE_SELECTORS` because `library.py`'s power-damage effect shares that set and only iterates `each_creature`). Tests: `test_par128_target_scope.py` (parse + execute + real cards).
- **Controller scope around a quality filter and on plural targets (PARSER_VERSION 522, +10 more, 0 regressed).** `_CREATURE_FILTER_SCOPED` puts an optional `NOT_YOU_TAIL` on either side of the power/toughness/keyword filter in the destroy/exile/damage "target creature with …" rows (`_scoped_creature_kind`; scope written on both sides is refused), giving `creature_you_dont_control` + `creature_filter` (Arbor Colossus, Elektra, Hidden Dragonslayer, Mudbutton Cursetosser). `_MULTI_TARGET_ALT` carries an optional plural scope tail ("your opponents control" / "an opponent controls" / "you don't control"), composed in `_multi_target_kind` only for the rows with a scoped pool (`_MULTI_TARGET_SCOPED_KINDS` — creatures, creatures and/or planeswalkers, nonland permanents, permanents, artifacts and/or enchantments; "target artifacts"/"target lands" read as broad `permanent` and stay unclaimed), so every plural verb takes it (Intrusive Packbeast, Roiling Waters, Saiba Trespassers, Sea God's Revenge); `_tap_multi_target` reads its whitelist through `target_kind_allowed`. `skip_next_untap_target` takes the scope too (Fogwalker, Skyline Cascade).
- **Scope on a group filter and on divided damage (PARSER_VERSION 523, +3, 0 regressed).** `damage_each_creature_keyword` takes the plural scope tail → `each_creature_opponents_control` + `selector_filter`, which that `DealDamageEffect` branch now applies (it ignored the filter before); `_DIVIDED_DAMAGE_RE` takes it and composes through `NOT_YOU_TARGET_KINDS` (bare "targets" has no scoped pool → unclaimed). Dragonlord Atarka, Ureni, Sagittars' Volley covered; Thundermaw Hellkite ("tap those creatures" after a group hit has no referent) and Polukranos ("each of those creatures deals damage equal to its power") stay open.
- **"Each other player" as an edict subject (PARSER_VERSION 524, +3, 0 regressed).** `_SACRIFICE_EDICT_SELECTOR_WORDS` reads "each other player" as `each_opponent`, the same reading `_SELECTOR_WORD_MAP` already gives it (no team play). Grave Pact, Rampage of the Valkyries, Savra, Queen of the Golgari.
- **Opponent-scoped and "other" mass selectors (PARSER_VERSION 525, +2, 0 regressed).** `_DESTROY_ALL_OPP_SELECTORS` gained `all_creatures → opponents_creatures` (the selector Llawan's bounce already used) so "destroy all creatures your opponents control" no longer fails closed on the scope (Dread Cacodemon — the ", then tap all other creatures you control" tail was already claimed); "return all other nonland permanents" reads a new `all_other_nonland_permanents` mass selector (`_mass_selector_objects`, in `_MASS_DESTROY_SELECTORS`, source excluded — Kederekt Leviathan).
- **"Those creatures" after a mass selector (PARSER_VERSION 531, +10, 0 regressed).** The MEC-28 `previous_selector` chain (`GameContext.previous_selector`, replayed through `group_selector_objects`) only announced two fixed selector values, so "creatures you control get +2/+1 until end of turn. Untap those creatures." had no referent. `segmenter._announces_group_selector` now also accepts an *unnarrowed* group: a pump whose selector is a structured `{"zone","of","filter"}` dict and whose params are only P/T/keywords (`_BARE_PUMP_PARAMS`), and a tap over one of `_SELF_DESCRIBING_TAP_SELECTORS` with no subtype rider (`_BARE_TAP_PARAMS`). The restriction is deliberate: the context records only the selector, so a subtype/filter param layered beside it would be lost by the pronoun (Valley Floodcaller's own note). New rows `tap_previous_selector` ("[then] tap/untap those creatures/them") and `skip_untap_previous_selector` ("they/those creatures don't untap during their controller's next untap step / their controllers' next untap steps"); engine: `TapEffect` resolves the `"previous_selector"` sentinel like `PumpEffect` does, and `SkipNextUntapEffect(subject="previous_selector")`. War Flare, Tenacity, Gleam of Resistance, Rallying Roar, Rally to Battle, Join Shields, Flying Crane Technique, The General, Essence of Antiquity, Clinging Mists. Tests at the end of `test_par128_target_scope.py`.
- **"Those creatures" after mass damage (PARSER_VERSION 532, +1, 0 regressed).** A creature-only mass `damage` clause (`each_creature`, `each_other_creature`, `each_creature_opponents_control`) now announces a group too (`_CREATURE_MASS_DAMAGE_SELECTORS`, mirrored by `attachments_transforms.PREVIOUS_GROUP_DAMAGE_SELECTORS`). Its group is *whoever the hit landed on*, not a re-run of the damage selector: `_apply_effects_partitioned` records `previous_selector = DAMAGED_GROUP_SENTINEL` (`"damaged_this_way"`) and `previous_group_objects` resolves that to `GameContext.damaged_this_way` (MEC-81's hit set), so a prevented hit is left out. `TapEffect` and `SkipNextUntapEffect` read the previous group through that helper. Thundermaw Hellkite; Pump/AddCounters do not read the sentinel yet.
- **"Those creatures" after counters on a mass group (PARSER_VERSION 533, +5, 0 regressed).** An unnarrowed `add_counters` creature group (`_CREATURE_MASS_COUNTER_SELECTORS`, params only kind/selector/count) announces its group; `_apply_effects_partitioned` records the `group_selector_objects` name via `counters_tokens.ADD_COUNTERS_GROUP_AFFECTS` (a subtype or `creature_filter` narrowing is *not* recorded — the context keeps only the name, so the pronoun would over-reach). Existing `tap_previous_selector` / `pump_previous_selector` rows do the rest: Virtue of Loyalty, Felidar Retreat, Domri City Smasher, Spider-Man Miles Morales, Now for Wrath, Now for Ruin!. Tests in `test_par128_target_scope.py`.
- **A targeted body under "for each `<quantity>`" (PARSER_VERSION 534, +21, 0 regressed).** `_bound_for_each_amount` refused any body that announced a target — a rule written for `for_each`, which hands each iterated object to the body *as its target* and would overwrite the RULE 115 pick. The path here is `bind`, which runs its body exactly once and forwards `BindEffect.target_specs`, so the refusal only blocked correct cards: "target opponent loses 1 life for each Vampire you control" (Bishop of the Bloodstained), "target opponent discards a card for each Shrine you control" (Honden), "target creature gets +1/+1 for each basic land type" (Gaea's Might), "put a +1/+1 counter on target creature for each …" (Canopy Crawler, Grief Tyrant, Lotleth Giant, Trenchpost, …). The measured amount never reads the target, so nothing else changes. **Duress-family fix in the same pass:** the `discard` row collapsed "target opponent" to `target_kind: "player"` (a discard that could be aimed at yourself); it now emits `opponent`, and `test_par36_discard_at_random.py`'s two pins, which had frozen the collapse, are corrected. Tests in `test_par128_target_scope.py` (parse, target-spec forwarding, executed life loss). Full suite and `--full-cache` tier green.
- **Duress family: opponent target + comma form (PARSER_VERSION 535, +2, 0 regressed).** `_HAND_DISRUPTION_RE` had the same "target opponent" → `player` collapse as `discard` (a Thoughtseize aimed at yourself); "target opponent" now emits `target_kind: "opponent"`, "target player" stays `player`. The pattern also reads the comma spelling ("… reveals their hand, you choose … from it, then that player discards that card"). Devour Intellect's "instead" override now shares one `opponent` requirement across both branches (`_instead_override_specs` refuses branches whose targets differ, which is why the two rows had to be fixed together); River's Grasp's second gated mode is claimed too.
- **Controller scope after a quality filter in the mass "can't block" group (PARSER_VERSION 536, +1).** `_CANT_BLOCK_TURN_GROUPS` gained "creatures without/with flying your opponents control" (`opponents_permanents` + `without_keyword`/`keyword` filter — `CantBlockEffect` already narrows through `matches_object_filter`). Stoneshock Giant.
- **"Put a counter on each of them" after a multi-target clause (PARSER_VERSION 537, +7, 0 regressed).** `AddCountersEffect.previous_subject` only ever read the *first* of `GameContext.previous_targets` ("tap target creature and put a stun counter on it"); the new `previous_group` flag walks all of them, and the `add_counters_previous_group` row ("put a/N +1/+1 | -1/-1 | stun counter(s) on each of them / each of those creatures / those creatures", `previous_subject_only`) emits it. Kinds are limited to the ones with a known engine reader (RULE 122.1c stun via `set_tapped`). Out Cold, Homesickness, Donatello Rad Scientist, Succumb to the Cold, Twisted Riddlekeeper, Stall for Time (kicker gate), Nature's Panoply. Still open: "on each of those creatures you don't control" (Lost in the Maze) and "each of those creatures" after a mass tap (Monstrosity of the Lake).
- **The general mass tap, "tap/untap all `<group>`" (PARSER_VERSION 538, +27, 0 regressed).** Mass tap had one dedicated row per phrase ("creatures you control", "Forests you control", "white creatures you control", "attacking creatures", …) and nothing for the rest — "tap all creatures your opponents control", "tap all nonwhite creatures", "tap all artifacts", "untap all creatures and lands" were a 37-card solo cluster. `tap_all_group` reads the group through `parse_count_phrase` and emits a *structured* selector; `attachments_transforms._is_valid_tap_selector` now accepts a battlefield `{"zone","of","filter"}` dict, which `TapEffect` already routed through `group_selector_objects`. It sits after the dedicated rows so their named selectors keep winning; any phrase carrying "target"/"that player" is refused. A bare structured tap selector also announces a replayable group (`_announces_group_selector`), so the `previous_selector` chain covers it: `AddCountersEffect(previous_selector=True)` (row `add_counters_previous_selector`) resolves "…then put a stun counter on each of those creatures" (Monstrosity of the Lake). Blinding Light, Bond of Discipline, Metal Fatigue, Ensnare, Githzerai Monk, Ivory Giant, Breaching Leviathan (also its "don't untap" tail), Awakening, Merrow Commerce, Aether Shockwave, Cryptic Command and 14 more. Known gap: "creatures without flying" isn't a `parse_count_phrase` shape (Deluge) — closed in v542 below.
- **"without `<keyword>`" as a tail of the shared object phrase (PARSER_VERSION 542, +3, 0 regressed).** `characteristic_phrase.parse_object_phrase` had "with `<qualifier>`" but no negation, so every phrase built on it (count phrases, mass taps, filters) failed on "creatures without flying". `_WITHOUT_TAIL` reads it (keyword vocabulary only, via `KEYWORD_WORDS`; "without flying or reach"/unknown words refuse) into `combat.matches_object_filter`'s existing `without_keyword`, in either tail order relative to the controller phrase. Deluge, Aboshan Cephalid Emperor, and Crimson Roc's "whenever ~ blocks a creature without flying" trigger filter (`related_filter`).
- **"Any player may activate this ability" as a parsed rider (PARSER_VERSION 543, +15, 0 regressed).** `ActivationCost.any_player_may_activate` (MEC-30) existed and three cards had been hand-authored on it (Mercenaries, Nullhide Ferox, Oft-Nabbed Goat's inverse), but the oracle front-end never set it, so the whole ~27-card cluster stayed unclaimed on a rider alone. `segmenter._ANY_PLAYER_MAY_ACTIVATE_RE` peels the trailing sentence from an activated ability's effect text into `cost["any_player_may_activate"]`; the "but only as a sorcery" form also emits the existing `sorcery_speed_marker`. Fan Favorite, Feral Hydra, Excavation, the Flailing cycle, the Mongers (Warmonger, Squallmonger, Sailmonger, Scandalmonger), Ifh-Bíff Efreet, Endbringer's Revel, Quicksilver Wall, Saproling Cluster, Oona's Prowler. An opponent activating Fan Favorite pumps the source, executed in `test_par128_target_scope.py`. The ~12 cards that still carry it are blocked on their own body, not this rider.
- **"Can't be regenerated this turn" (PARSER_VERSION 544, +8, 0 regressed).** Regeneration existed only as a shield (`RulesEngine.regenerate`) and a per-call `destroy(can_be_regenerated=False)` (Wrath of God's own rider); there was no turn-scoped "this creature can't be regenerated". `GameObject.temp_cant_be_regenerated` (cleared at cleanup, RULE 514.2) is read by `destroy`, which then skips the replacement pass exactly as the per-call flag does. `CantBeRegeneratedEffect` (`cant_be_regenerated`, ISA `create_continuous_effect`) names its subject three ways, one row each: a RULE 115 target (Gravebind, Hurr Jackal, Furnace Brood), the preceding clause's target — "it" (Engulfing Flames, Rage of Purphoros), and the creatures the preceding damage clause actually hit — "a creature dealt damage this way" (Incinerate, Jaya Ballard, Flamebreak), read off `GameContext.damaged_this_way` (MEC-81), so a prevented hit doesn't mark anything. Executed against a real shield in `test_par128_target_scope.py`: the shield saves the creature without the rider and does not with it. Still open: Bone Shaman's granted quoted form and Lim-Dûl's Cohort's block-trigger form.
- **The regeneration + exile rider pair (PARSER_VERSION 545, +3, 0 regressed).** `segmenter._REGEN_EXILE_RIDER_RE` reads "…damage to any target. If it's a creature | If this spell was kicked, it/that creature can't be regenerated this turn, and if it would die this turn, exile it instead" as the damage clause plus two riders on its hit set (`cant_be_regenerated{damaged_this_way}` and MEC-81's `grant_die_to_exile_this_turn{damaged_this_way}`). The "it's a creature" gate is not an `if_else`: it narrows the hit set — `GrantDieToExileThisTurnEffect.creature_only` (`CantBeRegeneratedEffect` already only marks creatures) — because a planeswalker or player the damage also hit takes the damage but neither rider; any other gate ("this spell was kicked") becomes each rider's own `condition`. Carbonize, Disintegrate (X damage), Scorching Lava. Executed: a shielded creature Carbonize kills lands in exile, and a player target leaves the riders inert.
- **The general mass-damage group (PARSER_VERSION 546, +29, 0 regressed).** Mass damage was a closed list of ten named `DealDamageEffect.selector` values ("each creature", "each creature you control"'s cousins, …), so "deals N damage to each creature you don't control", "…each other creature you control", "…each other creature without flying", "…each attacking creature", "…each non-Pirate creature" — a 65-card solo cluster — each failed on the group phrase alone. `damage_group` reads "each `<group>`" through `parse_count_phrase` (the singular head pluralized) into `DealDamageEffect.group`, a structured battlefield selector resolved through `group_selector_objects` (with the source as the reference, so "other" excludes it); it sits after `damage_selector`, whose named selectors keep winning. Amount is a number or X, so the where-X wrapper composes (Immolating Gyre, Gates Ablaze). Phrases naming "target"/"that player"/"dealt damage"/"blocking" are refused (they need the referent machinery, not a group). Barrage of Boulders, Cinder Giant, Fire Ants, Harbinger of the Hunt, Sandstorm, Fiery Cannonade, Marrow Shards, Vampires' Vengeance, Oros, Immolating Gyre, Gates Ablaze and 18 more. Executed for the you-don't-control, other-you-control and other-without-flying shapes.
- **Mass damage scoped to a player, and X on the named selectors (PARSER_VERSION 547, +14, 0 regressed).** "…to each creature `<X>` controls" names *whose* creatures: `DealDamageEffect.group_player` re-scopes the `of: "you"` group to `defending` (RULE 506.4 — Scalding Salamander-family attack triggers, Swathcutter Giant, Gouged Zealot), `event_player` (the trigger's damaged player, event `target_id` — Shockmaw Dragon), `previous_controller` (the preceding clause's target's controller, last-known — Flames of the Raze-Boar; its own `previous_subject_only` row, so "that player" only reads as a preceding target when there is one) or `player`/`opponent` (a real RULE 115 player target via `TargetSpec` — Simoon, Unified Lunge). `damage_selector` also takes an X amount now ("deals x damage to each creature and each player" — Sickening Dreams; the amount is `_substitute_x`'s literal `"x"`). Executed: chosen opponent, defending player (through a real attack declaration). Trade-off worth knowing: a bare "that player" with no preceding target reads as the trigger's event player, which is inert (no damage) rather than wrong if the trigger carries no such player.
- **The group + "and each player/opponent" union (PARSER_VERSION 548, +3).** `DealDamageEffect.group_and_players` (`each_player`/`each_opponent`) sends the same damage to the players after the group; `damage_group` strips the " and each player|opponent" tail (refused together with a player-scoped group). Conductor of Cacophony ("each other creature and each player"), Blockbuster, Delete; Themberchaud still stops on its own perpetual/exert lines.
- **Mass tap scoped to a chosen player (PARSER_VERSION 539, +6, 0 regressed).** "tap all creatures target opponent controls" / "tap all lands target player controls" is a RULE 115 *player* target plus a mass group. `TapEffect.selector_player` (`"player"`/`"opponent"`) declares that target (`TargetSpec(kind=…)`) and evaluates the selector — written `of: "you"` by `tap_all_player_group` — for the chosen player instead of the controller. Deliberately *not* announced as a replayable group (`_BARE_TAP_PARAMS` excludes the extra param): `GameContext.previous_selector` records only the selector, and replaying `of: "you"` under the source's controller would hit the wrong player, so Sleep's "those creatures don't untap during that player's next untap step" stays unclaimed. Assassin Gauntlet, Gulf Squid, Tempest Caller, Dawnglare Invoker, Naya Charm, Rustler Rampage.
- **A named counter on a mass group (PARSER_VERSION 540, +3, 0 regressed).** `AddCountersEffect.group` takes a structured battlefield selector (resolved through `group_selector_objects`) for the groups `_ADD_COUNTERS_SELECTORS` has no named entry for; `add_named_counter_group` reads "put a/N/X `<named>` counter(s) on each `<group>`" through `parse_count_phrase` (battlefield groups only, "target" refused). `impostor` and `hone` join `_NAMED_COUNTER_KINDS` (no reader anywhere in `game/`, the whitelist's own criterion). Illicit Masquerade, Dwalin Weaponmaster, Sporesower Thallid. Deliberately still out: the subsystem/keyword counters (`loyalty`, `level`, `fade`, `deathtouch`, `flying`) that the whitelist excludes — Mila, Garruk, Parallax Inhibitor, Venerated Teacher, Vraska Joins Up.
- **The general mass destroy / exile / bounce group, the last group-selector gap (PARSER_VERSION 549–550, +124 in all, 0 regressed).** "Destroy/exile all `<group>`" and "return all `<group>` to their owners' hands" were three closed selector lists (`_MASS_DESTROY_SELECTORS`, ~12 names), so "destroy all white permanents", "…all creatures you don't control", "…all artifacts and enchantments your opponents control", "return each other creature you control" (Evacuation, Denizen of the Deep) each failed on the group alone. `_mass_group_params` reads the object through `parse_count_phrase` into `DestroyEffect.group` / `ExileEffect.group` / `ReturnToHandEffect.group` (the same shape `DealDamageEffect.group` carries), with `group_player` scoping it to "target player / target opponent / defending player / that player controls" (`effects.core._group_objects` / `_group_scope_player`, shared by all three). It sits after the named-selector rows, so their numeric filters (mana value, toughness, "can't be regenerated") keep winning. Found on the way: `matches_object_filter` had no "no counters" — `parse_qualifier` read "with no counters on them" as a counter *kind* called "no" (Damning Verdict would have destroyed nothing) — so `no_counters` is now its own key.
- **"X target creatures" (PARSER_VERSION 549–550).** The announced {X} as the target count (`TargetSpec.count_selector="source_x_paid"`, already read by `resolved_count`) reaches tap/untap, exile, destroy, bounce and the counter-per-target row through `_MULTI_TARGET_QUANTIFIER_X`, a variant only those handlers opt into (every other handler keeps the plain quantifier, so an "x" count fails closed where the effect cannot read it). `count` is set to the cap (`_ANY_NUMBER_TARGET_CAP`), not 1: `_chosen_targets` slices the resolved pick list to it, and 1 would have kept only the first of X picks. The plural rows "target artifacts / enchantments / lands" read as the broad `permanent` kind, so "destroy X target artifacts" offered creatures and lands; they now name the single-type pools (`_RETURN_TO_HAND_KINDS` gained them, which also lets the singular "return target artifact" parse).
- **Plural "other" and "you control" (PARSER_VERSION 549).** `_MULTI_TARGET_QUANTIFIER` carries an optional "other" (`_multi_target_params` accepts it only for a pool that already leaves the source out, or maps it through `OTHER_TARGET_KINDS`), and the plural scope tail gained "you control" (`_MULTI_TARGET_YOU_KINDS`). "Put a +1/+1 counter on each of up to 2 other target creatures you control" (Felidar Savior, Basri's Acolyte) is `other_creature_you_control` × 2.
- **`noncreature_permanent`, a target kind (PARSER_VERSION 549).** "Destroy target noncreature permanent" (Bramblecrush, Woodfall Primus, Mold Shambler — 7 cards) is any permanent that is not a creature, lands included, unlike the hand-authored `noncreature_nonland_permanent`. It is a narrowing of `permanent` in `SCOPED_TARGET_BASE`, so every verb that takes a permanent takes it.
- **"Each creature blocking it" (PARSER_VERSION 549).** `blocking_source` is a `matches_object_filter` key (the creature is in the *reference* object's `blocked_by`, RULE 509.1a), carried by the mass-damage group. The reference is the effect's source, so under a trigger whose "it" is not the source the parser refuses it: an `attached_permanent` head ("whenever equipped creature becomes blocked, it deals …") stays unclaimed, and a group head must have stamped the dealer (`dealer_event_key`). Battle-Scarred Goblin and Ib Halfheart.
- **"Sacrifice it" under a group trigger (PARSER_VERSION 549).** `sacrifice_self` had no trigger-subject mode, so "whenever another Goblin you control becomes blocked, sacrifice it" sacrificed the permanent carrying the ability, not the Goblin (a wrong-but-MODELED claim on every such card). `SacrificeSelfEffect(target_kind="trigger_subject", trigger_event_key=…)` follows `tap`/`exile`/`return_to_hand`; the group-pronoun stamp in `segmenter._stamp_group_pronoun` emits it.
- **A player-scoped "those creatures" (PARSER_VERSION 549).** "Tap all creatures target player controls. Those creatures don't untap during that player's next untap step" (Sleep): the mass tap sets `GameContext.previous_selector` to `{scoped_selector, controller_id}` itself (the core's default, the bare selector, would replay the group for the ability's controller), and `previous_group_objects` resolves it. `PumpEffect`'s previous-selector path now goes through `previous_group_objects` too (it re-ran `group_selector_objects` on the raw value, which cannot read a scoped dict). `TapEffect.selector_player` gained `defending` (Pretender's Claim, Jangling Automaton) and `event_player` (Nature's Will).
- **Smaller slots (PARSER_VERSION 549–550).** "Counter target spell you don't control / an opponent controls [unless they pay {1}]" (`spell_you_dont_control`, Counterflux, Hope-Ender Coatl); "put a stun counter on each of those creatures you don't control" (`AddCountersEffect.previous_group_scope`, Lost in the Maze); "each of those creatures deals damage equal to its power to ~" (`DamageEqualToPowerEffect.dealer_group="previous_targets"`, Polukranos); "you may exert ~ as he attacks. When you do, he gains flying" (Themberchaud — the rider body reads he/she as "it").
- **Yield.** 548: 18,245 → 550: **18,369 / 34,811 (52.8%)**; Commander-legal 17,524 → **17,644 / 31,830 (55.4%)**. `test_par128_noncreature_blockers.py` (52 tests) executes each shape against the real engine; the plural-row precision change updated two pins (`test_multi_target_extended`, `test_par15_any_number_of_targets`) and `test_par30_clash_win_branch` (an opponent-scoped land wipe no longer fails closed).

### PAR-130: "target `<X>` that player controls" as a target-scope slot (PARSER_VERSION 512–514)

- **Slot.** `subgrammars.THAT_PLAYER_TAIL` sits in `TARGET` beside PAR-128's controller scope; `resolve_target_kind` composes it through `THAT_PLAYER_TARGET_KINDS` onto ten base pools (creature, creature or planeswalker, permanent, nonland permanent, land, nonbasic land, artifact, enchantment, and the two unions), each a `SCOPE_THAT_PLAYER` frame in `targeting.TARGET_FRAMES` that keeps the base kind's colour/mana-value/creature-filter flags. Three hand-rolled rows take the same tail: "nonblack creature" (`_destroy_non_creature`), "black or red permanent" (`_exile_target_two_color`), and "Equipment" (`equipment_that_player_controls`).
- **Antecedent from the head.** The slot can't see what "that player" refers to, so `gate._that_player_antecedent_ok` refuses any ability carrying such a kind unless its trigger names the player: a player-recipient `DAMAGE`, the RULE 510.2 combat-damage batch, an attack, `BECOMES_TARGET` (the targeting spell's controller), or "each opponent's/each player's `<step>`". The body also mustn't name another player before "that player". A granted quoted trigger is checked against its own quoted text. At targeting time, `targeting.trigger_player_antecedent` reads the same player off the firing event and fails closed with none. Reflexive "when you do" payoffs work unchanged because `enqueue_reflexive_trigger` already carries the outer event.
- **"For each opponent/player" as the antecedent.** `TargetSpec.per_player` (`"opponents"`/`"players"`) is one requirement per player. `targeting.expand_counts` splits it into rounds in turn order from the controller, each with `scoped_player_id`. The trigger path skips a round whose player controls nothing legal instead of dropping the ability (RULE 601.2c), and `effective_count` returns `PER_PLAYER_TARGET_CAP` so the verb takes the whole collapsed group. The parser side is `handlers._per_player_target_specs`, a `match_clause` fallback: it parses the body with the ordinary table and stamps `per_player` onto the "that player" requirements. `binding.core.build_effects` copies the stamp onto the built effect's `TargetSpec`, so no verb factory changed. At 512 only triggered abilities gathered per round; spells followed at 513 and activated abilities at 514.
- **Linked exile, plural.** `ExileEffect(remember=True)` with more than one pick also records every pick in `GameObject.linked_exile_ids`, and `ReturnLinkedExileEffect` returns them all. With a single `linked_exile_id`, "for each opponent, exile … until ~ leaves the battlefield" would only have given back the last card.
- **Bug fixed on the way.** "Becomes the target of a spell or ability" stored `item_kind: "spell or ability"` as an exact-match filter, but the event only carries `"spell"` or `"ability"`, so 43 modeled cards never triggered (Frost Titan, the Phantasmal/Illusion cycle, Heartfire Hero, …). "A spell or ability" now emits no filter. `test_par30_becomes_target_sacrifice`'s execute test hadn't caught it, because Lightning Bolt kills the Bear anyway. `test_mec18`'s Dokuchi Silencer pin ("targeted follow-up stays unclaimed") predated the `then_trigger` reflexive path and now pins that path.
- **Per-player rounds on the cast path (513).** A spell announces its targets through `legal_actions`, not through the trigger's pick-by-pick choice, so `targeting.spell_target_rounds` turns each `per_player` requirement into one *offered* requirement per round (scoped, labelled with the player's name, a round with nothing legal left out so it never locks the spell). `requirements_with_targets` offers those rounds, and clients needed no change: the board and `bots.pick_target_groups` already answer "one group per offered requirement". On the way back, `targeting.per_player_groups` (called from `engine/casting_mixin._cast_current_face` before the ordinary `partition_targets`) checks each round's pick against that round's legal pool (at most one, controlled by that player, mandatory unless "up to 1") and collapses the rounds back to one group per effect. It also accepts the flat `targets` list a client sends when only one requirement was offered. The gate walks a `spell_effect` under a spell context that permits the `per_player` stamp but still refuses a bare "that player" (a spell has no antecedent). "For **any number of** opponents" (Windgrace's Judgment) is a third scope, `any_opponents`: the opponent rounds, each declinable.
- **Activated rounds and a prior target (514).** `target_rounds` and `per_player_target_groups` generalize the cast implementation so an activated ability offers, validates and collapses the same per-player rounds. Separately, an ordered target list may establish the antecedent: a preceding target player/opponent, or the controller of a preceding opponent-controlled permanent. `TargetSpec.prior_target_antecedent` is stamped only after the whole ordered requirement list is known; the dependent offer is the union of controlled candidates, and `validate_that_player_groups` checks the submitted group against the immediately preceding pick on both cast and activation paths. A standalone spec remains fail-closed. Breaking of the Fellowship is the real-card proof; adversarial three-player execution rejects a second target controlled by somebody else.
- **"That much damage" and causative optionals (514).** The damage handlers accept "deals that much damage" for both an ordinary target and the mass selectors (`each creature/player/opponent/other opponent/you`). A private sentinel is resolved by the gate only under an amount-carrying trigger event; an unsafe spell/activation is refused, while a RULE 603.2c `EVENT_BATCH` is rebound to its captured `matching_count`. The optional spelling "you may have it/~ deal …" is normalized narrowly onto the same self-subject damage body. This accounts for most of v514's gain and keeps the pre-existing discard batch semantics intact.
- **Choice announcement composition (514).** A bare "choose target …" builds a no-op `ChooseTargetsEffect`, including `per_player`, so following clauses can consume `GameContext.previous_targets`; the segmenter can split a per-player choice announcement before a period or `, then`. PAR-132 owns the distinct chosen-object follow-up bodies that are still missing, not the target announcement/scope.
- **No-duration steal (513).** "gain control of target `<permanent>`" with no duration (Keiga, Invoke the Winds, Slave of Bolas, Blatant Thievery, Tempted by the Oriq) had no parser row at all; only hand-authored Entrancing Melody used the effect's RULE 611.2 `duration="permanent"` mode. `handlers._gain_control_permanent` emits that mode (untap/haste off; an "untap it" restatement turns the untap on) over any permanent kind, including the controller-scoped narrowings. A duration or a spell target never reaches it because the full match fails.
- **Yield and verification.** 512: 17,882 → 17,914 (+32). 513: → 17,926 (+12). 514: → **17,988 / 34,811** (+62, 0 regressed; **51.7%**); Commander-legal **17,276 / 31,830 (54.3%)**. `tests/test_par130_that_player_target_scope.py` has 52 grammar and adversarial three-player execute tests spanning trigger, spell and activation paths, including the prior-target server backstop and antecedent-dependent amount. Full verification: 9,271 passed / 316 skipped normally; 9,587 passed with `--full-cache`. The distinct body/referent clusters exposed by the sweep are calibrated under PAR-132 in `PARSER_LONG_TAIL.md`; PAR-130 itself has no remaining target-scope residue.

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
- **Passive-gerund and "turning … face up" causes (PARSER_VERSION 526, +1, 0 regressed).** `trigger_doubler._GERUNDS` gained "becoming the target of a spell or ability" and "being dealt damage" (finite: "becomes the target …", "is dealt damage"), and `_TURNING_FACE_UP` rewrites "turning `<phrase>` face up" to the passive head "`<phrase>` is turned face up" (the turner isn't the subject) — all read by the composed object head PAR-131 put those events in. Valiant Emberkin is covered; Wayta and Panoptic Projektor parse their doubler line but stay blocked on their other clauses (the fight-cost reduction, the face-down cost reduction). Tests: `test_par122_trigger_doubler_grammar.py` (grammar + a real damage-cause doubling).
- **Compound subject and a "while" gate (PARSER_VERSION 530, +1, 0 regressed).** `trigger_doubler._subject` falls back to a two-sided "`<A>` or `<B>`" subject when the single-phrase reading fails (`~` = the doubler itself, "a `<noun>` attached to it" = a permanent attached to the doubler) → `{"any_of": [...]}`, read by `continuous._doubler_side_matches`; "… triggers while you control N or more `<X>`" becomes the doubler's `active_if` through `parse_count_condition` (Sanctum of All). Cloud, Midgar Mercenary is covered; Sanctum of All and Cloud, Ex-SOLDIER parse their doubler line but stay blocked on other clauses (the upkeep "search your library and/or graveyard", "attach up to 1 target equipment … to it" / "draw a card for each equipped attacking creature"). Echoes of Eternity's "a colorless **spell** you control" is a spell's own triggers (cascade/storm), not a permanent's, and stays refused.

- **The last doubler shapes (PARSER_VERSION 551, +9, 0 regressed) — PAR-122 closed.** *Player-event cause:* `_GERUNDS` gained "drawing a card" → "a player draws a card" (Krang, the All-Powerful). *A cause that also scopes its subject:* `_CAUSE_CLAUSE` now reads "`<cause>` causes a triggered ability of `<subject>` to trigger", so "a creature dying … of ~ or an emblem you own" carries both halves. *Subject sides beyond a permanent:* `trigger_doubler._alternative` reads "an emblem you own" (`{"emblem"}`), "a `<noun>` spell you control" (`{"spell", "filter"}`, the noun read as a permanent phrase) and an ordinary "another `<noun>` you control"; `continuous._doubler_kind` classifies the doubled trigger's source as permanent / spell on the stack / `Emblem`, and `_doubler_side_matches` only lets a side name its own kind — a plain "a permanent you control" subject never doubles a spell or an emblem. `RulesEngine._queue_firing` is now the one place a firing is queued and doubled, so a spell's own cast trigger (`_collect_self_cast_triggers` — cascade/storm) and an emblem's trigger get the same RULE 603.2d treatment as a permanent's (Echoes of Eternity, The Masamune). *A granted doubler:* `TriggerDoublerEffect.attached` (`affects="attached_permanent"`, built by `static_handlers._granted_trigger_doubler` from "equipped creature has \"if … triggers an additional time\"") is *held* by the Equipment's host — `continuous._active_doublers` resolves the holder, so "this creature", the controller and "another" all mean the host. *A paid doubler:* `TriggerDoublerEffect.tap_cost` ("tap any number of Fish you control … an additional time for each Fish tapped this way", The Fish Brewer) is never a free copy: `_queue_firing` attaches the applicable offers to the first copy (`_TapOfferFiring`, a tuple subclass, so every `pending_triggers` consumer still unpacks `(ability, event)`), and `_place_triggers` opens a `trigger_doubler_tap` choice (multi-pick, "Fertig" to stop; `_resume_trigger_doubler_tap`) that taps the picks and re-queues the trigger once plus one copy per Fish. It is asked when the trigger is *placed*, not collected, because the choice needs the same suspend/resume the mode/target choices already have (`_pending_doubler_tap`). Riders the cards also needed: "copy it. You may choose new targets for the copy" under a cast trigger (`_COPY_THAT_SPELL_RE` widened — Echoes of Eternity's second ability, plus Chancellor of Tales, Gorion, Photon Blast Barrage, Rimefire Torque), "that's all colors" on an inline token (`_ALL_COLORS`; Fish Brewer, Planewide Celebration), "as long as equipped creature is attacking/blocking/tapped/untapped, it has …" (`_attached_state_condition`) and "… has first strike **and must be blocked if able**". The attached-state condition is deliberately read *only* by the RULE 613.6 "as long as" wrapper: offered to the shared `static_condition` it also made Narcolepsy/Volition Reins/Earthlore MODELED, but their "tap it"/"untap it" then acts on the Aura, not the host — wrong-but-MODELED, caught by executing them. Tests: `test_par122_trigger_doubler_grammar.py` (grammar + execution of every shape, incl. the negatives: a permanent-only doubler ignoring a spell, an emblem you *don't* own, a tap offer with nothing untapped). Wayta, Panoptic Projektor, Sanctum of All, Cloud, Ex-SOLDIER and Windcrag Siege parse their doubler line and stay blocked on unrelated clauses that belong to their own clusters (`PARSER_LONG_TAIL.md`; `PAR-99` for the Siege; `singletons.md` for Cloud).

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

- **What:** The parser gate recognizes any card mentioning "sticker" and fails closed with `NEVER_SUPPORTED`, distinct from `UNMODELED`, so its clauses never enter the processing-list ranking. PAR-145 (2026-10-02, v586) adds the type line "Stickers", including empty or ticket/stat-only text. `coverage_report.py` excludes these non-card inserts from its denominator under RULE 123.2 while retaining their ledger verdicts and never-supported count. All 48 `sunf` sheets move from UNMODELED to NEVER_SUPPORTED; the empty-text Secret Lair "Sticker sheet" moves from MODELED to NEVER_SUPPORTED. Coverage: 20,115 / 35,046 (57.4%); Commander: 19,349 / 32,068 (60.3%).
- **Files:** `parser/oracle/gate.py`, `parser/oracle/processing_list.py`, `services/coverage_db.py`, `scripts/coverage_report.py`
- **Why:** No handler will ever claim Sticker text, so leaving it as ordinary `UNMODELED` would permanently pollute the "what to build next" ranking. Sticker Sheets have no card characteristics (RULE 123.2).
- **Validation:** `tests/test_stickers_never_supported.py` covers type-line recognition, empty text, case variants, backlog exclusion and the denominator; parser-version lock updated. Full-cache verdict comparison and probe snapshot/diff verify that only Sticker Sheet verdicts change. Full pytest with `--full-cache`: 10,834 passed; two local-server proxy tests were sandbox-blocked and passed on rerun outside the sandbox (all 10,836 tests validated).

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

### Squirreled Away — Bloomburrow Commander (85/85 unique cards)

The saved deck is fully modeled: 19 explicit card factories close the previous 66/85 coverage. Behavioral tests live in `backend/tests/game/catalogue/cards/test_squirreled_away_deck.py`.

Reusable support includes additional token batches under replacement effects (Chatterfang with token doublers), death-dependent half-sized copies, optional recovery of milled permanents, repeated exact-three graveyard exile payments, borrowed mana abilities, and variable tap costs with mixed-color mana selection. Base power/toughness filters use layer-7b values; all-creature-type grants use the Comprehensive Rules creature-type list and apply before entry-trigger predicates. Garruk's Wolf loyalty trigger is parsed with PARSER_VERSION 594.


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

### Goblins (saved deck, fully playable) (Deck/Cube Playability Batches)

- **What:** Closed the 7 `UNMODELED` cards of the 39-card Goblins deck: six hand-authored (Goblin Matron and Wort, Boggart Auntie reuse the subtype `search` / `return_from_graveyard` shapes; Goblin Rabblemaster grants the synthetic `attacks_if_able` keyword to other Goblins through a layer-6 `grant_keyword`; Krenko, Tin Street Kingpin is `seq(add_counters, bind(power) -> create_token)`; Legion Loyalist is a Battalion `attackers_declared` head over a keyword `pump` plus `combat_restriction_this_turn` with `selector` and a token filter; Coat of Arms is a layer-7d anthem whose per-recipient count uses `shares_creature_type_with_reference`) and Reckless Bushwhacker through the new Surge mechanic (see the Casting & Costs entry).
- **Files:** `game/card_catalogue/{c,g,k,l,w}/` (one file per card), `tests/game/catalogue/cards/test_goblins_deck.py`

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

### Residue sub-items closed as a side effect of PAR-120/ENG-48–51 (audit 2026-09-29, PARSER_VERSION 500)

- **What:** A re-check of every card named in the open `PAR-*` tickets found nine sub-items
  already MODELED by the composed-grammar work (PAR-119/120's heads and count phrases, ENG-51's
  cost grammar), with no ticket of their own: PAR-107's "if an opponent controls more lands than
  you, search for a basic Plains" (Loyal Warhound, Scouting Hawk); PAR-108's "cast a spell from
  anywhere other than your hand" (Vega, the Watcher); PAR-111's "a creature an opponent controls
  dies, that player loses N life" (Assault Intercessor, Massacre Wurm) and "destroy target
  artifact or enchantment an opponent controls" (Rambunctious Mutt, Witch Enchanter); PAR-112's
  X Angel tokens (Entreat the Angels), "target opponent gets an emblem" (Ob Nixilis Reignited)
  and "whenever you sacrifice a permanent" (Juri, Master of the Revue); PAR-113's "attacks while
  you control a creature with power N or greater" (Nighthowl Pursuer, Ruby, Daring Tracker);
  PAR-123's delayed return to hand (Rienne, Angel of Rebirth).
- **Why:** Removed from `BACKLOG.md` only after **executing** each card against a real
  `GameEngine` (the parse verdict alone has hidden wrong-but-MODELED shapes before): the
  Intercessor/Wurm drain hits the dying creature's controller and ignores your own; Vega draws
  for a graveyard cast and not a hand cast; the Ob Nixilis emblem lands on the target opponent
  and drains *them* on every player's draw; Juri gets its counter from a sacrificed creature;
  the Pursuer/Ruby pump fires only with a power-4 creature out; Rienne returns a dead
  multicolored creature from the graveyard at the end step and leaves a monocolored one;
  Warhound fetches a tapped Plains only when behind on lands; Mutt offers only the opponent's
  artifact. One known imprecision kept: Warhound/Scouting Hawk carry their "if" as a
  resolution-time effect condition, not a RULE 603.4 intervening-if on the trigger, so the
  trigger still goes on the stack when the condition is false (it then does nothing).
- **Also found:** "target creature or planeswalker" parses on 83 cards but drops the
  planeswalker half of the target — filed as `PAR-127`.

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

### Narrative saved-deck analysis (ANA-1)

- **What:** `POST /api/decks/{id}/analyze` resolves the saved deck, requests a structured Claude/compatible-provider narrative and validates summary, archetype, WinCons, synergies, cohesion, issues and recommendations. Persistent `analyses.db` caches by deck/Oracle context, language, prompt version and provider/model; concurrent repeated requests reuse results, `force` refreshes. `Deck.analysis_id` and `GET /api/decks/{id}/analysis` expose the current result. Section/archetype edits invalidate the link; provider failures cannot persist malformed output. Settings are server-wide, keys redacted, with environment overrides and an explicit connection test. ANA-2/ANA-3 remain UI work.
- **Files:** `api/narrative_analysis.py`, `services/narrative_analysis.py`, `models/analysis/narrative.py`, `api/saved_decks.py`; [configuration and API contract](../Reference/LLM_INTEGRATION.md).


### Dynamic (simulated) deck analysis (ANA-4)

- **What:** `services/dynamic_analysis.py` runs N solo goldfish matches headlessly against a `Bot` and aggregates turn-by-turn stats. Matched Commander Spellbook combos are tracked independently: each records its first turn with all required copies on the player's battlefield, and the aggregate also records the first turn with any combo assembled. The successful mulligan actions taken in each match are aggregated as a mean/distribution; the Smart Bot uses its existing land-count heuristic, up to two mulligans. Combo assembly is board presence, not verification of template requirements or successful execution.
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
