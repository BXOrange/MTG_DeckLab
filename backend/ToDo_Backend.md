# Backend TODO

Open backend items. Completed work has moved to
[Done_Backend.md](Done_Backend.md) (section headers there mirror these).
See [../IMPLEMENTATION_STATUS.md](../IMPLEMENTATION_STATUS.md) and
`../docs/IMPLEMENTATION_GUIDE.md` for the phase plan this follows.

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
      belong here too. **Design agreed** in
      [../docs/09_ORACLE_EFFECT_PARSER.md](../docs/09_ORACLE_EFFECT_PARSER.md):
      two-stage compiler (front-end parses `oracle_text` → `AbilitySpec`
      IR; binder maps IR → `GameEffect` via the registry), a
      repo-committed handler catalogue (regex + builder) vs. the volatile
      card cache, parse-on-load / bind-per-game linking, and a fail-closed
      full-span coverage gate (`MODELED`/`UNMODELED`, unclaimed clauses →
      processing list → analyzer). Start at Phase 0 (IR + binder + one
      hand-wired card, no NLP).
      **Progress:** the Phase 1 *keyword catalogue* is in —
      `parser/oracle/catalogue/keywords.py` maps the full RULE 702 vocabulary
      (194 keywords) to its `AbilitySpec` shape (flag / number / cost /
      number+cost / quality) with a regex that extracts each parametric
      keyword's one parameter; `parse_keywords(card)` anchors on Scryfall's
      `keywords` array and pulls the parameter out of oracle text, emitting
      validated `keyword` specs (`AbilitySpec.keyword = {name, n?/cost?/
      quality?}`). **Flag keywords now bind**: `specs_for` folds the parsed
      keyword specs in, and the binder docks parameterless ones onto
      `GameObject.intrinsic_keywords`, which `game/combat.py` unions into its
      recognition. Still open: effect-clause handlers + coverage gate; and
      binding *parametric* keywords (kicker cost, annihilator N, protection
      quality — parsed and carried, but they need dedicated behaviour:
      alternative costs, combat maths, etc.).
- [~] Combat blocking + creature-vs-creature damage: **engine done** —
      `GameEngine.declare_blockers`/`can_block` and a rewritten
      `_step_combat_damage` handle blocked/unblocked attackers, gang blocks
      (lethal-first damage spread), and blockers striking back, with the
      SBA destroying lethal-damaged creatures. Attackers now declare a
      defender (player or opponent planeswalker, RULE 508.1a) and the solo
      goldfish gains a passive dummy so swings connect. Combat & evasion
      **keywords are done** (`game/combat.py` recognizes them off Scryfall
      `keywords` + oracle text; the engine honours them): flying/reach,
      menace, defender, haste, vigilance, first strike, double strike (two
      damage steps), deathtouch, trample, lifelink, indestructible, and
      protection-from (colour/creatures/everything). Keywords surface on the
      board as badges. Remaining: an *interactive* blocker-declaration UI
      (opponent-side, needs the multiplayer priority loop).
- [~] Static abilities / continuous-effects layer system (RULE 613):
      **engine done** — `game/continuous.py` re-derives every battlefield
      permanent's characteristics in layer order (4 type-changing, 6
      ability-adding, 7b/7c/7d power/toughness), stamping derived P/T, added
      types and granted keywords plus a per-object layer *trace* onto each
      object; recomputed on every SBA pass and before the view. `StaticAbility`
      + registry (`anthem`/`pt_set`/`grant_keyword`/`type_change`/
      `cost_reduction`) bind from `static` specs. Granted keywords flow into
      combat; cost reductions/increases apply at cast time (RULE 601.2f). The
      goldfish UI has an optional, default-hidden layer/static panel. Remaining:
      layers 1–3 (copy/control/text), 5 (colour), 7a CDAs, 7e P/T switch, and
      true dependency/timestamp ordering within a layer (currently registration
      order).
- [ ] Replacement-effect ordering by the affected player (RULE 616.1) —
      currently deterministic discovery order; needs a player prompt once
      interactive play does.
- [ ] Trigger ordering *within* a controller (RULE 603.3b) — currently
      APNAP by controller only, no intra-controller choice

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
