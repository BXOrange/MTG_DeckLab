# DeckLab: Server/Client Architecture

This document is the detailed companion to
[`03_ARCHITECTURE_AND_BUILDPLAN.md`](03_ARCHITECTURE_AND_BUILDPLAN.md)'s
system overview: the actual FastAPI REST/WebSocket surface, the
`GameSession`/`Lobby` split, and the security posture this project actually
ships with — not the aspirational client/server plan an earlier version of
this file described (React/Vue frontend, matchmaking, user accounts, LLM
integration). None of that exists here; see Part 6 for exactly what got
dropped and why.

For diagrams, see
[`12_ARCHITECTURE_DIAGRAMS.md`](12_ARCHITECTURE_DIAGRAMS.md). For the
frontend's own interaction model (the board, drag targets, the stack
overlay), see
[`05_GAME_UI_AND_CARD_INTERACTION.md`](05_GAME_UI_AND_CARD_INTERACTION.md).

---

# PART 1: ONE PROCESS, ONE PORT

## Why a single uvicorn process

The backend runs as **one** uvicorn process on purpose
(`setup/start.py`) — see `CLAUDE.md`'s "Concurrency / workers" section.
The game-session manager, the multiplayer lobby, and the dynamic-analysis
job registry are all in-memory, process-wide singletons
(`api/dependencies.py`'s `get_game_session_manager()` /
`get_lobby()` / job registry): a game or a lobby seat lives in a Python
object inside this one process, not in a shared database row, so
`uvicorn --workers N` would silently split every running game across N
processes that don't know about each other. There is no Redis, no
sticky-session load balancer, no horizontal scaling story — a game session,
a lobby table, and an analysis job all live and die with this one process.

Concurrency *within* that one process is real, though: every gameplay
endpoint is a synchronous `def`, so Starlette hands each request to an
AnyIO worker-thread pool sized by `config.SERVER_THREAD_WORKERS`
(`MTG_SERVER_THREAD_WORKERS` / `--server-threads`, default 40,
`api/app.py`'s `_apply_server_thread_workers`) — that number is the ceiling
on how many games can be mid-step at once. Deck analysis has its own,
separate pair of knobs: `DYNAMIC_ANALYSIS_WORKERS` caps how many analysis
*jobs* may run concurrently, and `DYNAMIC_ANALYSIS_MATCH_WORKERS` fans one
job's independent match simulations across a `ProcessPoolExecutor` to get
around the GIL (`config.py`).

The one thing the process does run as a genuine background task is the
**multiplayer watchdog** — `api/multiplayer_ws.sweeper`, started from
`api/app.py`'s `_lifespan` and cancelled on shutdown. It calls
`sweep_once` once a second (`SWEEP_INTERVAL_SECONDS`) to disconnect idle
players, expire lapsed seats and PLR-4 client tokens, and keep a table
moving when nobody is currently able to act — see Part 4.

## One port for the browser

**A browser only ever needs to reach the backend's port.** The frontend is
a separate, plain static-file process (`setup/no_cache_server.py`, default
`http://127.0.0.1:8765`), but the backend reverse-proxies anything outside
`/api`/`/ws` straight through to it (`api/frontend_proxy.py`,
`config.FRONTEND_ORIGIN`). `proxy_to_frontend` is registered **last** in
`api/app.py` (its catch-all `/{path:path}` route would otherwise shadow
every other route if registered earlier) and refuses to proxy anything
already reserved for the API (`_is_reserved_path`: `api/*`, `ws/*`) with a
plain 404, as a second, defensive line against exactly that mistake.

This is a server-to-server HTTP call (`httpx`), not a browser request, so
it is **not subject to CORS** — which is why `_LOCAL_DEV_ORIGIN_REGEX` in
`api/app.py` only ever has to admit `localhost`/`127.0.0.1` origins: the
two-origin-in-one-browser problem the CORS middleware exists for only
arises with `setup/start.py --frontend-only`, not the default path. The
frontend process itself stays loopback-only always; only the backend is
ever opened beyond `127.0.0.1`, and only when explicitly started with
`setup/start.py --host HOST` — see Part 5 for why that's opt-in.

---

# PART 2: THE REST API SURFACE

`backend/mtg_analyzer/api/` is a set of FastAPI `APIRouter`s, each mounted
once in `api/app.py`'s `create_app()`. None of them touch a user/auth
table — there isn't one.

| Router | Responsibility |
| --- | --- |
| `decks.py` | Parse/validate a decklist submitted as raw text (`POST /api/decks`) — the deck-import/analysis tab's non-persisted path. |
| `saved_decks.py` | CRUD on the one shared `DeckDatabase` (save, list, update, delete a `Deck` — author, sleeve, cube flag, favorites all live on this record). |
| `archetypes.py` | Archetype/synergy lookups backing the deck-analysis tab. |
| `cards.py` | Card-cache lookups (`POST /api/cards/resolve` batch name→`Card`, search) — the `CardDatabase`/`LazyCardLoader` front door. |
| `images.py` | Serves cached card art (`ImageCache`) so the browser never calls Scryfall directly. |
| `game.py` | Goldfish and Replay/Puzzle sessions: start, act, rewind, restart, delete, export a replay descriptor — see Part 3. |
| `game_ws.py` | `/ws/game/{game_id}` — a relay that exists but is not wired into any current frontend view; see Part 4. |
| `multiplayer.py` | The lobby-to-session bridge: create/join/configure a table, seat bots, start, act, concede, take back — see Part 4. |
| `multiplayer_ws.py` | `/ws/lobby` — presence plus the live push channel multiplayer actually uses; also owns `sweeper`/`sweep_once`. |
| `solo.py` | Solo-vs-Bots (PLR-14): the same multiplayer engine minus the lobby, one human seat plus 1–3 bot seats, plain REST. |
| `dynamic_analysis.py` | Kicks off/polls simulated-match deck analysis jobs (`services/dynamic_analysis.py`). |
| `import_external.py` | Server-side Archidekt import proxy (`services/archidekt_client.py`) — Moxfield was tried twice and reverted, Cloudflare-blocked. |
| `player_assets.py` | Player-uploaded token art and card-back sleeves, keyed by free-text player name (`services/player_assets.py`). |
| `frontend_proxy.py` | The catch-all described in Part 1; mounted last. |

`GET /api/health` is inlined directly in `create_app()` rather than its own
router — used by the frontend's `checkHealth()` (`frontend/src/js/api.js`)
to test the configured backend address on the Einstellungen tab.

---

# PART 3: THE SESSION MODEL

## `GameSession` wraps one `GameEngine`

`services/game_session.py`'s `GameSession` is the layer between the pure
rules engine (`game/game_engine.py`'s `GameEngine`, `models/game/
game_state.py`'s `GameState`) and the wire. It adds exactly what a
*play-a-real-game-over-HTTP* session needs that the engine itself has no
reason to know about:

- **Undo/rewind.** Every action is preceded by a full `GameState.clone()`
  snapshot pushed onto a bounded history (`MAX_HISTORY = 100`); `rewind(n)`
  restores real cloned state rather than replaying a log, so it can never
  diverge from what actually happened. `take_back` (multiplayer only) is a
  narrower, RULE-free convenience: it undoes back through the caller's own
  most recent `_history` entry — since there is one shared timeline, that
  also discards anything an opponent did afterward — and is legal
  regardless of who currently holds priority, the same exemption
  `concede` gets. See `CLAUDE.md`'s "Take-backs" section for the exact
  `_history`/`move_log` slicing discipline.
- **A wire-safe `view(perspective=...)`.** `GameSession.view()` renders the
  engine's state as plain JSON, redacting any zone the requesting
  `perspective` shouldn't see (RULE 400.2 — an opponent's hand or library
  order never serializes at all when it isn't yours to see) and computing
  `legal_actions` for that seat specifically rather than for whoever is
  active. `observer_view()` is the further-redacted form for a multiplayer
  spectator: nobody's hand.
- **Actions carry an actor.** `apply_action(action, actor_id=...)` — solo
  modes leave `actor_id` implicit (the active/human seat), multiplayer and
  solo-vs-bots always pass it explicitly. The engine's own per-player
  timing checks (RULE 601.3a's active-player gate on casting, RULE
  509.1a's "the attacking player does not declare blockers") already take
  an explicit player argument, so a non-active seat naturally gets exactly
  the instant-speed/response subset of `legal_actions` and nothing more —
  this isn't a separate permission layer bolted on top.

`GameSessionManager` (also in `services/game_session.py`) holds every open
`GameSession` in memory, keyed by a generated session id — the same
in-memory, single-process, not-persisted-across-restarts pattern as the
lobby and the WebSocket connection registries.

## One engine, four front doors

Goldfish, Replay/Puzzle, Solo-vs-Bots and Multiplayer are **the same
`GameEngine`/`GameState`**, reached through `GameSessionManager.
create_goldfish` / `create_replay` / `create_multiplayer` — they differ in
session *configuration*, never in engine code:

| Mode | Built via | What's different |
| --- | --- | --- |
| Goldfisch | `sessions.create_goldfish(...)` (`api/game.py`) | A passive dummy opponent (`_build_dummy_player`) fills the second seat; `interactive_priority` off, so `_run_step` auto-drains the stack exactly as it always has. |
| Replay/Puzzle | `sessions.create_replay(descriptor, loader)` (`api/game.py`) | `mode="replay"`, `require_setup=False`; a family of `edit_*` actions mutate state directly instead of the normal action set; save/load is JSON export/import of a re-resolvable descriptor (`services/replay.py`). |
| Solo gegen Bots | `sessions.create_multiplayer(seats, ...)` (`api/solo.py`), one human seat plus 1–3 bot seats, no `Lobby` involved | `interactive_priority` is on (`mode == MULTIPLAYER`) — real turns and priority — but there is no socket: `_advance_solo_bots` runs the bot(s) synchronously inside the same request and auto-passes the human through any opponent-turn window where passing is its only legal move. |
| Multiplayer | `sessions.create_multiplayer(seats, ...)` (`api/multiplayer.py`), seats resolved from a started `Lobby` game | Same engine config as Solo; reached over `/ws/lobby` pushes instead of being computed inline in one request/response — see Part 4. |

`GameSession.interactive_priority` (set from `mode == MULTIPLAYER` at
construction, mirrored onto `GameEngine.interactive_priority`) is the one
flag that actually changes engine behaviour: off, a step auto-resolves the
stack the moment nothing responds; on, RULE 117 priority is played out for
real turn by turn, and `GameSession._pass_priority` drives `GameEngine.
pass_priority(player)`. See `CLAUDE.md`'s "RULE 117 priority" section for
the exact mechanics (the empty-stack-ends-the-step branch the engine can't
own itself, the "Passen"/"End the turn" button split, the declare-blockers
carve-out).

---

# PART 4: THE MULTIPLAYER LAYER

## Lobby vs. session — two things kept strictly apart

`services/lobby.py` and `services/game_session.py` are deliberately two
separate modules with no shared vocabulary:

- **`Lobby`** (people and tables, **rules-free** — it has never heard of
  Magic) tracks every connected `LobbyPlayer` (presence: `online` /
  `available` / `playing`) and every `LobbyGame` (status: `setup` /
  `running` / `finished`, with `Seat`s holding a deck pick, an accept flag,
  and the purely cosmetic `Seat.banner_color`). A player is identified by
  **name** (`normalize_name` — case/whitespace-insensitive), not a
  server-issued id — see Part 5 for what that trades away and how the
  PLR-4 client token narrows it.
- **`GameSession`** (Part 3) is the one real `GameEngine`, once a table has
  actually started.

`api/multiplayer.py` is **the only bridge** between them: `POST /api/
multiplayer/games/{id}/start` resolves each seat's saved deck exactly the
way `api/game.py`'s `start_goldfish` resolves a goldfish deck (the shared
`expand_entries`/`resolve_seat_deck` helpers, the same Commander-legality
gate), builds the `GameSession` via `sessions.create_multiplayer(seats,
...)`, and hands the resulting session id to `Lobby.start(game_id,
session_id)`. The lobby never imports the engine or the card loader; the
session never imports the lobby.

## Bots are ordinary seats

A seat can be filled by a bot (`Seat.bot_kind`) instead of a human — from
the lobby's point of view a bot is just a `LobbyPlayer` with no socket
(exempt from both watchdogs, host picks its deck, it "accepts" the table
automatically). `services/bots.py`'s `Bot` base class is the load-bearing
part: **a bot plays through exactly the surface a browser has and
nothing else.** It reads `session.view(perspective=<its own id>)` — so
RULE 400.2 redaction means an opponent's hand and every library simply
aren't in its data — and only ever submits an entry from its own
`legal_actions` via `apply_action(action, actor_id=...)`. It never reads
`engine.state` directly. `GoldfishBot` (lands, else pass), `GreedyBot`
(everything, immediately, first legal target) and `ManaMaximizerBot` (a
dynamic-analysis diagnostic bot) are the three concrete policies; every
bot game this project runs doubles as a live test that the redaction
actually holds, because the bot has no other way to know what to do.

`run_bots(session, bots)` is called from two places: `api/multiplayer.py`
after every human action (right after `lobby.start()`, so a bot keeps its
opening hand before the humans see the mulligan screen, and again inside
`_after_move` so a human's move and every bot response to it are one
broadcast, never a flicker of intermediate boards) and once a second from
`api/multiplayer_ws.sweep_once`, which is what drives a table with no
human at it at all. `MAX_BOT_ACTIONS` is a yield point, not an error
budget.

## The redaction contract: `actor_id` + `view(perspective=...)`

Two properties turn a `GameSession` from solo to genuinely shared, both
already covered structurally in Part 3 but worth restating as the
multiplayer-specific guarantee:

- **Every action names its actor.** `POST /api/multiplayer/games/{id}/
  action` takes `player_id` from the request body (`MultiplayerActionRequest`,
  a `MultiplayerPlayerRequest` plus an `action` dict) — never from inside
  the action payload itself — so a client can only ever act *as itself*;
  `_dispatch` inside the engine additionally refuses an action from anyone
  but the current priority holder (not merely omitting it from that seat's
  `legal_actions` — a client could still post one it was never offered),
  with the one documented exception being RULE 509.1a's declare-blockers,
  a turn-based action the *defending* player takes while the attacker
  still holds priority.
- **Every push is redacted per recipient.** `LobbyConnectionManager.
  broadcast_game` (`api/multiplayer_ws.py`) iterates the game's own seats
  and observers and sends **each one their own** `session.
  view(perspective=seat.player_id)` / `session.observer_view()` — never one
  shared payload. This is why the socket sends per-connection rather than
  a single `broadcast()` call: the payloads genuinely differ per player,
  and that asymmetry *is* RULE 400.2 in wire form.

## `/ws/lobby`: presence and the push channel

`api/multiplayer_ws.py`'s `/ws/lobby` is one socket per browser tab,
opened the first time the Multiplayer tab is visited and held for the
whole session — holding it open **is** the presence signal, since this app
has no other liveness mechanism. It carries three kinds of thing:

1. **Presence.** Connecting makes a player `online`; a `{"type":
   "presence", "state": "available"}` client message (sent whenever the
   Multiplayer tab is actually in view) reports `available`; `playing` is
   derived server-side from holding a seat, never client-reported.
2. **Lobby snapshots.** Any change (someone connects, a table forms, a
   seat readies up) triggers `broadcast_lobby` — a fresh
   `lobby.snapshot()` to everyone — so the Setup screen never polls.
3. **Board pushes.** `broadcast_game`, described above — each participant's
   own redacted view, sent whenever a table's state changes.

Frontend: `frontend/src/js/lobbySocket.js`'s `connectLobbySocket` opens it,
auto-reconnects with backoff (`RECONNECT_DELAYS_MS`), re-sends presence and
a `subscribe_game` request on every (re)connect, and pings every 30s
(`PING_INTERVAL_MS`) purely as a liveness signal — a `ping` counts as
activity server-side (`lobby.touch`) exactly like a real game action does,
so a player who is still there but just thinking doesn't get disconnected
by `MTG_MULTIPLAYER_IDLE_TIMEOUT_SECONDS`.

**Reads (state) go over the socket; writes (actions) go over REST.** Every
multiplayer action a player *takes* — `POST /api/multiplayer/games/{id}/
action`, `/concede`, `/takeback`, and every Setup-screen call
(`/deck`, `/banner`, `/bots`, `/options`, `/ready`, `/start`) — is a plain
REST call; the socket only ever pushes the resulting state out, never
carries a player's own move in. That split is why every mutating REST
route in `api/multiplayer.py` both returns its own result to the caller
*and* calls `lobby_connections.broadcast_lobby`/`broadcast_game` before
returning — the REST response is what the caller who has no socket yet (or
whose socket lags) still gets; the broadcast is what reaches everyone else.

## Reconnects, timers, and the watchdog

`api/multiplayer_ws.sweep_once`, run once a second by the app-lifespan
`sweeper` task, is the mechanism behind every multiplayer timer described
in `CLAUDE.md`'s "Presence, reconnects and timers" section: it closes an
idle priority-holder's socket
(`config.MULTIPLAYER_IDLE_TIMEOUT_SECONDS`), drops a seat whose disconnect
grace period lapsed (`MULTIPLAYER_DISCONNECT_GRACE_SECONDS`, conceding for
them if a game is running), forgets an abandoned PLR-4 `client_token` past
`CLIENT_TOKEN_VALIDITY_SECONDS` (purging that name's uploaded sleeves/token
art too if no other still-recognized player shares it), and — every pass,
unconditionally — passes RULE 117 priority for anyone currently
disconnected (`pass_for_absent_players`) and runs any bot whose turn it now
is, which is what keeps a table with nobody currently connected moving (or
lets an all-bot table play itself out).

---

# PART 5: `/ws/game/{game_id}` — the relay that exists but isn't used

`api/game_ws.py` defines a second WebSocket, `/ws/game/{game_id}`,
structurally similar to `/ws/lobby`: a client sends a `player_action`
message, the server runs it through the `GameSession` already registered
under that `game_id` in the same `GameSessionManager` the REST API uses,
and broadcasts the resulting (unredacted — it has no `perspective`
argument) `view` to every connection on that `game_id`. `frontend/src/js/
gameSocket.js` implements a matching client (`connectGameSocket`), but by
its own doc comment "isn't wired into any view yet" — Goldfisch and Replay
both drive their sessions purely over REST (`goldfishView.js`/
`replayView.js` calling straight into `api.js`-style `fetch` wrappers
against `api/game.py`), and Multiplayer/Solo use the `/ws/lobby` +
`api/multiplayer.py`/`api/solo.py` REST surface described in Part 4
instead. Treat `/ws/game/{game_id}` as present-but-dormant infrastructure,
not a channel anything currently depends on, when reasoning about the live
system.

The underlying reason goldfish/replay don't need a socket at all: they're
single-player-perspective by construction (a goldfish dummy opponent never
acts on its own; a replay board has no other client to push to unless it's
a 2-player puzzle, which — like Solo-vs-Bots — computes everything
synchronously inside one request/response instead). A push channel earns
its keep exactly where state must reach *several independent browsers*
without polling, which is Multiplayer's actual shape and Goldfisch/Replay's
is not.

---

# PART 6: SECURITY POSTURE

**This app has no authentication.** There is no login, no password, no
session cookie that grants access to anything. A player is identified by
free-text **name** (`services/lobby.py`'s `normalize_name`) plus, once a
browser has ever saved a Profil name, an unsigned **`client_token`**
cookie (PLR-4 stub, `settings.js`'s `mtg_client_token`, 90-day sliding
validity via `MTG_CLIENT_TOKEN_VALIDITY`): once presented, `Lobby.connect`
resolves that browser by its token rather than by name at all, so two
browsers sharing a display name stay distinct players instead of merging
into one seat. This is explicitly **not real auth** — it's client-trusted,
unsigned, and anyone who knows (or guesses) a token could present it —
just enough for one browser to keep recognizing itself across reloads
without colliding with someone else using the same name. Actually closing
that gap is tracked as its own open item (PLR-9), not solved.

Because there is no accounts system, saved decks, player-uploaded token
art/sleeves, and every running game are **readable and writable by anyone
who can reach the process** — there is no per-player ownership check on a
saved deck, and player assets are keyed by free-text name, not a verified
identity. **This must never become the default posture on an open
network.** `setup/start.py` binds to loopback by default; reaching it from
another machine on the LAN is opt-in via `setup/start.py --host HOST`
(passed straight through as uvicorn's own `--host`), and only the backend
process is ever meant to bind beyond loopback — the frontend static
process stays loopback-only unconditionally, reached only through the
backend's own reverse proxy (Part 1). See `CLAUDE.md`'s "Run & test"
section for the exact flags and the macOS Local-Network-permission caveat
on binding beyond loopback.

Validation is still fully server-side, in the one sense that *is* true of
this project: every action a client sends is checked against `GameEngine.
legal_actions`/`_dispatch` before it changes any state, and hidden zones
are redacted server-side per Part 4 — a client cannot see an opponent's
hand by inspecting network traffic, and cannot make an illegal move stick
by sending one directly. What's absent is any notion of *who is allowed to
be at this table at all* — that's a LAN-trust model, not a security
boundary, and the app is built and documented accordingly.

---

# PART 7: WHAT GOT DROPPED FROM THE OLD PLAN

The version of this document being replaced described a "Before: CLI
Monolith / After: Server-Client Web" transition aimed at a browser client
built on "React/Vue/etc", a server with a "Matchmaking" service, a "User
DB" (`Users` table, `username`/`password_hash`), an "LLM Integration"
service, and a generic PostgreSQL/Redis/CDN production deployment sketch.
None of that describes this project:

- **No frontend framework.** `frontend/src/js/` is buildless ES modules —
  `render*(container)` functions that set `innerHTML` and wire DOM
  listeners directly (`CLAUDE.md`, `05_GAME_UI_AND_CARD_INTERACTION.md`).
  There is no React/Vue, no JSX, no `npm start`/webpack dev server, no
  build step at all; editing a file under `frontend/src/**` and reloading
  the browser is the entire workflow.
- **No matchmaking.** A table is opened and joined explicitly through the
  lobby (Part 4) — there is no queue, no "find opponent" service, and no
  code anywhere resembling one.
- **No user accounts.** Nothing in this codebase has a password hash or a
  `Users` table; identity is the free-text name / `client_token` pair
  described in Part 6, full stop.
- **No LLM integration anywhere in the running app.** Deck analysis
  (`services/archetype_analysis.py`, `services/dynamic_analysis.py`, the
  Analyze tab) is heuristic/simulation-based — real bots playing real
  simulated games against a deck, not a model call. There is no Claude/
  OpenAI/etc. API client in this codebase.
- **No PostgreSQL, no Redis, no CDN, no Docker deployment.** Persistent
  data (saved decks, player assets) is SQLite under `MTG_DATA_DIR`; the
  disposable card cache is SQLite under `MTG_CACHE_DIR` (`config.py`).
  There is exactly one deployable unit: the single uvicorn process
  described in Part 1.

For what actually replaced the old plan's phase framing (the engine was
N-player throughout rather than bolted on later, bots are ordinary
players rather than a "strategy engine" layer, …), see
[`03_ARCHITECTURE_AND_BUILDPLAN.md`](03_ARCHITECTURE_AND_BUILDPLAN.md)'s
own Part 5. For what's actually still open on the server/client surface
covered by this document, use
[`../implementation-state/BACKLOG.md`](../implementation-state/BACKLOG.md)
rather than trusting anything that looks like a phase checklist — none
exists any more.
