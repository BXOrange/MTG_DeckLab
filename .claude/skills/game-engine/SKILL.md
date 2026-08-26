---
name: game-engine
description: Work on the rules engine in backend/mtg_analyzer/game/ — implement a game mechanic or MEC/ENG backlog ticket, add an effect/trigger/replacement/static/interactive choice, fix layer-system or combat behaviour, or debug why a card doesn't do what it should in a real game. Ships engine_bench.py, which boards, casts, resolves and fights a real card against a real GameEngine from one command (event trace + board diff, no throwaway test file), searches every engine registry for a primitive that already exists, and sizes a mechanic against the full 34k-card cache.
---

# Working in the rules engine

Four files carry most of it and all four are large: `effects.py` (9.2k lines),
`rules_engine.py` (7.6k), `ability_catalogue.py` (6.6k), `game_engine.py`
(4.5k). Two costs dominate any change here — **finding the right place**, and
**finding out what the engine currently does** — and `scripts/engine_bench.py`
exists for both.

```bash
cd backend && source venv/bin/activate
BENCH=../.claude/skills/game-engine/scripts/engine_bench.py
```

## Orient first — don't grep four huge files blind

```bash
python $BENCH where layers        # or: triggers, sba, mana, combat, targeting, …
python $BENCH where               # the whole map
python $BENCH rule 613.7          # the CR text itself, in one hop
python $BENCH events --grep tap   # the EventType vocabulary
python $BENCH primitives 'fight'  # every registry at once: does this already exist?
python $BENCH cards 'monstrosity' # what the ticket is really worth, and what blocks it
```

**`primitives`** is the standing "don't rebuild what you have" check, run over
the live registries rather than a written-down list: registered effect types
(with the params each factory actually reads), replacement types, events,
`pending_choice` kinds, every `RulesEngine`/`GameEngine` method, `GameObject`
state, the 194 RULE 702 keywords, and the hand-authored cards. Search the
*shape*, not the word — a primitive built for another card is named after that
card's flavour, which is exactly how a ticket ends up three deferrals deep
describing something that shipped two batches ago.

**`cards`** sizes a mechanic against the real ~34k-card cache in under a
second: how many cards use it, how many already work (parser-MODELED or
hand-authored), and — the useful part — the ranked templates blocking the
rest. A ticket's card estimate is usually stale and usually high; the ranking
also shows the two or three clause families a mechanic decomposes into (the
activation, its trigger, its static), which is the actual work breakdown.

`rule` collapses the three-step `rules_wiki` lookup (index → line → Read the
975 KB CR file at an offset) into one command. Use it whenever you're about to
write a `RULE <n>` comment — the comment should match what the rule says.

`docs/implementation-state/Done_Backend.md` is the other half of orientation:
search it for the mechanic's name before designing anything. It records *why*
shipped work looks the way it does, and this engine has a long history of a
primitive existing already under a different card's name.

## See what the engine actually does, before changing it

```bash
python $BENCH inspect "Llanowar Elves"
python $BENCH inspect --text "Creatures you control get +1/+1." --type "Enchantment" --with-bear
python $BENCH play "Mulldrifter"
python $BENCH play "Lightning Bolt" --target-creature
python $BENCH combat "Serra Angel" --blocker "Air Elemental"
```

- **`inspect`** boards the card, binds it, runs the layer engine, and prints:
  the parse verdict, every bound triggered/activated/static/replacement
  ability with its real fields, derived P/T + `static_trace`, mana abilities,
  and its legal actions. `--with-bear` also boards two vanilla creatures and
  prints *their* derived state — an anthem or lord is only visible in what it
  does to other permanents, so that section is where you check it landed.
- **`play`** advances to a main phase, fills the mana pool, casts, and runs
  `resolve_until_stable()` — the engine's own all-pass priority window, so ETB
  triggers actually fire — then prints the full event trace and a board diff.
  This is the "does it behave, or does it only parse" check.
- **`combat`** runs a real declare-attackers → blockers → damage sequence. A
  refused block is reported, not raised: that refusal is usually the answer.

Reading the trace is the debugging method. The failure modes in order:

| Symptom | Look at |
| --- | --- |
| `inspect` shows nothing bound | card is UNMODELED, or the spec `type` string is missing from `EffectRegistry` — the silent no-op |
| bound, but no event on cast | the trigger condition never matched — `effect_binder._trigger_condition`, and check the engine actually fires an event carrying `instance_id` for that verb |
| event fires, board unchanged | the effect resolved into nothing — a `legal_targets` branch returning `[]`, or a selector param dropped because it isn't in `_SELECTOR_KEYS` |
| P/T or keywords wrong | layer order in `continuous.recompute`; read `static_trace`, which names the source and layer per modification |

## The invariants that bite

- **Derived state is stale until you recompute.** `power`/`toughness`/
  `is_creature`/`granted_keywords` read what `continuous.recompute` stamped.
  It runs on every SBA pass and before the session view — anywhere else, call
  `engine.recompute_continuous_effects()` first or you're reading printed
  values plus counters.
- **`models/` must not import `game/` at module load.** Where a model needs
  engine logic, use a function-scoped import; `combat.py`/`continuous.py`
  import models only under `TYPE_CHECKING`.
- **A new effect type needs `EffectRegistry.register`** in `game/effects.py`,
  and any new selector param needs adding to `_SELECTOR_KEYS` — otherwise it
  is silently dropped at bind time and the effect quietly does less than the
  card says.
- **A new `pending_choice` kind needs `GameEngine.resolve_choice` to dispatch
  it.** That if/elif chain ends in a bare `else: resolve_search_choice(...)`,
  so a kind you forget does *not* raise — it is answered as a library search,
  and the table wedges only in a real game. `python $BENCH choices --gaps`
  audits every kind against its stops (resolver, engine dispatch, board icon);
  `search` is the intended occupant of that else-branch, anything else flagged
  there is a bug.
- **Nothing derived from card text becomes code.** Effects are a whitelisted
  `type` + clamped params; the binder is the only thing that turns specs into
  behaviour.
- **`turn_number` vs `round_number`.** `turn_number` is the rules-correct
  RULE 500.1 count and is what the engine reads everywhere; `round_number` is
  display-only. Don't "fix" either into the other.
- **Comment rules-relevant code with its CR number** (`RULE 613.7`), matching
  the surrounding density. `python $BENCH rule 613.7` before you write it.

## A mechanic ticket includes its parser

A `MEC` ticket is **engine primitive + oracle handlers + `PARSER_VERSION`
bump, in one batch** — a primitive with no way for a real card's text to reach
it isn't shipped. For the parser half use the **`extend-parser` skill**; it
owns the handler recipe, the coverage measurement and the doc sync.

Before writing "needs a new primitive" anywhere, run `python $BENCH primitives
'<shape>'` and grep `Done_Backend.md` for an equivalently-shaped primitive
built for a different card — then cite it or rule it out explicitly.
Already general and frequently missed: `request_pay_cost_then`,
`CreateDelayedTriggerEffect` (RULE 603.7), `request_choose_objects`,
`dig_until`, `request_name_card`, `GameState.deferred_effects` (RULE 608.2),
`GameEffect.extra_target_specs`, `GameContext.trigger_event`,
`TriggeredAbility.mana_ability`.

Hand-authoring a genuinely singleton card in `game/ability_catalogue.py` is
the sanctioned escape valve, not a defeat — see
[the authoring guide](../../../docs/Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md).
An item deferred a **second** time must be hand-authored in that same batch or
explicitly promoted; it must not roll to a third deferral.

## Tests

```bash
python -m pytest -q                      # ~2700 tests, ~45s, keep it green
python -m pytest -q tests/test_x.py      # one file
python -m pytest -q --full-cache         # opt-in: the cube-batch regressions
python scripts/run_tests.py              # adds a 120s whole-run wall clock
```

A single test running past 20s aborts by itself (`pytest-timeout` in
`pytest.ini`) rather than hanging the run. `run_tests.py` covers the rarer hang
the per-test timer can't reach — collection, a session fixture, a C-level block.

Write **execute** tests, not just parse tests: build a `GameEngine`, bind, run
the effect, assert the board changed. The bench's own fixtures
(`new_engine`/`put`/`to_hand`) are the same five every test file redefines —
copy them from a neighbouring `tests/test_*_family.py` so the new file reads
like its siblings. Cover the negative case too: a restriction that must still
refuse, an SBA that must still fire.

Details and worked patterns: **[reference/adding-a-mechanic.md](reference/adding-a-mechanic.md)**.

## Closing out

- [ ] `BACKLOG.md`: **delete** the ticket, don't tick it. Append the narrative
      — what shipped and *why it's built that way* — to the matching section
      of `Done_Backend.md`. Keep only the part of a ticket that isn't done.
- [ ] Sweep: grep `BACKLOG.md` for other tickets your new primitive closes or
      narrows, and update them in the same pass. A primitive landing is
      exactly when this repo has historically forgotten to look.
- [ ] `frontend/src/js/implementationStatusView.js` — the user-facing
      Engine-Status tab. Keep it in sync when coverage changes.
- [ ] `CLAUDE.md`'s "Implementation state" if the change alters the
      orientation summary (a new subsystem, a closed gap).
- [ ] Commits only when asked; branch first if on `main`.
