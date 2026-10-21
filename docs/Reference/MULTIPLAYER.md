# Multiplayer and Solo

Architecture and invariants for two- to four-player tables (`MIN_SEATS`/`MAX_SEATS`
in `services/lobby.py`; four is a UI-readability limit, the engine is N-player) and
Solo vs. bots. Files: `services/lobby.py`, `api/multiplayer.py`,
`api/multiplayer_ws.py`, `api/solo.py`, `services/game_session.py`,
`frontend/src/js/multiplayerView.js`, `lobbySocket.js`, `soloView.js`,
`gameBoardView.js` (driven through an injected transport).

## Layers

- `services/lobby.py` is **rules-free** (people and tables: presence state,
  seats, deck picks, mulligan style, per-seat accept). `services/game_session.py`
  is the game (one `GameEngine`). `api/multiplayer.py` is the only bridge: it
  resolves each seat's deck like `api/game.py` (same `expand_entries`, same
  legality gate) and hands `Lobby.start()` a session id.
- A session is *shared* because: actions carry an actor
  (`apply_action(action, actor_id=...)`); `view(perspective=...)` redacts hidden
  zones server-side (RULE 400.2; `observer_view()` hides everyone's); `/ws/lobby`
  is presence and push channel and sends each participant their own view; and
  priority is played out for real.
- `Seat.banner_color` is cosmetic, lives in the lobby (Setup shows it before a
  game), reaches the board via `seatStatus`; palette derived in `bannerColors.js`.
- Table feed (VIS-4, `services/table_feed.py`): preset emotes plus engine-event
  announcements, no priority passes; `view()` carries the latest 200 entries;
  emotes never advance gameplay or drive bots.
- Concession and committed player losses apply RULE 800.4a immediately: owned
  objects leave, control effects end, departed-controller abilities/copies
  cease, and remaining controlled objects are exiled. Priority passes to the
  next living seat. Resolved control effects retain their original controller
  and duration separately from ownership; Aura control is recomputed after
  removal. Session history holds independent pre-concession snapshots for
  review/rewind, including terminal games; the live board is cleaned immediately.
  `GameState.pending_leave_ids` remains empty for snapshot compatibility.

## Priority (RULE 117)

- Opt-in per session (`GameSession.interactive_priority`, on only for
  `MULTIPLAYER`; engine flag `GameEngine.interactive_priority`). Off, `_run_step`
  auto-drains the stack and every solo path is untouched.
- On, a step only puts triggers on the stack and the active player holds priority.
  `GameSession._pass_priority` drives `GameEngine.pass_priority(player)` (APNAP
  round, resolve the top once everyone passed); the session itself ends the step
  when all pass on an empty stack (RULE 117.4, `_advance_to_priority_window`).
- **No "advance the turn" action in a shared game**: `advance_step` is refused,
  the primary button is "Passen".
- Only the priority holder may act, enforced in `_dispatch` (not just filtered from
  `legal_actions`) — except RULE 509.1a declare-blockers, which the defender takes
  while the attacker holds priority; "no blocks" is an empty `assignments` list.

## Solo bot updates

One action per response: human POSTs return before bots answer; each following GET
applies at most one bot action. The board polls once per second while
`bot_action_pending`. Human priority is never passed server-side.

## Take-backs

`GameSession.take_back`: table-configured (`LobbyGame.takebacks_per_player`),
RULE-free undo, legal regardless of priority, scoped to the caller's own last
`_history` entry (which also discards later opponent actions). Not `rewind`
(solo-only). Slice `_history` and `move_log` by tail-relative depth, never an
absolute index: `_history` drops old entries past `MAX_HISTORY`, `move_log` does
not.

## Presence, reconnects, timers

- Players are identified by normalized **name** (survives reload); a second
  connection with the same name takes over the seat (`replaced`). A browser that
  has saved a Profil name also has a random `client_token`
  (`settings.js` `mtg_client_token`, 90-day sliding); `Lobby.connect` resolves by
  token first, so two browsers with one display name stay distinct. Not auth (PLR-9).
  Tokens unused for `MTG_CLIENT_TOKEN_VALIDITY` are forgotten along with that
  name's `player_assets.py` uploads unless another player shares the name.
- A lost socket does not forfeit: a grace period
  (`MTG_MULTIPLAYER_DISCONNECT_GRACE`, 90s) with `pass_for_absent_players`, then
  concede. A priority holder silent past `MTG_MULTIPLAYER_IDLE_TIMEOUT` (120s) has
  the socket closed. Both swept once a second by `api/multiplayer_ws.sweep_once`.
- Client countdown (`gameBoardView.js` `autoPassArmed`/`railTimerHtml`,
  `reactTimerSuppressedHere()`) runs when this client holds priority on another
  player's turn, or with something on the stack, or in passive upkeep/draw/end
  steps; suppressed in your own main phases and combat. Auto-passes at zero; any
  board interaction cancels it. Length is a server setting:
  `config.MULTIPLAYER_SPELL_TIMER_SECONDS` (20s, 0 = off), per-table override
  `LobbyGame.spell_timer_seconds` (`view()["priority"]["timer_seconds"]`).
- **Yields (VIS-12)** live on the server: `set_yield` arms a one-shot yield
  (`GameSession._yields`, `view()["priority"]["yields"]`); `_auto_pass_followups`
  passes the seat's windows for the rest of an opponent's turn (`turn`) or, on
  your turn, up to the end step (`end_step`). Never passes with another player's
  item on the stack or a `pending_choice`; cancelled by any real action or
  take-back. `set_stops` keeps standing stops per step. Both opt-in per seat.
  Keys: Space = pass, Enter = pass this turn, E = skip to end step.
