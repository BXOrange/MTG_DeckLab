# CLAUDE.md — project wiki for Claude

Orientation for working in this repo. Keep it current when you change
architecture, conventions, or the rules-engine feature set.

## What this is

An MTG (Magic: The Gathering) deck analyzer with a **rules-accurate game
engine**. The headline feature is the **"Goldfisch" (goldfish) mode**: play a
saved deck against the real backend rules engine — step through the turn, play
lands, tap mana, cast spells with the stack, attack, all validated server-side
against the Comprehensive Rules (referenced as `RULE <n>` throughout the code).

Two halves:

- **`backend/`** — Python (FastAPI). The card model, rules engine, oracle
  effect IR, and the game-session API. This is where the depth is.
- **`frontend/`** — a static, buildless ES-modules app (no bundler). Tabs for
  deck import/analysis, saved decks, the goldfish board, the **"Replay"**
  board editor (a.k.a. puzzle mode), the card cache, Multiplayer
  (**Setup** = lobby + game configuration, **Board** = the shared game,
  disabled until you're at a table), and
  an **"Engine-Status"** tab documenting engine coverage, plus two header icon
  buttons: **"Einstellungen"** (server address, player-uploaded token art,
  card-back sleeves) and **"Profil"** (`profileView.js` — just the player
  name, split out of Einstellungen so it reads as "who you are" rather than
  a connection setting). UI language is **German**; MTG keyword names stay
  English ("Flying", "Trample").

The **Replay/Puzzle mode** is the goldfish's sibling: instead of playing a
legal deck from turn 1 you *construct an arbitrary board* (1 player = puzzle, or
2 = with an opponent) and play from there. It reuses the same `GameSession`/
`GameEngine` — a session with `mode="replay"` and `require_setup=False` plus
a family of `edit_*` actions (`services/game_session.py`) that mutate state
directly (add/remove/move objects+tokens, tap, flip, counters, life, poison,
player counters, commander damage, turn/phase). Save/load is JSON export/import
of a **re-resolvable descriptor** (`services/replay.py`: `serialize_replay`
/ `build_replay_engine` — the models have no `from_dict`, so cards are stored
by id/name and rebuilt from the cache; tokens carry a self-describing block).
`GET /api/game/{id}/replay-export` works for a goldfish session too, so a
goldfish position can be exported and re-opened in Replay. Frontend:
`frontend/src/js/replayView.js`.

**Multiplayer** (UC4) is a real game of **two to four players** against the
same engine, not a stub (`services/lobby.py`'s `MIN_SEATS`/`MAX_SEATS`;
four is where the board UI stops being readable, not a rules limit — the
engine has been N-player throughout). Two layers, strictly separated:
`services/lobby.py` is
**rules-free** (people and tables — `LobbyPlayer` with a presence state of
`online`/`available`/`playing`, `LobbyGame` with seats, deck picks, an
agreed mulligan style and a per-seat "accept"), and `services/
game_session.py` is the game (one `GameEngine`, as always).
`api/multiplayer.py` is the only bridge: it resolves each seat's saved
deck exactly like `api/game.py` resolves a goldfish deck (same
`expand_entries`, same legality gate) and hands `Lobby.start()` a built
session id. Four things make a session *shared* rather than solo:
**actions carry an actor** (`apply_action(action, actor_id=...)`) so the
engine's own per-player validation decides what a non-active seat may do;
**`view(perspective=...)` redacts hidden zones server-side** (RULE 400.2 —
an opponent's hand never leaves the process, `observer_view()` hides
everyone's); **`/ws/lobby`** (`api/multiplayer_ws.py`) is presence *and*
the push channel, sending each participant their own view rather than one
shared payload; and **priority is played out for real** (below).
A seat also carries one purely cosmetic thing, `Seat.banner_color`
(`normalize_banner_color` — any subset of WUBRG, or grey for colourless,
defaulting to the deck's colour identity when a deck is picked): the
colours the shared board paints that player's title bar in. It lives in
the lobby rather than in the game state (it's a property of the person at
the table, and Setup must show it before there is a game), so it reaches
the board through the same `seatStatus` hook as connection state; the
palette and all 32 combinations are derived from six hexes in
`frontend/src/js/bannerColors.js` rather than enumerated in CSS.
`RulesEngine.concede` (RULE 104.3a) defers the RULE 800.4a board cleanup
to the next turn (`GameState.pending_leave_ids`) so a concession doesn't
yank a board away mid-turn. Frontend: `multiplayerView.js` +
`lobbySocket.js`, driving the shared `gameBoardView.js` through an
injected transport.

**RULE 117 priority** is opt-in per session (`GameSession.
interactive_priority`, on only for `MULTIPLAYER`; the engine flag is
`GameEngine.interactive_priority`). Off, `_run_step` auto-drains the stack
exactly as it always has — every solo path is untouched. On, a step only
puts triggers on the stack, the active player holds priority, and
`GameSession._pass_priority` drives `GameEngine.pass_priority(player)`
(which already owned the APNAP round: record the pass, hand priority on,
resolve the top of the stack once everyone has passed). The half the
engine can't do is RULE 117.4's *other* branch — all passed on an **empty**
stack ends the step — so the session does that (`_advance_to_priority_
window`, which runs through untap/cleanup since those give nobody
priority). Consequence worth knowing: **there is no "advance the turn"
action in a shared game**; `advance_step` is refused and the board's
primary button becomes "Passen". Only the priority holder may act, enforced
in `_dispatch` and not merely filtered out of `legal_actions` (a client
could post an action it was never offered) — except RULE 509.1a's
declare-blockers, a turn-based action the *defending* player takes while
the attacker still holds priority (and "declares no blocks" is itself a
complete, submittable answer — an empty `assignments` list — not a state
the UI can just fail to reach).

**Take-backs** (`GameSession.take_back`) are a table-configured, RULE-free
undo convenience — not `rewind`, which is a solo-practice, whole-history
tool disabled in multiplayer. Host-set in Setup (`LobbyGame.
takebacks_per_player`), legal regardless of priority (same exemption as
`concede`), and scoped to *the caller's own* last `_history` entry — which,
since there is only one shared timeline, also discards anything an
opponent did afterward. `_history` now carries each entry's actor id for
exactly this; slice it (and `move_log`) by a tail-relative depth, never an
absolute index — `_history` drops its oldest entries past `MAX_HISTORY`
but `move_log` never does, so the two can differ in length.

**Presence, reconnects and timers.** A lobby player is identified by
**name** (`services/lobby.py`'s `normalize_name`), not by the server-issued
id: that's what survives a page reload, so reconnecting with the same
Profil name walks back into the same seat mid-game. The trade is explicit —
two people sharing a name share a seat, and the second to connect takes
over (the old socket is closed with a `replaced` reason) — **unless**
either browser has ever saved a Profil name, which mints it a random
`client_token` (PLR-4 stub, `settings.js`'s `mtg_client_token` cookie,
90-day sliding validity): once a client presents one, `Lobby.connect`
resolves it by that token instead of by name at all, so two browsers
sharing a display name stay distinct players rather than merging. Not real
auth (unsigned, client-trusted, still PLR-9 to actually close) — just
enough for one browser to keep recognizing itself without colliding with
someone else's. A token unused for `MTG_CLIENT_TOKEN_VALIDITY` (default 90
days, never while connected or mid-game) is forgotten, along with that
name's `player_assets.py` uploads if no other still-recognized player
shares it (`Lobby.expired_token_players`/`name_in_use_by_other`, swept
alongside the timers below). Losing a socket
doesn't forfeit: `Lobby.disconnect` starts a grace period
(`MTG_MULTIPLAYER_DISCONNECT_GRACE`, default 90s) and meanwhile the server
**passes priority for the absent player** (`pass_for_absent_players`) so
the table keeps moving; letting it lapse concedes for them. A player who
holds priority and is silent past `MTG_MULTIPLAYER_IDLE_TIMEOUT` (default
120s) has their socket closed — not to police slow play, but because a tab
that died without a clean close would otherwise hold the table forever.
Both timers are swept once a second by `api/multiplayer_ws.sweep_once`,
run from the app's lifespan. Client-side, **auto-pass** (settings.js
cookies, default on / 3s / opponent-turns-only) counts down whenever this
client holds priority and passes at zero; touching the board cancels that
window, and both the toggle and the seconds are adjustable on the board
itself as well as in Einstellungen.

**Bots (UC5, `services/bots.py`)** fill a seat at such a table — they are
players, not a mode. The load-bearing rule is that a bot plays through the
*client* surface and nothing else: it reads `session.view(perspective=<its
own id>)` (so RULE 400.2 redaction means an opponent's hand and every
library simply aren't in its data) and may only submit entries from its own
`legal_actions` via `apply_action(action, actor_id=...)`. Never read
`engine.state` from a bot — the engine's per-seat validation is what makes
a bot legal, and every bot game doubles as a test of the redaction. `Bot`
fixes the *order* a seat handles things in (`decide`: pending choice →
mulligan → RULE 509.1a declare-blockers, which the defender takes while the
attacker holds priority → `play()` only if it holds priority) and
subclasses override policy only — `GoldfishBot` (lands, else pass) and
`GreedyBot` (everything, immediately, first legal target). Bots have no
loop of their own: `run_bots(session, bots)` is called after each human
action, right after `lobby.start()` (so a bot keeps its opening hand before
the humans see the mulligan screen), and once a second by the sweeper —
which is what drives a table with no humans at it. It runs *before* the
broadcast, so a human's move and every bot answer to it are one push.
`MAX_BOT_ACTIONS` is a yield point, not an error budget. In the lobby a bot
is an ordinary `LobbyPlayer`/`Seat` (+`Seat.bot_kind`), so the engine never
learns bots exist; the differences are all social — a bot seat with a deck
counts as ready, bots are kept out of presence sweeps, the host acts for
them (`add_bot`/`remove_bot`/`set_deck(seat_id=…)`), and a table whose last
*human* leaves is dropped rather than left playing itself.

**Player-uploaded art** (Einstellungen tab): a player can upload art for
tokens that have no real Scryfall art (matched by token name) and a
library of card-back "sleeve" designs, one of which can be picked per
saved deck (`Deck.sleeve_id`). Stored server-side keyed by the free-text
player name (this app has no auth) — set on the **Profil** tab
(`profileView.js`), read via `getSettings().playerName` — via `services/
player_assets.py` / `api/player_assets.py` rather than client-side,
specifically so a shared backend can serve them to an opponent too at a
multiplayer table.
The goldfish/Replay board (`gameBoardView.js` `resolveImageUrl`) renders
a token's uploaded art when present, and falls back to the active
sleeve for a face-down/transformed token with none — real transformed
DFCs keep their genuine Scryfall back-face art, so the sleeve fallback
has no visible effect yet until a face-down permanent state
(morph/manifest, not yet modeled) can reach that branch.

The **Profil** tab also carries two smaller per-player preferences
alongside the player name: **favorite decks** — a starred subset of the
saved-decks list (`services/player_assets.py`'s third table,
`favorite_decks`, same `player_name`-keyed storage as sleeves/token
art — decks aren't owned in this single shared `DeckDatabase`, so the
star can't live on `Deck` itself) that `goldfishView.js`'s and
`multiplayerView.js`'s deck pickers list first; and **multiplayer
default settings** (format, mulligan style, takebacks, RULE 103.1/103.2
randomization) — purely client-side cookies (`settings.js`, same
convention as auto-pass in Einstellungen), applied once by
`multiplayerView.js`'s `createGame()` via the same host-only
`setMultiplayerOptions` call the table's own option rows use, right
after a table is created.

A saved `Deck` also carries a free-text, optional `author` field (a
descriptive credit, not an owner/auth concept — this app still has no user
accounts) — set on the deck-import/edit tab and shown read-only in the
saved-decks list, preserved-on-omission the same way `sleeve_id` is
(`api/saved_decks.py`'s `save_deck`: a re-save that doesn't send `author`
keeps the existing value). The saved-decks list also gained client-side
color-identity/legality filters, the same checkbox-fieldset pattern the
card cache view uses (`savedDecksView.js`/`cachedCardsView.js`).

A saved `Deck` can also be flagged `is_cube` (`models/deck.py`) — a card
pool (e.g. a curated "cEDH staples" reference list) rather than a real,
legal Commander deck. When set, `services/deck_validation.py` skips both
the structural Commander checks (100-card total, singleton,
`parser/deckliste_parser.py`) and the semantic ones (ban list, color
identity, Partner — `services/commander_legality.py`) entirely, rather
than reporting the pool's inherent "violations" as errors — same
preserved-on-omission save semantics as `author`/`sleeve_id`. Set via a
"Als Cube behandeln" checkbox on the deck-import/edit tab
(`deckImportView.js`); the saved-decks list shows a 🧊 badge instead of
the usual legality check (`savedDecksView.js`) and gained a matching
"Art" (Deck/Cube) filter, same checkbox-fieldset pattern as color/legality.

## Run & test

```bash
# Full app (frontend static server on http://localhost:8765; sets up backend venv)
./start.sh                     # add --backend-tests to also run pytest

# Backend tests directly (do this after any backend change)
cd backend && python -m pytest -q
# or: source backend/venv/bin/activate && pytest backend/tests/
```

The backend FastAPI app is `mtg_analyzer.api.app:app`. There is **no JS build
step** and no Node toolchain — edit `frontend/src/**` and reload. There is no
JS test runner, so validate frontend changes by reasoning + reading; validate
backend changes with pytest (the suite is fast, ~500+ tests, keep it green).

**Starting is offline-safe, and must stay that way.** `start.py` calls
`setup/install.py`'s `ensure_backend_venv()` on every run, so anything that
does gets to decide whether the app can start without internet: it installs
with `pip --no-index` first (an already-complete venv is verified locally in
~0.2s, opening no socket) and only falls back to an index-using run when
that fails; a fresh venv can be built offline from the wheelhouse
`setup/install.py --download-wheels` caches in `setup/wheels/`. Nothing else
in a start reaches the network — the frontend loads no external script/font/
image, card data and art come from `backend/cache/`, and tokens/dungeons/
variant cards are committed JSON in `mtg_analyzer/data/`. Don't reintroduce
an unconditional `pip install --upgrade pip` (it always queries PyPI);
`backend/tests/test_setup_offline_start.py` pins this down.

**Stuck-test detection is automatic** (`backend/pytest.ini`, `pytest-timeout`):
any single test running past 20s aborts with a `Timeout (>20.0s) from
pytest-timeout.` traceback naming it, instead of hanging the run — no
extra flag needed, plain `pytest -q` already has it. `backend/scripts/
run_tests.py` is a thin wrapper (`python scripts/run_tests.py [--hard-timeout
SECONDS] [pytest args...]`) adding a hard wall-clock ceiling (default 120s)
on the *whole run*, for the rarer hang the per-test timer can't reach
(collection, a session-scoped fixture, or a true C-level block) — it kills
the process group and reports the last test that had started.

## Claude Code skills

Four project-scoped skills live in `.claude/skills/` and should be invoked
(not reimplemented ad hoc) for the work they cover:

- **`extend-parser`** (`.claude/skills/extend-parser/SKILL.md`) — extending
  the oracle-text parser (`parser/oracle/`): add/widen an effect/static/
  trigger handler to raise `MODELED` coverage, close a `PAR-*` ticket, or
  make specific cards parse. Ships `parser_probe.py` (~5s against the full
  34k-card cache: which real cards a change would unlock, whether a regex
  edit broke anything).
- **`game-engine`** (`.claude/skills/game-engine/SKILL.md`) — engine work in
  `game/`: implement a mechanic or `MEC`/`ENG` ticket, add an effect/
  trigger/replacement/static/interactive choice, fix layer-system or combat
  behaviour, or debug a card's live behaviour. Ships `engine_bench.py`
  (boards/casts/resolves/fights a real card against a real `GameEngine`
  from one command — event trace + board diff, no throwaway test file —
  and searches existing registries for a primitive before you build a new
  one).
- **`hand-author-card`** (`.claude/skills/hand-author-card/SKILL.md`) —
  hand-authoring a specific card's abilities into `game/ability_catalogue.py`
  (a replacement effect, a triggered ability with a real conditional
  predicate, or any card the oracle-text parser can't fully claim) rather
  than a parser handler. Ships `author_card.py`: pulls the card's real
  oracle text, shows what the parser already claims for free (so you copy
  that part instead of re-deriving it), finds the closest-shaped existing
  catalogue entry to adapt, and assembles a paste-ready factory function +
  `register()` call + test skeleton in one command.
- **`inspect-db`** (`.claude/skills/inspect-db/SKILL.md`) — read-only
  lookups against the five SQLite stores (card cache, raw Scryfall data,
  parser-coverage ledger, saved decks, player assets). A short routing
  SKILL.md points at exactly one lean `reference/<store>.md` per store
  (path, schema, gotchas), so a lookup only ever loads the one store that
  matters. Ships `query.py`, a read-only SQL runner that resolves each
  store's real on-disk path itself and refuses non-`SELECT` statements.

## Architecture & data flow

```code
Card (models/card.py)            immutable printed characteristics
  └─ GameObject (models/game_object.py)   one instance in a zone, mutable state
GameState (models/game_state.py)  battlefield/stack/players/turn + event bus
RulesEngine (game/rules_engine.py) rules primitives: cast, damage, draw, SBAs…
GameEngine  (game/game_engine.py)  turn/phase loop, actions, legal_actions, combat
GameSession (services/game_session.py) wraps an engine: snapshots/undo, wire view
API (api/game.py)  ── JSON ──▶  frontend (src/js/goldfishView.js)
```

`RulesEngine`/`GameEngine` are each a **composition of per-responsibility
mixins** (ENG-20/21, 2026-07-29) rather than one file holding every method —
`game_engine.py`/`rules_engine.py` themselves shrank to `__init__` + (for
`RulesEngine`) the RULE 616 replacement-effect core + the class declaration;
everything else lives in `game/engine/*_mixin.py` (turn loop incl.
`new_game`, combat, casting, lands, activation, mana, legal_actions, misc)
and `game/rules/*_mixin.py` (triggers, casting resolution, damage/death,
draw/discard, mana/counters, copies, search, state-based actions, misc
systems). This is invisible from outside `game/`: both classes keep their
exact public method names/signatures, so `engine.cast_spell(...)`/
`rules.deal_damage(...)`/etc. still work exactly as before, and searching by
method name (grep/IDE) finds the right file regardless of which mixin
defines it.

Oracle-text → behaviour pipeline (docs/09):
`AbilitySpec` IR (`parser/oracle/spec.py`, pure JSON-shaped data, the security
boundary) → **binder** (`game/effect_binder.py`) → live `GameEffect` objects via
the `EffectRegistry` (`game/effects.py`). **Bind-on-load** is wired:
`build_goldfish_engine` calls `bind_from_catalogue(obj)` for every object it
creates, sourcing specs from `game/ability_catalogue.py` (a hand-authored,
name-keyed registry — e.g. Evolving Wilds' fetch) **and** the oracle-text
front-end. That front-end (`parser/oracle/`, docs/09 Phase 1) is `normalize` →
`segmenter` → `catalogue/handlers` (effect families over shared
`catalogue/subgrammars`) → `gate.parse_oracle`, which returns `AbilitySpec`s +
a fail-closed `MODELED`/`UNMODELED` coverage verdict. `specs_for` falls back to
it for *unregistered* cards, adding effect/triggered specs only when the card is
fully `MODELED` (never half-resolving). The front-end has **no `game/` imports**
(the security boundary); binding stays the binder's job.

### Key game/ modules

- `effects.py` — effect hierarchy + `EffectRegistry` (whitelisted `type` →
  factory). One-shot effects, `TriggeredAbility`, `ActivatedAbility`,
  `StaticEffect` (phase-skip), `StaticAbility` (layer system), `ReplacementEffect`.
- `combat.py` — combat/evasion **keyword recognition** (off Scryfall `keywords`
  & oracle text) and the rules they impose (blocking legality, damage steps).
- `continuous.py` — the **RULE 613 layer engine**. `recompute(state)` re-derives
  every battlefield permanent's characteristics in layer order and stamps
  derived P/T, types, granted keywords + a per-object `static_trace`.
- `costs.py` — regex parser for **activated-ability costs** (`Cost: Effect`).
- `ability_catalogue.py` — card→`AbilitySpec` registry (bind-on-load source),
  now also falling back to the oracle-text parser (`parser/oracle/gate.parse_oracle`)
  for unregistered `MODELED` cards + `enters_tapped` (RULE 614.1, oracle-derived).
- `targeting.py` — legal-target computation (RULE 115 / 601.2c).
- `mana_abilities.py`, `models/mana_cost.py`, `models/mana_pool.py` — mana.

## Implementation state (summary)

The user-facing detail lives in the frontend **Engine-Status tab**
(`frontend/src/js/implementationStatusView.js`) — keep that file in sync when
the engine gains/loses coverage. This section is a short orientation only —
for the actual mechanic-by-mechanic detail (what shipped, *why* it was built
that way, which tests cover it), read
[docs/implementation-state/Done_Backend.md](docs/implementation-state/Done_Backend.md);
for open gaps and exactly what's left on a partial feature, read
`docs/implementation-state/BACKLOG.md`. Search both for a mechanic's name
rather than re-deriving its state from the code or duplicating detail here —
`Done_*.md` is organized by section (Rules Engine, Game Engine, Card-type &
structural coverage, …), `BACKLOG.md` by ticket category.

**Implemented**: the full turn/stack/priority/SBA loop; the mulligan
procedures a table can agree on (`MULLIGAN_STYLES` — London, Vancouver,
"next 7", none; Vancouver's scry-1 is queued per seat in turn order after
the *whole table* has kept, since the state holds one `pending_choice`);
targeting; the whole mana model (generic/color/colorless/hybrid/mono-hybrid/
Phyrexian/{X}), including RULE 605.3a **spend restrictions** ("Spend this
mana only to cast a creature spell") as tagged lots in `models/mana_pool.py`
gated by a caller-supplied predicate (`game/mana_abilities.py`'s
`restriction_predicate_for_cast`/`_for_activation`), RULE 605.1a "any
combination of colors" mana (`ManaAbility.any_combination`,
`GameEngine.tap_for_mana`'s `color_split`), and RULE 605.1a hand-zone mana
abilities ("Exile this card from your hand: Add …", Elvish/Simian Spirit
Guide — `hand_mana_abilities_for`/`GameEngine.activate_hand_mana_ability`);
all common combat keywords incl. landwalk; the RULE 508/509
**combat-restriction/requirement/multi-block** family in full — both the
plain flag forms ("~ can't attack.") and every qualified restriction (a
blocker filter — "…can't be blocked by creatures with power 2 or
less"/"…except by Walls"/"…by more than one creature" — an "unless
`<board condition>`" gate, "…alone" with its own aggregate
`EventType.ATTACKS_ALONE` trigger, and the resolve-time "target creature
can't block this turn"), RULE 509.1c/d's **requirements** (the mirror
image — "~ must be blocked if able."/"All creatures able to block ~ do
so.", synthetic flag keywords like `attacks_if_able`, checked by
`GameEngine._enforce_block_requirements` as declare-blockers closes; plus
the resolve-time, pairwise "target creature blocks/can't block ~ this
turn [if able]" naming a specific attacker via
`GrantCombatRestrictionEffect`'s `restrict_to_source`), and RULE 509.1b's
**multi-block permissions** ("~ can block an additional creature each
combat."/"…any number of creatures.", `GameObject.additional_blocking` +
`combat.max_blocks_for`/`has_block_capacity`, with combat damage divided
evenly across every attacker a multi-blocker ends up blocking via
`GameEngine._split_blocker_damage`) — plus the family's last two gaps, a
filter whose threshold is a **board count instead of a literal int**
("Creatures with power less than the number of Islands you control can't
block ~." — Kraken of the Straits, `matches_object_filter`'s
`power_lt_count_selector` + `continuous.count_selector`'s
`lands_you_control_of_type_<x>`, scoped to the *attacker's* controller per
RULE 613.7c) and a **group scope with its own power/toughness qualifier**
("Each creature you control with power 4 or greater can't be blocked by
more than one creature." — Challenger Troll/Flopsie, `group_selector_
objects`'s `min_power`/`max_power`/`min_toughness`/`max_toughness`, which is
also why `continuous.recompute` now stamps `combat_restriction` *after* the
layer-7 P/T pass instead of before it, so a same-pass anthem is visible to
the qualifier) — the qualified/requirement/multi-block kinds all riding one
`combat_restriction` static that `continuous.recompute` stamps onto
`GameObject.combat_restrictions` but that is *evaluated at combat time*,
since who's defending and who else is attacking don't exist yet when the
layer engine runs; the RULE 613
**layer system** (layers 1–7, timestamp-ordered within a layer + a bounded
RULE 613.8 dependency pass, `EffectRegistry`-bridged for every hand-authored/
parsed `static` spec shape, including layer-6 grants of a non-keyword mana
or triggered ability and `affects="attached_permanent"` for Auras/Equipment/
Reconfigure); Aura/Equipment/Fortify/Reconfigure attachment; activated
abilities incl. loyalty `[±N]` costs; triggered abilities + RULE 616
replacement effects, both with **interactive ordering** when 2+ apply to the
same event/trigger batch, and a triggered ability's own target/"you may"
chosen interactively too — including, since 2026-07-16, 2+ *different*
targeting effects on one spell/ability each resolving against their own
target instead of a shared list (`StackItem.target_groups`, gathered
automatically one at a time for a triggered ability; for a **spell or
activated ability** the board sends the per-requirement partition it
already gathers round by round, and `targeting.partition_targets` derives
it from a flat in-printed-order list otherwise — a declined "up to one" is
the one case only an explicit partition can express); a
ward cost's own `{X}` (RULE 702.21b, resolved fresh against the board at
the ward ability's own resolution time, not when it triggers); the one-shot
effect library (damage/draw/discard/
destroy/counter/search/gain_life/mill/exile/tap/counters/pump/scry/
create-token/copy_permanent/become_copy/cascade/discover/proliferate/fight/…
— `fight` (RULE 701.14) being one atomic effect rather than two damage
effects, since 701.14b's cancellation is mutual (either creature gone or no
longer a creature → *neither* deals damage) and 701.14a's two damage events
are simultaneous; either fighter may be a chosen target, the source itself,
an Aura's host, or a **pronoun bound to the previous clause's target**
("target creature you control gets +1/+2 until end of turn. It fights …" —
`GameContext.previous_targets`, which also carries "choose target … and
target …. Then those creatures fight each other"), and
`damage_equal_to_power` is the same shape one-way (Rabid Bite); `scry` (RULE
701.18) and `surveil` (RULE 701.31) being one
implementation (`RulesEngine._LOOK_TOP_KINDS`: look at the top N, send any
number *somewhere*, order the rest back on top; scry's "somewhere" is the
bottom of the library, surveil's is the graveyard), each a genuine
two-phase `pending_choice` —,
including mass "destroy/exile all X [with a toughness/mana-value filter]"
board wipes, RULE 601.2c's untargeted-selector shape `DestroyEffect`/
`ExileEffect` share with `DealDamageEffect`); tokens (RULE
704.5d lifecycle), Living Weapon's germ-token self-attach and Renown's
counter-placement now real behaviour, not just keyword recognition;
**monstrosity** (RULE 701.37) and **adapt** (RULE 701.46) — deliberately
*not* one mechanic, since monstrosity's gate is a designation
(`GameObject.is_monstrous`, feeding both an `EventType.BECAME_MONSTROUS`
trigger and an "as long as ~ is monstrous, …" conditional static) while
adapt's is simply the creature's current +1/+1 counters;
RULE 613.6 **conditional statics** and RULE 611 **durations** as two
general systems rather than per-card params — `game/static_conditions.py`
is one whitelisted "as long as `<condition>`" vocabulary (state,
characteristics, whose turn it is, a board count scoped to you *or* to any
opponent, a named permanent, life/hand/cards-drawn-this-turn) carried by
*any* static in its `active_if` param and evaluated live every
recompute, with the older per-card gates (`active_player_only`,
`min_level`, `min_count_selector`) translated into it — and with a
`CONDITION_SUBJECTS` `of` key choosing *which object* every kind reads
(the source by default, the **attached permanent** for an Aura's "as long
as enchanted permanent is a creature", or a floating static's affected
one), so a new subject costs nothing per kind; `game/durations.py`,
`GameState.floating_statics` and `effects.GrantUntilEffect` are the
time-bound half, for every duration the turn-scoped `temp_*` fields can't
express ("until your next turn", "until end of combat", RULE 611.2b's
"for as long as `<condition>`", which *ends* an effect rather than merely
suspending it the way `active_if` does) — both bounds are surfaced on the
goldfish/shared board's "Statische Effekte" panel, with a currently-false
gate dimmed rather than hidden; **goad** (RULE 701.15) as a
per-goader designation (`GameObject.goaded_by`, its no-expiry sibling
`goaded_permanently` for "…goaded for the rest of the game", and a
re-derived `_goaded_by_static` for the "enchanted creature … is goaded"
Auras, all unioned by `combat.goaders`) imposing both of 701.15b's
requirements — "attacks
each combat if able" riding the existing `attacks_if_able` check, and
"attacks a player other than the goader if able" as a whole-attack
requirement checked leaving the declare-attackers step; a **target count
read off the board** at announce time (RULE 601.2c —
`TargetSpec.count_selector`, split into one gathering round per target by
`targeting.expand_counts` and merged back by `collapse_groups`, for "for
each opponent, goad up to one target creature that player controls" and
"goad up to X target creatures"), and `GameContext.created_objects`, the
referent for a clause naming what an *earlier clause of the same
resolution* just created ("**The tokens** are goaded …");
planeswalkers; commander damage + tax; the full RULE 702
keyword catalogue (194 keywords, flag keywords bound to combat, RULE 702.8b
Flash now gating cast timing, and — since 2026-08-05 — RULE 702.90/91
**Infect**/**Wither** as real damage-conversion behavior in
`RulesEngine.deal_damage` rather than just parse-level flag recognition:
an infect source's damage becomes poison counters on a player and
-1/-1 counters on a creature, wither the creature-only half); a trigger-subject family for "whenever
equipped/enchanted creature `<verb>`" and "deals combat damage to a player"
(`effect_binder`'s `"attached_permanent"`/`"self_or_attached_permanent"`
subjects + a `EventType.DAMAGE` `"filter"` predicate); "play/cast
from the top of your library" as a standing, battlefield-sourced permission
(`game/top_library.py` — Oracle of Mul Daya/Glarb, Calamity's Augur
hand-authored; the goldfish board's library zone shows the top card and its
buttons whenever a player has this active); RULE 601.2b's "as ~ enters,
choose a creature type/color" (Adaptive Automaton/Caged Sun/A-Thran
Portal-shaped) as a second `enter_replacement` family alongside "enter as a
copy of target X" — an interactive `pending_choice` offered before
battlefield entry (`RulesEngine._offer_enter_choices`/`resolve_enter_choice`,
`GameObject.chosen_type`/`chosen_color`), read back live every layer-engine
recompute by a dynamic `subtype_from_source`/`color_from_source`/
`add_subtypes_from_source` selector param so the board updates if the choice
is ever changed (Replay/Puzzle mode) rather than being baked in once; and the
deeper card-type structures — DFC transform + day/night/daybound-nightbound,
modal-DFC/Adventure/Split-Fuse/Prepared casting, Saga chapters, Class/Leveler
level-ups, and **battles** (RULE 310 — defense counters as the permanent's
only "toughness", a third `"battle"` defender kind alongside player/
planeswalker, the separate `GameObject.protector_id` who is the *defending*
player for it (310.8d) and the only legal blocker (310.8c) — which is what
lets a Siege be attacked by its own controller (310.8b) — and the Siege
defeat cycle, noticed by the SBA pass rather than at any counter-removal
site so every route to zero defense reaches it).

The **oracle-text → behaviour parser** (docs/09, `parser/oracle/`) is the
main ongoing effort: `normalize` → `segmenter` → `catalogue/handlers` →
`gate.parse_oracle` turns oracle text into `AbilitySpec`s with a fail-closed
`MODELED`/`UNMODELED` coverage verdict (a card only gets parsed effects when
*fully* modeled — never half-resolved). It covers most one-shot effect
families, ETB/dies/attacks/blocks/Saga-chapter triggers with RULE 603.1
subject scoping, `<cost>: <effect>` activated abilities, modal spells (both
spell-level and triggered-ability-level, "choose one —"/"choose one or
both —", "choose *N* —" for N>=2 — Kolaghan's/Austere Command-shaped,
combining N modes' effects in printed order — and, since 2026-07-16,
"choose *N* or more —" for a variable N, Farewell-shaped, combining
whichever modes were picked, also in printed order),
additional cast costs, the counter family, RULE 614.1 enters-tapped clauses
(all four conditional variants) and enters-with-N-counters clauses, static
anthem/lord clauses, and graveyard-card recursion/exile (Regrowth/
Reanimate/Deathrite Shaman-shaped — own/any/an opponent's graveyard × any
card type); regenerate (RULE 701.16 — a new pre-emptively-fired
`EventType.DESTROY` `RulesEngine.destroy` runs through the existing
replacement-effect machinery so `RulesEngine.regenerate`'s shield can
intercept it; also closed a RULE 701.16c gap where sacrifice previously
went through `destroy` too and could have wrongly been save-able by a
shield — sacrifice now uses the new non-destructive
`RulesEngine.put_into_graveyard`); RULE 115.1a "up to one target" (any
`{TARGET}`-based handler) generalized to N>=2 for `destroy`/`exile`/
`damage` (since 2026-07-16 — "destroy two target creatures"/"up to two
target artifacts and/or enchantments"; other targeting families stay
N=1-only until a real card needs it); a "remove a counter from ~"
activation cost (RULE 701.19/602.1); a generalized "search your library
for X" tutor/ramp/fetch grammar (criteria filters, "reveal", destination/
pronoun variants, reordered "shuffle...put on top" — 13 real popular
tutors, onto the already-generic `SearchLibraryEffect`); RULE 702.33b's
"if this spell was
kicked, \<effect\>." as an *additional* effect (`EffectSpec.condition` +
`game/effects.py`'s `ConditionalEffect`, not the "if kicked, ... instead"
amount-override shape); oracle-text recognition of 3 of the 5
already-bound replacement families (`double_tokens`/`double_counters`/
`additional_damage` — standing-permanent clauses; `prevent_damage`'s
two real cards are a different, still-unmodeled one-shot-spell shape);
and surveil (RULE 701.31, mirroring the existing scry handler/effect
shape exactly); and RULE 702.33b's kicked-conditional RULE 614.1 entry
counters — "if ~ was kicked, it enters with N counters on it" and its
Multikicker-scaled "…for each time it was kicked" sibling
(`counters.py`'s `kicked_gate`/`kicked_scale`, resolved against
`GameObject.kicker_count` in `RulesEngine._apply_entry_counters`).
and three "permission" statics that aren't about a permanent's own
characteristics at all, so each is consulted by a dedicated per-player/
per-object helper in `game/continuous.py` rather than the RULE 613 layer
engine proper (`cast_limit`/`draw_limit`/`no_untap`'s existing treatment):
"you may play an additional land on each of your turns" (`extra_land_drop`,
`continuous.extra_land_plays_for` — its one-turn resolve-time sibling
"…this turn" is the new `extra_land_play`/`ExtraLandPlayEffect`); "you have
no maximum hand size" (`no_max_hand_size`, `continuous.
has_no_maximum_hand_size`); and "you may choose not to untap ~ during your
untap step" (`no_untap_optional`) — the one real new engine primitive here,
since the untap step has no mid-step pause to ask fresh every turn, modeled
as a sticky `GameObject.skip_untap` toggle instead (`GameEngine.
set_skip_untap`); and RULE 400.7 + RULE 712.8's "exile ~/this saga, then
return it to the battlefield transformed under its owner's control"
(`exile_return_transformed` — a genuine zone change, not an in-place face
swap: a transforming Saga's own final chapter, Fable of the Mirror-Breaker-
shaped, or a transform-flip permanent's activated ability phrased this way
instead of a bare "transform ~", Ayara/Clive/Jin-Gitaxias-shaped).
Three more greenfield subsystems, previously deprioritized per the
completion roadmap's M6: the **Monarch** (RULE 725, `GameState.monarch_id`/
`RulesEngine.become_monarch`) and **Initiative** (RULE 726, `initiative_id`/
`take_initiative`) designations, each with their own inherent, source-less
triggered abilities (the monarch's own end step draws a card; either
designation swaps to a creature's controller when it deals that designation's
holder combat damage) checked fresh off live state by `RulesEngine.
_collect_inherent_triggers` rather than found by the ordinary per-permanent
trigger scan — neither is attached to any permanent for that to find. RULE
726's "venture into the dungeon" companion trigger isn't fired (dungeons,
RULE 309, aren't modeled at all yet), so a card whose only clause is "You
take the initiative." still becomes fully MODELED on the strength of the
designation swap and its own combat-damage-steal trigger alone. **Emblems**
(RULE 114, "\[Player\] get\[s\] an emblem with '\[ability\]'") create a
command-zone marker with no characteristics beyond the quoted ability
(`models/emblem.py`'s `Emblem` — a minimal `source` stand-in carrying just
`controller_id`/`timestamp`, since an emblem has no permanent to bind onto
at bind-on-load like every other ability); the quoted ability is recursively
parsed into a full nested `AbilitySpec` at parse time
(`parser/oracle/catalogue/handlers.py`'s `_emblem_ability_spec`, mirroring
the Aura/Equipment quoted-grant recursion) and bound once, at resolve time,
against that synthetic source (`RulesEngine.create_emblem`); `game/
continuous.py`'s static-ability scan and `RulesEngine._collect_triggers`
both read every player's `Player.emblems` alongside the battlefield so a
static/triggered emblem ability applies exactly like a permanent's own.
`parse_oracle` itself is now memoized (content-keyed on
every field it reads, `parser/oracle/gate.py`) since it's called once per
`GameObject` built — a popular card no longer gets re-parsed from scratch
on every copy/every game. `parser/oracle/processing_list.py` tracks
cache-wide coverage and ranks the next handlers worth building. The cache is
now bulk-loaded with the **full ~35k-card Oracle universe**
(`scripts/import_bulk.py`), so coverage is measured against that: **34.2%
covered (11,894 / 34,811) as of 2026-08-17, PARSER_VERSION 92** (parser-`MODELED` **or**
hand-`AUTHORED`).
Re-measure with `scripts/coverage_report.py` (ledger-backed — see
`services/coverage_db.py`) before trusting this number; Batches 1–10 are all
shipped; open parser tickets are `PAR-*` in
`docs/implementation-state/BACKLOG.md`, and the long-tail strategy (plus
its recurring lessons and worked samples) is
`docs/implementation-state/PARSER_LONG_TAIL.md`. **Stickers (RULE 123) are a
permanent project non-goal, not a backlog gap** — will never be
implemented; the gate classifies any card mentioning "sticker" as
`NEVER_SUPPORTED` (`parser/oracle/gate.py`), a verdict distinct from
`UNMODELED` kept out of both the "covered" count and the processing-list
backlog ranking.

A **replacement-effects batch** closed most of the open RULE 616.1 backlog:
`prevent_damage`'s one-shot spell shield (Riot Control/Thought Lash —
`PreventDamageEffect`/`RulesEngine.prevent_damage_to_player`, a turn-scoped
`ReplacementEffect` on `Player.player_effects` rather than a permanent's own,
since nothing is being regenerated); the damage-multiplying family gaining
oracle-text recognition (Furnace of Rath/Dictate of the Twin Gods's unscoped
"double", Fiery Emancipation's "triple", Gratuitous Violence's own
creature-scoped phrasing — `_double_damage_replacement`'s new `multiplier`/
`creature_only` params, also fixing a latent bug where the hand-authored
Gratuitous Violence entry wrongly required combat damage); and Lurrus of the
Dream-Den's own trailing "exile instead of graveyard" clause
(`GraveyardCastPermissionEffect.exile_if_would_be_put_into_graveyard`,
redirecting at `RulesEngine._move_to_graveyard` — the one choke point every
graveyard-bound move funnels through, regardless of cause). The same batch
also added two RULE 605.3a mana-spend-restriction kinds (`chosen_type_spell`
— Cavern of Souls/Unclaimed Territory, resolved per-instance off the land's
own chosen creature type at tap time; `mana_value_or_x_spell` — Helga/
Troyan) and RULE 122 energy's `{E}` activated-ability cost pips
(`ActivationCost.pay_energy`). A **follow-up batch** then closed the rest of
that ToDo section: more RULE 616.1 replacement families — life-gain rewrite
(Angel of Vitality/Boon Reflection, `gain_life_replacement` on a new
`EventType.LIFE_GAIN`), recipient-scoped +1/+1 counter replacement (Hardened
Scales additive / Branching Evolution double / Kami permanent-scoped,
`_double_counters_replacement`'s `plus`/`multiplier`/`recipient` params),
and "if ~ would die, exile it instead" (Gloomshrieker/Corpseweaver Prodigy,
`die_to_exile` on a new `EventType.WOULD_DIE`); **Throne of Eldraine** fully
MODELED (chosen-colour mana production `ManaAbility.color_selector`, the
`monocolored_spell`-of-chosen-colour restriction, and its second ability's
colour-locked cost `ActivationCost.spend_only_chosen_color`); and energy's
resolve-time optional "you may pay {E}{E}. If you do, `<effect>`." (Aether
Chaser, `pay_energy_then`/interactive `request_pay_energy_then` choice) plus
"you get {E}" production (`get_energy`).

A **triggers/grants batch** then closed that whole ToDo section (seven
items, +238 cards): RULE 603.1 **group-subject damage triggers** ("whenever
a creature you control deals combat damage to a player" — needed DAMAGE's
own `source_controller_id`/`source_id` keys threaded into
`effect_binder._build_group_ok`, whose object lookup had been hard-coded to
`instance_id`); **"Sacrifice ~ unless you pay `<cost>`."** (RULE 701.17, the
biggest remaining upkeep-trigger template) as a real interactive
pay-or-lose-it `pending_choice`, deliberately built on **ward's** existing
machinery — `_can_pay_ward_cost`/`_pay_ward_cost` were never ward-specific,
so they were renamed `_can_pay_player_cost`/`_pay_player_cost` and shared
rather than duplicated; **quoted granted phase/upkeep triggers** (RULE 500.7
`STEP_BEGIN` grants, with `phase_relation` resolved against the *granted-to*
permanent's controller — Commander's Authority/Clawing Torment); **Aura
lifecycle triggers** — RULE 700.4's long "is put into a graveyard from the
battlefield" folded to "dies" in `normalize`, which exposed a real engine
bug (`_move_to_graveyard` fired `EventType.DIES` for *creatures only*, so a
dying Aura/enchantment/land was invisible to every dies-trigger) — plus
`ReturnToHandEffect`'s self form (Rancor/Flickering Ward); **standing
granted protection** (RULE 702.16 as a genuine layer-6 concept,
`grant_protection_static`/`GameObject._granted_protections`, the
continuously-re-derived sibling of the resolve-time `temp_protections`
grant — Hungry Lynx/Righteous War/Absolute Grace/Voice of All);
**type grants past the battlefield** (RULE 613.4a — `continuous.
_apply_off_battlefield_types`, a dedicated pass over the controller's
non-battlefield zones + their spells on the stack, for Arcane Adaptation/
Leyline of Transformation/Ashes of the Fallen, alongside the battlefield
half for Xenograft/Realmwright/Lifecraft Engine); and **quoted
mana-ability grants** ("Elves you control have '{T}: Add {B}.'" — recognized
directly by `static_handlers._granted_mana_options`, since a plain mana
ability is claimed-*without*-a-spec by the segmenter and the nested parse
has nothing to re-emit).

A **cEDH-cube batch** (batch 25, 2026-07-22) then made all **43 cards** of
that pool playable, closing the whole "cEDH staples cube" ToDo section. Six
new *general* mechanisms carried most of it, each closing several cards at
once: `GameContext.trigger_event` (RULE 603.1 — the firing event exposed for
exactly one resolution window, so an effect can depend on *which* firing
without every `apply()` growing a parameter); the **triggered mana ability**
(RULE 605.1b/605.4, `TriggeredAbility.mana_ability` — resolves off-stack, so
its mana is spendable in the payment that triggered it: Wild Growth,
Kinnan); `pay_cost_then` (RULE 118.3 — the general form of the shipped
energy-only optional payment, with an "if you don't" branch and an
event-named payer: Mana Vault, Wandering Archaic, both Pacts);
`GameEffect.extra_target_specs` (**two independently-chosen targets of
different kinds in one clause** — Brass Squire, Halvar, Archdruid's Charm);
`RulesEngine.dig_until` (the cascade dig with predicate and both
destinations parameterized) alongside `request_name_card` (the only choice
whose answer space isn't enumerable from game state — Demonic Consultation);
and the two remaining loop shapes, **repeat-until-a-predicate** (Helm of
Obedience) and **open-ended** (Lim-Dûl's Vault, bounded by its own life
payment). Four RULE 702 keywords went from recognized-but-inert to real
behaviour — **Fading** (702.32), **Soulbond** (702.94, genuine pairing state
broken as an SBA), **Mutate** (702.140, merging onto the host, which stays
the same permanent per 702.140c) and **Bargain** — plus a *granted* Escape
(702.138 from Underworld Breach rather than printed), a control **exchange**
(701.10, Gilded Drake), mass phasing + a player life-lock (702.26b/119.6,
Teferi's Protection), and RULE 606.5c's `[-X]` loyalty cost. Two latent bugs
surfaced and were fixed on the way: `creature_you_control` had been
*excluding* the ability's own source (so Mother of Runes couldn't protect
herself and a Karoo land couldn't bounce itself — only the new
`other_creature_you_control` excludes it now), and an "up to one target"
trigger with no legal target was being dropped rather than resolving with
zero targets (RULE 115.1a — which is what makes Gilded Drake sacrifice
itself on an empty board).

A follow-up **batch 26** then closed that pool's whole documented residue —
the nine narrow simplifications each shipped card had recorded — so nothing
of it is open any more. The load-bearing piece was **RULE 608.2 suspended
resolutions** (`GameState.deferred_effects` / `RulesEngine.
resume_deferred_effects`): the state holds exactly one `pending_choice`, so
a resolution with 2+ interactive effects had been letting the second
silently overwrite the first player's prompt; the remainder of the effect
list is now parked and resumed once the choice is answered. On top of that:
**Entwine** as a real priced modal upgrade (RULE 702.42a — a second,
separately-priced and lockable "choose all" cast action, replacing the free
`or_both` flag Tooth and Nail had been borrowing); per-found-card
**conditional search destinations** (`SearchLibraryEffect.destination_if`);
Beseech the Mirror's **face-down exile** round trip (RULE 701.20a,
`GameObject.face_down_in_exile` plus Rebound's own exile free-cast window,
with the "…to hand if it wasn't cast this way" half as a delayed trigger);
**The Ring tempts you** (RULE 701.51/701.52 — `Player.ring_level`/
`ring_bearer_id` as a designation subsystem in the Monarch/Initiative mould,
its level-1 static split between a layer-4 legendary grant and a
`can_block` restriction, its levels 2–4 built fresh per firing so they
follow the *current* bearer); a **general interactive object chooser**
(`RulesEngine.request_choose_objects`) that replaced the "auto-pick the
first candidate" convention across seven cards at once, carrying its whole
decision — including "if you do" follow-ups as serialized `EffectSpec`s —
as clone-safe data rather than a closure; **mutate under the pile** (RULE
702.140b) with a real `non_human_creature_you_own` target line; **RULE
305.7**'s land-type ability removal (which also closed the same hole for
Humility/Dress Down, since `mana_abilities_for` had never honoured
`loses_all_abilities`); and parser recognition of the compact inline
"gets A **or** B" activated ability. Full detail, wave by wave, in
`docs/implementation-state/Done_Backend.md` ("cEDH staples cube").

A **card-type-structures batch** (2026-07-28) then closed the last four
structural card-type gaps at once, so RULE 300–315 and RULE 900–905 are
both complete. **Face-down spells and permanents** (RULE 708 — morph,
megamorph, disguise, manifest, cloak, `game/face_down.py`) are modeled as a
*face swap*, the same shape a DFC transform already used: the object's whole
face-up bundle is stashed (`GameObject._face_up_snapshot`) and `card` is
swapped for a synthetic 2/2 with no text, so the layer engine, combat and
the board read a plain 2/2 with no special case; casting face down is a
fourth `face` on `cast_spell` (`face="face_down"`, {3} per RULE 702.37a),
turning face up is a real RULE 116.2b **special action** (`GameEngine.
turn_face_up` — no stack, no timing gate, one offered option per legal
route, since RULE 701.40c lets a manifested morph card use either its morph
cost or its mana cost). **Dungeons** (RULE 309, `models/dungeon.py` +
`game/dungeons.py`) are plain data on `Player.dungeon` rather than a
`GameObject` (the `Emblem` argument), with the room graph parsed out of the
*raw* printed card text — "(Leads to: …)" is arrows, not reminder text, so
it must be read before `normalize` strips parentheticals — and venturing
(RULE 701.49) implemented branch-for-branch, which also completed RULE
726.2: the initiative now fires all three of its inherent abilities. The
RULE 603.1/500.7 **trigger-condition vocabulary** went from four object
verbs and four steps to ten and nine, all driven by one table
(`segmenter._TRIGGER_VERBS`) that feeds every subject regex — a verb earns
a row only if the engine fires an event carrying an `instance_id` for it,
which is why "becomes untapped" is still deliberately absent. And the RULE 9
**casual variants** — Planechase (901), Archenemy (904), Vanguard (902) —
are playable behind a `GameFormat` record (`models/game_format.py`), reusing
the dungeon idea of a command-zone pool that begins outside the game
(`game/variants.py`, `services/variant_card_database.py`). The RULE
809/810/811 **team** variants are deliberately out: they change the turn
structure itself, so they're a turn-loop/seats project, tracked as `PLR-14`
rather than as a card type. A format picker (Commander/Constructed/
Planechase/Archenemy/Vanguard/Planechase Commander) reaches both the
Multiplayer **Setup** table options (`LobbyGame.game_format`, host-only,
`api/multiplayer.py`'s `POST .../options`, plus a host-only RULE 904
Archenemy seat picker once the format has that variant) and the Goldfisch
start screen (`StartGoldfishRequest.gameFormat`) — `GET /api/game/formats`
backs both pickers off the one `models/game_format.FORMATS` catalogue.
`build_goldfish_engine`/`build_multiplayer_engine` (`services/
game_session.py`) apply it via `GameEngine._setup_variants`, same as
`GameEngine.new_game`. A per-seat **Vanguard avatar** picker (every
Vanguard seat just gets a random avatar) and its avatars' rules text
beyond the hand-size/life-total modifiers already applied are a
**permanent non-goal**, not an open ticket — see `docs/implementation-
state/BACKLOG.md`'s MEC callout: `scripts/import_bulk.py` already drops
the Scryfall `vanguard` layout from the card cache entirely, so avatar
text can never reach the parser's coverage ranking regardless.

A follow-up batch (2026-08-06) finished the "Eliferate"/"Imodane" saved
decks to full playability (91/91 and 69/69) and, along the way, fixed two
durable engine bugs that had silently blocked *any* card from ever
triggering off them: `RulesEngine.add_counters`/`add_player_counters` and
`create_token` each computed their event through `apply_replacements`
but never called `state.fire_event` on the result, so COUNTER and
CREATE_TOKENS events were never broadcast to `_collect_triggers`. It also
added RULE 603.3d **trigger doubling** (Roaming Throne — `continuous.
trigger_doubler_bonus`/`TriggerDoublerEffect`, "an additional time"
rather than "a bigger effect", no prior analogue) and **"spell
watchers"** (`GameState.spell_watchers`, Dual Strike's "when you next
cast an instant or sorcery this turn, copy it") — a GameState-level
mechanism distinct from both an object-bound `TriggeredAbility` and a
step-bound RULE 603.7 `DelayedTrigger`. Imodane, the Pyrohammer's own
signature ability ("whenever an instant or sorcery spell you control
that targets only a single creature deals damage to that creature,
Imodane deals that much damage to each opponent") needed
`DealDamageEffect.amount_from_trigger_event` plus two new DAMAGE-event
flags (`source_is_instant_or_sorcery`/`source_targets_only_single_
creature`) computed at the point where both the source's card type and
the *resolving effect's own* `target_spec` shape are known. Full detail,
including every documented per-card simplification, in
`docs/implementation-state/Done_Backend.md`'s "Eliferate (finish) and
Imodane" entry.

A first pass (2026-08-06) then started on a much larger ask — making all
**seven "cEDH"-named saved decks/cubes** playable (`Ojer cEDH`/`cEDH
Rocco`/`[cEDH] Glarb Bloomsday`/`cEDH staples`/`cEDH staples 2`/`cEDH
M-K`/`cEDH Kinnan`, a 393-unique-card pool an order of magnitude past any
prior single-deck batch) — tracked as ordinary open work (`MEC-12` in
`BACKLOG.md`) rather than forced to one-sitting completion. It fixed a
segmenter false-negative (`_COST_LOOKS_REAL` didn't recognize "Exile this
card from your hand: Add …" as a real cost, even though `costs.py`/
`mana_abilities.py` already fully implement RULE 605.1a hand-zone mana
abilities — Simian/Elvish Spirit Guide), added `TaxedDrawEffect` (RULE
118.3's "unless" idiom applied to a draw, where the payer is the
*triggering spell's own caster* rather than the ability's controller —
Rhystic Study/Mystic Remora/Esper Sentinel), and hand-authored Force of
Will/Negation/Vigor and Daze at their real printed mana cost with RULE
118.9's alternative "pitch" cost dropped (a confirmed-unbuilt mechanism,
113 cards cache-wide per `parser_probe.py blocked` — its own open item
now, not rebuilt per-card). `BACKLOG.md`'s `MEC-12` also records several
other confirmed-missing primitives found along the way (that `free_cast_
condition` RULE 601.2f free-casting has never actually been reachable
from a real game session — the UI never surfaces it) so the next pass
doesn't have to re-derive them.

A second pass (2026-08-06) then closed that first pass's own headline
missing primitive: RULE 115.4/601.2c **"change the target of target
spell"** (`ChangeTargetEffect`/`RulesEngine.change_target`, `game/
effects.py`/`game/rules/misc_mixin.py`) — a live retarget of an
*already-existing* stack item, distinct from the already-shipped "choose
new targets for a freshly-made **copy**" (RULE 707.10c). The changer is
this effect's own controller, not the targeted spell's (RULE 115.4a);
legal alternatives are recomputed fresh against the *current* board (RULE
115.1c), always including the current target itself (nothing excludes a
"new" pick from matching the old one) — a single legal option auto-
applies with no prompt, the same "forced, asking would be theatre" idiom
`_choose_objects_choice` uses. At the time, deliberately spells-only (not
the full "spell or ability" Deflecting Swat is printed with — retargeting
an *ability* on the stack needed a stable way to name one, since
`StackItem.obj` is `None` for an ability item) and scoped to a spell with
exactly one existing target (both real cards in scope only ever retarget
one — ENG-26 below lifted the first restriction; the second still holds).
Hand-authored Misdirection (mandatory) and Deflecting Swat (optional,
"you may") at their real printed mana cost ({3}{U}{U}/{2}{R}), RULE
118.9's alternative cost dropped at the time (MEC-15 below built it).
Full detail, both passes: `docs/implementation-state/Done_Backend.md`'s
"seven 'cEDH'-named saved decks" entries.

A sort-into-categories pass (2026-08-06) then filed the second pass's own
"confirmed-missing primitives" as six standalone tickets and closed every
one the same day. **ENG-26** built the "target an activated/triggered
ability" primitive the paragraph above deferred (RULE 115/608.2b —
`StackItem.stack_id`, a stable identity every stack item gets alongside a
spell's own `GameObject.instance_id`; `targeting.py`'s `"ability"`/
`"spell_or_ability"` kinds; `CounterAbilityEffect`, hand-authored onto
Stifle/Trickbind; `ChangeTargetEffect`'s new `spell_or_ability=True`,
closing Deflecting Swat's own real printed scope). **ENG-27** built two
mana primitives sizing the ticket had mis-described (Bloom Tender's real
cached text turned out to be a deterministic "one mana of each color
among your permanents" aggregate, not a menu — `ManaAbility.
color_selector`'s `"colors_among_permanents_you_control"`; Carpet of
Flowers needed a genuinely targeted, once-per-turn, "X mana of any one
color" triggered ability instead, since RULE 605.5a disqualifies a
targeted ability from ever being a mana ability at all —
`AddManaEffect.amount_from_target_count_selector`/`once_per_turn_
ability`, `GameObject.added_mana_with_ability_this_turn`). **ENG-28**
fixed `cast_prohibition` silently dropping its own `active_if` gate (a
bug, not a missing feature) and added a general "During your turn,
`<static>`." RULE 613.6 wrapper alongside the existing "as long as" one —
156 cards solo-blocked on that phrase alone, not just the two the ticket
named. **MEC-15** built RULE 118.9's alternative-cost primitive for real
— `AbilitySpec.alt_cost`, `GameObject.alt_cast_cost`/`alt_cast_condition`,
`GameEngine.can_cast`/`cast_spell`'s new `alt_cost=True` branch parallel
to the existing `free=True` one — and, critically, the UI wiring neither
`free=True` nor `alt_cost` had ever had: `_offer_cast` now offers a
free/alt-cost cast as its own action alongside the plain one, each only
when actually payable, round-tripped by `GameSession._dispatch_cast_
spell`. Force of Will/Negation/Vigor/Daze all gained their real
alternative cost. **MEC-16** bound RULE 702.24 Cumulative Upkeep for the
first time (`CumulativeUpkeepEffect`, `_kw_cumulative_upkeep`) — the
keyword was already parser-recognized, just never wired to behaviour;
since keyword binding is independent of hand-authoring, Mystic Remora and
Thought Lash's own long-standing "not built yet" simplifications closed
for free, without either spec being touched. **MEC-17** built RULE
702.45-adjacent Imprint (`ImprintEffect`, `request_choose_objects`'s new
`remember=True`, `ManaAbility.color_selector`'s `"imprinted_card_colors"`)
for Chrome Mox. Full detail, all six: `docs/implementation-state/
Done_Backend.md`'s matching entries (search each ticket id).

A **Marchesa V4.2 batch** (2026-08-10) made the whole 96-card "Marchesa
V4.2" saved deck playable, closing its 21 previously-unmodeled cards
through a mix of general parser handlers (most of the batch — "gain
control of target creature [with mana value N or less] until end of
turn. Untap it. It gains haste." — the threaten-effect family, ~90 cards
— and its untargeted "untap all creatures and gain control of them"
sibling; "Destroy target X. It can't be regenerated." — 110+ cards;
"basic Island, Swamp, or Mountain card"-shaped combined search criteria — the Panorama/
Landscape/Monument tri-land cycles, ~40 cards; "each player/opponent
sacrifices N `<type>` of their choice" mass edicts; "whenever you/an
opponent draws a card, `<effect>`" — the Sheoldred/Underworld Dreams
trigger family; "sacrifice an artifact or creature" additional costs;
"Sacrifice it. When you do, `<effect>`." collapsed to a plain sequence
for its one safe (mandatory-antecedent) case) and seven hand-authored
entries for the rest (Liliana, Dreadhorde General's edict-family loyalty
abilities plus a genuinely new "sacrifice all but one of each permanent
type" `-9`; Kiki-Jiki/Puppeteer Clique sharing a new "create/reanimate
with haste, `[sacrifice/exile]` it at the beginning of the next end
step" primitive; Mikaeus, the Unhallowed's damage-sourced destroy plus a
negated-subtype anthem selector; Spark Double's copy-with-extra-counter;
Danny Pink's per-creature "for the first time each turn" counter-draw
grant; Arcane Denial's controller-redirected delayed draw; Black Market
Connections' `STEP_BEGIN`-wrapped "choose one or more" reusing Farewell's
own `modes` shape; and a deliberately partial Agatha's Soul Cauldron,
whose mana-spend-restriction-lift and dynamic ability-borrowing clauses
are real, substantial, un-built primitives left as an open gap rather
than silently modeled). Along the way it found and fixed five dormant
engine bugs no prior card had exercised: `SacrificeEffect`'s
`each_player`/`each_opponent` selector silently overwriting one player's
sacrifice choice with the next's when 2+ needed a real pick in the same
resolution (now sequenced via `GameState.deferred_effects`, the same
RULE 608.2 idiom `_apply_effects_partitioned` already used one level up);
`_matches_permanent_type`'s three near-duplicate copies (one per mixin)
never recognizing `"planeswalker"`/`"battle"` and silently falling through
to "any permanent"; `DrawCardEffect` consuming a shared `targets` list
even when it declared no target of its own; and both the parser-facing
and layer-6-grant "which event field names the firing object" tables
missing a `COUNTER` row entirely (any "whenever counters are put on ~"
self-subject/granted trigger was unreachable). See `docs/implementation-
state/Done_Backend.md`'s "Marchesa V4.2" entry for full detail on every
primitive and bug fix, and its own list of what a future batch should
build next (the ~200-card "you may `<action>`. When you do, `<effect>`."
optional-antecedent family in particular — this batch's mandatory-
antecedent collapse deliberately doesn't touch it).

A **Vivi B4 batch** (2026-08-10, same day) then made the "Vivi B4" saved
deck (a 99-card storm-shell Commander deck) fully playable — 18 of its 99
unique cards were unmodeled, closed via 11 general parser handlers plus 7
hand-authored entries. The single biggest parser win of the whole batch was
`look_top_select` (`RulesEngine.look_top_select`) — "Look at the top N cards
of your library. Put M of them into your hand and the rest `<destination>`."
(Anticipate/Dig Through Time/Diabolic Vision-shaped), the fixed-selection-
count sibling of scry/surveil's per-card away/stay decision, closing 38+
cards at once; a widened cast-spell trigger subject ("whenever **you/an
opponent/a player**" now on the *typed* row, not just the untyped one)
closed another 51. Also shipped: `ReturnToLibraryEffect` (RULE 701.3's
"put target X on top/bottom of its owner's library", 10 cards) plus mass
"return all X" support on `ReturnToHandEffect`; a new RULE 702.137
**Delirium** condition; `IntuitionEffect` (a genuine two-player interactive
search — the caster picks, a *targeted opponent* chooses which one is
kept); `CoinFlipEffect` finally giving the long-dormant `RulesEngine.
coin_flip` (RULE 705.1) its first real consumer; `ActivationCost.hand_zone`
(a land's own "pay `<N>`: put this card from your hand onto the
battlefield" special action, `graveyard_zone`'s hand-zone sibling); and
`GrantSelfActivatedAbilityEffect` (RULE 714.2c's *lasting* Saga-chapter
self-grant) for the batch's largest single card, Urza's Saga. That last one
surfaced a real, **cache-wide** dormant bug: every "create an N/N `<color>`
`<Subtype>` **artifact** creature token" clause (Construct/Thopter/Servo/
Golem tokens across dozens of cards) silently produced a token missing the
Artifact card type entirely — `services/token_database.py`'s
`synthesize_token_card` treated "Creature"/"Artifact" as strict either/or,
and all three of the parser's independent token-description word-splitters
already recognized "artifact" as a supertype marker and just discarded it
rather than threading an `is_artifact` flag through. Fixed at the root
(`synthesize_token_card` now combines "Artifact Creature", the three
duplicated word-splitting loops consolidated into one shared
`_split_token_mid_words` helper) rather than worked around for just the one
card that surfaced it. Left open, tracked as `MEC-23`/`MEC-24`: Quicksilver
Elemental's "gains all activated abilities of target creature" (needs a
new "temporarily copy a target's whole live ability set" primitive, a
different shape from the existing single-fixed-ability layer-6 grant), and
the single-*target* (as opposed to Past in Flames' "each") flashback-grant
family (Recoup/Snapcaster Mage-shaped, ~10 cards). Full detail — every
primitive, every card, the token-type bug's full trace — in
`docs/implementation-state/Done_Backend.md`'s "Vivi B4" entry.

**MEC-18/MEC-19** (2026-08-11) closed two RULE 603.1-adjacent trigger-family
gaps, both far bigger than their filing sessions had scoped them. MEC-18
generalized RULE 118.3's `pay_cost_then` (already shipped for Mana Vault/
Wandering Archaic) from two hardcoded oracle-text shapes to the whole "you
may `<sacrifice/discard/pay-mana/pay-life>`. When you do, `<effect>`."
family — no new engine primitive, a parser-recognition widening plus a
guard fix so the generic "you may " stripper doesn't eat the clause first
(89 real cards). MEC-19 built `EventType.BECOMES_TARGET` (RULE 115/601.2c
targeting had never reached the event bus — `RulesEngine.check_ward` is now
the general "targets finalized" choke point, still doing ward's own
unchanged direct check alongside it) and `CounterUnlessPayEffect` (a thin
adapter onto `resolve_ward_effect` for the ~90-card cycle that prints
Ward's exact outcome as ordinary text instead of the keyword), closing
Goldspan Dragon's "attacks or becomes the target of a spell" and Tectonic
Giant by name plus 14 more real cards. Full detail in
`docs/implementation-state/Done_Backend.md`'s "MEC-18/MEC-19" entry.

**MEC-25/MEC-20/MEC-21** (2026-08-11) closed three more named gaps, none
needing a wholly new mechanism. MEC-25 gave `grant_mana_ability` an
*upgrade* shape (`GameObject.granted_mana_ability_upgrades`, `mana_abilities.
mana_abilities_for`'s cost-shape replace-matching) so a layer-6 mana grant
can carry its own non-`{T}`-only cost and replace a matching printed
ability instead of stacking a second one — Goldspan Dragon's Treasures now
keep exactly one "{T}, Sacrifice this artifact: Add two mana of any one
color" ability, at the real printed amount. MEC-21 built the general "cards
exiled with ~" tracker the user asked to see generalized — `GameObject.
exiled_with_ids`, stamped by `ExileEffect`'s new `track_exiled_with` mode,
the accumulating sibling of the single-slot O-Ring `linked_exile_id`,
reusable by any future "exile with ~" card (~185 cached cards print that
shape) — and used it for Agatha's Soul Cauldron's own two previously-open
clauses: `grant_borrowed_activated_ability` (`continuous.
_apply_borrowed_activated_abilities`/`_retarget_effect_source`, RULE 113.7c
— reads an exiled creature's own bind-on-load abilities and rebuilds each
as a fresh `ActivatedAbility` redirected onto the grantee) and
`grant_any_color_for_activation` (a standing RULE 605.1a wildcard
*permission* over activation-cost mana, `continuous.
any_color_for_activation`, newly reached from all three activation-cost
payment sites in `game/engine/activation_mixin.py` via `ManaPool`'s
existing `wildcard` param). MEC-20 closed RULE 601.2f's "Expertise" cycle
— `effects.FreeCastFromHandEffect` opens a `request_choose_objects`
`"grant_free_cast"` choice that *arms* a picked hand card's existing
`GameState.free_cast_instance_ids` entry rather than casting it immediately,
so the caster still gets the ordinary `legal_actions` cast option with full
targeting; one parser handler covers a literal cap, the `"x"` sentinel
(Electrodominance), and a count-selector cap (Epistolary Librarian's "where
X is the number of attacking creatures") in one row. Full detail — every
primitive, every card, the "you may " peel-guard/ability-word gotchas hit
along the way — in `docs/implementation-state/Done_Backend.md`'s
"MEC-25/MEC-20/MEC-21" entry.

**MEC-23/MEC-24** (2026-08-11) closed the last two gaps the Vivi B4 batch
had left open. MEC-23 (Quicksilver Elemental) needed the *resolve-time,
single-target* sibling of MEC-21's *standing* ability-borrowing static:
`effects.GainActivatedAbilitiesOfTargetEffect` snapshots a target's
`activated_abilities` once, at resolution, redirecting each via the
existing `continuous._retarget_effect_source` onto a new turn-scoped
`GameObject.temp_granted_activated_abilities` field (unioned with the
layer-6 grant by the one `granted_activated_abilities` property every
consumer already reads) — later changes to the target's own abilities
don't retroactively change what was copied. Its own "spend blue mana as
though it were mana of any color" clause widened `continuous.
any_color_for_activation` with `self_only` (this permanent's abilities
only, not Agatha's unscoped "creatures you control") and `from_color`
(only *that* WUBRG letter substitutes, not all five — a new `ManaPool.
_solve` branch: `[real_color, wildcard_color]` rather than every color).
Hand-authored as a genuine singleton shape; two more real cards found
printing the same wildcard phrasing (Drana and Linvala, Scheming Fence)
need a *standing, group/choice-scoped* borrow instead, filed as `MEC-26`
rather than re-deferred a third time. MEC-24 built the *targeted* sibling
of the already-shipped untargeted "each instant and sorcery card in your
graveyard gains flashback…" grant (Recoup/Snapcaster Mage/Slickshot
Lockpicker/Sphinx of Forgotten Lore/Katilda and Lier) — `GameState.
temp_flashback_grants` (`instance_id -> cost`), a per-*graveyard-card*
marker (the same shape `temp_play_permissions` already uses for a
temporarily-castable exiled card) rather than one hung off the granting
permanent, since the grant must survive independently of whatever
granted it. `effects.GrantFlashbackToTargetEffect` stamps it;
`_graveyard_cast_keyword`/`_flashback_cost` (`game/engine/{lands,
casting}_mixin.py`) consult it alongside a printed Flashback keyword, so
cost computation and the RULE 702.34a exile-after-cast fall out of the
existing Flashback machinery with no new casting code. Full detail, both
tickets: `docs/implementation-state/Done_Backend.md`'s "MEC-23/MEC-24"
entry.

**MEC-26** (2026-08-11, same day — the mandatory hand-author-or-promote
close for the two cards MEC-23 had just deferred a second time) built the
*standing, group-scoped* sibling of MEC-23's resolve-time snapshot:
`grant_borrowed_activated_ability` (MEC-21's own static) gained a
`source_mode` param generalizing beyond `exiled_with_ids` — `"group"`
reads a live `affects` selector straight off the battlefield every
recompute (Drana and Linvala's "all creatures your opponents control");
`"chosen_permanent"` reads a single donor named once by a new interactive
ETB pick (Scheming Fence — `ChoosePermanentEffect`/`request_choose_
objects`'s new `"choose_permanent"` action, `GameObject.
chosen_permanent_id`, a new `continuous.group_selector_objects` selector
of the same name). Both printed "Activated abilities of `<X>` can't be
activated" clauses needed no new code — `continuous.activation_prohibited`
already reused the ordinary `affects` vocabulary, just never scoped to
these selector values by a real card before — and both "you may spend
mana as though it were mana of any color to activate those abilities"
clauses were fully covered by MEC-23's existing `self_only`, since neither
card prints any *other* activated ability of its own; the ticket's own
worry that `self_only` might over-scope didn't survive contact with the
actual cards. Found and fixed one latent bug along the way:
`grant_borrowed_activated_ability` defaulted `has_counter_kind` to
`"+1/+1"` for every caller, not just Agatha's own qualifier, so Drana and
Linvala's `affects="self"` grantee (no +1/+1 counters of her own) was
silently filtered to nothing — now `None` unless a caller explicitly asks
(Agatha's own catalogue entry already did). Full detail:
`docs/implementation-state/Done_Backend.md`'s "MEC-26" entry.

**MEC-29** (2026-08-12) closed the two cards a MEC-28 pass had left open —
this time with two genuinely new primitives rather than a further
deferral. **RULE 702.122 Crew** went from parser-*recognized* (a bare
keyword spec, satisfying the coverage gate) to real behaviour for the
first time: `ActivationCost.crew_power`, `GameEngine._resolve_crew_cost`/
`_crew_pool` (an "any number from a pool" cost sized by a power
*threshold*, not `tap_others`' exact count), `GameObject.crewed_by_ids`
(RULE 702.122c, reset each untap step), and `effect_binder.
_crew_activated_ability` binding "Crew N" onto every Vehicle in the cache
at once via the same `_keyword_activated_ability` dispatch Equip/Cycling
already use — the same "recognized but inert" gap PAR-9 closed for
Cycling. Needed two supporting fixes to actually work rather than merely
bind: `Card.vehicle_power`/`vehicle_toughness` (RULE 208.1 — a noncreature
permanent's own printed P/T, which this model had never captured at all,
so a freshly crewed Vehicle came in 0/0 and died to RULE 704.5f
immediately), and a real parser bug in `_ANTHEM_RE`'s `_scope` (a bare
"Vehicles you control" anthem had been silently mis-modeled as
`creatures_you_control`, since nothing blocked a non-creature *subtype*
word the way `_NONCREATURE_TYPES` already blocks non-creature *types* —
fixed with `_ARTIFACT_SUBTYPES`/`_vehicle_scope_params`, shared by
`_GRANT_RE`/`_QUOTED_GRANT_RE` too). A new `"crewed_by_self"` RULE 603.1
group-subject trigger-condition key closes **Balthier and Fran**'s own
"whenever a Vehicle crewed by ~ this turn attacks" (hand-authored — the
phrasing is a cache-wide singleton, not worth a grammar row). **Tifa,
Martial Artist**'s "whenever **one or more** creatures you control with
power 7 or greater deal combat damage to a player" needed correcting this
ticket's own prior framing first: RULE 603.1 group-subject scoping for "a
creature you control deals combat damage to a player" already existed
(Bident of Thassa/Deepfathom Skulker) — the real gap was the "one or
more" *quantifier*, the same aggregate-vs-per-instance distinction
`EventType.PLAYER_ATTACKED` already exists to get right for "a player
attacks you with one or more creatures" rather than reusing the
per-declaration `ATTACKS` event. Built the combat-damage sibling the same
way: `EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER`
(`GameEngine._apply_combat_damage`), fired once per (contributing
creatures' controller, player hit) pair per damage step — not once per
qualifying creature, so two simultaneous 7-power hits trigger this exactly
once, not twice — carrying `max_power` for a new `contributor_power_at_least`
trigger-condition threshold (`effect_binder._trigger_condition`) to read,
since the aggregate event names no single acting object a `"group"`
condition's own per-object `min_power` filter could check. Full detail:
`docs/implementation-state/Done_Backend.md`'s "MEC-29" entry.

**ENG-30** (2026-08-12, same day) closed the gap MEC-28 had worked around
rather than deferring it further: RULE 601.2c's third target-count
shape — a genuine *range* ("one or two target creatures": at least one, at
most two), which `targeting.TargetSpec` had no field for (only an exact
`count` or an "up to `count`" 0..N `optional` reading existed). Built as
`TargetSpec.count_max` plus `effective_count` (the real resolve-time
slicing cap every `game/effects.py` consumer needed switched to, since
slicing by the RULE 601.2c *minimum* would have silently dropped a
legally-chosen second target); the interactive gathering split into the
two paths this engine already had for "how many" (`RulesEngine.
_continue_trigger_multi_target`'s round-by-round trigger-target choice,
`gameBoardView.js`'s `expandMultiTargetRequirements` for a spell/ability
cast) — both now expand to `count_max` rounds with the first `count`
mandatory and the rest declinable, reusing the existing "up to N" stop-early
idiom rather than inventing a new one. The shared parser quantifier every
multi-target family already read (`catalogue.handlers._MULTI_TARGET_
QUANTIFIER`) gained a third alternative for "N or M ", which for free
widened `tap`/`return_to_hand`/`return_from_graveyard`/`add_counters`/
`pump`'s existing multi-target rows; the two families that don't share that
quantifier (`divided_damage`'s own local grammar, the pump family's
dedicated "up to two" rows) got matching dedicated range rows, plus a new
`PumpEffect.previous_subject` mode (mirroring `TapEffect`/
`ReturnToHandEffect`'s existing "They…" pronoun idiom) for the "…1 or 2
target creatures…. They [each] get/gain `<X>`." two-clause shape. Found and
fixed a dormant bug on the way: the pre-existing "up to two target
creatures…" pump row (unrelated to this ticket's own range shape) had been
setting a spec key the `"pump"` `EffectRegistry` factory never read, so
every card on that template silently offered only one target. Raph & Leo,
Sibling Rivals (MEC-28's own hand-authored stopgap) now uses the real
range instead of its single-mandatory-target simplification. Cut the
`parser_probe.py blocked "[0-9] or [0-9] target"` SOLO list from 30 to 14 —
the remainder each block on a separate, unrelated gap (a nonstandard
counter kind, an "activate only if" cost restriction, a negated-keyword
filter, a mana-value filter on a graveyard search, an additional-cost
keyword, a multi-source fight shape, and others), individually diagnosed
rather than left bundled under one ticket. Full detail:
`docs/implementation-state/Done_Backend.md`'s "ENG-30" entry.

A **Kinnan/M-K completion batch** (2026-08-13) then finished two of
MEC-12's seven cEDH decks outright — `cEDH Kinnan` (100/100) and `cEDH
M-K` (97/97), 31 unique cards, all hand-authored (no parser handlers this
round). Each card needed a genuinely new primitive or a real combination
of existing ones: a destroy/exile-then-controller-digs-their-own-library
effect (Polymorph/Transmogrify) built on `dig_until`'s new "actually
reshuffle" rest destination; a forced (non-choice) retarget
(`ChangeTargetEffect`'s new `redirect_to_source`, Spellskite/Hydroelectric
Specimen); a still-on-the-stack bounce that pulls a spell out of
`GameState.stack` directly (Sink into Stupor, Hullbreaker Horror);
"hexproof"-shaped evasion checked against the *blocker's own*
characteristics for the first time (Void Winnower's even-mana-value
block restriction); a mana-production multiplier consulted straight from
`GameEngine.tap_for_mana` (Nyxbloom Ancient); a cost *floor* kept
structurally apart from the existing additive cost-reduction net
(Trinisphere); gaining control of a spell still on the stack, not a
permanent (Commandeer); a genuine "end the turn" (Day's Undoing,
`GameState.end_turn_requested` drained by `GameEngine.advance_step` since
an effect can't reach `_turn_steps`/`_cursor` directly); a standing,
never-turn-swept exile cast permission (Lukka's +1, `GameState.
exile_cast_condition`); the `EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_
PLAYER` aggregate event (MEC-29) widened with real subtypes, an actual
damage-dealt amount distinct from its existing power *threshold*, and a
commander-designation flag (Kediss/Malcolm); RULE 700.2's missing "choose
*up to* one" modal quantifier (Hullbreaker Horror); and an X-value
sentinel read off `GameObject.x_paid` for a triggered ability firing well
after its own casting resolution ended (Invasion of Ikoria) — which also
confirmed `SearchLibraryEffect`'s existing `zones=["library",
"graveyard"]` already fully supports "search library and/or graveyard"
end-to-end (always shuffles when library is among them, RULE 701.19e),
correcting this doc's own stale "needs a `request_search` extension"
claim below. Two documented simplifications (Into the Flood Maw's Gift
mechanic, Veil of Summer's qualified/player-level hexproof) were dropped
as real standalone engine work disproportionate to one card each, and two
`StaticAbility`-construction bugs (a missing `source=` silently no-opping
an `affects="self"` grant; `EnterAsCopyReplacement`'s `ability_kind` must
be `"enter_replacement"`, not `"static"`) were found and fixed along the
way. Full detail, every primitive and every bug:
`docs/implementation-state/Done_Backend.md`'s "MEC-12: Kinnan and M-K
completed" entry.

A first **MEC-30** pass (2026-08-17) then carded the standing `prevent_
damage` replacement (RULE 615/616.1) — registered since the original
replacement-effects batch but never bound to any card until now, distinct
from that batch's own one-shot `prevent_damage_shield` (Riot Control/
Thought Lash). Widened `to`/`recipient_filter`/`recipient_union`/
`source_filter`/`amount` (incl. `{"all_but"}`/`{"half"}`)/
`amount_count_selector` and a generic `rider` follow-up
(`RulesEngine.apply_prevent_rider`) close the Sphere cycle/Urza's Armor/
Shield of the Realm-shaped standing-shield family (RULE 613.6's `active_if`
now gates *any* replacement generically, not just this one); RULE 702.64
Absorb went from inert to real, bound structurally rather than parsed; and
a genuinely new one-shot primitive — `RequestPreventDamageSourceEffect`/
`PreventDamageFromTargetEffect`, `request_choose_objects`'s new
`"remember_source"` action, `prevent_damage_to_player`/`_to_target`'s new
`watched_source_id`/`rider` params, and the unscoped-recipient
`prevent_damage_from_source` — covers RULE 616.1d's "a source of your
choice" (Circle of Protection/Rune of Protection). 15 cards close purely
via a new parser regex family, 5 more are hand-authored. A **second pass**
the same day then hand-authored 32 more — the full Circle of Protection and
Rune of Protection cycles plus Story Circle/Prismatic Circle/Circle of
Solace's RULE 601.2b "as this enters, choose a color/creature type" shape
(three new `combat.matches_object_filter` keys — `color_any`/
`color_from_source`/`subtype_from_source` — read by `RequestPreventDamage
SourceEffect`'s candidate gathering) and New Way Forward's two-riders-off-
one-shield shape (`apply_prevent_rider`'s `rider` param now also accepts a
list). A **third pass** the same day closed the rest of Family A (7
cards) — Rem Karolus/Hedron-Field Purists/Battletide Alchemist
mechanically; Nine Lives via one new symmetric trigger-condition key
(`source_counters_at_least`) rather than the genuinely-new RULE 603.8
state-trigger subsystem the ticket had assumed; Insult // Injury/Isengard
Unleashed via the pass's one real new mechanism (`GameState.damage_
prevention_disabled` + a `ReplacementEffect.prevents_damage` marker
gating `RulesEngine._run_replacement_loop`, plus `grant_damage_
multiplier_this_turn`, the spell-cast sibling of the standing
`double_damage` replacement); Ajani Steadfast's all-three-loyalty-
abilities (not just its emblem, per a Haazda Shield Mate-shaped
`specs_for` gotcha). **Phases 5-6** the same day closed 6 more Family B
cards via several small, individually-scoped chooser extensions (a
recipient scoped to "you and/or creatures you control", a rider gated by
the watched source's own colour, a life-gain reading a shared target's
power) plus Opal-Eye, Konda's Yojimbo's own RULE 616.1c *redirection* — the
first in this engine, which surfaced and fixed a real, previously-
unreachable bug in `RulesEngine.deal_damage` itself: its `_finish` closure
had always resolved every branch against the damage event's *original*
recipient, never re-reading a replacement's own rewritten `target_id`, so
no card could ever actually redirect damage before now. A **fourth pass**
the same day then fixed the standing RULE 616.1e ambiguity papercut two
prior passes had each mentioned and left alone (per this file's own
"deferred a second time must be fixed or promoted" rule): none of the 12
`ReplacementRegistry` factories in `game/effects.py` ever passed a
`condition` to their `ReplacementEffect`, so `can_replace` only ever
checked the event *type* — every real applicability gate (recipient,
source, "while it has a counter", …) lived as an early no-op guard buried
inside `replacement_fn` itself, which is why Gisela's two unrelated
replacements always both reported "applicable" and opened a pointless
ordering choice on every hit. Fixed by extracting each factory's existing
guard into a named `_applies` closure wired in as `effect.condition`. A
**fifth pass** closed Penance/Seasoned Tactician/Bone Mask's three
cost-shape gaps — a new "put a card from your hand on top of your
library" non-mana cost (`ActivationCost.put_hand_card_on_library`,
`ActivationMixin._resolve_put_hand_card_cost` mirroring `_resolve_
discard_cost`'s "chosen_ids, or auto-pick" shape); `costs.
exile_top_of_library` widened from a bare bool to a real printed count
(every existing caller checked so Thought Lash doesn't regress); a new
`apply_prevent_rider` kind, `"exile_top_of_library_scaled"` (`mill`'s
exile-instead-of-graveyard sibling); and `RequestPreventDamageSourceEffect`'s
new `recipient="any"` for Penance's own unqualified "prevent that
damage" (no "to you" at all, unlike every other card in this family),
reaching the already-shipped unscoped `prevent_damage_from_source` shield.
A **sixth pass** then closed the two cards flagged from the start as the
family's genuinely bigger builds. Mercenaries ("Any player may activate
this ability") surfaced a real gap: RULE 602.2b makes whoever *activates*
an ability that ability's controller for its resolution, but nothing
distinguished that from a permanent's own printed controller anywhere in
the effect-application path — `ActivationCost.any_player_may_activate`
widens `can_activate`'s ordinary controller-only eligibility gate, and
`GameContext.resolving_controller_id` (the activator, set/restored by
`resolve_top_of_stack` exactly like `trigger_event`, read by
`PreventDamageEffect`'s new opt-in `recipient_is_activator`/`watched_
source_is_self`) is what makes the shield actually protect whoever paid
for it. Rhystic Circle ("Any player may pay {1}. If no one does, …") is a
genuine multi-player, aggregate-outcome tax — every player independently
gets a chance to pay in turn order, the first to pay cancels the whole
thing, and the payoff only fires once, if literally everyone declined —
`RequestAllPlayersDeclineOrEffect`/`RulesEngine.request_all_players_
decline_or`, the aggregate-outcome mirror of PAR-13's existing `request_
each_player_pay_or` (which applies its own effect *per decliner* rather
than once in aggregate, so the two can't share one advance loop despite
both being chains of ordinary single-player pay/decline choices). A
**seventh pass** then closed the family's last card, Desperate Gambit
("Choose a source you control and flip a coin. If you win, `<effect>`. If
you lose, `<effect>`.") — a genuinely conditional effect *selection*
scoped to one already-chosen source, not a rider: `ChooseSourceCoinFlip
Effect` opens the chosen-source chooser family's third member (candidates
narrowed to "a source **you control**", not "of your choice"), and the
coin (`RulesEngine.coin_flip`, RULE 705.1) isn't flipped until the pick
resolves — heads calls the one genuinely new primitive, `RulesEngine.
grant_damage_multiplier_from_source` (the single-source-scoped doubling
mirror of `prevent_damage_from_source`, *not* a mode of the controller-
wide `grant_damage_multiplier_this_turn`), tails calls the already-shipped
`prevent_damage_from_source` directly — its own docstring had anticipated
exactly this reuse since the first pass. **MEC-30 is closed**: every card
the original 80-row cache search surfaced is now `MODELED` or hand-
authored, and every primitive built along the way (RULE 613.6 `active_if`
on any replacement, RULE 616.1c redirection, RULE 616.1e's real
`can_replace` condition, the RULE 602.2b activator/controller distinction,
the multi-player aggregate-outcome tax) is general enough for a future,
unrelated card to reuse without rebuilding it. Full detail, all seven
passes: `Done_Backend.md`'s "MEC-30" entry.

**Notable gaps** (see `docs/implementation-state/BACKLOG.md` for the full list with exact
scope on each): a kicked spell's "if kicked, ... instead" *override* conditional (as opposed to the
additional-effect shape already shipped); Doomsday's own "exile up to five
cards in a pile" (a distinct, still-unbuilt mechanic — not the same gap
as a plain "search your library and/or graveyard for a card" clause,
which `SearchLibraryEffect`'s existing `zones` param already handles end
to end, confirmed by the Kinnan/M-K batch above); the *oracle coverage* of
the battle pool (the RULE 310 engine is done, but only 12 of the 39
cached battles are MODELED — the other 27 are blocked on ordinary
effect-body grammar, enumerated in
`docs/implementation-state/PARSER_LONG_TAIL.md` as that document's worked
example; the biggest cluster needs only a **parser handler**, since its
engine primitive `request_pay_cost_then` already exists); and the
narrower already-shipped-feature rough edges (e.g. re-validating an
*existing* attachment's legality every SBA pass, not just on the host
leaving; combining interactive trigger-ordering with a targeted trigger;
bespoke *conditional* transform triggers like Delver of Secrets;
non-creature group scopes for the anthem/grant families, which keeps
"Other enchantments have '…'"-shaped cards closed even though the layer
engine's selectors are ready; the "Combat statics" ToDo entry is now fully
closed — combat *requirements*, multi-block permissions, a count-selector
threshold filter, and a qualified group scope have all shipped) — all
now tracked in that same file rather than split across siblings.

Hand-authoring a card's abilities directly (rather than waiting on the
oracle-effect front-end, or for a replacement-clause/conditional-trigger the
front-end can't express yet) goes in `game/ability_catalogue.py` — see
[docs/Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md](docs/Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md)
for the field-by-field how-to and the full `EffectSpec`/layer whitelist.

Implementation state is three kinds of document, kept strictly apart —
**open points**, **worklogs**, **examples** — all under
`docs/implementation-state/`:

| Kind | File | Rule |
| --- | --- | --- |
| Open points | `BACKLOG.md` | The *single* backlog, backend **and** frontend, as categorized tickets (`ENG` game engine, `PAR` parser, `MEC` game mechanics, `PLR` player management, `VIS` visuals, `DB` database, `ANA` deck analysis — the former `TYP` card-types category is retired, RULE 300–315 being complete). Open scope only — no history. |
| Worklogs | `Done_Backend.md`, `Done_Frontend.md` | Catalogues, organized by game-mechanic/app-area (not chronologically) — what shipped and *why it was built that way*, one entry per feature/primitive under a subsystem heading. Entry headings are the stable, searchable unit now (not the whole file being append-only); closing a ticket means filing its narrative under the matching subsystem entry, merging into it if one already covers the same primitive, rather than appending at the end. |
| Examples | `PARSER_LONG_TAIL.md` | Standing strategy + recurring lessons + enumerated worked samples for the indefinite parser tail. Neither backlog nor worklog. |

(The former `backend/ToDo_Backend.md` and `frontend/ToDo_Frontend.md` are
gone — merged into `BACKLOG.md`.) The plan to finish is
`docs/implementation-state/10_COMPLETION_ROADMAP.md`
(dependency-ordered milestones, reconciling the backlog files above into a
coverage table). `docs/` is organized by *kind of question*: `requirements/`
(what should it do), `concepts/` (how is it designed — architecture, effect
system, oracle parser, plus [PlantUML architecture diagrams](docs/concepts/12_ARCHITECTURE_DIAGRAMS.md)),
`Reference/` (how do I do X, or look something up — card-cache format,
card-catalogue authoring, plus the Comprehensive Rules text + `rules_wiki/`),
`implementation-state/` (what's built now — the roadmap above, both `Done_*`
files, and the original phased `IMPLEMENTATION_GUIDE.md`). See
[docs/README.md](docs/README.md) for the full map. End-user documentation
(how to *use* the app — deck import, Goldfisch, Replay/Puzzle, settings —
not how it's built) lives separately in [`user-docs/`](user-docs/), in
English and German.

## Conventions & gotchas

- **RULE references**: comment rules-relevant code with the CR number
  (`RULE 613.7`). Match the surrounding comment density and style. To read the
  actual rule text, use the wiki in `docs/Reference/rules_wiki/` — it maps every rule
  number and glossary term to its line in the CR source (too large to load whole);
  regenerate with `build_wiki.py` after a rules update.
- **Model → game import boundary**: `models/` must not import `game/` at module
  load. Where a model needs engine logic (e.g. `GameObject.to_dict` showing
  keywords), use a **function-scoped import** and keep the `game/` side pure of
  runtime model imports (`combat.py`, `continuous.py` only import models under
  `TYPE_CHECKING`).
- **`turn_number` vs `round_number`**: `GameState.turn_number` is the
  rules-correct count (RULE 500.1 — *every* player's turn is a turn, so a
  two-player game is on turn 7 when the starting player takes their
  fourth), and it is what the engine reads everywhere. `round_number` is
  display-only: how often the turn has come back to whoever started, which
  is what a player means by "we're on turn 4". The board shows the round
  and puts the turn in a tooltip. Don't "fix" either one into the other.
- **Derived characteristics**: `GameObject.power/toughness/is_creature/
  granted_keywords` read layer-engine output stamped by `continuous.recompute`,
  falling back to printed+counters when no pass has run. Recompute runs on every
  SBA pass and before the session view — call `engine.recompute_continuous_effects()`
  if you read derived state outside those points.
- **Security**: nothing derived from card text becomes code. Effects are a
  whitelisted `type` string + clamped params (`spec.py`); the binder is the only
  thing that turns specs into behaviour.
- **No magic numbers**: a numeric literal whose meaning isn't obvious from
  its immediate context (a threshold, weight, cap, timeout, percentage,
  scoring constant, …) must be a named module- or class-level constant with
  a short comment stating what it represents — and, when the value is a
  judgment call rather than a rule-derived fact, *why* that value — not
  inlined at the call site. `services/dynamic_analysis.py`'s
  `INFINITE_MANA_THRESHOLD` is the pattern: named, with a comment
  explaining the reasoning behind the exact number. Applies project-wide,
  backend and frontend.
- **Configuration**: on-disk paths and a few runtime constants (cache/data
  dirs, Scryfall User-Agent/rate limit) live in `mtg_analyzer/config.py`,
  overridable via `MTG_CACHE_DIR`/`MTG_DATA_DIR`/`MTG_USER_AGENT`/
  `MTG_SCRYFALL_MIN_REQUEST_INTERVAL` env vars — point a one-off script or
  test run elsewhere without colliding with a real dev server's cache/saved
  decks. Service modules (`card_database.py`, `deck_database.py`, etc.) keep
  their old constant names (`CACHE_ROOT`, `DEFAULT_DB_PATH`, …) as aliases
  onto `config.py`'s values; `api/dependencies.py`'s singletons import
  straight from `config.py`. `LazyCardLoader`'s loading *policy* is also
  here: `SCRYFALL_PRIMARY` (`MTG_SCRYFALL_PRIMARY` env var, or
  `./start.sh --scryfall-primary`) — default `False`, **cache-primary**:
  an already-cached card is served as-is even if it looks `stale`
  (missing mana-cost/image data, a pre-fix `Card.partner_with`
  reminder-text tail — see `services/lazy_card_loader.py`'s `_is_fresh`),
  never silently refetched, so an ordinary deck load can't make a
  surprise Scryfall call (or hit its rate limit) just from browsing
  already-known cards. `True` restores this project's original
  **scryfall-primary** behavior of always refetching a stale row. A name
  that's never been cached at all is *always* fetched once either way —
  that part isn't a policy choice.
- **Frontend**: no framework. Views are `render*(container)` functions setting
  `innerHTML` and wiring listeners; escape user/card text with `escapeHtml` /
  `escapeAttr`. Client-only prefs persist via cookies (`cookies.js`).
- **Commits**: only when asked; branch first if on `main`. End commit messages
  with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- **Backlog/worklog split discipline**: `BACKLOG.md` is read in full often
  (by humans and Claude) and, unlike `Done_*.md`, isn't a durable catalogue
  — it holds *only* open work. **Closing a ticket = deleting it from
  `BACKLOG.md`** and filing its narrative into `Done_Backend.md` /
  `Done_Frontend.md`, organized by game-mechanic/app-area rather than by
  date (see each file's own preamble): find the entry for the primitive/
  feature the ticket touched and extend it, or add a new entry under the
  matching subsystem section (e.g. `## Replacement Effects`, `##
  Multiplayer`) if none exists yet — don't just append at the end of the
  file, and don't create a second entry for a primitive that already has
  one. A ticket that closed several cards by combining existing primitives
  (a saved-deck/cube playability push) gets one short entry under `##
  Deck/Cube Playability Batches` instead, naming what closed and pointing
  at the primitive entries it used. Never leave a `[x]`, a "shipped" note,
  or even a "moved to Done_*.md" pointer in `BACKLOG.md`; if only part of a
  ticket is done, keep only the part that isn't. Finished detail left in the
  backlog defeats the split and taxes every future read.
- **No half-implementations — close the loop, don't let a deferred item
  silently roll over.** Every batch/session prioritizes by real
  cards-unlocked (correct — see
  `docs/implementation-state/PARSER_LONG_TAIL.md`), but that has a failure
  mode: a modest-yield item never wins
  the "next batch" slot against bigger ones, so it gets deferred a second
  and third time while the ticket describing it goes stale — worse, a
  *later* batch can build the exact primitive an earlier deferred item was
  "blocked on," for an unrelated card, and never loop back to close the
  original entry. Concrete example this bit us on 2026-07-20: Batch 4
  deferred "draw a card at the beginning of the next turn's upkeep" as
  needing "a delayed-trigger phrasing distinct from a standing phase
  trigger"; Batch 22 (2026-07-18) then built exactly that primitive
  (`CreateDelayedTriggerEffect`/`GameState.delayed_triggers`, RULE 603.7)
  for a *different* card (Mana Drain) — and the original ToDo entry was
  never revisited, so it still read as engine-blocked when the real
  remaining gap had shrunk to "write the parser handler." Similarly,
  "grant an activated ability" (Umbral Mantle/Squirrel Nest) was deferred
  as needing a new primitive in Batch 3, confirmed again in Batch 7, and
  is *still* neither built nor hand-authored as the stopgap this repo's
  own escape valve explicitly sanctions (`game/ability_catalogue.py` — see
  [docs/Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md](docs/Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md)),
  three rounds of deferral in. To prevent this: (1) before writing "needs a
  new primitive/mechanism" in a `BACKLOG.md` ticket, grep `game/effects.py`/
  `game/rules_engine.py`/`Done_Backend.md` for whether an equivalently-shaped
  primitive already exists from a *different* card's batch — cite it or
  rule it out explicitly, don't assume; (2) whenever a batch **does** build
  a new primitive, grep `BACKLOG.md` for any other ticket the same
  primitive would also close or narrow, and update them in the same pass —
  a primitive landing is exactly the moment to sweep for this, not an
  afterthought; (3) an item deferred a **second** time must either get
  hand-authored as a stopgap in that same batch (the sanctioned escape
  valve — a named blocker cited across 2+ batches is reason enough on its
  own) or be explicitly flagged as promoted to next-up — it must not be
  allowed to silently roll to a third deferral with unchanged wording.

## Where to look first

| Task | Start in |
| --- | --- |
| Combat / keywords | `game/combat.py`, `game/game_engine.py` (`_step_combat_damage`) |
| Static abilities / P/T / anthems | `game/continuous.py`, `models/game_object.py` |
| "As long as …" conditions on a static (RULE 613.6) | `game/static_conditions.py` (the whitelist + evaluator), a static's `active_if` param, `parser/oracle/catalogue/static_handlers.py` (`_STATIC_CONDITION_RES`, `_conditional_static_specs`) |
| "Until …" durations on a continuous effect (RULE 611) | `game/durations.py`, `GameState.floating_statics`, `effects.GrantUntilEffect` — note "until end of turn" stays on the `temp_*` path |
| How many targets a spell/ability wants (RULE 115.1/601.2c) | `game/targeting.py` (`TargetSpec.count`/`count_max`/`count_selector`, `effective_count`, `resolved_count`, `expand_counts`/`collapse_groups`) |
| A clause naming what a previous clause targeted or created | `effects.GameContext.previous_targets` / `created_objects` (both maintained by `_apply_effects_partitioned`) |
| Activated abilities / costs | `game/costs.py`, `game/game_engine.py` (`activate_ability`) |
| Card abilities / fetch lands / enters-tapped | `game/ability_catalogue.py`, `effect_binder.bind_from_catalogue` |
| Hand-authoring a specific card's effects | `hand-author-card` skill, [docs/Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md](docs/Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md) |
| Effects / triggers | `game/effects.py`, `game/effect_binder.py` |
| Which trigger conditions the parser recognizes | `parser/oracle/segmenter.py` (`_TRIGGER_VERBS` object subjects, `_PHASE_STEP_WORDS`, `_PLAYER_TRIGGER_CONDITIONS` "whenever **you** scry/surveil", `_VARIANT_TRIGGER_CONDITIONS`) |
| Face-down permanents (morph/disguise/manifest/cloak) | `game/face_down.py`, `models/game_object.py` (`turn_face_down`/`turn_face_up`), `game/game_engine.py` (`turn_face_up`, `face="face_down"`) |
| Dungeons + venturing | `models/dungeon.py`, `game/dungeons.py`, `services/dungeon_database.py`, `rules_engine.venture_into_the_dungeon` |
| Formats & casual variants (Planechase/Archenemy/Vanguard) | `models/game_format.py`, `game/variants.py`, `services/variant_card_database.py`, `game_engine.new_game(game_format=…)` |
| "Play/cast from top of library" permission | `game/top_library.py`, `game/game_engine.py` (`can_play_land`/`can_cast`/`legal_actions`), `gameBoardView.js` (`libraryTopHtml`) |
| On-disk paths / env-var config | `backend/mtg_analyzer/config.py` |
| Goldfish UI | `frontend/src/js/goldfishView.js` |
| Multiplayer (lobby, seats, shared board) | `backend/mtg_analyzer/services/lobby.py`, `api/multiplayer.py`, `api/multiplayer_ws.py`, `frontend/src/js/multiplayerView.js`, `lobbySocket.js`, `bannerColors.js` (seat banner colours) |
| Bots filling a multiplayer seat (UC5) | `backend/mtg_analyzer/services/bots.py` (`Bot`/`GoldfishBot`/`GreedyBot`/`run_bots`), `services/lobby.py` (`Seat.bot_kind`, `add_bot`), `frontend/src/js/multiplayerView.js` (`addBotHtml`/`seatRowHtml`) |
| Replay/Puzzle mode (build+save/load a board) | `backend/mtg_analyzer/services/replay.py`, `game_session.py` (`edit_*` actions), `frontend/src/js/replayView.js` |
| Archidekt deck import proxy | `backend/mtg_analyzer/services/archidekt_client.py`, `api/import_external.py` (Moxfield was tried and reverted twice — Cloudflare-blocked; don't re-add it without checking that's changed) |
| Refreshing the full Oracle card pool (new set) | `backend/scripts/update_card_pool.py` — re-downloads the Scryfall `oracle_cards` bulk dump, merges it into `RawCardStore`, reseeds the app cache, and prints a ban-list drift heads-up (`scripts/import_bulk.py` is first-load only; its default reuses an on-disk dump) |
| Applying a ban-list update | `backend/scripts/update_ban_lists.py` — rewrites a hand-maintained ban-list constant (`BAN_LIST_TARGETS`, just `services/commander_legality.py`'s `BANNED_COMMANDER_CARDS` today) straight from the raw store's live `legalities` data; no network of its own, run `update_card_pool.py` first. `--format <key>`/`--dry-run` |
| Player-uploaded token art / card-back sleeves | `backend/mtg_analyzer/services/player_assets.py`, `api/player_assets.py`, `frontend/src/js/connectionSettingsView.js`, `frontend/src/js/profileView.js` (player name), `gameBoardView.js` (`resolveImageUrl`/`setAssets`) |
| Engine coverage doc (user-facing) | `frontend/src/js/implementationStatusView.js` |
| What's still open (any area) | [docs/implementation-state/BACKLOG.md](docs/implementation-state/BACKLOG.md) — tickets by category |
| Why shipped work looks the way it does | [Done_Backend.md](docs/implementation-state/Done_Backend.md) / [Done_Frontend.md](docs/implementation-state/Done_Frontend.md) |
| Parser-tail strategy, lessons, worked samples | [docs/implementation-state/PARSER_LONG_TAIL.md](docs/implementation-state/PARSER_LONG_TAIL.md) |
| Looking up a `RULE <n>` in the CR text | `docs/Reference/rules_wiki/` (rule#/term → source line; see its `README.md`) |
| Full docs/ map (requirements/concepts/Reference/implementation-state) | [docs/README.md](docs/README.md) |
| How to *use* the app (not build it) | [user-docs/](user-docs/) (English + German) |
