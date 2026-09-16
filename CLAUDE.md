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
  deck import/analysis, saved decks, the goldfish board, **"Solo gegen
  Bots"** (the Multiplayer engine — real turns, priority, hidden hands —
  against 1–3 bots, with no lobby/socket; `soloView.js` + `api/solo.py`),
  the **"Replay"** board editor (a.k.a. puzzle mode), the card cache,
  Multiplayer (**Setup** = lobby + game configuration, **Board** = the
  shared game, disabled until you're at a table), and
  an **"Engine-Status"** tab documenting engine coverage, plus two header icon
  buttons: **"Einstellungen"** (`connectionSettingsView.js` — *only* the
  backend server address + connection test now) and **"Profil"**
  (`profileView.js` — everything player-facing: player name, multiplayer
  default settings, auto-pass / board-comfort toggles, player-uploaded token
  art + card-back sleeves, favorite decks). Anything about *who you are* /
  *how you play* is Profil; anything about *reaching the server* is
  Einstellungen. UI language is **German**; MTG keyword names stay
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
primary button becomes "Passen" (on the priority holder's own board
banner — the left rail carries only table/layout controls). Only the
priority holder may act, enforced
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
run from the app's lifespan. Client-side, a **per-priority countdown** runs
whenever this client holds priority **on another player's turn** — the
response window a phase hands round once the active player passes
(`gameBoardView.js`'s `autoPassArmed`/`railTimerHtml` gate on
`reactTimerSuppressedHere()`). On your **own** turn it's suppressed during
your main phases and combat (you're the one acting there, RULE 117; a
half-finished turn mustn't tick away under you), but still runs whenever
there's something on the stack to respond to, or during the passive
upkeep/draw/end steps — an absent active player otherwise is the
`MTG_MULTIPLAYER_IDLE_TIMEOUT`'s job. When it does run it auto-passes at
zero (a shrinking progress bar in the board's left rail —
`gameBoardView.js`'s repurposed `autoPassArmed`/`syncAutoPass`); any
interaction with the board, or the rail's "interrupt" button, cancels it
for that window. It is always on (no opt-in checkbox any more) and its
length is a **server** setting, not a cookie:
`config.MULTIPLAYER_SPELL_TIMER_SECONDS` (`MTG_MULTIPLAYER_SPELL_TIMER`,
default 20s, 0 = off), per-table overridable by the host in Setup
(`LobbyGame.spell_timer_seconds`, carried to the board on
`view()["priority"]["timer_seconds"]`). A manual **"End the turn"** button
next to "Passen" is the deliberate opposite of that suppression: click it
and every priority window this client holds — main phases and combat
included — auto-passes for the rest of the current turn regardless of what
`legal_actions` offers (`endTurnActiveHere`), a speed-up for a player who's
decided they have nothing left they want to do this turn. It self-disarms
once that turn ends or on any real board interaction, and never touches a
`pending_choice` or a turn-based action (declare attackers/blockers) —
neither goes through `pass_priority`.

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

**Player-uploaded art** (**Profil** tab): a player can upload art for
tokens that have no real Scryfall art (matched by token name) and a
library of card-back "sleeve" designs, one of which can be picked per
saved deck (`Deck.sleeve_id`). Stored server-side keyed by the free-text
player name (this app has no auth) — set on the same **Profil** tab
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

The **Profil** tab also carries two more per-player preferences
alongside the player name and asset uploads: **favorite decks** — a starred subset of the
saved-decks list (`services/player_assets.py`'s third table,
`favorite_decks`, same `player_name`-keyed storage as sleeves/token
art — decks aren't owned in this single shared `DeckDatabase`, so the
star can't live on `Deck` itself) that `goldfishView.js`'s and
`multiplayerView.js`'s deck pickers list first; and **multiplayer
default settings** (format, mulligan style, takebacks, RULE 103.1/103.2
randomization) — purely client-side cookies (`settings.js`, same
convention as the auto-pass toggles on the same tab), applied once by
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
step** or required Node runtime — edit `frontend/src/**` and reload. Optional
frontend linting is available through the project-local environment created by
`setup_dev.sh`; there is no JS test runner. Validate backend changes with
pytest (the suite is fast, ~500+ tests, keep it green).

For non-trivial frontend changes, use the real-browser verification available
through Playwright in `backend/venv`, driving Chromium against the static
frontend server and running backend, rather than relying only on API replay.

**A browser only ever needs to reach the backend's port.** `setup/start.py`
still runs two processes (backend `uvicorn`, frontend `no_cache_server.py`),
but the backend reverse-proxies anything outside `/api`/`/ws` straight
through to the frontend process (`api/frontend_proxy.py`,
`config.FRONTEND_ORIGIN`, default `http://127.0.0.1:8765`) — a
server-to-server call, not subject to CORS. `run_servers()` opens the
browser at the backend port, not the frontend one; the frontend process
stays loopback-only and isn't meant to be opened directly. This is why
`_LOCAL_DEV_ORIGIN_REGEX` in `api/app.py` only ever had to admit
`localhost`/`127.0.0.1` origins — the two-origin problem it exists for is
now the exception (`--frontend-only`), not the default path.

**Reachable from other computers on the network is opt-in, via
`start.py --host HOST`** (passed straight through as uvicorn's own
`--host`; omitted by default, so uvicorn's loopback-only default applies
unchanged). This app has **no authentication** — anyone who can reach the
host/port can read and write saved decks, player uploads, and play in any
game, so this must never become the default. Only the backend needs to
bind beyond loopback; `no_cache_server.py` stays loopback-only always (the
backend proxies it internally, same-machine only). On macOS, binding
beyond loopback triggers the OS's "Local Network" privacy permission,
which is unreliable for an unsigned CLI script (see
`no_cache_server.py`'s own comment on why *it* never does this) — the same
risk now applies to the one process that does. `settings.js`'s
`DEFAULT_SERVER_URL` defaults to `window.location.origin` (not a
hardcoded `localhost:8000`) for exactly this reason: a browser loading the
app via a LAN IP must have its own API calls resolve to that same IP, not
to its own machine's `localhost`.

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

**A plain `pytest -q` skips a whole tier.** Tests that need the real ~35k-card
cache (every `test_cube_batch_*` module, plus anything marked `full_cache`) are
opt-in: `pytest --full-cache` or `MTG_FULL_CACHE_TESTS=1`
(`tests/conftest.py`). They read an *isolated* cache — `backend/conftest.py`
redirects `MTG_CACHE_DIR` to `backend/cache/test/` and seeds it itself, so they
never touch the production `backend/cache/db/cards.db`, and **never export
`MTG_CACHE_DIR` at the production cache to run tests**: that `setdefault` is
the only thing standing between a test run and a wiped 35k-card cache. Run the
tier before closing anything that changes engine or parser behaviour — an
opt-in tier accumulates stale assertions at exactly the rate the rest of the
codebase improves, and ENG-38 closed six of them at once (five were pins that
had quietly stopped describing the engine, one was a live bug).

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

Five project-scoped skills live in `.claude/skills/` and should be invoked
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
- **`understand-card`** (`.claude/skills/understand-card/SKILL.md`) — the
  read-and-explain step *before* the other four: what does a card do under
  the Comprehensive Rules, and how far does the pipeline already get. Ships
  `understand_card.py` (`card`/`clause`/`check`/`term`/`rulings`) — raw vs
  `normalize`d text, per-clause `MODELED`/`UNMODELED` verdict, every keyword +
  the RULE that defines it, a governing-rules roll-up from the glossary terms
  in the text (the two-hop `rules_wiki` lookup done for you), a `check` that
  cross-references parser coverage against what `bind_from_catalogue` actually
  produces, and `rulings` — Scryfall's "Notes and Rules Information" fetched
  once (project UA + rate limit) and cached under `<CACHE_DIR>/rulings/`, with
  the `RULE <n>`s each ruling cites resolved to passages and any ruling that
  looks like it explains an `UNCLAIMED` clause flagged. Reads only (bar that
  one rulings fetch); hands off to `parser_probe.py` / `engine_bench.py` /
  `author_card.py` for the work itself.

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
  energy, poison/infect/wither/toxic; controlling another player's
  turn/combat (RULE 720 — Mindslaver/Emrakul family; `GameState.
  TurnControl` + `GameSession` decision routing).
- **Card-type structures** — DFC transform + day/night/daybound; meld
  (RULE 701.42 — exile the pair, one melded permanent, un-melds on leave);
  modal-DFC/Adventure/Split-Fuse/Prepared casting; Sagas, Class/Leveler/
  Station level-ups; battles (RULE 310); face-down permanents (morph/
  manifest/disguise/cloak); dungeons + venturing (RULE 309); the RULE 9
  casual variants (Planechase/Archenemy/Vanguard).

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

**Coverage: 45.52% (15,846 / 34,811) as of 2026-09-16, measured at
PARSER_VERSION 412** (v412 is PAR-79's ninth increment: "return another
target creature you control to its owner's hand" (Deputy of Acquittals/
Jeskai Barricade) — `other_creature_you_control` (RULE 109.5, built for
Giver of Runes) was already whitelisted in `targeting.ALLOWED_TARGET_
KINDS` and already resolved by `resolve_target_kind`; `_return_to_hand`'s
own closed `_RETURN_TO_HAND_KINDS` set had just never been widened to
accept it — a one-line fix, the same "existing primitive, missing
widening" shape this file's history keeps rediscovering. +5 (2 SOLO
targets, 3 bonus — Aegis Automaton/Flock Impostor/Prehistoric Pet), zero
regressed. Guardians of Koilos ("another target **historic** permanent")
and Stockpiling Celebrant ("another target **nonland** permanent")
deliberately stay open: `resolve_target_kind` doesn't recognize either
qualifier combined with "another…you control" at all yet (confirmed via
direct check, not just the `_RETURN_TO_HAND_KINDS` gap this increment
closed) — a separate, smaller grammar widening, not attempted this pass.
v411 is PAR-79's eighth increment: the Alora,
Cheerful `<X>` cycle's own "at the beginning of the next end step, return
that creature to its owner's hand[. if you do, `<effect>`]." —
`catalogue.handlers._DELAYED_SAC_EXILE_WHEN_FIRST_RE` (already shipped for
the sacrifice/exile "when-first" siblings, MEC-52) widened with a "return"
verb branch and an optional "if you do" tail collapsed into the *same*
`create_delayed_trigger`'s own effects list, plus a new `segmenter.
_PREFIXED_DELAYED_SAC_EXILE_RE` dispatch so an unrelated earlier sentence
(Alora's own "up to 1 target attacking creature can't be blocked this
turn.") in front of the delayed clause doesn't block it — every existing
"certain antecedent, if-you-do collapses to a plain sequence" reduction in
this family (`_SACRIFICE_THEN_WHEN_YOU_DO_RE` et al.) assumed the
collapse *is* the whole ability body, which Alora's own three-sentence
shape breaks. No new engine primitive: `create_delayed_trigger`'s
`capture="previous_or_self"` already bakes RULE 608.2's "that creature"
referent onto every inner effect it builds (including a follow-up one),
so the "if you do" tail just needed to reach the same effects list rather
than open a second, independently-timed delayed trigger. Closes Alora,
Cheerful Assassin/Mastermind/Swashbuckler and Alora, Rogue Companion (+4,
zero regressed, `pytest -q` full suite) — see
[test_par79_unblockable_family.py](backend/tests/test_par79_unblockable_family.py).
Alora, Cheerful Scout/Thief stay UNMODELED: their own "if you do" tails
name "it"/"that creature" *again* ("it perpetually gets +1/+1"), a second
pronoun reference this recursive parse has no way to resolve against the
same baked referent (a `PumpEffect` built with no target at all would be
worse than unclaimed) — real, separately-scoped residue, not attempted
this pass.
v410 is PAR-79's seventh increment: "return
another/`<N>` other `<type>`[s] you control to its owner's hand"/"tap
another/`<N>` other untapped `<type>`[s] you control" as ordinary RULE
608.2c resolve-time-choice effect bodies (neither has a "target" word, so
there's no RULE 115 fizzle risk to worry about modeling one as a target)
— no new engine primitive, since the pre-existing `ChooseObjectsEffect`/
`"choose_objects"` chooser (`RulesEngine._request_choose_objects`, already
this project's general "which one of my own permanents" picker — Tevesh
Szat's sacrifice, Cloudstone Curio's bounce) only needed a `require_
untapped` filter param it didn't have yet. Combined with the sixth
increment's `_may_effect_then` ("You may `<effect>`. If you do,
`<effect2>`.") this closes that handler's own three named motivating
cards — Biblioplex Kraken/Gravelgill Scoundrel/Tidal Terror — which, despite
being its explicit examples, still hadn't parsed even once it shipped: a
**dormant bug**, found while diagnosing why. `segmenter._peel_optional`'s
guard against premature "you may " stripping (`_PAY_ENERGY_THEN_PEEL_
GUARD_RE`) was scoped only to `_MAY_COST_THEN_CLAUSE`'s cost vocabulary
(protecting `pay_cost_then_general`'s own claim), so it stripped these
three cards' leading "you may " — and the reflexive "if you do" gate
along with it — before `_may_effect_then`'s own regex, which requires
that exact prefix, ever got a chance to match; every non-cost antecedent
`_may_effect_then` was built for has silently failed this way since the
sixth increment shipped. Fixed by widening the guard's antecedent
*vocabulary* (mirroring how it already lists `_MAY_COST_THEN_CLAUSE`), not
its shape: a first attempt that widened the guard's *shape* to match any
"you may `<X>`. if/when you do" clause regressed 11 unrelated cards
(Chaos Spewer/Hikari, Twilight Guardian/Sunfire Torch/Yawgmoth Demon &c.)
whose own "certain, self-referential antecedent" reduction handlers
(`_SACRIFICE_THEN_WHEN_YOU_DO_RE`/`_EXILE_SELF_THEN_DELAYED_RETURN_RE`/
`_EARTHBEND_THEN_WHEN_YOU_DO_RE`/`_DISCARD_THEN_IF_YOU_DO_RE`) specifically
*depend* on that same peel — the two families are deliberately disjoint,
not one shape to generalize. +13 (the 3 SOLO targets plus 10 bonus cards
sharing the same antecedent grammar outside PAR-79's own search phrase —
Ambrosia Whiteheart/Ambush Krotiq/Aviary Mechanic/Civil Servant [+ its
Alchemy reprint]/Havengul Skaab/Invasive Species/Loyal Gryff/Rescuer
Chwinga/Yarok's Wavecrasher), zero regressed (`pytest -q`, full suite) —
see [test_par79_unblockable_family.py](backend/tests/test_par79_unblockable_family.py).
46 SOLO cards remain open on PAR-79's own search phrase at PARSER_VERSION
411, each its own separately-shaped residue — see `BACKLOG.md`'s PAR-79
entry.
v409 is a real bug fix, +0/+0 coverage — auditing
v408's consolidation one layer down found `subgrammars._TARGET_ROWS`'s
"target attacking/blocking/tapped/untapped creature" row collapses onto the
bare "creature" kind by design, but nothing preserved the discarded word
elsewhere: **Assassinate** ("Destroy target tapped creature") parsed
`MODELED` but would destroy *any* creature in a real game. New sibling
`resolve_target_creature_state_filter` is now merged into `creature_filter`
by eight handler families (destroy/exile/damage/tap/return_to_hand/pump/
add_counters/connive/unblockable); a second, independent instance of the
same root shape (`_pump_subtype_target`/`_grant_subtype_target` guessing
"attacking"/"blocking" as a literal, unmatchable creature *subtype*) was
fixed the same way; `ConniveEffect` gained a real `creature_filter` param
for the one card (Raffine, Scheming Seer) that needed it. 87 already-
`MODELED` cards corrected, 0 regressed — see
[test_target_creature_state_filter_family.py](backend/tests/test_target_creature_state_filter_family.py).
v408 is the structural consolidation one layer up, +0/+0 — PAR-79's two
dedicated "attacking"/"legendary" target-filter rows were a strict subset
of the general "target `<object-filter phrase>`" row once `object_filter`
itself was taught those two flag words, so the dedicated rows were deleted;
see `handler-recipe.md`'s "decompose into atomic grammar units" for why
this is a fix-the-axis case rather than new coverage. v407/
v406/v405 are PAR-79's sixth increment, closing
several more shared-grammar axes found while sweeping the trigger-condition
residue the fifth increment surfaced — `object_filter` gained an `any_of`
union combinator ("except by artifact creatures and/or red creatures",
Firefright Mage — a union across *different* filter dimensions, unlike
`color_any`/`subtype_any`'s same-dimension ORs) and a "N or more creatures"
blocker-*count* route (`combat.min_blockers`, distinct from a characteristic
filter); `animate_self`/`animate_target` (RULE 613.4d's "becomes a `<colors>`
`<subtype>` creature" family) gained colour-word recognition and a widened
real-creature-type whitelist (the Ravnica guild Keyrune/Monument cycles
alone print ten different types the old 7-word list never covered) — which
uncovered a genuine dormant engine bug: layer 5's colour-changing static
(`continuous._apply_layer_5_color`) had **no `EffectRegistry` factory
reaching it at all**, so nothing in the whole codebase could actually create
one; a card using this shape would have parsed `MODELED` while silently
never changing colour, caught by the execute test (not the parse-level one)
before it shipped; a "mana **spent** (not mana value)" trigger threshold
(Sahagin) reusing the already-stamped `GameObject.mana_spent_to_cast`;
`UnblockableEffect` gained `previous_subject` ("…target creature you
control. **That creature** can't be blocked this turn.", mirroring
`GrantUntilEffect`'s own previous-subject reference); and a new general
`"optional"`-wrapping-a-`seq` composition for "You may `<effect>`. If you
do, `<effect2>`." antecedents that are an ordinary resolving effect rather
than a cost (`OptionalEffect`'s own docstring had already spelled out this
exact composition — no new primitive, just the missing recognizer).
+90 total across both sub-increments (`parser_probe.py diff`, 0 regressed).
53 SOLO cards remain on PAR-79's own search phrase — mostly the six-card
Alora delayed-trigger-with-payoff cycle, a handful of cards needing new
interactive mechanics (a bluffing guess, a hidden-information reveal) this
project doesn't model yet, and true one-off bodies better suited to
`game/ability_catalogue.py` hand-authoring than more parser grammar — see
`BACKLOG.md`'s PAR-79 entry for the categorized residue.
v404/v403 are PAR-79's fifth increment, and the first
one aimed at the trigger-*condition* layer rather than the unblockable
effect body itself: `parser_probe.py card` on individual SOLO cards showed
most of the residue's real blocker was an unrecognized cast/attack trigger
*condition* sitting in front of an `unblockable`/pump-and-unblockable clause
that already parsed fine (Merfolk Cave-Diver/Sahagin/Snooping Page/
Hraesvelgr of the First Brood/Undercover Butler/Martha Jones/Matterbending
Mage, checked individually). Applying handler-recipe.md's newly-documented
"decompose into atomic grammar units" rule at that layer instead of the
single-clause layer PAR-78/79's earlier increments used it at:
`_CAST_SPELL_TRIGGER_MV_AT_LEAST_RE`/`_CAST_SPELL_TRIGGER_X_RE`/
`_CAST_SPELL_TRIGGER_FIRST_X_RE`/`_CAST_SPELL_TRIGGER_HISTORIC_RE` each
reached an `effect_binder` predicate (`spell_mana_value_at_least`/
`spell_has_x`/`first_x_spell`/`spell_is_historic`) that PAR-60 had already
built and wired up, with **zero segmenter regex ever reaching any of the
four** — the same "primitive already exists, only the recognizer is
missing" shape this file's own long history keeps rediscovering, just
never checked systematically for this family before. `_ETB_AND_CAST_
TRIGGER_RE` recognizes RULE 603.1's "When ~ enters and whenever you cast
`<clause>`, `<effect>`" compound (two independent triggers sharing one
effect body, RULE 603.2) by reconstructing each half as its own ordinary
trigger line and re-entering `segment_line` on it — reusing the *entire*
existing ETB/cast-trigger grammar rather than re-deriving any of it, rather
than a fused condition or a second copy of every cast filter.
`defender_has_most_life_predicate` (`game/binding/core.py`) is the RULE
603.4 `>=` mirror of the already-shipped "if no opponent has more life
than that player" gate, for "attacks the player with the most life or tied
for most life" (Undercover Butler). +32 newly covered (`parser_probe.py
diff`, 0 regressed) across the two sub-increments — of which four
(Hraesvelgr of the First Brood, Matterbending Mage, Undercover Butler,
Basim Ibn Ishaq) are PAR-79's own SOLO cards; the rest (Angry Rabble,
Brinelin the Moon Kraken, Jhoira/Cabal Paladin/eight more off the historic-
spell row, …) are the "widened shared primitive reaches cards outside your
own ticket" signal the decomposition rule calls out as evidence the fix
belongs at the axis. 57 SOLO cards remain on "can't be blocked this turn"
itself, now mostly delayed-trigger compounds (the Alora cycle),
optional-effect-then-payoff triggers, and other real per-card body gaps
rather than trigger-recognition dead ends — see `BACKLOG.md`'s PAR-79
entry.
v402 is PAR-79's fourth increment: a whole missing
trigger-*condition* category, found mid-diagnosis of why Cunning
Survivor/Devourer of Memory stayed unclaimed despite their own
`unblockable` clause already parsing fine. Both `EventType.DISCARD_CARD`
and `EventType.CYCLED` were already fully engine-ready (correct payload,
already-registered `_GROUP_CONTROLLER_EVENT_KEYS` entries) — the entire
gap was that `segmenter._PLAYER_TRIGGER_CONDITIONS` (the same table
SCRY/SURVEIL/LIFE_GAINED already use) had no row for the *unscoped*
"whenever you discard/cycle a card" shape, only the pre-existing
self-scoped "when you cycle THIS card,". Four new rows, mirroring that
table's own "you scry or surveil"/"you surveil or scry" two-event-list
precedent for the "cycle or discard"/"discard or cycle" compound pair.
+25, zero regressed — only 1 of the 25 was actually counted in PAR-79's
own search phrase; the other 24 use the identical trigger for an
unrelated payoff, closed as a side effect of fixing the shared condition
table. 61 SOLO cards remain on "can't be blocked this turn" itself — see
`BACKLOG.md`'s PAR-79 entry for the categorized residue.
v401 is PAR-79's third increment: the qualified
"except by `<filter>`" family (RULE 509.1b's *permitted*-set restriction,
`combat.blocker_allowed`'s existing `"only_blocked_by"` arm — already
shipped for the standing static, just needed a resolve-time "this turn"
parser route), `UnblockableEffect`'s new mass (`selector`) and multi-target
(`count`/`count_max`/`optional`) forms mirroring `CantBlockEffect`'s own
shapes exactly, and several bare-target widenings that had fallen behind a
sibling handler. Built as atomic, shared parts rather than one more row per
phrase variant — a real mid-batch correction: the first cut of the
subtype-target widening was a closed, ever-growing word list keyed to this
one search phrase, replaced with a fix to the *shared* `static_handlers.
object_filter` instead (a full Oxford-comma N-way OR-split, and a
singular-"creature" pluralization at its own boundary rather than teaching
the underlying `_scope` a form none of its other callers print) — which is
also why two cards outside this ticket's own search phrase (Turtle Lair;
a `parser_probe.py diff` bonus) picked up coverage from the same change.
That same widening also surfaced and fixed a real latent bug: `_scope`
guessing a subtype literally named `"1/1"` off Lovestruck Beast's "unless
you control a 1/1 creature" (a filter that could never match any real card,
silently making the restriction unsatisfiable instead of correctly staying
UNMODELED) — `_scope` now fails closed on any candidate subtype containing
a digit. +15, zero regressed. 63 SOLO cards remain — this ticket bundles
roughly a hundred independently-shaped small gaps under one search phrase
by design (a missing "discard a card" trigger event, a new cost-reduction
shape, a new "optional effect then follow-up" composition primitive, the
six-card Alora cycle's delayed trigger, …), so closing it to zero SOLO is
not one sitting's work — see `BACKLOG.md`'s PAR-79 entry for the full,
categorized residue.
v397 closes one card of PAR-82's residue — Phenax,
God of Deception's own granted "{T}: Target player mills X cards, where X
is this creature's toughness." Re-verification found the ticket's own
premise stale: "creatures you control have '`<ability>`'"/"enchanted
creature has '`<ability>`'" already correctly resolve today
(`_QUOTED_GRANT_RE`/`_ATTACHED_QUOTED_GRANT_RE`), so every remaining SOLO
card is blocked by its own unrelated inner-ability gap, not a shared
subject-shape recognition gap. Phenax's own gap was `MillEffect.
count_selector`'s already-shipped `"source_toughness"` reading having no
parser route (`_mill_source_pt`). +1, zero regressed. 13 SOLO cards
remain, each a distinct, separately-scoped primitive/recognition gap — see
`BACKLOG.md`'s PAR-82 entry.
v396 closes PAR-81 — "switch target creature's power
and toughness until end of turn" as a resolving one-shot effect. `"pt_
switch"` already existed as a `StaticAbility` layer 7e type (RULE 613.4d/
701.28) for a granted/printed standing ability; the new `"switch_power_
toughness"`/`SwitchPowerToughnessEffect` primitive wires the same swap into
a resolving spell/ability body instead. Stamps a new `GameObject.temp_pt_
switch_count` — an **odd/even counter, not a bool**: RULE 613 applies each
continuous effect in timestamp order, so two independent switches on one
object in the same turn must cancel back out, caught by an execute-level
test (a first cut used a plain bool, silently turning a second switch into
a no-op). Four shapes: bare RULE 115 target, self-referential ("~'s"/"its"
power and toughness), the untargeted mass form ("each creature's…"), and
the multi-target "up to N/any number of target creatures" form. +23, zero
regressed. Two cards stay UNMODELED on separate, unrelated gaps (Wandering
Fumarole's quoted-ability grant on a land-creature; Mangled Soulrager's
paired boon-emblem grant). See `Done_Backend.md`'s "Oracle-Text Parser
Front-End" PAR-81 entry.
v395 closes the first increment of PAR-80 — X-spell
"target creature gets +X/+`<N>` until end of turn." Needed no new engine
primitive: `RulesEngine._substitute_x` already walks any bound effect's own
`power`/`toughness` for the literal `"x"`/`"-x"` sentinel, and `PumpEffect.
amount_from_count_selector`/`_axis` already read a live board count on one
or both axes — pure parser recognition of the bare X-spell/X-ability form
(`_pump_target_x`, with an optional "and gains `<keyword>`" tail) plus a
closed "where X is `<phrase>`" table (`_pump_target_x_selector`:
`creatures_you_control`, `creature_cards_in_your_graveyard`,
`cards_in_your_hand`, `life_gained_this_turn`, the five basic-land-type
counts). +20, zero regressed. 19 SOLO cards remain, each a distinct new
amount referent ("greatest `<X>` among…", a die roll, "cards revealed this
way", the target's own current power, a just-revealed card's mana value) —
see `BACKLOG.md`'s PAR-80 entry, kept open rather than closed.
v394 closes PAR-79's second increment — "another
target legendary creature can't be blocked this turn" (Bessie, the
Doctor's Roadster, `creature_filter`'s `"legendary"` key) and a bare-
subtype-as-noun target, "target `<subtype>`[, `<subtype>`, or `<subtype>`]
can't be blocked this turn" (Aquatic Incursion's "target merfolk",
Corsairs of Umbar's "target goblin, orc, or pirate" — a closed word list,
this project's own PAR-78 convention for this exact shape, not an open
vocabulary). +4, zero regressed. A prior pass through this file's
changelog and `Done_Backend.md` had wrongly marked this ticket fully
"closed" with a fabricated "0 UNMODELED remaining" claim — `parser_probe.py
blocked "can't be blocked this turn"` disproves it (77 SOLO cards still
open: the six-card Alora cycle's delayed-return compound, activation-
cost-reduction/frequency riders, a qualified "except by `<keyword>`"
evasion form, and Brotherhood Spy/Cunning Survivor/Devourer of Memory's
real blocker being an unrelated conditional phase-trigger gap that only
incidentally shares this search phrase) — corrected in both files rather
than left standing; ticket reopened in `BACKLOG.md` with the accurate
residue. See `Done_Backend.md`'s "Combat" section, PAR-79 entry.
v393 closed PAR-78 — "Prevent all damage that would be
dealt to `<target>`" broad recognition. The ticket's own "not a new
primitive" framing was only partly right: `PreventDamageEffect`/
`"prevent_damage_shield"` already had the unlimited "all" shield, but there
was no `source_filter` ("by creatures"/"by sources you don't control"/…)
on *any* prevention primitive, and no board-wide "creatures[ you control]"
recipient shield — both new (`RulesEngine._prevent_damage_to_creatures`).
The bigger find: a bare **permanent's own** un-triggered "Prevent all
damage that would be dealt to `<X>`." line is a *standing* RULE 613/616
replacement effect, not a one-shot resolve-time grant — `segment_line`'s
own `allow_spell_effect` gate already correctly left it unclaimed for the
one-shot family; the real primitive was the already-shipped
`ReplacementRegistry` `"prevent_damage"` factory (MEC-30), reached through
`catalogue/replacements.py`'s `replacement_clause_specs` (not `static_
handlers.py`, where a first pass wrongly placed it — `ability_kind`
distinguishes "static"/StaticAbility from "replacement"/ReplacementEffect
at bind time, and only the latter routes through that registry). Two
parallel `source_filter` vocabularies now exist by design: `catalogue.
handlers._PREVENT_SOURCE_FILTER_PHRASES` (one-shot) and `catalogue.
replacements._PREVENT_ALL_SOURCE_FILTER_PHRASES` (standing, extending the
pre-existing `_prevent_damage_replacement`'s own `color`/`card_type`/
`is_creature`/`controller` keys with `subtype`/`keyword`/`enchanted`) —
different effect kinds, no shared class to unify them through. A second
pass closed the remaining ~26 SOLO cards' genuinely separate mechanics: the
"sources of **the color** of your choice" chooser (Avacyn, Guardian
Angel) needed a real new primitive — `RequestPreventDamageChosenColorEffect`/
`RulesEngine._request_prevent_damage_chosen_color`, a fresh resolve-time
WUBRG choice distinct from both the Circle of Protection family's "**a
source** of your choice" (picks one permanent) and RULE 601.2b's own
`"choose_color"` (an ETB-only, once-per-object pick) — feeding the answer
into the ordinary `source_filter={"color": …}` key; the interactive
"a source of your choice" chooser family itself (Consulate Surveillance/
Protective Sphere/Samite Ministration/Shieldmage Advocate/Prismatic Ward)
was hand-authored in `game/ability_catalogue/damage_prevention.py` per
`catalogue/replacements.py`'s own documented MEC-30 convention (not
parser-recognized), picking up two smaller reusable primitives along the
way — `combat.matches_object_filter`'s `color_from_noted_mana` (Protective
Sphere's "shares a color with the mana spent on this activation cost",
reading `ActivationCost.note_spent_color`/`GameObject.noted_mana_color`,
Jeweled Amulet's own MEC-43 primitive) and `apply_prevent_rider`'s
`if_source_color_any` (Samite Ministration's "black **or** red", widening
the existing single-colour `if_source_color` gate) — plus the standing
replacement family's own `source_filter={"color_from_source": True}`
(Prismatic Ward). Three more real-card widenings closed along the way:
the self-subject pronoun family now accepts "him"/"her" alongside "it"
(Gideon, Ally of Zendikar); the RULE 115 target shape gained a closed
two-word subtype-OR `creature_filter` (Wellgabber Apothecary's "target
tapped Merfolk or Kithkin creature"); and a new devotion-shaped
`static_conditions.py` kind, `control_permanent_of_each_color` (Spirit of
Resistance's "as long as you control a permanent of each color"). 45 cards
closed by parser recognition, 6 more hand-authored, zero regressed
(`pytest -q`, `parser_probe.py diff`). A real residue stays open,
explicitly out of this ticket's scope rather than silently dropped —
riders beyond `if_source_color_any` (Channel Harm/Comeuppance/Judgment of
Alexander/Brace for Impact's own "for each N damage prevented, `<effect>`"
follow-ups); reciprocal "…and dealt by" shields (Heart of Light/Kiora, the
Crashing Wave); quoted-ability-loss cost-based removal (Glittering
Lion/Lynx's "loses \"`<quoted ability>`\""); a RULE 115-targeted damage
*source* (Stonewise Fortifier's "…by target creature", as opposed to an
interactively-chosen or filter-matched one); a "blocking this" source
filter (Wall of Vapor); a reciprocal same-color-as-recipient condition
(Well-Laid Plans); a "those permanents" group-reference recipient
(Mutational Advantage); and a spell (not permanent) source_filter
distinction (Bronze Horse) — each its own genuinely separate primitive,
none sharing enough shape with another to build once. See `docs/
implementation-state/Done_Backend.md`'s "Oracle-Text Parser Front-End"
PAR-78 entry.)
v391 closes PAR-77 — the Rebel/Mercenary graveyard-return
filter. PAR-70 built the "`<subtype>` permanent card" qualifier for library
search; this extends the identical qualifier to `return_from_graveyard`'s
target family — `_GRAVEYARD_TYPE_WORD`/`_graveyard_target_kind` gained
"rebel permanent"/"mercenary permanent" alongside the existing
"nonland permanent"/"non-aura enchantment" two-word phrases, and
`targeting._GRAVEYARD_TYPE_FILTERS` gained the matching `rebel_permanent`/
`mercenary_permanent` predicates (a type-line substring check, same
reasoning PAR-70 already established: both subtypes are exclusively
creature subtypes in paper Magic, so no separate creature-subtype
vocabulary is needed). +1 — Ramosian Revivalist ("{6}, {T}: Return target
Rebel permanent card with mana value 5 or less from your graveyard to the
battlefield.") — zero regressed (`pytest -q`). See `docs/implementation-
state/Done_Backend.md`'s "Oracle-Text Parser Front-End" PAR-77 entry.)
v390 closes PAR-76 — "Full party" (RULE 700.8/702.129) as
a conditional-magnitude override, generalizing the already-shipped
`DealDamageEffect.amount_if_kicked`/`amount_if_raid` family with a new
`amount_if_full_party` field, also added to `AddCountersEffect`, both
reading the already-shipped `"creatures_in_your_party"` count selector as a
live >= 4 threshold. Two cards — The Destined Black Mage ("~ deals 1 damage
to each opponent. If you have a full party, it deals 3 damage to each
opponent instead.") and The Destined White Mage ("put a +1/+1 counter on
target creature you control. If you have a full party, put 3 +1/+1
counters on that creature instead.") — each a fixed singleton parser row
matching the whole two-sentence clause as one unit, since no other cached
card pairs "full party" with a magnitude override on a third effect shape
yet. +2, zero regressed (`pytest -q`). See `docs/implementation-state/
Done_Backend.md`'s "Oracle-Text Parser Front-End" PAR-76 entry.)
v389 closes PAR-75 — "Doctor's companion" (RULE 702.124m)
referenced by another card as a card-quality filter, not just printed on
itself (which PAR-69 already handled). Two cards: An Unearthly Child's Saga
chapter ("reveal cards from the top of your library until you reveal a
Doctor card, a card with doctor's companion, or a Vehicle card…") is a
three-way OR predicate over `dig_until`'s `criteria`, composed via
`card_query`'s existing `"or"` key plus a new, generically-reusable
`has_keyword` criterion (`Card.keywords` membership). Rose Noble's cast
trigger ("whenever you cast a Doctor spell or creature spell with doctor's
companion, draw a card.") is an OR of two *structurally different*
cast-trigger filters (a subtype match vs. a type + keyword match) no single
AND-combined `trigger` dict can express — modeled as two independent
triggered abilities sharing the same effects (`Segment.extra_specs`), safe
because a real Doctor card and a real companion card are never the same
physical card, so the two conditions can never both fire off one cast. New
`trigger` key `spell_has_keyword` (`game/binding/core.py`), mirroring
`spell_subtype_any`'s shape but checking the cast object's printed
keywords instead of its type line. +2, zero regressed (`pytest -q`); also
updated a PAR-69 test that had pinned this exact gap as a documented
UNMODELED limitation. See `docs/implementation-state/Done_Backend.md`'s
"Oracle-Text Parser Front-End" PAR-75 entry.)
v388 closes PAR-74 — the "Spirit or Arcane spell" cast-
trigger filter, Kamigawa. The ticket's own diagnosis was stale: that OR-of-
two-subtypes filter already worked (PAR-52+58); what actually blocked all
15 SOLO cards was a distinct, previously-unclaimed *effect body* per card.
Fixes/additions, smallest first: `_CAST_SPELL_TRIGGER_RE`'s dispatch was
missing the `self_subject=True` its untyped sibling already passed — a bare
"~" in a typed/color/subtype cast trigger's body failed closed for a reason
unrelated to this ticket (+23 cache-wide, Kami of the Painted Road);
`handlers._token_keywords`/`_split_keywords_with_parametric` never resolved
a landwalk *variant* slug ("forestwalk") the way the static-grant family
already did (+22, Orbweaver Kumo); `_GROUP`'s selector list gained "each
other creature you control" (Kodama of the South Tree); a new generic
"becomes a N/M [`<type>`] creature until end of turn" animation family
(self and target) reached RULE 613.4d's already-shipped `grant_until`/
`type_change` primitive (Incubator's/Hedge Whisperer's own shape) for the
first time (+several, Jade Idol/Soilshaper/Hydroform/Kamahl, Fist of
Krosa); "tap or untap target **creature**" widened alongside the existing
"target permanent" row (Teller of Tales); a small new primitive
(`ExileHandCardEffect`/`RulesEngine.exile_hand_choice`, the exile-zone
sibling of `discard_choice`) for "target opponent exiles a card from their
hand" (Kyoki, Sanity's Eclipse); `_SEARCH_CRITERIA` widened for an
enchantment *subtype* ("an Aura card with enchant creature", Tallowisp);
"reveal the top N … put all `<filter>` cards into hand, rest to the bottom
in any order" reached `InspectTopChooseEffect` with `max_picks` forcing the
"all" (Elder Pine of Jukai); PAR-71's "that spell's mana value" referent
extended to `DestroyEffect.filter`/`DiscardEffect.filter` (mass wipe/
discard) and a new `TargetSpec.exact_mana_value` (the exact-match sibling
of `max_mana_value`'s ceiling, Celestial Kirin/Infernal Kirin/Skyfire
Kirin); `TargetSpec.spell_filter` gained `subtype_any` for "counter target
spirit or arcane spell" (Hisoka's Defiance, `card_types`' fixed main-type
lookup can't express a subtype); and `_SACRIFICE_THEN_WHEN_YOU_DO_RE`'s
"When you do," collapse (a certain antecedent once the ability's own outer
"you may" is already peeled) widened to "If you do," plus a new exile-zone
sibling reusing `ExileEffect(remember=True)` + `ReturnLinkedExileEffect`
via a RULE 603.7 delayed trigger (Dreamcatcher/Hikari, Twilight Guardian).
Execute-testing caught one real, previously-latent bug along the way:
`ExileEffect`'s self mode (`target_kind=None`) silently ignored its own
`remember`/`track_exiled_with` flags — only the RULE 115 targeted branch
stamped `linked_exile_id`, so no self-exile-then-delayed-return card had
ever worked; fixed alongside this ticket's own first use. +70 real cards,
zero regressed (`pytest -q`, full suite). See `docs/implementation-state/
Done_Backend.md`'s "Oracle-Text Parser Front-End" PAR-74 entry.)
v387 closes the first increment of PAR-79 — "`<Name>`/
target creature can't be blocked this turn" broad recognition:
`UnblockableEffect`/the `"unblockable"` effect key already existed end to
end (ENG-32, Rogue's Passage/Giant Koi) — this batch is parser recognition
only, three widened shapes, all reusing the existing primitive: a keyword
grant plus unblockable in one sentence ("~ gains lifelink until end of
turn and can't be blocked this turn"), "another target attacking creature
can't be blocked this turn", and an optional "with power N or less/
greater" target-power suffix (mirroring `_GAIN_CONTROL_EOT_RE`'s own
identical suffix) added to both the new handler and the pre-existing bare
form. +24, zero regressed (`parser_probe.py diff`). ~81 SOLO cards remain
on the same search phrase, now split across several distinct smaller
shapes with no dominant template left — see `BACKLOG.md`'s PAR-79 entry,
kept open rather than closed. v386 closes MEC-86 — Prepared (RULE 722.3a): the engine
primitive (`GameObject.prepared`, `RulesEngine.make_prepared`,
`BecomePreparedEffect`) and the parser handler for a card's own "~ becomes
prepared" trigger already existed; the whole gap was one missing
dispatch — "~ enters prepared." (no "when…", RULE 722.3a's other, bare
phrasing) fell through unclaimed. `gate.py` now synthesizes the equivalent
"when ~ enters, it becomes prepared" trigger for that shape. +22, execute-
tested end to end (ETB sets `prepared`, creates the exiled copy, casting it
resolves and clears the flag). Also closes MEC-87 — Horsemanship (RULE
702.31): a recognized flag keyword with zero engine enforcement
(`combat.py` had no `has_horsemanship` at all) — wired into `can_block`,
plus five parser handlers widening existing small keyword-filter
vocabularies (`static_handlers._FILTER_KEYWORD_WORDS`, `handlers.
_CREATURE_FILTER_KEYWORD_WORDS`, the flying-only mass-damage filter, a new
multi-target tap filter row) and one new permanent (non-"until end of
turn") pump-and-grant shape for a genuine Portal Three Kingdoms "this
effect lasts indefinitely" card. +30, zero regressed. Also closes MEC-88 —
Banding (RULE 702.22): `has_banding` plus RULE 702.22j's damage-assignment
reroute (`game/engine/combat_mixin.py`'s `_assign_blocked_attacker`, now
routing to a new even-split `_assign_blocked_attacker_evenly` whenever
Banding is on either side of a block — execute-tested via a real
multi-blocker combat) — the actual behavioural payoff the grant-only
keyword needed. RULE 702.22c's interactive attacking-band declaration is
explicitly out of scope (no MODELED card exercises it); "bands with other
`<quality>`" collapses to plain Banding throughout. +9 via parser
(`Cathedral of Serra`'s "bands with other legendary creatures" quoted-grant
cycle, `Soraya the Falconer`, `Shelkin Brownie`) plus one hand-authored
singleton (`Master of the Hunt` — its "create a *named* token, then grant
it a quoted ability" compound is a genuinely separate, unbuilt ~60-card
template family, confirmed via `parser_probe.py`, well outside this
ticket). Four real cards (`Tolaria`, `Urza's Avenger`, `Nature's Blessing`,
`Wall of Caltrops`) stay UNMODELED, each blocked by its own separate,
non-Banding template gap — see `Done_Backend.md`'s "Banding" entry for the
individual reasoning. Zero regressions across all three tickets
(`pytest -q`, core combat-damage code included). Also closes PAR-72 — Party (RULE 700.8/702.129) generalized
from a cost-reduction "per"/"full party" boolean condition (PAR-53) into the
general resolve-time `amount_from_count_selector`/`count_selector` family:
`continuous.count_selector`'s existing `"creatures_in_your_party"` branch is
now read by ten distinct effect-verb templates (mana, counter-tax, +1/+1
counters self/target, pump self/target/multi-target/negative, gain life,
token creation, scry, a combined life-drain, damage single/twice/split-to-
controller, an inspect-top library dig, and a CDA/anthem pair on the static
side). Three primitives gained a param, all pure widening: `GainLifeEffect.
count_selector_multiplier`, `ScryEffect.count_from_count_selector`,
`InspectTopChooseEffect.count_from_count_selector`/`count_plus`; plus
`CounterSpellEffect.unless_pays_extra_selector` and a `segmenter.py`
trailing-sentence peel folding "This ability costs {N} less to activate for
each…" into the already-existing, previously hand-authored-only
`ActivationCost.dynamic_reduction`. +20 solo cards from the ten handler
families plus 10 bonus closures — 2 from Burakos's own self-type-grant line
(Stonework Packbeast/Veteran Adventurer print the identical sentence) and 8
from widening `_pump_unblockable` (Seafloor Stalker's own effect body)
from target-only to the general self/target/group `_SUBJECT` macro, which
turned out to unlock a whole unrelated self-pump-and-unblockable cluster —
+30 total, zero regressed. Acquisitions Expert was
deliberately left UNCLAIMED — its "reveal a number of cards… you choose
one" shape needs the *hand's owner*, not the caster, to pick which cards
get revealed, a genuinely different two-step interactive primitive out of
this ticket's scope. Execute-testing caught one real, previously-latent
bug: `DealDamageEffect.recipient_subject`'s resolution path read raw
`self.amount` instead of `_amount_for`, silently dropping `amount_from_
count_selector`/`amount_from_trigger_event`/`amount_if_target_color`
whenever combined with `recipient_subject` — no shipped card had combined
them before now, fixed alongside this ticket's own use. See
`docs/implementation-state/Done_Backend.md`'s "Oracle-Text Parser
Front-End" PAR-72 entry.
v384 closed PAR-71 — "that spell's mana value" as a
resolve-time amount referent, extending the shipped `amount_from_trigger_
event`/`count_from_trigger_event`/`pt_from_trigger_event` family (every
`SPELL_CAST` event already carries `mana_value`) to `PumpEffect`/
`GainLifeEffect`/`LoseLifeEffect`/`AddCountersEffect` plus two new fields —
`MillEffect.count_from_trigger_event`, `DiscoverEffect.mana_value_from_
trigger_event`; +10. A second referent was needed for "Counter target
spell. `<effect>`, where X is that spell's mana value." (Hurl into
History/Access Denied/Overwhelming Intellect/Spell Swindle), where "that
spell" is the *countered* RULE 115 target, not a trigger event —
`segmenter._announces_creature_target` gained a `counter`-spec case,
backed by `DiscoverEffect.mana_value_from_subject` (`DrawCardEffect.
amount_from_subject`/`CreateTokenEffect.count_from_subject` already had
it) reading the existing `"previous_subject_mana_value"` referent; +4, +14
total, zero regressed. Imp's Mischief/Draining Whelk print the identical
trap on `lose_life`/`add_counters` and were deliberately left unclaimed
rather than guessed (no card needed that pairing built this batch).
Execute-testing (not just parse verdicts) caught three real bugs en route,
all fixed: `_characteristic_of_subject` never unwrapped a "spell"-kind
target's `StackItem` to its `GameObject` before reading `.card` (silently
reading 0 for *any* `"previous_subject_mana_value"`/`"…_power"` measurement
of a targeted spell, not just this batch's new use); and the `"discover"`/
`"mill"` `EffectRegistry` factory lambdas were never updated to forward
this same batch's own new constructor params, silently dropping them at
bind time despite correct parsing.)
v383 closes PAR-69 (Doctor's companion, RULE 702.124m,
the third partner-ability FLAG-keyword variant alongside Partner/Choose a
Background) and PAR-70 (the Mercadian Masques Rebel/Mercenary recruiter
tutor chain, `_SEARCH_CRITERIA`'s new `subtype` qualifier onto the existing
`"search"` `EffectSpec`, no new primitive). +3 and +17, +20 total, zero
regressed. Also fixed a pre-existing, unrelated bug found while proving
PAR-70 end-to-end: `GameContext._request_search` (`game/effects/core.py`)
was missing the `then_specs` param `RulesEngine._request_search`/
`SearchLibraryEffect` already had (a gap left by PAR-35..42's `then_specs`
plumbing), which raised `TypeError` on *any* search effect resolving
through an activated/triggered ability or a cast spell — 16
previously-broken tests now pass.
v382 (MEC-85, no bump — hand-authored, like PAR-67 below:
Cruel Alliance/Too Evil to Stay Dead's own RULE 702.194b Teamwork "instead"
clause changes a RULE 115 target's *legality* (the mana-value cap drops
entirely rather than a magnitude changing), newly answerable at target-offer
time via new `targeting.TargetSpec.unless_flag`; Earth's Mightiest Heroes'
own "instead" clause changes a *selection count* ("up to one" vs "any
number" of a library-zone pick, no RULE 115 target at all), via new
`InspectTopChooseEffect.max_picks_if_teamwork` generalizing MEC-72's
`inspect_top_n_choose`. All three confirmed singleton via `parser_probe.py
blocked`, +3.
v382's only genuine parser-classification change is
PAR-68's "teamwork" ability-word strip, +0 on its own — see the ledger
entry below; PAR-68 otherwise, like PAR-67 right before it, is hand-
authored: Agent Maria Hill's "becomes tapped to pay a teamwork cost"
trigger (new `GameEngine.set_tapped(reason=...)` tag + `requires_tap_
reason` predicate), Virtual Assistant's "whenever you cast a spell using
teamwork" trigger (new `requires_spell_cast_via_teamwork` predicate — this
one needed a genuine cast-pipeline ordering fix, Teamwork's own tap
payment moved ahead of `self.rules.cast_spell` so `GameObject.
teamwork_paid` is already true by the time `SPELL_CAST` fires), Helicarrier
Strike's magnitude-only "instead" override (new `DealDamageEffect.
amount_if_teamwork`, mirroring `amount_if_kicked`), and Beast Mode's
trailing `condition={"teamwork_paid": True}` gate reading "that creature"
via `AddCountersEffect.previous_subject` — all four confirmed singleton via
`parser_probe.py blocked`, +4. PAR-67 (v381, no bump) — the
counter-removal-followup residue beyond PAR-66's plain accumulator (Garnet,
Princess of Alexandria's chosen-Saga lore-counter removal; Lily Bowen,
Raging Grandma's "remove all but N" partial-removal count; Sage of Hours'
cost-paid "counters removed this way" reading `GameObject.
counters_removed_as_cost`, the `x_paid` sibling a cost payment — rather
than a resolving effect — needs) — same hand-authored treatment, all three
confirmed singleton, +3; v381 closes PAR-53 — Party (RULE 700.8/702.129), wiring the already-built `creatures_in_your_party` count selector to its cost-reduction form and a `"full party"` condition — PAR-56 — Teamwork (RULE 702.194) rider grammar, which also found and fixed a dormant bug where `"teamwork_paid"` was missing from `SUBJECT_FLAGS`, so an earlier-shipped rider condition silently never fired despite parsing fine — PAR-65 — parametric-keyword static grants, starting with Ward `<cost>` (RULE 702.21b; the engine's `ward_cost` grant loop was already fully generic, only the parser's keyword-list regexes couldn't capture the cost) — and PAR-66 — "counters removed this way" as a resolve-time amount, a new `GameContext.counters_removed_this_way` accumulator mirroring `objects_exiled_this_way`; +65 total, zero regressed; v380 closes PAR-47 — the charge-counter add/spend cluster's residual gaps (`_add_named_counter` gains `COUNT_X`, `_pump_x` gains the "-x/-x" polarity, `_gain_life` accepts "x") — and PAR-51 — Storied (RULE 702.195, the Hobbit-Dwarves cluster) as a plain Ascend/city's-blessing-shaped designation, plus `normalize`'s comma-less "`<Name>` the `<Epithet>`" self-reference fold, +35; v379 closes PAR-43 — the Aura/Equipment "for each `<X>`" anthem form plus ~25 new `count_selector` entries shared with the self-scoped form, +70; v378 closes PAR-59's Haunt payoff wrappers; v377 adds PAR-56's additive Teamwork rider condition; v376 closes PAR-52's Spirit-or-Arcane cast triggers; v375 fixes the spurious `Jump`/`Jump-start` label split from PAR-51's trace; v374 closes PAR-50's combat-damage assignment statics; v373 closes PAR-49's Mistform creature-type overwrite; v372 closes PAR-45's opponent-choice entry replacement; v371 closes PAR-44's deck-construction exception; v370 closes PAR-64's Raid positional forms; v367 closes PAR-41's X-scaled discard and graveyard-exile additional costs;
v366 closes PAR-38's remaining upkeep-damage riders
and Elfhame Sanctuary's conditional draw-step skip; v365 closes PAR-36's combat-damage-scaled discard;
v364 closes PAR-35's combat-only casting restriction,
paid conditional Flash, and the generic Flash/next-cleanup-sacrifice rider;
v363 closes generic group/state quoted-ability grants,
including Threshold bodies; v362 recognizes Unquenchable Fury's quoted attack
trigger with damage equal to the defending player's hand size; v361 recognizes Glowcap Lantern's attached
top-library permission plus quoted explore grant; v360 recognizes Leyline Immersion's restricted
any-combination mana grant; v359 recognizes player-or-planeswalker combat damage
that creates that-many named tokens; v358 recognizes Kaldra Compleat's quoted
combat-damage exile; v357 recognizes Sinstriker's Will's quoted
combat-targeted power damage; v356 recognizes Dragon Throne of Tarkir's quoted
other-creature, source-power group pump; v355 recognizes combat targets for exile effects;
v354 recognizes attacking-or-blocking creature targets;
v353 recognizes quoted counter-scaled combat damage;
v352 recognizes quoted grants after attached keywords;
v351 recognizes quoted anthem-keyword-trigger grants;
v350 recognizes quoted anthem-plus-subtype grants;
v349 recognizes quoted all-lands untaps;
v348 recognizes quoted nonland-permanent-count pumps;
v347 recognizes quoted subtype-plus-trigger grants;
v346 recognizes quoted Werewolf-target grants;
v345 recognizes quoted cumulative-upkeep grants;
v344 recognizes sacrificed-toughness quoted grants;
v343 recognizes host-power-scaled quoted token grants;
v342 recognizes defending-player-scoped quoted attack grants;
v341 recognizes two independently quoted attached grants;
v340 recognizes quoted hasty self-copy grants with their delayed exile;
v339 recognizes unscoped each-upkeep quoted grants;
v338 recognizes quoted damage abilities that tap a colorless damaged target;
v337 recognizes source-subtype damage overrides;
v336 adds complete Blood tokens and their named-token grammar;
v335 recognizes target pumps scaled by your creatures;
v334 recognizes one-shot damage shields for you;
v333 regrants other-players' untap-step land abilities;
v332 recognizes quoted attacks that target another attacker;
v331 regrants quoted spell-target triggers;
v330 regrants quoted conditional self-statics;
v329 regrants quoted attacks-alone triggers;
v328 models Blinding Powder's quoted unattach cost and combat shield;
v327 recognizes quoted damage abilities targeting a blocker;
v326 recognizes quoted "destroy target Equipment" abilities;
v325 recognizes quoted untap triggers on attached abilities;
v323 recognizes "sacrifice ~ unless it attacked this turn"; v322 reads "pay
its mana cost" live from the granted-to permanent; v321 recognizes the
controller-scoped untargeted "sacrifice a <permanent>" effect body; v320
recognizes Dual Casting's quoted spell-copy ability; v319 recognizes the
quoted-grant inner clause "tap or untap target permanent"; v318 is ENG-37
B7's `effect_amounts` `resource`
`aggregate` — "max"/"min"/"sum" over a `scope`-worth of players, so a `bind`
can measure "the greatest number of cards a player discarded this way"
(Windfall); plus `spec.py`'s `aggregate` amount-spec key; vocabulary-only,
no parser handler emits it, no verdict change, +0; v317 is ENG-37 B5's
`effect_amounts` `trigger_event`
kind — read a numeric field off `GameContext.trigger_event` (Counterbalance's
"same mana value as the revealed card" vs the SPELL_CAST event);
vocabulary-only, no verdict change, +0; v316 is ENG-37 B5's
`effect_conditions` widening —
an `any` (OR) combinator + an `amount_compare` predicate (number-vs-number
over two `effect_amounts` measurements), plus `spec.py`'s amount-spec
shape-check; vocabulary-only, no verdict change, +0; v315 is ENG-37 B5's
reveal-referent respelling — `handlers._reveal_top_conditional` (Goblin
Guide) now emits `seq(reveal_top, if_else(is_card_type of "revealed"))`
instead of the retired `reveal_top_conditional_to_hand` fusion; no verdict
change, +0; v314 is MEC-84's controller-scoped
permanent-left-battlefield history — the Revolt / Disappear "if a permanent
left the battlefield under your control this turn" gate, +18; v313 is
MEC-83's `effect_amounts` `counters` + `domain` kinds — ENG-37's `bind`
node can now measure a named counter on a permanent and RULE 702.42a
Domain, +13; v312 is MEC-82's RULE 614
conditional magnitude replacement — "gets -2/-2; if kicked, -6/-6 instead"
now overrides the pump's printed P/T via `PumpEffect.power_if_kicked`
rather than stacking, the damage-axis `amount_if_kicked` sibling, +10;
v311 is MEC-81's RULE
616 group-scoped die-to-exile arm — the "if a creature dealt damage this
way would die this turn, exile it instead" rider now reads the actual hit
set, so mass/multi-target damage forms stop failing closed, +13; v310 was
MEC-79's RULE 701.64
Harness — the "harnessed" designation + the Infinity Stones' "∞"-ability
gate, + a `_BLINK_PLAIN_RE` "other"/"another" widen, +4; v309 was MEC-78's
RULE 701.69a Heal — remove marked damage + Wolverine's heal-on-damage
replacement, +1; v308 was MEC-77's Meld, +3; v307 was MEC-76's Fateseal,
+2; v306 was MEC-75's RULE 706 dice subsystem, +12; v305 was
42.47%/14,784, and 302–304 were PAR-62's +197-card zero-regression
connective increments)
(parser-`MODELED` or hand-`AUTHORED`, measured against the full ~35k-card
Oracle universe from `scripts/import_bulk.py`). Re-measure with
`scripts/coverage_report.py` (ledger-backed, `services/coverage_db.py`)
before trusting this number. The **Commander-legal** slice — the subset
that matters for Goldfisch/Deck-Analyzer — is 47.80% (15,213 / 31,830);
measure it with `scripts/coverage_report.py --commander-legal-only`
(records a separate `…-commander` snapshot row) and segment the
still-UNMODELED remainder by *cause* (wrapper re-measure / recurring
template → `PAR-*` / set-specific → `PAR-*` / missing primitive → `MEC-*` /
bespoke hand-authoring tail) with the read-only
`scripts/commander_tail_report.py`. The long-tail strategy (recurring lessons,
worked samples, known-open clusters) is in
`docs/implementation-state/PARSER_LONG_TAIL.md` — **not** a per-version
changelog any more (that was worklog duplicating `Done_Backend.md`, removed
2026-09-09); a shipped handler's narrative belongs in `Done_Backend.md` under
the primitive's own subsystem heading. Open parser tickets are
`PAR-*` in `BACKLOG.md`. **Stickers (RULE 123) are a permanent project
non-goal** — the gate classifies any "sticker" card as `NEVER_SUPPORTED`, a
verdict distinct from `UNMODELED` and kept out of both the covered count and
the backlog ranking.

**Notable open gaps** are tracked with exact scope in `BACKLOG.md`: a kicked
spell's "if kicked, … instead" override that *also* grants a keyword
(Colossal Growth — the plain magnitude override is shipped for both the
damage and pump axes, MEC-82); Doomsday's "exile up to five cards in a pile";
the oracle
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
| Open points | `BACKLOG.md` | The *single* backlog, backend **and** frontend, as categorized tickets (`ENG` game engine, `PAR` parser, `MEC` game mechanics, `PLR` player management, `VIS` visuals, `DB` database, `ANA` deck analysis — the former `TYP` card-types category is retired, RULE 300–315 being complete). Open scope only — no history. **Up-for-scheduling work only**; parked/low-priority tickets and permanent non-goals move to `DEFERRED.md` so this file stays cheap to read in full. |
| Parked / non-goals | `DEFERRED.md` | Low-priority or large-and-unscheduled tickets pulled out of `BACKLOG.md` (they keep their id + full write-up), plus the "never to be built" guardrails (Stickers, Attractions, Vanguard avatars). Same open-scope-only discipline. Promote by moving a block back into `BACKLOG.md`. |
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
| "As long as …" conditions on a static (RULE 613.6) | `game/static_conditions.py` — the project's **single state-predicate vocabulary**, read by statics' `active_if`, trigger intervening-ifs, `binding/core.py`'s replacement gate and (via `game/effect_conditions.py`) resolving effects; plus `parser/oracle/catalogue/static_handlers.py` (`_STATIC_CONDITION_RES`, `_conditional_static_specs`) |
| "Until …" durations on a continuous effect (RULE 611) | `game/durations.py`, `GameState.floating_statics`, `effects.GrantUntilEffect` — note "until end of turn" stays on the `temp_*` path |
| How many targets a spell/ability wants (RULE 115.1/601.2c) | `game/targeting.py` (`TargetSpec.count`/`count_max`/`count_selector`, `effective_count`, `resolved_count`, `expand_counts`/`collapse_groups`) |
| A clause naming what a previous clause targeted, created, or revealed | `effects.GameContext.previous_targets` / `created_objects` / `revealed_card` (all maintained by `_apply_effects_partitioned`; `revealed_card` is the `of: "revealed"` referent, set by `reveal_top`) |
| Activated abilities / costs | `game/costs.py`, `game/game_engine.py` (`activate_ability`) |
| Card abilities / fetch lands / enters-tapped | `game/ability_catalogue.py`, `effect_binder.bind_from_catalogue` |
| Hand-authoring a specific card's effects | `hand-author-card` skill, [docs/Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md](docs/Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md) |
| Effects / triggers | `game/effects.py`, `game/effect_binder.py` |
| Which trigger conditions the parser recognizes | `parser/oracle/segmenter.py` (`_TRIGGER_VERBS` object subjects, `_PHASE_STEP_WORDS`, `_PLAYER_TRIGGER_CONDITIONS` "whenever **you** scry/surveil", `_VARIANT_TRIGGER_CONDITIONS`) |
| Face-down permanents (morph/disguise/manifest/cloak) | `game/face_down.py`, `models/game_object.py` (`turn_face_down`/`turn_face_up`), `game/game_engine.py` (`turn_face_up`, `face="face_down"`) |
| Dungeons + venturing | `models/dungeon.py`, `game/dungeons.py`, `services/dungeon_database.py`, `rules_engine.venture_into_the_dungeon` |
| Formats & casual variants (Planechase/Archenemy/Vanguard) | `models/game_format.py`, `game/variants.py`, `services/variant_card_database.py`, `game_engine.new_game(game_format=…)` |
| "Play/cast from top of library" permission | `game/top_library.py`, `game/game_engine.py` (`can_play_land`/`can_cast`/`legal_actions`), `gameBoardView.js` (`libraryTopHtml`) |
| Who an effect acts on / how much it measures (an operand naming a referent) | `backend/mtg_analyzer/game/effect_operands.py` (`{"of": …, "as": "controller"}`), `game/effect_amounts.py`; both resolve referents through `effect_conditions.subject_of` |
| Combining effects: branching, "you may", "for each", "…equal to" | `backend/mtg_analyzer/game/effects/composition.py` (`seq`/`if_else`/`optional`/`for_each`/`bind`), `game/effect_amounts.py` (what `bind` measures) |
| An "if `<predicate>`, `<effect>`" gate on a resolving effect (RULE 603.4/702.33b) | `backend/mtg_analyzer/game/effect_conditions.py` (referents + the `GameContext` predicates + the flat-key translator), `game/static_conditions.py` (every state predicate, shared with statics/triggers/replacements), `parser/oracle/segmenter.py`'s `_CONDITION_PREFIXES` |
| A player choice: opening one, answering one, adding a new kind | `backend/mtg_analyzer/game/continuations.py` (the handler registry), `RulesEngine.open_choice`/`resolve_choice` |
| What an effect type/engine method *is* (instruction/fusion/alias/…) | `backend/mtg_analyzer/game/isa.py`, `scripts/isa_report.py --registry` |
| Which operations the corpus actually uses, and their argument frames | `scripts/isa_report.py --corpus` (re-derives `13_` §5.6b from the ledger) |
| What a `TargetSpec.kind` decomposes into (types × scope × filters) | `game/targeting.py`'s `TARGET_FRAMES` |
| On-disk paths / env-var config | `backend/mtg_analyzer/config.py` |
| Goldfish UI | `frontend/src/js/goldfishView.js` |
| Solo vs. bots (Multiplayer engine, no lobby) | `backend/mtg_analyzer/api/solo.py`, `frontend/src/js/soloView.js`; shared picker/mulligan/banner markup in `frontend/src/js/gameSetup.js` (also used by goldfish/multiplayer) |
| Multiplayer (lobby, seats, shared board) | `backend/mtg_analyzer/services/lobby.py`, `api/multiplayer.py`, `api/multiplayer_ws.py`, `frontend/src/js/multiplayerView.js`, `lobbySocket.js`, `bannerColors.js` (seat banner colours) |
| Bots filling a multiplayer seat (UC5) | `backend/mtg_analyzer/services/bots.py` (`Bot`/`GoldfishBot`/`GreedyBot`/`run_bots`), `services/lobby.py` (`Seat.bot_kind`, `add_bot`), `frontend/src/js/multiplayerView.js` (`addBotHtml`/`seatRowHtml`) |
| Replay/Puzzle mode (build+save/load a board) | `backend/mtg_analyzer/services/replay.py`, `game_session.py` (`edit_*` actions), `frontend/src/js/replayView.js` |
| Archidekt deck import proxy | `backend/mtg_analyzer/services/archidekt_client.py`, `api/import_external.py` (Moxfield was tried and reverted twice — Cloudflare-blocked; don't re-add it without checking that's changed) |
| Refreshing the full Oracle card pool (new set) | `backend/scripts/update_card_pool.py` — re-downloads the Scryfall `oracle_cards` bulk dump, merges it into `RawCardStore`, reseeds the app cache, and prints a ban-list drift heads-up (`scripts/import_bulk.py` is first-load only; its default reuses an on-disk dump) |
| Applying a ban-list update | `backend/scripts/update_ban_lists.py` — rewrites a hand-maintained ban-list constant (`BAN_LIST_TARGETS`, just `services/commander_legality.py`'s `BANNED_COMMANDER_CARDS` today) straight from the raw store's live `legalities` data; no network of its own, run `update_card_pool.py` first. `--format <key>`/`--dry-run` |
| Player-uploaded token art / card-back sleeves | `backend/mtg_analyzer/services/player_assets.py`, `api/player_assets.py`, `frontend/src/js/profileView.js` (upload UI + player name), `gameBoardView.js` (`resolveImageUrl`/`setAssets`) |
| Default art for a vanilla ("1/1 white Soldier") token | `backend/mtg_analyzer/services/token_database.py` (`TokenArtLibrary`, keyed by exact name/power/toughness/colors — a token name is reprinted at multiple stat lines across sets), `data/token_art.json`, `scripts/build_token_art_library.py` (rebuild from a fresh Scryfall bulk dump); consumed by `synthesize_token_card` and `services/replay.py`'s `_token_card` |
| Engine coverage doc (user-facing) | `frontend/src/js/implementationStatusView.js` |
| What's still open (any area) | [docs/implementation-state/BACKLOG.md](docs/implementation-state/BACKLOG.md) — tickets by category; parked/low-priority + non-goals in [DEFERRED.md](docs/implementation-state/DEFERRED.md) |
| Why shipped work looks the way it does | [Done_Backend.md](docs/implementation-state/Done_Backend.md) / [Done_Frontend.md](docs/implementation-state/Done_Frontend.md) |
| Parser-tail strategy, lessons, worked samples | [docs/implementation-state/PARSER_LONG_TAIL.md](docs/implementation-state/PARSER_LONG_TAIL.md) |
| Looking up a `RULE <n>` in the CR text | `docs/Reference/rules_wiki/` (rule#/term → source line; see its `README.md`) |
| Full docs/ map (requirements/concepts/Reference/implementation-state) | [docs/README.md](docs/README.md) |
| How to *use* the app (not build it) | [user-docs/](user-docs/) (English + German) |
