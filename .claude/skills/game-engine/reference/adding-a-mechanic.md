# Adding a mechanic to the engine

Paths relative to `backend/mtg_analyzer/`. Use
`python $BENCH where <topic>` to jump; this file is the *how*, not the map.

## Pick the right shape first

The engine has five ability shapes, all subclassing `GameEffect`
(`game/effects/core.py`, one of ~15 modules the former `effects.py` was split
into by family — `game/effects/registry.py` is where concrete types get
registered). Picking wrong is the most expensive mistake available here,
because it is only obvious two hundred lines in.

| Shape | Is it | RULE | Tell |
| --- | --- | --- | --- |
| one-shot `GameEffect` | a thing that happens once, on resolution | 608 | "draw a card", "destroy target …" |
| `TriggeredAbility` | fires on an event, uses the stack | 603 | starts "when"/"whenever"/"at" |
| `ActivatedAbility` | a cost its controller may pay | 602 | `Cost: Effect` |
| `StaticAbility` | continuously re-derives characteristics via the layer engine | 613 | "creatures you control get +1/+1", type/keyword grants |
| `ReplacementEffect` | rewrites an event *before* it happens, never uses the stack | 614/616 | "instead", "as … enters", "if … would …" |

Two things that look static but are **not** the layer engine's job:
per-player *permissions* ("you may play an additional land", "you have no
maximum hand size", "cast limit") are consulted by dedicated helpers in
`game/continuous.py`; and a `StaticEffect` is a rule modification (phase
skipping), not a characteristic change.

A combat restriction is a third case: `continuous.recompute` **stamps** it onto
`GameObject.combat_restrictions`, but it is *evaluated at combat time* — who is
defending and who else is attacking don't exist when the layer engine runs.

## The registration chain

An effect is only real once every link exists. Missing links fail *silently*,
which is why the bench's `inspect` prints each of them:

1. **The class** — subclass `GameEffect`, implement
   `apply(self, context: GameContext, targets=None)`. Mutate the game through
   `context.engine` (the `RulesEngine` primitives), not `context.state`
   directly: that's what makes an effect-caused draw run through the same
   replacement and trigger machinery as a draw-step draw.
2. **`EffectRegistry.register("your_type", lambda p: YourEffect(...))`** —
   in `game/effects/registry.py` (the concrete-registration module; the
   `EffectRegistry` class itself is in `core.py`). The whitelisted `type`
   string is the security boundary: parsed card text never becomes code, it
   only names a registered factory. An unregistered type raises on `create`,
   but a *misspelled* one in a spec simply never binds.
3. **`_SELECTOR_KEYS`** (in `game/effects/registry.py`) — any new selector
   param you pass through a static spec. Not listed = silently dropped.
4. **Targeting** — set `target_spec` (a `TargetSpec`) in `__init__` if the
   effect targets, so RULE 601.2c can refuse the cast when no legal target
   exists. Two independently-chosen targets in one clause go in
   `extra_target_specs`; `apply` then reads `targets[0]`, `targets[1]` in
   printed order.
5. **A parser handler or a catalogue entry**, or no real card can reach it —
   see the `extend-parser` skill, or hand-author in `game/card_catalogue/`
   (one file per card, under a lowercased-first-letter folder;
   `game/card_registry/core.py` holds `register`/`specs_for`).

## Interactive effects

Anything that asks a player something is a `pending_choice` on the state, not a
blocking call. The state holds **exactly one** at a time — a resolution with
two interactive effects would have had the second overwrite the first, which is
what `GameState.deferred_effects` / `RulesEngine.resume_deferred_effects`
(RULE 608.2) exists to prevent: park the rest of the effect list and resume
when the choice is answered. Reuse the general choosers rather than inventing
a prompt shape: `request_choose_objects`, `request_name_card`,
`request_pay_cost_then`, `_can_pay_player_cost`/`_pay_player_cost`.

Carry a choice's whole decision — including "if you do" follow-ups, as
serialized `EffectSpec`s — as **clone-safe data, not a closure**. `GameState`
is deep-copied for undo/snapshots; a closure doesn't survive it.

## Events

A trigger can only listen for an event the engine actually fires, carrying the
data the condition needs (usually `instance_id`, often `controller_id`).
`python $BENCH events --grep <word>` lists the vocabulary; `grep -rn
"EventType.<NAME>"` in `game/rules/*_mixin.py`/`game/engine/*_mixin.py` shows
who fires it (`rules_engine.py`/`game_engine.py` themselves hold almost none
of this any more — see CLAUDE.md's ENG-20/21 mixin split).

If your mechanic needs a firing that doesn't exist, add it at the choke point
every route passes through, not at the individual call sites. Precedents worth
copying: `_move_to_graveyard` is the single funnel every graveyard-bound move
uses; `WOULD_DIE`/`DESTROY` are fired *pre-emptively* so a replacement can
intercept; the Siege defeat cycle is noticed by the **SBA pass** rather than at
each counter-removal site, so every route to zero defense reaches it.

Two real bugs this rule would have prevented: `_move_to_graveyard` fired `DIES`
for creatures only, so a dying Aura was invisible to every dies-trigger; and
`_build_group_ok`'s object lookup was hard-coded to `instance_id`, so
group-subject damage triggers couldn't see `source_controller_id`.

## Layer-system work (RULE 613)

`continuous.recompute(state)` re-derives every battlefield permanent from
scratch, in layer order, with a bounded RULE 613.8 dependency pass, and stamps
`power`/`toughness`/types/`granted_keywords` plus a per-object `static_trace`.

- **Read `static_trace` before theorising.** It names the source, layer and
  delta for every modification — `inspect` prints it.
- **Order within a pass matters.** `combat_restriction` is stamped *after* the
  layer-7 P/T pass specifically so a same-pass anthem is visible to a
  power/toughness qualifier. If your static reads another's output, say why in
  a comment and put it after.
- **Scope carefully.** A count-selector threshold is scoped to the *attacker's*
  controller per RULE 613.7c, not the reader's.
- **Off-battlefield grants are a separate pass**
  (`_apply_off_battlefield_types`, RULE 613.4a) covering the controller's other
  zones and their spells on the stack.

## Tests

New file `backend/tests/test_<mechanic>_family.py`, copying a neighbour's
fixtures (`_creature`/`_engine`/`_put`/`_modeled`). Cover:

- **parse → MODELED** for a real card's oracle text, when the mechanic has a
  parser half.
- **execute**: bind, run, assert the board changed. Non-negotiable — two
  shipped families passed the whole suite and crashed on first real use.
- **the negative**: the restriction that must still refuse, the SBA that must
  still fire, the trigger that must *not* fire on a near-miss event.
- **interaction**, where the mechanic has one: with an anthem, with a
  replacement effect, with `loses_all_abilities` (Humility/Dress Down), with a
  second copy of itself.

Mark a test `@pytest.mark.full_cache` if it needs the real card cache — those
are opt-in (`--full-cache`) so the ordinary run stays fast and synthetic.

## Worked precedents to imitate

Search `Done_Backend.md` for these when the shape matches; each was built to be
general and is cheaper to reuse than to re-derive:

- **suspended resolution** — `GameState.deferred_effects` (RULE 608.2)
- **delayed trigger** — `CreateDelayedTriggerEffect` (RULE 603.7)
- **optional payment with an "if you don't" branch** — `pay_cost_then` (118.3)
- **per-firing data without changing `apply`'s signature** —
  `GameContext.trigger_event` (603.1)
- **mana produced by a trigger, spendable in the payment that triggered it** —
  `TriggeredAbility.mana_ability` (605.1b/605.4)
- **a face swap that leaves the object the same permanent** — DFC transform and
  face-down (708) share it; the layer engine and combat need no special case
- **command-zone data that isn't a permanent** — `Player.dungeon` (309),
  `models/game/emblem.py` (114), the RULE 9 variant pools
