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
  deck import/analysis, saved decks, the goldfish board, the card cache, and an
  **"Engine-Status"** tab documenting engine coverage. UI language is **German**;
  MTG keyword names stay English ("Flying", "Trample").

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

## Architecture & data flow

```
Card (models/card.py)            immutable printed characteristics
  └─ GameObject (models/game_object.py)   one instance in a zone, mutable state
GameState (models/game_state.py)  battlefield/stack/players/turn + event bus
RulesEngine (game/rules_engine.py) rules primitives: cast, damage, draw, SBAs…
GameEngine  (game/game_engine.py)  turn/phase loop, actions, legal_actions, combat
GameSession (services/game_session.py) wraps an engine: snapshots/undo, wire view
API (api/game.py)  ── JSON ──▶  frontend (src/js/goldfishView.js)
```

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
  + oracle text) and the rules they impose (blocking legality, damage steps).
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
the engine gains/loses coverage. In short, **implemented**: full turn/stack/SBA
loop; London mulligan; targeting; mana (generic/color/colorless/hybrid/mono-
hybrid/phyrexian/{X}); all common **combat keywords** (flying, reach, first/
double strike, deathtouch, trample, vigilance, lifelink, menace, defender,
haste, indestructible, protection-from, **landwalk**); **static abilities** via
the layer system (layers 2 control / 4 type / 5 colour / 6 abilities / 7a CDA /
7b–d P/T / 7e switch, **timestamp-ordered within a layer**, + cost adjustment);
**activated abilities** with full cost parsing incl. **loyalty `[±N]` costs**;
**triggered abilities** (event-based) + replacement effects (bound via
`ReplacementRegistry`, e.g. `prevent_damage`); **interactive trigger ordering**
(RULE 603.3b, opt-in `state.interactive_ordering`); one-shot effects
(damage/draw/discard/destroy/counter/search/gain_life/mill/exile/tap/
+1+1-counters/create-token/**copy_permanent**/cascade/discover/…); **tokens**
with the RULE 704.5d cease-to-exist lifecycle (`GameObject.is_token`,
`RulesEngine.create_token`); **planeswalkers** (loyalty abilities at
sorcery-speed with a once-per-turn gate, damage removes loyalty, 0-loyalty SBA);
commander damage plus **commander tax** (903.8); counters; **basic card
structures** (DFC
`GameObject.transform`, token copies, Saga lore counters + final-chapter
sacrifice); a basic **interactive priority primitive** (`pass_priority(player)`,
RULE 117). The **RULE 702 keyword catalogue**
(`parser/oracle/catalogue/keywords.py`) parses all 194 keywords off a card into
`keyword` `AbilitySpec`s (flag/number/cost/number+cost/quality shapes, each
parametric one with its extractor regex); **flag keywords bind** — the binder
docks them onto `GameObject.intrinsic_keywords`, which combat honours. The
**oracle-effect front-end** (docs/09 Phase 1, `parser/oracle/`) turns oracle
text into `AbilitySpec`s for the effect families (damage/draw/discard/destroy/
gain_life/counter/mill/exile/tap/+1+1-counters/create-token) as spell_effects,
ETB/dies/attacks/blocks triggers, **`<cost>: <effect>` activated abilities**,
and **`static` anthem/lord clauses** ("creatures you control get +N/+N", tribal
"Other Goblins …", token anthems, colour-scoped/global "Black creatures …",
compound "get +N/+N and have [kw]" via `catalogue/static_handlers.py` +
subtype/tokens/color/exclude_self selectors in
`continuous.affected_objects`) — all with a fail-closed coverage gate, so plain
instants/sorceries/ETB-triggers/activated/static abilities resolve with no
catalogue entry. `processing_list.py` reports cache-wide coverage + a ranked
build order for the next handlers. **Not yet**: richer effect families
(pump/regenerate/scry/modes — each needs a one-shot effect first); oracle-text
*recognition* of replacement clauses (the binder is ready — a front-end
target/duration grammar is not); *behaviour* for the remaining parametric
keywords (kicker/escape alt-costs, annihilator/afflict combat maths — the
parameter binds onto `parametric_keywords` but nothing consumes it yet);
replacement/prevention **ordering** by the affected player (RULE 616.1 — trigger
ordering 603.3b *is* interactive); wiring the interactive priority primitive
into the **multiplayer session/WebSocket** (`create_multiplayer` still stubbed);
layers 1 (copy-of)/3 (text-change) + full dependency ordering (613.8);
Aura/Equipment attachment resolution; and the deeper card-type structures
(MDFC back-face cast, Adventure/Split casting, Saga/Class/Leveler *chapter
abilities*, battles/dungeons — the basic Saga-lore/DFC-transform/token-copy
scaffolding is in).

Living backlogs: `backend/ToDo_Backend.md` (open) and `backend/Done_Backend.md`
(shipped). The plan to finish is `docs/10_COMPLETION_ROADMAP.md` (dependency-
ordered milestones). Design docs: `docs/01`–`10` + `docs/IMPLEMENTATION_GUIDE.md`
(the original Weeks 1–4 status roadmap is archived at
`docs/history/IMPLEMENTATION_STATUS.md`).

## Conventions & gotchas

- **RULE references**: comment rules-relevant code with the CR number
  (`RULE 613.7`). Match the surrounding comment density and style. To read the
  actual rule text, use the wiki in `Reference/rules_wiki/` — it maps every rule
  number and glossary term to its line in the CR source (too large to load whole);
  regenerate with `build_wiki.py` after a rules update.
- **Model → game import boundary**: `models/` must not import `game/` at module
  load. Where a model needs engine logic (e.g. `GameObject.to_dict` showing
  keywords), use a **function-scoped import** and keep the `game/` side pure of
  runtime model imports (`combat.py`, `continuous.py` only import models under
  `TYPE_CHECKING`).
- **Derived characteristics**: `GameObject.power/toughness/is_creature/
  granted_keywords` read layer-engine output stamped by `continuous.recompute`,
  falling back to printed+counters when no pass has run. Recompute runs on every
  SBA pass and before the session view — call `engine.recompute_continuous_effects()`
  if you read derived state outside those points.
- **Security**: nothing derived from card text becomes code. Effects are a
  whitelisted `type` string + clamped params (`spec.py`); the binder is the only
  thing that turns specs into behaviour.
- **Frontend**: no framework. Views are `render*(container)` functions setting
  `innerHTML` and wiring listeners; escape user/card text with `escapeHtml` /
  `escapeAttr`. Client-only prefs persist via cookies (`cookies.js`).
- **Commits**: only when asked; branch first if on `main`. End commit messages
  with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

## Where to look first

| Task | Start in |
| --- | --- |
| Combat / keywords | `game/combat.py`, `game/game_engine.py` (`_step_combat_damage`) |
| Static abilities / P/T / anthems | `game/continuous.py`, `models/game_object.py` |
| Activated abilities / costs | `game/costs.py`, `game/game_engine.py` (`activate_ability`) |
| Card abilities / fetch lands / enters-tapped | `game/ability_catalogue.py`, `effect_binder.bind_from_catalogue` |
| Effects / triggers | `game/effects.py`, `game/effect_binder.py` |
| Goldfish UI | `frontend/src/js/goldfishView.js` |
| Engine coverage doc (user-facing) | `frontend/src/js/implementationStatusView.js` |
| Looking up a `RULE <n>` in the CR text | `Reference/rules_wiki/` (rule#/term → source line; see its `README.md`) |
