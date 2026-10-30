# Bots (UC5)

Architecture and driver rules for bot seats. Policy detail lives elsewhere:
[SMART_BOT.md](SMART_BOT.md) (Smart Bot knowledge, combos, limits) and
[LLM_INTEGRATION.md](LLM_INTEGRATION.md) (AI Bot, rejection feedback, call budgets).

## Rules

- A bot is a player, not a mode. It plays through the **client surface only**: it
  reads `session.view(perspective=<own id>)` (RULE 400.2 redaction, so no opponent
  hand or library) and submits only entries of its own `legal_actions` via
  `apply_action(action, actor_id=...)`. **Never read `engine.state` from a bot.**
- The shared dispatcher canonicalizes policy choice IDs against the current
  offered actions. Missing or invented answers fall back to an offered base
  decision; asynchronous waiting, free-text choices and valid Proliferate
  selections retain their explicit contracts.
- `Bot.decide` fixes the order: pending choice → mulligan → RULE 509.1a
  declare-blockers (the defender acts while the attacker holds priority) →
  `play()` only if it holds priority. Subclasses override policy only.
- Policies (`services/bot_policies/`, one class per file; `services/bots.py`
  reexports them and owns the registry and driver): `GoldfishBot`, `GreedyBot`,
  `ManaMaximizerBot`, `SmartBot`, `SmartBot2`, `AIBot`, `McpBot` (seat played by an external
  MCP client, see [MCP.md](MCP.md); falls back to Smart Bot while the client is silent). `prepare(session)` attaches policy
  context before each fresh view.
- `SmartBot2` uses a separate mechanic/style profile, action utility and
  bounded combat/timing/choice planning; see [SMART_BOT.md](SMART_BOT.md).
  Its diagnostic trace is visible only to its own perspective.
- Smart1/Smart2 Proliferate choices and the human board's editable defaults
  share public marginal counter utility (`smart_bot2/counters.py`). Neither
  the recommendation nor an individual staged pick applies counters; the
  selection finishes before placement. Unknown counter uses remain neutral.
- `SmartBot` is the default in Solo, Multiplayer and dynamic analysis (also when
  an API request omits the kind); an explicitly chosen policy is preserved.
- All policies accept offered opening-hand permissions (RULE 103.6) and complete
  their follow-up choices; they keep position-scoped rejection feedback across
  rebuilds and try another selection before passing.
- "Pass this turn" (VIS-12): `Bot.decide` posts `set_yield` on an opponent's turn
  when the policy's `can_pass_turn` says every empty-stack window would be a pass.
  The server still gives it priority for opponent stack items.

## Driver and lobby

- Bots have no loop of their own: `run_bots(session, bots)` runs after each human
  action, right after `lobby.start()`, and once a second from the sweeper (which
  drives a table with no humans). It runs *before* the broadcast, so a human's
  move and the bot answers are one push. `MAX_BOT_ACTIONS` is a yield point, not
  an error budget.
- AI requests run in bounded background workers and preserve priority while
  pending; solo view polling and the multiplayer watchdog collect results.
- In the lobby a bot is an ordinary `LobbyPlayer`/`Seat` (+`Seat.bot_kind`); the
  engine never learns bots exist. A bot seat with a deck counts as ready, bots
  are kept out of presence sweeps, the host acts for them
  (`add_bot`/`remove_bot`/`set_deck(seat_id=…)`), and a table whose last human
  leaves is dropped.
- Dynamic analysis uses 1–3 passive opponents (`opponentCount`, default 1) with
  hidden hands/libraries and no turns of their own.
