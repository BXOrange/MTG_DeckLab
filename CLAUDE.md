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
cd backend && python -m pytest -q                    # with the venv already active
# or, from any shell/interpreter, no active venv needed:
python backend/scripts/run_tests.py [pytest args...]  # resolves venv/venv_win itself
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

This is orientation only. The mechanic-by-mechanic detail — what shipped,
*why* it was built that way, which tests cover it — lives in
[docs/implementation-state/Done_Backend.md](docs/implementation-state/Done_Backend.md),
organized by subsystem (Rules Engine, Game Engine, Card-type coverage, …).
Open gaps and exactly what's left on a partial feature live in
`docs/implementation-state/BACKLOG.md` (tickets by category). The user-facing
version is the frontend **Engine-Status tab**
(`frontend/src/js/implementationStatusView.js`) — keep it in sync when engine
coverage changes. Search those for a mechanic's name rather than re-deriving
its state from the code or duplicating detail here.

**The rules engine is broadly complete.** Implemented, in brief:

- **Turn structure** — full turn/phase/step loop, the stack, RULE 117
  priority (opt-in per session, played out for real in multiplayer), the
  RULE 704 state-based-action pass, all agreed-on mulligan procedures.
- **Mana** — the whole model (generic/colour/colourless/hybrid/mono-hybrid/
  Phyrexian/{X}), RULE 605.3a spend restrictions, "any combination of
  colours", hand-zone mana abilities, triggered mana abilities.
- **Combat** — every common keyword incl. landwalk; the full RULE 508/509
  restriction / requirement / multi-block family (plain flags and qualified
  forms, board-count thresholds, group-scoped qualifiers); goad.
- **Continuous effects** — the RULE 613 layer system (layers 1–7, dependency
  pass, `EffectRegistry`-bridged for every parsed/hand-authored static
  shape); RULE 613.6 conditional statics and RULE 611 durations as two
  general systems (`game/static_conditions.py`, `game/durations.py`);
  attachment (Aura/Equipment/Fortify/Reconfigure).
- **Abilities** — activated (incl. loyalty `[±N]`/`[-X]`), triggered, RULE
  616 replacement effects; interactive ordering and interactive
  target / "you may" choices; RULE 603.7 delayed triggers; RULE 608.2
  suspended resolutions.
- **One-shot effect library** — damage, draw, discard, destroy, counter,
  search/tutor, mill, exile, tap, counters, pump, scry/surveil, token
  creation, copy, cascade/discover, proliferate, fight, board wipes, and
  most one-shot families the parser emits.
- **Keyword actions** — every RULE 701 keyword action has an engine
  primitive (PAR-29, closed).
- **Designations & subsystems** — planeswalkers, commander damage + tax,
  Monarch, Initiative, The Ring, emblems, Speed, the Case solve machine,
  energy, poison/infect/wither/toxic.
- **Card-type structures** — DFC transform + day/night/daybound; modal-DFC/
  Adventure/Split-Fuse/Prepared casting; Sagas, Class/Leveler/Station
  level-ups; battles (RULE 310); face-down permanents (morph/manifest/
  disguise/cloak); dungeons + venturing (RULE 309); the RULE 9 casual
  variants (Planechase/Archenemy/Vanguard).

**The oracle-text parser is the main ongoing effort.** Pipeline:
`normalize` → `segmenter` → `catalogue/handlers` → `gate.parse_oracle`,
returning `AbilitySpec`s plus a fail-closed `MODELED`/`UNMODELED` verdict (a
card gets parsed effects only when *every* clause is claimed — never
half-resolved). It covers most one-shot effect families, ETB/dies/attacks/
blocks/Saga-chapter triggers with RULE 603.1 subject scoping, `<cost>:
<effect>` activated abilities, modal spells, additional cast costs, the
counter family, enters-tapped / enters-with-counters clauses, static
anthem/lord clauses, graveyard recursion, and much of the RULE 701 keyword
trail. The RULE 702 keyword catalogue (~195 rows,
`parser/oracle/catalogue/keywords.py`) is parser *recognition* only — not
proof of engine behaviour; don't cite a keyword as implemented from the
catalogue's mere existence.

**Coverage: 38.9% (13,555 / 34,811) as of 2026-09-02, PARSER_VERSION 215**
(parser-`MODELED` or hand-`AUTHORED`, measured against the full ~35k-card
Oracle universe from `scripts/import_bulk.py`). Re-measure with
`scripts/coverage_report.py` (ledger-backed, `services/coverage_db.py`)
before trusting this number. The **Commander-legal** slice — the subset
that matters for Goldfisch/Deck-Analyzer — is ~40.8% (12,973 / 31,830);
measure it with `scripts/coverage_report.py --commander-legal-only`
(records a separate `…-commander` snapshot row) and segment the
still-UNMODELED remainder by *cause* (wrapper re-measure / recurring
template → `PAR-*` / set-specific → `PAR-*` / missing primitive → `MEC-*` /
bespoke hand-authoring tail) with the read-only
`scripts/commander_tail_report.py`. The per-version changelog and the long-tail
strategy (recurring lessons, worked samples) are in
`docs/implementation-state/PARSER_LONG_TAIL.md`; open parser tickets are
`PAR-*` in `BACKLOG.md`. **Stickers (RULE 123) are a permanent project
non-goal** — the gate classifies any "sticker" card as `NEVER_SUPPORTED`, a
verdict distinct from `UNMODELED` and kept out of both the covered count and
the backlog ranking.

**Notable open gaps** are tracked with exact scope in `BACKLOG.md`: a kicked
spell's "if kicked, … instead" *override* conditional (the additional-effect
shape is shipped); Doomsday's "exile up to five cards in a pile"; the oracle
coverage of the battle pool (the RULE 310 engine is done, ~12 of 39 cached
battles MODELED); and assorted rough edges on already-shipped features.
**PAR-30** — PAR-29's residual per-card effect-body grammar — is the current
parser push.

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
- **Configuration**: on-disk paths and runtime constants (cache/data
  dirs, Scryfall User-Agent/rate limit, multiplayer timers, worker/pool
  sizes) live in `mtg_analyzer/config.py`. Each value resolves with a
  fixed precedence: **`MTG_*` env var > `mtg_analyzer/config.json` >
  built-in default**. The JSON file is committed with every knob written
  out at its default plus a per-section `_comment` (keys starting with
  `_` are ignored); a missing/malformed file is ignored and the server
  still starts. Point elsewhere with `MTG_CONFIG_FILE`. The env vars
  (`MTG_CACHE_DIR`/`MTG_DATA_DIR`/`MTG_USER_AGENT`/
  `MTG_SCRYFALL_MIN_REQUEST_INTERVAL`/…) still work and still win, so a
  one-off script or test run points elsewhere without colliding with a
  real dev server. Service modules (`card_database.py`, `deck_database.py`,
  etc.) keep their old constant names (`CACHE_ROOT`, `DEFAULT_DB_PATH`, …)
  as aliases onto `config.py`'s values; `api/dependencies.py`'s singletons
  import straight from `config.py`.
- **Concurrency / workers**: the backend runs as **one** uvicorn process
  on purpose (`setup/start.py` — the game-session manager, multiplayer
  lobby and dynamic-analysis job registry are in-memory process-wide
  singletons, so `uvicorn --workers N` would split them). Concurrency
  within that process has three configurable knobs (env var / `config.json`
  `[workers]` / `start.sh` flag): `SERVER_THREAD_WORKERS`
  (`--server-threads`, default 40) sizes the AnyIO request-thread pool
  applied in `api/app.py`'s lifespan — every gameplay endpoint is a sync
  `def`, so this is the ceiling on games mid-step at once;
  `DYNAMIC_ANALYSIS_WORKERS` (`--analysis-jobs`, default 4) is an
  admission cap on concurrent analysis *jobs* (`_JobWorkerPool`); and
  `DYNAMIC_ANALYSIS_MATCH_WORKERS` (`--analysis-match-workers`, default 0
  = one per CPU core, 1 = off) is the real speed-up — `run_dynamic_analysis`
  fans one job's independent match simulations across a
  `ProcessPoolExecutor` (GIL-bypassing), falling back to in-process for a
  small job (`_MIN_MATCHES_FOR_PROCESS_POOL`) or if the pool can't start.
- **Logging**: nothing configured logging before, so `mtg_analyzer.*`
  records fell through to `logging.lastResort` (WARNING+ only). `config.
  LOG_LEVEL` (`MTG_LOG_LEVEL` / `config.json` `logging.level` /
  `./start.sh --log <level>`) now sets the `mtg_analyzer` parent logger's
  level, applied in `create_app()` via `_configure_logging()`. Default
  **WARNING** (the engine/parser are chatty at INFO); the root level
  stays WARNING so raising the app to DEBUG doesn't unmute third-party
  libraries. `start.sh --log` passes the same level to uvicorn as
  `--log-level` (whose own default this project overrides to `warning`).
- **Scryfall loading policy** lives in `config.py` too:
  `SCRYFALL_PRIMARY` (`MTG_SCRYFALL_PRIMARY` env var, or
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
- **`Card.flavor_name` only resolves if the *cached* printing happens to
  carry it.** `CardDatabase.get_card` matches a lookup name against both
  `name` and `flavor_name` (e.g. "Godzilla, King of the Monsters" →
  Zilortha), so a Universes Beyond alternate-name printing *can* resolve —
  but `scripts/import_bulk.py` seeds the cache from Scryfall's
  `oracle_cards` bulk dataset, which picks exactly **one** representative
  printing per oracle id (not necessarily the alt-name one), so
  `flavor_name` is blank unless that specific printing was chosen. Confirmed
  via `inspect-db`: "Balin's Tomb" (the LOTR alternate name for Ancient
  Tomb) does **not** resolve today — Ancient Tomb is cached, but its row's
  `flavor_name` is empty — even though the lookup mechanism itself is real
  and already works for other cards. Don't conclude "not a real Scryfall
  card" from a failed lookup without checking this; it may instead be an
  alt name whose specific printing lost the oracle_cards representative-row
  selection.
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
