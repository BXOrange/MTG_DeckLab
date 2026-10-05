# DeckLab: Architecture

This document describes the system as it actually exists today: a FastAPI
backend with a rules-accurate MTG game engine, served to a buildless
static-ES-modules frontend. It replaced an earlier version of this file
that described a CLI-only, single-process, phase-by-phase build plan written
before the project became a client/server web app — that plan is long since
superseded and none of its phases describe how the app is actually built
now. For the historical phased plan, see
[`../implementation-state/IMPLEMENTATION_GUIDE.md`](../implementation-state/IMPLEMENTATION_GUIDE.md);
for what's shipped vs. still open, see
[`../implementation-state/BACKLOG.md`](../implementation-state/BACKLOG.md) and
[`Done_Backend.md`](../implementation-state/Done_Backend.md)/[`Done_Frontend.md`](../implementation-state/Done_Frontend.md).
For a diagram companion to this prose, see
[`12_ARCHITECTURE_DIAGRAMS.md`](12_ARCHITECTURE_DIAGRAMS.md).

---

# PART 1: SYSTEM OVERVIEW

Two halves in one repo, talking over HTTP/JSON and WebSockets:

- **`backend/`** — Python, FastAPI, one uvicorn process. The card model,
  rules engine, oracle-text→effect pipeline, and every game-session API.
  This is where the depth is; see [`04_SERVER_CLIENT_ARCHITECTURE.md`](04_SERVER_CLIENT_ARCHITECTURE.md)
  for the API/session/WebSocket shape in detail.
- **`frontend/`** — a static, buildless ES-modules app (no bundler, no
  framework, no Node runtime required to run it). Plain `render*(container)`
  functions that set `innerHTML` and wire listeners; see
  [`05_GAME_UI_AND_CARD_INTERACTION.md`](05_GAME_UI_AND_CARD_INTERACTION.md).

**There is no separate matchmaking service, user database, or LLM
integration** — none of those exist in this project; game rooms are an
in-memory lobby (below), decks/players are identified by free text (no
accounts), and there is no LLM in the loop anywhere in the running app.
Anything describing those as present is describing an abandoned early plan,
not the current system.

**A browser only ever needs to reach the backend's port.** The backend
reverse-proxies anything outside `/api`/`/ws` straight through to the
frontend's own static-file process (`api/frontend_proxy.py`) — a
server-to-server call, not a CORS-relevant one. The frontend process stays
loopback-only; only the backend is ever opened to the network, and only
when explicitly started with `--host` (this app has no authentication, so
that's opt-in — see `CLAUDE.md`'s "Run & test" section for the exact
flags/env vars).

## System layers (top-down)

```
┌─────────────────────────────────────────────────────────────────┐
│ FRONTEND (frontend/src/js/, buildless ES modules)                │
│ ├─ Tab views: deck import/analysis, saved decks, card cache      │
│ ├─ Goldfisch board (goldfishView.js) — solo practice vs. engine  │
│ ├─ Solo gegen Bots (soloView.js) — Multiplayer engine, no lobby  │
│ ├─ Replay/Puzzle board (replayView.js) — construct-a-board       │
│ ├─ Multiplayer: Setup (lobby) + Board (shared game)               │
│ │    (multiplayerView.js, lobbySocket.js, gameBoardView.js)      │
│ ├─ Einstellungen (connectionSettingsView.js) / Profil (profileView.js) │
│ └─ Engine-Status (implementationStatusView.js)                    │
└────────────────────────────┬──────────────────────────────────────┘
                             │ HTTP/JSON + WebSocket
┌────────────────────────────▼──────────────────────────────────────┐
│ API LAYER (backend/mtg_analyzer/api/, FastAPI routers)             │
│ ├─ decks, saved_decks, archetypes, cards, images                 │
│ ├─ game (goldfish/replay sessions) + game_ws                      │
│ ├─ multiplayer (lobby bridge) + multiplayer_ws                    │
│ ├─ solo (Multiplayer engine, no lobby)                            │
│ ├─ dynamic_analysis, import_external, player_assets                │
│ └─ frontend_proxy (serves the static frontend through this port)  │
└────────────────────────────┬──────────────────────────────────────┘
                             │
┌────────────────────────────▼──────────────────────────────────────┐
│ SESSION / LOBBY LAYER (backend/mtg_analyzer/services/)             │
│ ├─ game_session.py — GameSession: wraps one GameEngine             │
│ │    (snapshots/undo/rewind, take-backs, wire-safe view, replay)  │
│ ├─ lobby.py — Lobby/LobbyPlayer/LobbyGame/Seat (rules-free:        │
│ │    people and tables, presence, seat/deck picks, bot seats)     │
│ └─ bots.py — Bot/GoldfishBot/GreedyBot, playing through the same   │
│      client surface (session.view + apply_action) a human uses    │
└────────────────────────────┬──────────────────────────────────────┘
                             │
┌────────────────────────────▼──────────────────────────────────────┐
│ GAME ENGINE LAYER (backend/mtg_analyzer/game/)                     │
│ ├─ GameEngine — turn/phase/step loop, actions, legal_actions,      │
│ │    combat (game_engine.py + game/engine/*_mixin.py)              │
│ ├─ RulesEngine — cast, damage, draw, triggers, SBAs, replacement   │
│ │    effects (rules_engine.py + game/rules/*_mixin.py)             │
│ ├─ combat.py, continuous.py (RULE 613 layers), targeting.py,       │
│ │    costs.py, mana_abilities.py, static_conditions.py,            │
│ │    durations.py, face_down.py, dungeons.py, variants.py          │
│ └─ effects/ — EffectRegistry + the GameEffect hierarchy           │
└────────────────────────────┬──────────────────────────────────────┘
                             │
┌────────────────────────────▼──────────────────────────────────────┐
│ ABILITY SOURCING (backend/mtg_analyzer/game/ + parser/oracle/)     │
│ ├─ card_catalogue/ — hand-authored per-card AbilitySpecs           │
│ ├─ card_registry/ — register()/specs_for() lookup mechanism        │
│ ├─ binding/core.py — AbilitySpec → live GameEffect (bind-on-load) │
│ └─ parser/oracle/ — normalize → segmenter → catalogue/handlers →   │
│      gate.parse_oracle: oracle text → AbilitySpec for any card     │
│      not in the hand-authored catalogue, fail-closed MODELED/      │
│      UNMODELED verdict (see 09_ORACLE_EFFECT_PARSER.md)            │
└────────────────────────────┬──────────────────────────────────────┘
                             │
┌────────────────────────────▼──────────────────────────────────────┐
│ DATA / MODEL LAYER (backend/mtg_analyzer/models/, services/)       │
│ ├─ models/cards/card.py — immutable printed characteristics        │
│ ├─ models/game/game_object.py — one instance in a zone, mutable    │
│ ├─ models/game/game_state.py — battlefield/stack/players/turn +    │
│ │    event bus; models/game/player.py, dungeon.py, emblem.py       │
│ ├─ models/decks/deck.py, models/mana/ (cost + pool)                │
│ ├─ services/card_database.py, lazy_card_loader.py,                 │
│ │    scryfall_client.py, raw_card_store.py — the card cache        │
│ ├─ services/deck_database.py, deck_validation.py,                  │
│ │    commander_legality.py, archidekt_client.py                   │
│ └─ services/coverage_db.py, token_database.py, player_assets.py,   │
│      dungeon_database.py, variant_card_database.py                 │
└─────────────────────────────────────────────────────────────────┘
```

**Model → game import boundary**: `models/` must not import `game/` at
module load time (a `game/`-needing lookup on a model uses a
function-scoped import instead) — this keeps the plain data model usable
without pulling in the whole rules engine, and `game/`'s own low-level
modules (`combat.py`, `continuous.py`) only import models under
`TYPE_CHECKING`. See `CLAUDE.md`'s "Conventions & gotchas".

**Security boundary**: oracle text never becomes code. `AbilitySpec` is a
pure JSON-shaped IR — a whitelisted `type` string plus clamped params
(`parser/oracle/spec.py`) — and the binder (`game/binding/core.py`) is the
only thing that turns a spec into live behaviour via the `EffectRegistry`'s
whitelisted factories. The oracle-text front-end (`parser/oracle/`) has no
`game/` imports at all, by design.

---

# PART 2: GAME MODES

The same `GameEngine`/`GameState` core drives four distinct front-door
experiences, differentiated by session config rather than by separate
engines:

| Mode | What it is | Session shape |
| --- | --- | --- |
| **Goldfisch** | Solo practice: play a saved deck against the rules engine, turn by turn, stepping through phases yourself | `GameSession(mode="goldfish")`, `interactive_priority` off — `_run_step` auto-drains the stack |
| **Replay / Puzzle** | Construct an arbitrary board (1 player = puzzle, 2 = with an opponent) and play from there; reuses the goldfish engine plus `edit_*` actions that mutate state directly | `GameSession(mode="replay", require_setup=False)`; save/load is JSON export/import of a re-resolvable descriptor (`services/replay.py`) |
| **Solo gegen Bots** | A real game — turns, priority, hidden hands — against 1–3 bots, no lobby/socket | Built directly via `api/solo.py`, same Multiplayer engine underneath as the lobby mode |
| **Multiplayer** | A real game of two to four players (or bots) at a shared table, over WebSocket | `services/lobby.py` (people/tables, rules-free) hands a built session id to `services/game_session.py`; `api/multiplayer.py` is the only bridge between the two |

Multiplayer is what turns a session from solo to shared: **actions carry an
actor** (`apply_action(action, actor_id=...)`, so the engine's own per-player
validation decides what a non-active seat may do); **`view(perspective=...)`
redacts hidden zones server-side** (RULE 400.2 — an opponent's hand never
leaves the process); **`/ws/lobby`** pushes each participant their own view
rather than one shared payload; and **RULE 117 priority is played out for
real** (`GameEngine.interactive_priority`, opt-in per session — off, every
solo/goldfish/replay path auto-drains the stack exactly as it always did).
Bots (`services/bots.py`) fill a seat like any player: a bot reads
`session.view(perspective=<its own id>)` and only submits entries from its
own `legal_actions`, so a bot game doubles as a redaction test. See
`CLAUDE.md`'s "What this is" section for the full behavioural detail on
each mode (take-backs, disconnect/idle timers, the priority countdown,
banner colours, etc.) — this document only covers the structural shape.

---

# PART 3: BACKEND DATA FLOW

```
Card (models/cards/card.py)              immutable printed characteristics
  └─ GameObject (models/game/game_object.py)   one instance in a zone, mutable state
GameState (models/game/game_state.py)     battlefield/stack/players/turn + event bus
RulesEngine (game/rules_engine.py)        rules primitives: cast, damage, draw, SBAs…
GameEngine  (game/game_engine.py)         turn/phase loop, actions, legal_actions, combat
GameSession (services/game_session.py)    wraps an engine: snapshots/undo, wire view
API (api/game.py, api/multiplayer.py, …) ── JSON ──▶  frontend (src/js/*View.js)
```

`RulesEngine`/`GameEngine` are each a **composition of per-responsibility
mixins** rather than one file holding every method: `game_engine.py`/
`rules_engine.py` shrink to `__init__` plus the class declaration (and, for
`RulesEngine`, the RULE 616 replacement-effect core); everything else lives
in `game/engine/*_mixin.py` (turn loop, combat, casting, lands, activation,
mana, legal_actions, misc) and `game/rules/*_mixin.py` (triggers, casting
resolution, damage/death, draw/discard, mana/counters, copies, search,
state-based actions, misc systems). This is invisible from outside `game/`
— both classes keep their exact public method names/signatures, so
`engine.cast_spell(...)`/`rules.deal_damage(...)` work exactly as if they
were defined on one class; grep/IDE symbol search finds the right file
regardless of which mixin defines a given method.

The oracle-text → behaviour pipeline: `AbilitySpec` IR (`parser/oracle/
spec.py`) → binder (`game/binding/core.py`) → live `GameEffect` objects via
the `EffectRegistry` (`game/effects/` package — `core.py`, `composition.py`,
and a dozen more themed modules; `registry.py` holds `EffectRegistry`
itself). Bind-on-load means every object a
session creates gets `bind_from_catalogue(obj)` called on it, sourcing
specs from `game/card_registry.specs_for` — which checks the hand-authored
`game/card_catalogue/` first (one file per card) and falls back to the
oracle-text front-end (`parser/oracle/`: `normalize` → `segmenter` →
`catalogue/handlers` → `gate.parse_oracle`) for any unregistered card,
adding parsed specs only when the card is fully `MODELED` (a card is never
half-resolved). See [`09_ORACLE_EFFECT_PARSER.md`](09_ORACLE_EFFECT_PARSER.md)
for the parser pipeline in detail and
[`07_GAME_LOOP_EFFECT_SYSTEM.md`](07_GAME_LOOP_EFFECT_SYSTEM.md) for the
effect/trigger/replacement system.

---

# PART 4: FRONTEND

No framework, no bundler, no build step — `frontend/src/**` is edited and
the browser reloads it directly. Views (`frontend/src/js/*.js`) are
`render*(container)` functions that set `innerHTML` and wire DOM listeners;
shared setup markup (deck picker, mulligan, banner colours) lives in
`gameSetup.js` and is reused by goldfish/solo/multiplayer. User-facing text
is data-driven through `i18n.js` + `locales/{en,de}.js` (UI language is
switchable; MTG keyword names always stay English). Client-only
preferences persist via cookies (`cookies.js`, `settings.js`) — never via a
server-side user account, since none exists.

The interactive game board (`gameBoardView.js`) is shared across goldfish,
replay, and multiplayer, driven through an injected transport (direct API
calls for goldfish/replay, `gameSocket.js`/`lobbySocket.js` for
multiplayer/solo over WebSocket). See
[`05_GAME_UI_AND_CARD_INTERACTION.md`](05_GAME_UI_AND_CARD_INTERACTION.md)
for board/interaction design and
[`06_CARD_GRAPHICS_AND_LAZY_LOADING.md`](06_CARD_GRAPHICS_AND_LAZY_LOADING.md)
for how card art is fetched, cached, and lazily loaded.

---

# PART 5: WHAT REPLACED THE ORIGINAL 7-PHASE PLAN

The document this one replaces framed the build as seven sequential phases
(rules infrastructure → core rules engine → game loop → CLI UI →
multiplayer → LLM analysis → bot automation) for a single-process CLI tool.
None of that framing survived contact with the real project:

- There was never a CLI UI phase — the project went straight to a web
  frontend once the rules engine existed, and the CLI never shipped.
- "LLM-Powered Deck Analysis" as a phase never happened; deck analysis
  today (`services/archetype_analysis.py`, `services/dynamic_analysis.py`,
  the **Analyze**/`analyzeView.js` tab) is heuristic/simulation-based, not
  an LLM call. There is no LLM integration anywhere in this app.
- Multiplayer didn't get bolted onto a finished 2-player engine — the
  engine has been N-player throughout, and the actual multiplayer work was
  the lobby/session split, WebSocket push, and RULE 117 priority described
  in Part 2 above.
- Bots (`services/bots.py`) aren't a scoring/strategy-engine AI layered on
  top of the rules engine; they're ordinary players that only ever see
  `session.view()` and only ever submit from `legal_actions` — see Part 2.
- The "rules engine" itself grew far past RULE 601/608/504/117/603/607 —
  it now covers the full turn structure, mana model, combat/keyword
  family, the RULE 613 layer system, every RULE 701 keyword action, and
  most one-shot effect families (see `CLAUDE.md`'s "Implementation state"
  section for the current, maintained summary — don't trust phase
  checkboxes to describe what's built; they're gone from this doc on
  purpose).

For what's actually left to build, use
[`../implementation-state/BACKLOG.md`](../implementation-state/BACKLOG.md)
(open tickets, backend and frontend) and
[`../implementation-state/10_COMPLETION_ROADMAP.md`](../implementation-state/10_COMPLETION_ROADMAP.md)
(the synthesized, dependency-ordered status) rather than any phase plan —
none exists any more, because the project no longer fits a linear
"finish layer N before starting layer N+1" shape: the parser tail, engine
mechanics, and frontend polish now proceed in parallel, ticket by ticket.

---

# PART 6: THE GUIDING PRINCIPLE — THE RULES ARE THE SPECIFICATION

(Carried over from the original July 2026 "rules-driven" plan, the only part of
it that survived unchanged.)

The Comprehensive Rules are not guidelines; they deterministically define card
types, when spells and abilities may be used, how the stack resolves and in
what order events happen. So the engine is a *specification-implementation*
problem, not a design problem: don't invent a priority scheme or an ordering
heuristic — find the rule, code it, cite it.

In practice:

- **Cite the rule where you implement it** (`RULE 603.3b`) and write tests that
  name the rule they pin down. The actual CR text is looked up in
  [`../Reference/rules_wiki/`](../Reference/rules_wiki/) — never from memory.
- **New cards extend data, not the engine.** A card is an `AbilitySpec` (parsed
  or hand-authored) bound to whitelisted effects; supporting a new card should
  not require touching the turn loop, stack or combat code. When it does, a
  general primitive is missing — build that, not a one-off.
- **Validate against the rulebook, not against "does the design work".** When
  engine behaviour and a rule disagree, the rule wins.
- **Test pyramid:** unit tests per effect/primitive, integration tests through
  `GameEngine`/`GameSession` (stack, triggers, priority), and whole-game runs
  with bots; plus an opt-in tier against the full card cache.

**Rule numbers are easy to get wrong.** The original plan cited several that
don't match the CR, and the same slips recur: RULE 504 is the *draw step* (mana
abilities are 605, paying costs 601.2h); RULE 607 is *linked abilities*
(simultaneous-trigger ordering is 603.3b, in APNAP order); RULE 109 is objects
and 110 permanents (card types are 300–315, players 102–103); RULE 116 is
special actions (countering is 701.6); RULE 702.19 is trample. Part 5 above
still lists "RULE 601/608/504/117/603/607" for the original plan's scope — read
504 and 607 there as the plan's mistakes, not as the mana and trigger rules.
