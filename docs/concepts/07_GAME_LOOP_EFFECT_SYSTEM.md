# DeckLab: Game Loop & Effect System

This document describes the real turn/phase/step loop and the real
effect/trigger/replacement system as they exist in the backend today. It
replaced an earlier version of this file written before the rules engine
existed — a "bad approach / good approach" teaching document arguing (in
invented pseudocode) that phases must be data-driven and effects must be a
real object system, because cards change the rules rather than merely doing
things. That argument turned out to be correct, and the system described
below is, in its bones, what that pseudocode was reaching for — several of
the real modules' own docstrings cite this document by name and part number,
because they were written to satisfy it. What changed is that pseudocode
became ~30k lines of real code with years of Comprehensive-Rules edge cases
built on top, which this rewrite grounds in actual file paths, class shapes,
and method signatures rather than sketches. See
[`03_ARCHITECTURE_AND_BUILDPLAN.md`](03_ARCHITECTURE_AND_BUILDPLAN.md) for
how this fits the rest of the system (the mixin split, the layer diagram),
[`09_ORACLE_EFFECT_PARSER.md`](09_ORACLE_EFFECT_PARSER.md) for how oracle
text becomes the `AbilitySpec`s this document's binder turns into behaviour,
and [`12_ARCHITECTURE_DIAGRAMS.md`](12_ARCHITECTURE_DIAGRAMS.md) for a
diagram companion to this prose.

---

# CRITICAL INSIGHT: Rules Are Mutable by Cards

The fundamental truth that breaks most MTG implementations:

**Cards don't just do things. Cards change the rules.**

Real examples this engine actually has to handle, not hypotheticals:

- "Skip your next untap step." (Stasis) — the turn loop's own step-skip check
  (`RulesEngine.should_skip_step`), not a special case in the phase walker.
- "If you would draw a card, draw two instead" *and* a different permanent
  saying "if a player would draw a card, that player mills a card instead"
  on the same event — `RulesEngine.apply_replacements`, RULE 616, has to
  chain both, in an order a player chooses, and keep chaining until nothing
  else applies (RULE 616.1f).
- "Creatures entering the battlefield don't cause abilities to trigger."
  (Torpor Orb) — `continuous.trigger_suppressed`, consulted by the trigger
  collector before a single ability is even checked.
- "This ability triggers only once each turn." / "at the beginning of the
  next end step, `<effect>`." — an ordinary triggered ability isn't enough
  to express either; RULE 603.7's delayed triggers
  (`GameState.delayed_triggers`) are a distinct mechanism from RULE 603's
  ordinary event-triggered ones.

This requires an architecture where rules are consulted, not hardcoded;
where several independently-printed effects can combine and be reordered
(RULE 616's replacement chains, RULE 613's layer system); and where a new
card's behaviour is *data* — a whitelisted effect `type` plus parameters —
not a new `if` branch somewhere in the engine. All three are real properties
of the shipped code below, not aspirations.

---

# PART 1: The turn/phase/step loop (RULE 500)

`backend/mtg_analyzer/game/phases.py` is a small, data-only module — three
classes, no imports besides `typing` — that exists *specifically* to avoid
the "bad approach" this document originally argued against: a turn is not a
hardcoded call sequence, because cards skip and insert phases. Its own
docstring says so directly:

> "docs/07 PART 1 is explicit that phases must NOT be a hardcoded call
> sequence, because cards reorder and skip them ('skip your next untap
> step'). So a turn is *data*: an ordered list of `GamePhase`s, each an
> ordered list of `GameStep`s."

The real shapes:

```python
class GameStep:
    def __init__(self, name: str, rule: str = "", gives_priority: bool = True): ...

class GamePhase:
    def __init__(self, name: str, steps: list[GameStep]): ...

class TurnSequence:
    def __init__(self, phases: list[GamePhase]): ...
    def iter_steps(self): ...  # yields (phase, step) pairs in turn order
```

`gives_priority` (RULE 500.2/117.3a) marks the two steps nobody gets
priority in — untap and cleanup (RULE 502/514) — directly on the step, so
the loop doesn't need a hardcoded exception list either.
`default_turn_sequence()` builds the standard RULE 500.1 turn fresh on every
call (beginning: untap/upkeep/draw → precombat main → combat:
begin_combat/declare_attackers/declare_blockers/combat_damage/end_combat →
postcombat main → ending: end/cleanup), so a caller that wants to graft in
an extra combat phase can mutate its own copy without touching anyone
else's turn.

## The engine that walks it

`game/engine/turn_loop_mixin.py`'s `TurnLoopMixin` (one of `GameEngine`'s
mixins — see `03_ARCHITECTURE_AND_BUILDPLAN.md`'s "System layers" and PART 3
below for the mixin split) is the real walker. Two entry points exist for
two different callers:

- **`run_turn()`** calls `begin_turn()` then iterates
  `default_turn_sequence().iter_steps()` straight through, calling
  `_run_step(phase, step)` for each — the whole-turn-at-once shape a bot or
  a test uses.
- **`start()` / `advance_step()`** is the goldfish/interactive shape: the
  engine keeps its own `_turn_steps` list and `_cursor` (exposed as
  `step_cursor`, restored by `resume_at` after an undo), and
  `advance_step()` runs exactly one `(phase, step)` pair per call, rolling
  into the next turn via `_begin_turn_steps()` once the cursor runs out. A
  session drives this one step at a time so a player can act between steps
  with full undo.

`_run_step(phase, step)` is where the "cards change the rules" property
actually lives:

```python
def _run_step(self, phase, step):
    ...
    # Rule-override skips (docs/07 PART 8): "skip your untap step", etc.
    if self.rules.should_skip_step(self.state.active_player, step.name):
        return
    ...
    self._execute_step_body(step)
    if not step.gives_priority:
        self.state.priority_player_index = None
    else:
        self.give_priority(self.state.active_player)
        if self.interactive_priority:
            self.rules.put_triggers_on_stack()
        else:
            self.resolve_until_stable()
```

`should_skip_step` is a single, generic consult — a step is skipped because
some effect says so, not because the loop special-cases "Stasis" — and
`_run_step` doesn't otherwise know or care what card caused the skip. The
untap step has its own narrower variant of the same idea
(`continuous.all_untap_steps_skipped` plus each object's own
`skip_next_untap`/`skip_untap` flags), for "you skip your untap step" vs.
"permanents don't untap" being different, real, CR-distinct effects.

## Priority (RULE 117) — two modes, one engine

`GameEngine.interactive_priority` (off by default, on only for
`MULTIPLAYER` sessions — see `CLAUDE.md`'s "RULE 117 priority" section for
the full session-level behavioural detail this document doesn't repeat)
picks which of two real, both-shipped paths a priority window takes:

- **Off** (goldfish/replay/solo): `resolve_until_stable()` auto-drains the
  stack — check state-based actions, finish any deferred effect, put fired
  triggers on the stack, resolve the top, repeat — until the stack is empty,
  the game ends, or a resolving effect needs a player choice
  (`state.pending_choice`), at which point it returns early so the session
  can surface that choice and resume later via `resolve_pending_choice`.
- **On**: only `rules.put_triggers_on_stack()` runs; nothing resolves on its
  own. `pass_priority(player)` is the real RULE 117.3/117.4 APNAP
  mechanism — it records the pass, and if any living player hasn't passed
  yet it hands priority to the next one (APNAP order) and returns `False`
  without resolving anything, which is what lets a non-active player
  respond before the stack moves. Only once every living player has passed
  in succession does it resolve the top of the stack, re-run state-based
  actions, put any newly-fired triggers on the stack, and return priority to
  the active player (RULE 117.3b) — `True`, something resolved.

Both paths share the same underlying primitives
(`check_state_based_actions`, `put_triggers_on_stack`,
`resolve_top_of_stack`); interactivity is a difference in *who decides when
to advance*, not a second implementation of resolution.

---

# PART 2: The effect hierarchy and `EffectRegistry`

The old version of this document sketched a base `GameEffect` with four
invented subclasses and reasoned through three registration strategies
(plain classes, a generic parameter dict, a class+registry hybrid) before
recommending the hybrid. The real code took exactly that path — the base
class's own docstring says so:

> `game/effects/core.py`, `class GameEffect(ABC)`: "Base class for all
> effects (docs/07 PART 2)."
>
> `game/effects/core.py`, `class EffectRegistry`: "The hybrid design from
> docs/07 PART 4: predefined classes stay type-safe, but oracle-text parsing
> (a later step) can create effects by name + params without the engine
> knowing each card."

What differs from the old sketch is scale and precision, not shape. The
effect hierarchy isn't one file any more — `game/effects.py` split into the
`game/effects/` package (`core.py` for the base classes plus
`GameContext`/`EffectRegistry`; `composition.py` for the five composition
nodes below; and eleven further modules —
`attachments_transforms.py`, `choices_actions.py`, `counters_tokens.py`,
`damage_draw.py`, `exile_control.py`, `game_status.py`, `library.py`,
`life_sacrifice.py`, `registry.py`, `replacements.py`,
`returns_graveyards.py`, `stack.py` — each holding a themed slice of the
now-hundreds of concrete effect classes that register into the same
`EffectRegistry`). Likewise `effect_binder.py` is now `game/binding/core.py`
(3600+ lines) — the split happened for the same "one grep-able file per
concern" reason the mixin split did (PART 3 of
`03_ARCHITECTURE_AND_BUILDPLAN.md`), not a change of design.

## The real class shapes (RULE 611/613/614/602/603)

All four live in `game/effects/core.py`, each a `GameEffect` subclass:

- **`StaticEffect`** — a player-scoped rule override, not a battlefield
  characteristic change: `kind` names what it overrides (e.g.
  `"skip_phase"`, with `params["phase"]` the step to skip), `duration`
  controls its lifetime (`"permanent"`, `"end_of_turn"`, `"next_turn"`,
  `"once"`). It has no imperative `apply` — a skip is *consulted*
  (`StaticEffect.skips_step`, read by `should_skip_step`), not executed.
- **`StaticAbility`** — the RULE 613 continuous-effect kind: a battlefield
  permanent's static reshaping other permanents' characteristics (an
  anthem, a granted keyword, a type/colour change, a mana-cost reduction).
  `layer` selects one of RULE 613.7's sublayers via a real
  `LAYER_NUMBERS` table (`"type"` → 4, `"ability"` → 6, `"pt_set"` → 7b,
  `"pt_mod"` → 7d/anthems, `"pt_switch"` → 7e, plus a non-layer `"cost"`
  bucket for RULE 601.2f cost adjustments); `affects` names the object set
  it touches; `params` is the modification. It carries `duration`/
  `duration_data` for a *resolve-time* grant ("target creature gains
  flying until end of turn") parked in `GameState.floating_statics` — see
  PART 6. Like `StaticEffect`, its `apply` is a no-op: `game/continuous.py`
  reads these off the battlefield every recompute (PART 3) rather than
  running them.
- **`TriggeredAbility`** — RULE 603: `trigger_event` names the `EventType`
  it watches, an optional `condition` callable is the extra RULE 603.1
  predicate, and `effects` are the one-shot effects it places on the stack.
  It also carries the machinery a *fixed, bound-once* effects list needs to
  express real cards: `modes`/`modes_choose`/`modes_at_least`/
  `modes_or_both`/`modes_repeatable`/`modes_exhaust_per_turn` for RULE
  700.2 modal triggers, `once_per_turn` for "only once each turn",
  `reflexive` for RULE 603.3d's "that permanent/spell" (the event's own
  subject, not a freely chosen target), `mana_ability` for RULE 605.4's
  stack-free triggered mana abilities, and `functions_from_graveyard`/
  `functions_from_stack` for abilities whose source isn't on the
  battlefield when they fire. A trigger whose *magnitude* genuinely varies
  per firing (Rampage's per-block blocker count, a ward ability's own
  caster/target pair) doesn't fit a bound-once effects list at all — the
  sanctioned answer is building a fresh `TriggeredAbility` (or a raw
  `StackItem`) with the per-firing data baked in at the call site, not new
  IR (see `RulesEngine.check_rampage`/`check_ward`).
- **`ReplacementEffect`** — RULE 614: `event_type` plus a
  `replacement_fn: (event, context) -> GameEvent | None` that rewrites (or,
  returning `None`, prevents) the event. Never touches the stack.
- **`ActivatedAbility`** — RULE 602: `cost` is a full `ActivationCost`
  (`game/costs.py` — mana, tap/untap, sacrifice, life, discard, counter
  removal), `effects` go on the stack once paid. Also carries
  `once_per_turn`/`once_per_game` (RULE 702.177a Exhaust/Power-up),
  `attach_kind` (which of equip/fortify/reconfigure generated it, read by
  `services/bots.py`'s `GreedyBot`), and the same `modes` shape
  `TriggeredAbility` has, chosen before the ability goes on the stack.

There is no separate `WinConditionEffect`/"win/loss override" class as the
old sketch imagined — RULE 104's actual loss conditions
(`_sba_check_player_loss`, `_player_loses`, `_loss_prevented`) are part of
the RULE 704 state-based-action pass (PART 5), and a "you can't lose"
effect is an ordinary predicate that pass consults, not a distinct effect
type. Folding a whole effect *kind* into an existing mechanism rather than
inventing a parallel one is a repeated real pattern below, not unique to
this case.

## `EffectRegistry`: the whitelist, verbatim

```python
class EffectRegistry:
    _factories: dict[str, Callable[[dict[str, Any]], GameEffect]] = {}

    @classmethod
    def register(cls, effect_type: str, factory) -> None: ...

    @classmethod
    def create(cls, effect_type: str, params: dict | None = None) -> GameEffect:
        if effect_type not in cls._factories:
            raise ValueError(f"unknown effect type: {effect_type!r}")
        return cls._factories[effect_type](params or {})

    @classmethod
    def is_registered(cls, effect_type: str) -> bool: ...
```

This is the project's actual security boundary, and it is exactly as narrow
as it looks: `game/binding/core.py`'s `build_effects` refuses any `type` the
registry doesn't know (`BindError`) before anything runs. Nothing derived
from card text ever becomes Python code — an `AbilitySpec` (from the
hand-authored `game/card_catalogue/` or the oracle-text parser,
`parser/oracle/`) is a whitelisted `type` string plus clamped `params`
(`parser/oracle/spec.py`), and the binder is the *only* place allowed to
turn one into a live `GameEffect`. See `09_ORACLE_EFFECT_PARSER.md` for how
a spec is produced; this document only covers what happens once one exists.

## Composition: the axis the old sketch didn't know it needed

Neither the old pseudocode nor the registry above says how to express "if
`<condition>`, A, otherwise B", "you may do A", "for each player, A", or "do
A, then B using a number measured from A" without inventing a new
registered effect *type* for every card that needs one of those shapes —
which is exactly what happened for a while: `game/isa.py` at one point
counted 84 such one-off fusions. `game/effects/composition.py` is the fix,
five general nodes built once, each an ordinary `EffectRegistry` entry so
the whitelist still gates them at every depth:

| Registered type | Class | What it expresses |
| --- | --- | --- |
| `"seq"` | `SeqEffect` | a list, as a value — so a list can be an operand of the other four |
| `"if_else"` | `IfElseEffect` | RULE 603.4/701.30d branching on an `effect_conditions` gate |
| `"optional"` | `OptionalEffect` | RULE 601.2b "you may", as a wrapper rather than a per-effect flag |
| `"for_each"` | `ForEachEffect` | RULE 101.4 iteration over players or a selector's objects |
| `"bind"` | `BindEffect` | RULE 608.2's "…equal to", measuring an amount once and substituting it into the body |

Each node's own body is an ordinary list of `EffectSpec`s built through the
same `binding.build_effects` every other effect goes through, so nesting one
composition node inside another costs nothing new. Every body runs through
the same `_apply_effects_partitioned` helper the flat case uses, so a player
choice opened anywhere inside one (a target, a modal pick) pauses and
resumes exactly as it would at the top level; `ForEachEffect` additionally
parks its own remaining iterations so a loop body can ask a question once
per item instead of one prompt overwriting the last.

---

# PART 3: How effects combine and reorder — RULE 613 layers, RULE 616 replacement ordering

The old document's PART 3 sketched one generic "apply each replacement in
player-chosen order, repeat" loop and left layers unaddressed entirely. Two
separate, real systems now cover this — they don't share an algorithm,
because RULE 613 and RULE 616 are genuinely different problems (one
re-derives *characteristics* from scratch every time the board settles; the
other *rewrites an event* once, right as it's about to happen).

## RULE 613: the continuous-effects layer engine (`game/continuous.py`)

`StaticAbility` objects don't run — `game/continuous.py`'s `recompute(state)`
is what actually applies them, every time state-based actions check the
board (and before every session view is served). It resets every
battlefield object's derived characteristics, then re-derives them layer by
layer, in RULE 613.7 order:

1. **Layer 1** — copy effects (RULE 707), the conditional/continuous case
   only ("as long as `<condition>`, ~ is a copy of `<X>`" — Vesuvan
   Shapeshifter); the other two copy mechanisms this engine models (a
   permanent's own "enter as a copy" choice, a temporary "until end of turn"
   copy) are discrete mutate/revert operations instead, since neither needs
   re-evaluating every recompute.
2. **Layer 2** — control-changing effects. The *only* layer where RULE
   613.8's dependency system is modeled (`_order_control_effects`) — every
   other sublayer's selectors were traced and confirmed unable to construct
   a genuine order-dependency, so timestamp order (RULE 613.7,
   `_in_layer`) is enough everywhere else.
3. **Layer 3** — text-changing effects (RULE 612), scoped to a
   word-substitution over `GameObject.effective_oracle_text` (not a full
   re-parse — bound abilities/keywords stay fixed at bind time).
4. **Layer 4** — type-changing effects.
5. **Layer 5** — colour-changing effects.
6. **Layer 6** — ability-adding effects (a granted keyword or a full
   granted ability). A static a layer-6 grant *itself* produces (an
   anthem/lord granted to something else) is re-gathered and re-applied
   within the same `recompute` pass so it doesn't lag a full extra cycle.
7. **Layer 7** — power/toughness, in full sublayer order: 7a
   characteristic-defining P/T, 7b set, 7c counters, 7d modify (anthems),
   7e switch.

Plus a non-layer bucket, **cost adjustments** (RULE 601.2f), computed in the
same pass though not part of 613 itself. The result — derived power/
toughness, granted keywords, added types, and a per-object, per-layer
`static_trace` for debugging — is stamped back onto each `GameObject`; reads
of `obj.power`/`obj.is_creature`/`combat.keywords_of` always see this live
layer stack, never a raw printed value once a game is running (see
`CLAUDE.md`'s "Derived characteristics" convention).

## RULE 616: replacement-effect ordering (`RulesEngine.apply_replacements`)

This is the part of `RulesEngine` the mixin split (PART 4 of
`03_ARCHITECTURE_AND_BUILDPLAN.md`) deliberately did *not* pull into a
mixin — `rules_engine.py`'s own class docstring calls it out as this class's
"own central entry point rather than one responsibility among several."
`apply_replacements(event)` walks a real loop, matching the old sketch's
intent almost exactly but backed by actual RULE 616 subsection numbers:

```python
while current is not None:
    applicable = [effect for effect in self._all_replacement_effects()
                  if id(effect) not in applied and effect.can_replace(current, self.context)]
    if not applicable:
        break
    if len(applicable) > 1:
        # RULE 616.1e: the affected player chooses which applies next —
        # opens an interactive `replacement_order` pending_choice.
        ...
    chosen = applicable[0]
    applied.add(id(chosen))
    current = chosen.apply_replacement(current, self.context)
```

Each effect may apply **at most once** to a given event (tracked by Python
object identity in `applied`), and applying one can expose others that
weren't applicable before — RULE 616.1f's "repeat this process until there
are no more applicable replacement effects" — which is exactly why this is
a loop rather than a single pass. When exactly one effect applies there's
nothing to choose and it just runs; when two or more apply simultaneously,
RULE 616.1e says the *affected player* chooses the order (a draw event's
affected player is whoever is drawing, a damage event's is whoever takes
it — `_event_affected_player_id`), surfaced as a real
`replacement_order` `pending_choice` rather than a deterministic tie-break,
so a Tymna-draws-two / Leyline-of-the-Void-mills-instead double-replacement
is genuinely player-decided, not hardcoded to always run in discovery
order.

---

# PART 4: Triggered abilities (RULE 603/607) and delayed triggers (RULE 603.7)

The old document's sketch for triggers was "check every permanent on every
event." The real mechanism (`game/rules/triggers_mixin.py`'s
`TriggerCollectionMixin`) does start from that same idea — `_collect_triggers`
really does scan every permanent, every emblem, and every RULE 9
command-zone source on every fired `GameEvent` — but it's a two-phase
collect-then-place pipeline with real RULE 603.3 ordering, not an
event-to-effect shortcut:

1. **Collection** (`_collect_triggers`, called as part of firing any
   `GameEvent`): for each candidate ability, `TriggeredAbility.check_trigger`
   tests the event type, the ability's own `condition` predicate, and
   `once_per_turn`. A triggered *mana* ability resolves immediately here
   (RULE 605.4 — no stack, so its mana is spendable within the very payment
   that triggered it); everything else is appended to
   `self.pending_triggers` as `(ability, event)`. Suppression is checked
   first and applies globally: `continuous.trigger_suppressed`/
   `trigger_suppressed_for` (Torpor Orb/Elesh Norn, Mother of Machines) can
   skip the whole scan or just one controller's abilities before a single
   `check_trigger` call happens. A handful of trigger families have no
   single permanent source at all (the Monarch, the Initiative, rad
   counters — RULE 725/726/728) and are collected by dedicated
   `_collect_inherent_triggers`-style methods instead of the permanent
   scan.
2. **Placement** (`put_triggers_on_stack`, called as each priority window
   opens): RULE 603.3b's APNAP ordering — the active player's own triggers
   are placed first, which means they end up *lowest* on the stack and
   resolve *last*. When `state.interactive_ordering` is on and the active
   player has two or more simultaneous triggers, they choose the order via
   a `pending_choice` instead of a fixed placement order.

## Delayed triggers (RULE 603.7)

"At the beginning of your next upkeep, `<effect>`." isn't an ordinary
triggered ability at all — it isn't watching a live `EventType`, it's
waiting for a specific *future step*. `GameState.delayed_triggers` holds
`DelayedTrigger` records (`controller_id`, `step`, `effects`, `scope`,
optional `targets`/`condition`/`min_turn`) created by a resolving spell or
ability. `GameEngine._fire_delayed_triggers(step_name)` — called from
`_run_step`, right after `STEP_BEGIN` fires — checks every pending one
against the step just reached: `scope="controller"` needs the active player
to be the one who set it up ("your next upkeep"); `scope="any"` fires at the
very next matching step regardless of whose turn it is ("the next end
step"). A due trigger's optional `condition` (RULE 603.4's "…unless `<X>`",
evaluated through the same `ConditionalEffect` whitelist the parser's
`EffectSpec.condition` uses) is re-checked right before it's placed, then
it's pushed onto the stack as an ordinary `StackItem` and dropped — it fires
exactly once. This is a genuinely separate mechanism from RULE 603's
ordinary event-triggered abilities, not a variant of the same collection
scan; `CLAUDE.md`'s implementation-state summary calls this out for the
same reason.

---

# PART 5: State-based actions (RULE 704)

`game/rules/sba_mixin.py`'s `StateBasedActionsMixin.check_state_based_actions`
loops `_sba_pass()` until a pass makes no change (RULE 704.3 — "these
actions happen immediately... This is called performing a state-based
action"). Each pass first re-derives continuous effects
(`continuous.recompute`) so anything reading power/toughness/keywords sees
current values, then tries a fixed, RULE-cited sequence of checks — Ascend,
Storied, Start Your Engines, Soulbond validity, the Ring-bearer sweep,
player loss (RULE 104), zero toughness, zero loyalty, battle/siege defeat,
Saga completion, lethal damage, counter annihilation, illegal-attachment
detachment, un-bestow, the legend rule (RULE 704.5j), the commander-zone
choice, stray tokens leaving the battlefield — stopping and returning `True`
at the *first* check that actually changes something, so the very next pass
re-derives state from scratch before trying the next check. This is
deliberately broader than the old document's four-item illustrative list
(zero toughness, duplicate legendary, aura-enchants-nothing, zero life) —
that was always meant as an example, not a spec, and the real check list has
grown with the engine. See `Done_Backend.md`'s Rules Engine section for the
full, maintained catalogue rather than trusting an enumeration here to stay
current.

---

# PART 6: "As long as…" (RULE 613.6) and "until…" (RULE 611) — the two systems the original plan didn't know it needed

Neither of these existed as a concept in the original document — they're
what got learned building the ~250 real "as long as"/"until" clauses in the
card cache, once doing it one bespoke boolean parameter at a time
(`active_player_only`, `min_level`, `min_count_selector`, …) started
repeating the same trap for every new clause.

**`game/static_conditions.py`** is the single evaluation path for RULE
613.6 conditional statics: a small, whitelisted dict — `{"kind": <name>,
...}` — carried in a `StaticAbility`'s `active_if` param and evaluated
**live, every recompute**, against that ability's own source and
controller. Fail-closed like every card-text-derived vocabulary in this
project: an unrecognized `kind` (or a malformed param) makes the condition
false rather than raising, since this runs inside the layer engine on every
recompute. It never caches — that's what makes "as long as ~ is untapped"
turn back off the instant the permanent taps, with no event and no
bookkeeping. Deliberately distinct from three lookalikes it is *not*:
`game/condition_query.py` (cast/activation legality — RULE 702.8b
flash/606.3 loyalty timing — which has to work for a card still in hand),
`parser/oracle/spec.py`'s own `_ALLOWED_CONDITION_KEYS` (whether an
already-resolving one-shot effect applies, e.g. "if kicked"), and
`GameEngine._combat_condition_met` ("~ can't attack unless `<board
condition>`", evaluated against a *defending* player no recompute-time
condition can see).

**`game/durations.py`** is the time-bound counterpart: where
`static_conditions` answers "while *what* is true" (and can turn back on),
`durations` answers "until *when*" and, once its window closes, the effect
is gone for good — RULE 611.2b treats even a condition-bounded duration
("for as long as you control ~") this way, as distinct from an
`active_if` gate that can flicker on and off indefinitely. A duration lives
on the `StaticAbility` itself (`duration`/`duration_data`), and the ability
sits in `GameState.floating_statics` until swept. The existing
`temp_power`/`temp_keywords`/`temp_protections` per-object fields are
deliberately *not* folded into this system — they express exactly one
duration (until end of turn, swept at cleanup per RULE 514.2) and remain
the path every ordinary pump/grant uses; `durations.py` exists for every
*other* duration a resolve-time grant needs (`your_next_turn`,
`end_of_combat`, `next_end_step`, `for_as_long_as`, `rest_of_game`), because
a `temp_*` field has nowhere to record when — or whether — it should end.

---

# PART 7: What changed from the original 985-line teaching document

- **The invented `GamePhase`/`TurnSequence` sketch became real, and the real
  version cites this document.** `game/phases.py` is essentially the "good
  approach" pseudocode, for real — its own docstring quotes PART 1's
  reasoning. What the sketch didn't anticipate: a `GameStep.gives_priority`
  flag baked into the data (RULE 500.2's untap/cleanup exception needed no
  separate list), and a dual-mode walker (`run_turn()` for a whole turn at
  once, `advance_step()`/cursor-based for a goldfish session with undo
  between steps) rather than one `execute_turn` loop.
- **The four-type effect hierarchy shipped almost exactly as sketched, and
  the registry pattern is cited by name in the real code** — `EffectRegistry`'s
  own docstring calls itself "the hybrid design from docs/07 PART 4." What
  the sketch underestimated was *scale*: one `effects.py` became a
  fourteen-module `game/effects/` package, one `effect_binder.py` became a
  3600-line `game/binding/core.py`, and a fifth mechanism — the five
  composition nodes (`seq`/`if_else`/`optional`/`for_each`/`bind`) — had to
  be built once a card catalogue of real size made "one bespoke fused
  effect type per compound sentence" an 84-type liability rather than a
  one-off.
- **RULE 616 replacement ordering shipped close to the sketch's own loop**,
  now backed by an interactive `pending_choice` for the RULE 616.1e
  multi-effect case rather than an always-deterministic order, and kept
  deliberately *outside* the mixin split as `RulesEngine`'s own remaining
  responsibility.
- **RULE 613's layer system, RULE 603.7 delayed triggers, RULE 613.6
  conditional statics, and RULE 611 durations didn't exist in the original
  plan at all.** They're the largest real gap between the 985-line document
  and the shipped engine — not because the old plan was wrong about what it
  covered, but because it hadn't yet met the ~250-clause "as long as"/
  "until" long tail, RULE 613.7's sublayer ordering, or the difference
  between an ordinary trigger and a delayed one, all of which turned out to
  need dedicated modules rather than fitting inside the four-effect-type
  sketch.
- **RULE 704 state-based actions grew from a four-item illustrative list
  into a ~20-check lettered sequence** re-run to a fixed point every time
  the board changes — see `Done_Backend.md` for the maintained catalogue
  this document deliberately doesn't duplicate.

For what's built beyond this document's scope — the oracle-text parser
front-end that produces the `AbilitySpec`s this document's binder consumes,
combat/keyword mechanics, mana, card-type structures — see
`09_ORACLE_EFFECT_PARSER.md` and `CLAUDE.md`'s "Implementation state"
section, and for open work see
[`../implementation-state/BACKLOG.md`](../implementation-state/BACKLOG.md).
