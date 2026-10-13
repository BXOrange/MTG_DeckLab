# CLAUDE.md

Orientation only, loaded in full every session. Rules for editing this file are at the bottom.

## What this is

MTG deck analyzer with a **rules-accurate game engine** validated server-side against the Comprehensive Rules (`RULE <n>` in code). Headline feature: **Goldfisch** mode (play a saved deck against the real engine).

- **`backend/`**: Python/FastAPI. Card model, rules engine, oracle-effect IR, game-session API.
- **`frontend/`**: static, buildless ES modules, German UI (MTG keywords stay English). Tabs: deck import/analysis, saved decks, Goldfisch, "Solo gegen Bots" (`soloView.js`, `api/solo.py`), Replay (board editor/puzzle: `GameSession` with `mode="replay"`, `edit_*` actions, JSON descriptor in `services/replay.py`), card cache, Multiplayer (Setup = lobby, Board = shared game), Engine-Status. Header: **Profil** (who you are / how you play: name, defaults, uploads, favorites) vs. **Einstellungen** (reaching/configuring the server, LLM).

## Run & test

```bash
./start.sh                                            # app on http://localhost:8765 (--backend-tests adds pytest)
python backend/scripts/select_tests.py --run          # smallest test slice for the git diff (skill: run-tests)
python backend/scripts/run_tests.py [pytest args]     # finds the venv itself; or: cd backend && python -m pytest -q
```

- Keep the backend suite green after any backend change. Plain `pytest -q` **skips the full-cache tier**: run `--full-cache` before closing engine/parser work. **Never point `MTG_CACHE_DIR` at the production cache.**
- No JS build step. Verify non-trivial frontend changes in a real browser (Playwright in `backend/venv`).
- Startup, network, config, workers, logging, Scryfall policy: [OPERATIONS.md](docs/Reference/OPERATIONS.md). Starting must stay offline-safe; LAN access stays opt-in (`--host`), the app has no auth.

## Architecture

```text
Card (models/cards/card.py)  →  GameObject (models/game/game_object.py)   printed vs. in-zone state
GameState (models/game/game_state.py)       zones, stack, players, turn, event bus
RulesEngine / GameEngine (game/)       rules primitives / turn loop, actions, combat; each a composition of mixins in game/rules/ and game/engine/
GameSession (services/game_session.py) snapshots/undo, wire view      API (api/) ── JSON ──▶ frontend/src/js/
```

Oracle text → behaviour: `parser/oracle/` (`normalize` → `segmenter` → `catalogue/handlers` → `gate.parse_oracle`: `AbilitySpec` IR plus a fail-closed `MODELED`/`UNMODELED` verdict) → binder (`game/binding/core.py`) → live effects via `EffectRegistry` (`game/effects/registry.py`). Specs come from hand-authored `game/card_catalogue/<letter>/<slug>.py` (one file per card, registered through `game/card_registry/`) or the parser fallback for fully `MODELED` cards. See [authoring guide](docs/Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md).

## Invariants

- **Security boundary**: nothing derived from card text becomes code. Effects are a whitelisted `type` plus clamped params (`spec.py`); only the binder turns specs into behaviour; `parser/oracle/` has no `game/` imports.
- **Import boundary**: `models/` must not import `game/` at module load (use function-scoped imports).
- **Derived characteristics** (`power`, `toughness`, `is_creature`, `granted_keywords`) come from `continuous.recompute` (RULE 613); call `engine.recompute_continuous_effects()` if you read them outside SBA passes or the session view.
- **`turn_number`** is rules-correct (every player's turn counts, RULE 500.1) and what the engine uses; **`round_number`** is display only. Do not merge them.
- **Hidden information**: `view(perspective=...)` redacts zones server-side (RULE 400.2). **Bots** use only their own view and `legal_actions`, never `engine.state` ([BOTS.md](docs/Reference/BOTS.md)).
- **Priority** (RULE 117) is opt-in per session, on for multiplayer; only the priority holder may act, enforced in `_dispatch` ([MULTIPLAYER.md](docs/Reference/MULTIPLAYER.md)).
- The RULE 702 keyword catalogue in the parser is *recognition only*, not proof of engine behaviour. **Stickers (RULE 123) are a permanent non-goal** (`NEVER_SUPPORTED`).
- **Code style**: comment rules-relevant code with `RULE <n>` (text via `docs/Reference/rules_wiki/`); match surrounding comment density; **no magic numbers** (named constant with a why-comment, e.g. `INFINITE_MANA_THRESHOLD`); frontend views are `render*(container)` functions, escape card/user text with `escapeHtml`/`escapeAttr`, prefs in cookies (`cookies.js`).
- **Commits** only when asked; branch first if on `main`; end with the attribution line from the session instructions.

## Docs and work tracking

All under `docs/implementation-state/` unless noted; [docs/README.md](docs/README.md) maps the rest, `user-docs/` is end-user help.

- `BACKLOG.md`: open work only, as tickets (`ENG PAR MEC PLR VIS DB ANA BUG`). `DEFERRED.md`: parked work and permanent non-goals.
- `Done_Backend.md` / `Done_Frontend.md`: what shipped and why, organized by subsystem. Closing a ticket = delete it from the backlog and extend the matching entry there.
- `workingOn.md`: resumable state of the ticket in progress; **read it first**, update at every milestone, delete the block on close. A partly done ticket keeps only a terse backlog point; its residue lives in its block.
- `PARSER_LONG_TAIL.md` (parser strategy), `singletons.md` (single-card gaps for hand-authoring), `10_COMPLETION_ROADMAP.md`.
- Never mark work done from a plan or stale ticket text; code and tests are authoritative. Before writing "needs a new primitive" in a ticket, grep for an existing one; when a primitive lands, sweep the backlog for tickets it closes; a twice-deferred item gets hand-authored or promoted, never silently deferred again.
- Use the skills in `.claude/skills/` (`extend-parser`, `game-engine`, `hand-author-card`, `understand-card`, `inspect-db`, `singleton-sweeper`, `ticket-management`, `run-tests`) instead of improvising. `.claude/agents/`: `ticket-grinder` (run as main agent: `claude --agent ticket-grinder`) delegates tickets to `ticket-worker`.
- Keep the Engine-Status tab (`frontend/src/js/implementationStatusView.js`) in sync when engine coverage changes. Re-measure coverage with `scripts/coverage_report.py`; never quote a number from memory.
- Bug reports (`bug-reports/`, Git-ignored, contain hidden zones): read [BUG_REPORTS.md](docs/Reference/BUG_REPORTS.md) before analyzing; never commit or delete them.

## Where to look first

Full task → file table: [CODE_MAP.md](docs/Reference/CODE_MAP.md). Subsystem notes: [MULTIPLAYER.md](docs/Reference/MULTIPLAYER.md), [BOTS.md](docs/Reference/BOTS.md), [ENGINE_MECHANICS_NOTES.md](docs/Reference/ENGINE_MECHANICS_NOTES.md), [PLAYER_PROFILE.md](docs/Reference/PLAYER_PROFILE.md), [MANA_ADVICE.md](docs/Reference/MANA_ADVICE.md), [COMMANDER_SPELLBOOK.md](docs/Reference/COMMANDER_SPELLBOOK.md), [SMART_BOT.md](docs/Reference/SMART_BOT.md), [LLM_INTEGRATION.md](docs/Reference/LLM_INTEGRATION.md).

| Task | Start in |
| --- | --- |
| Combat / keywords | `game/combat.py` |
| Layers, P/T, anthems | `game/continuous.py` |
| State predicates ("as long as…", intervening-if) | `game/static_conditions.py`, `game/effect_conditions.py` |
| Effects, triggers, composition | `game/effects/` (`registry.py`, `composition.py`), `game/binding/core.py` |
| Player choices | `game/continuations.py` (`open_choice`/`resolve_choice`) |
| Targeting | `game/targeting.py` |
| Costs / activation | `game/costs.py`, `game/engine/activation_mixin.py` |
| Hand-authored card | `game/card_catalogue/`, `hand-author-card` skill |
| Parser | `parser/oracle/`, `extend-parser` skill |
| Paths, env vars | `mtg_analyzer/config.py` |
| Goldfish / Solo / Multiplayer / Replay UI | `goldfishView.js`, `soloView.js`, `multiplayerView.js`, `replayView.js`, shared `gameBoardView.js` |
| Refresh Oracle pool / ban lists | `backend/scripts/update_card_pool.py`, `update_ban_lists.py` |

## Editing this file

- **Anti-proliferation**: keep it orientation only. Add a line only if an agent working *anywhere* needs it every time; otherwise put it in `docs/Reference/` behind a one-line pointer. Grep before creating a doc; extend the existing one. No duplicated facts, no new section for one feature.
- **Anti-worklog**: no "what shipped" narrative, card names, ticket IDs or per-batch numbers here. Those belong in `Done_*.md`, the card's code and tests, or `BACKLOG.md`/`workingOn.md`. Closing a ticket does not touch this file unless a convention or invariant changed.
