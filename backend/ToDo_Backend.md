# Backend TODO

Open backend items. Completed work has moved to
[Done_Backend.md](Done_Backend.md) (section headers there mirror these).
See [../IMPLEMENTATION_STATUS.md](../IMPLEMENTATION_STATUS.md) and
`../docs/IMPLEMENTATION_GUIDE.md` for the phase plan this follows.

## Mana cost model (Backlog)

- [ ] Hybrid/Phyrexian nuance for *stale* cached rows: `ManaCost.from_card`
      reconstructs a plain cost from the flat pip tally for cards cached
      before `mana_cost_string` existed, which can't recover a `{W/U}` /
      `{W/P}` distinction (never stored in the flat dict). A cache refresh
      restores full fidelity; a targeted re-fetch/backfill of just those
      rows would avoid needing a full wipe. See Done "Mana cost model".

## Configuration (Backlog)

- [ ] On-disk paths (`CACHE_ROOT`/`DEFAULT_DB_PATH` in
      `card_database.py`, `DATA_ROOT`/`DEFAULT_DECKS_DB_PATH` in
      `deck_database.py`) are hard-coded module constants with no
      override hook. Came up concretely: verifying a change against a
      real running server means pointing it at these same fixed,
      repo-relative paths as any dev instance you might have running —
      there's no way to redirect a one-off/test server elsewhere, so
      the two can collide (a cleanup between test runs can wipe a dev
      server's actual cache/saved decks out from under it). With schema
      versioning now in place a stray script pointed at `DEFAULT_DB_PATH`
      *clears* rather than just reads it — extra reason to make paths
      overridable. Pull these — and other scattered constants, e.g.
      `scryfall_client.py`'s `_USER_AGENT`/`_MIN_REQUEST_INTERVAL_SECONDS`,
      `image_cache.py`'s `_USER_AGENT` — into one config module (e.g.
      `mtg_analyzer/config.py`), reading overrides from environment
      variables (e.g. `MTG_CACHE_DIR`, `MTG_DATA_DIR`) with the current
      hard-coded values as defaults. `api/dependencies.py`'s singletons
      would read from there instead of importing the path constants.

## Rules Engine (Phase 2) — remaining

- [ ] Oracle-text → effect *parser* (docs/07 PART 5): spells still carry
      no auto-derived effects, so an instant/sorcery resolves as a no-op
      unless a fixture attaches effects via the `spell_effects`/ability
      hooks. A growing set of one-shot effects + the registry exist —
      damage/draw/discard/destroy/gain_life/counter/search (see Done
      "Rules Engine") — but nothing turns a card's `oracle_text` into
      them yet; that parser is the gap. Search is basic type/subtype
      matching only; richer criteria (mana value, colour, "you may")
      belong here too.
- [ ] Combat blocking + creature-vs-creature damage: combat is still
      unblocked-attackers-hit-a-player only (docs/02 R2.7). Declaring
      blockers and assigning combat damage between creatures is the next
      combat step (interactive, so opponent-side).
- [ ] Replacement-effect ordering by the affected player (RULE 616.1) —
      currently deterministic discovery order; needs a player prompt once
      interactive play does.
- [ ] Trigger ordering *within* a controller (RULE 603.3b) — currently
      APNAP by controller only, no intra-controller choic
## Game Engine (Phase 3) — remaining

- [~] Multiplayer game session + priority system (UC4): **stubbed** —
      `GameSessionManager.create_multiplayer` raises
      `MultiplayerNotImplementedError` and `POST /api/game/multiplayer`
      returns 501, so the mode/route exist end-to-end (the frontend
      shows a "coming soon" panel) but the interactive priority loop is
      not built. The pieces exist (multiple players, turn rotation,
      per-player priority pointer, action validation); priority is
      currently auto-passed with no response window, so two humans can't
      yet hold priority and respond to each other's spells. Needs an
      interactive priority loop (offer priority → collect an action or a
      pass → resolve top of stack on all-pass).
- [ ] Wire the `WebSocket /ws/game/{game_id}` handler (`api/game_ws.py`)
      into a server-held session: it's still the transport-only relay,
      not feeding actions into `GameEngine`. Solo play uses the REST
      session API (fine for one player); the WebSocket becomes necessary
      for multiplayer (pushing an opponent's moves). Swap its
      `_broadcast_action` stand-in for "run the action through the
      session/engine, broadcast `GameState.to_dict()`".

## LLM Deck Analysis (UC2)

- [ ] `POST /api/decks/{id}/analyze`: Claude API integration, prompt
      templates, structured output parsing, caching (docs/02 UC2,
      docs/04 Phase 6). `Deck.analysis_id` is already reserved to link a
      saved deck to whatever this produces — no `Analysis` model/table
      exists yet, design that alongside this endpoint rather than
      assuming the reserved field's shape is final.

## Auth & persistence

- [ ] User accounts, login/signup (docs/04 PART 4 REST endpoints).
- [ ] No user accounts yet, so saved decks aren't scoped to an owner —
      anyone hitting the API sees every saved deck. Revisit once auth
      exists.
- [ ] Game history / session persistence.

## Bot AI (UC5)

- [ ] Greedy bot strategy (docs/02 UC5) — a start exists in
      `GameEngine.run_goldfish_turn`/`auto_play_step` (play a land, tap
      out, cast cheapest-first, swing); a real bot would weigh lines.

## Import — follow-up from the frontend

- [ ] Server-side Moxfield import proxy
      (`GET /api/import/moxfield/{deckId}`), tried client-side and
      reverted (see `../frontend/ToDo_Frontend.md` "Import — follow-ups"):
      Moxfield's Cloudflare protection returned HTTP 403 on every
      plain request tried by hand, including from a browser origin.
      A server-side fetch removes the browser-CORS obstacle but still
      isn't guaranteed to get past bot protection — may need
      browser-like request headers or a headless-browser fallback.
