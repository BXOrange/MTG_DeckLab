"""Composite IR nodes — the third axis of `EffectSpec` (ENG-37, `14_` S3).

What was missing
----------------
`docs/concepts/14_PARSER_GRAMMAR_DESIGN.md` describes the engine's effect
types as a cross-product of four axes — operation × operands × **composition**
× linkage — of which axis 3 did not exist. An `AbilitySpec` could carry a
*list* of effects, and that list ran in order, but a list is the only
composition it had. There was no way to say "if `<condition>`, A, otherwise
B", "you may A", "for each X, A", or "A, then B using a number measured from
A" — so every card printing one of those shapes got a **new registered effect
type** fusing its parts together. `game/isa.py` counted 84 of them.

These five nodes are that axis, written once:

* ``seq``      — a list, as a value, so a list can be an operand of the others
* ``if_else``  — RULE 603.4/701.30d branching on an `effect_conditions` gate
* ``optional`` — RULE 601.2b's "you may", as a wrapper rather than a per-effect
                 ``optional`` flag that each effect has to reimplement
* ``for_each`` — RULE 101.4 iteration, over players or a selector's objects
* ``bind``     — RULE 608.2's "…equal to", measuring once into the body

Everything they are made of already existed. The bodies are ordinary
`EffectSpec` lists built through `binding.build_effects`, so the ``type``
whitelist keeps gating every depth (docs/09) and `AbilitySpec.validate()`
already recurses into them (the ENG-37 security half, PARSER_VERSION 299).
The conditions are ENG-36's vocabulary. The suspension is ENG-35's iteration
frame. This module is the wiring, not new machinery — which is the point:
a composition node that needed its own resumption or its own predicate
language would just be another fusion with a grander name.

Suspension
----------
Every body runs through `_apply_effects_partitioned`, so a choice opened
anywhere inside one parks the rest exactly as it does at the top level, and
the frames unwind innermost-first. ``for_each`` additionally parks its own
remaining iterations (ENG-35's `RulesEngine.defer_iteration`), which is what
lets a loop body ask a question once per item instead of overwriting the
previous player's prompt.
"""

from __future__ import annotations

from typing import Any, Optional

from ...models.game.game_object import GameObject
from .. import effect_amounts, effect_conditions
from ..targeting import TargetSpec
from .core import EffectRegistry, GameContext, GameEffect, _apply_effects_partitioned

#: How a `for_each` names the players it iterates, in APNAP order (RULE
#: 101.4). Deliberately the same three words `SacrificeEffect.selector` and
#: `MillEffect.player_selector` already use, rather than a fourth spelling.
PLAYER_SCOPES: frozenset[str] = frozenset({"each_player", "each_opponent", "you"})


def _as_spec_dicts(raw: Any) -> list[dict[str, Any]]:
    """A body parameter → plain `EffectSpec`-shaped dicts.

    Accepts what producers actually write: dicts (the catalogue's own
    spelling), or `EffectSpec` objects (a hand-built test/entry).
    """
    body: list[dict[str, Any]] = []
    for entry in raw or []:
        if hasattr(entry, "to_dict"):
            entry = entry.to_dict()
        if isinstance(entry, dict) and isinstance(entry.get("type"), str):
            body.append(entry)
    return body


def _resolve_x(value: Any, x_paid: int) -> Any:
    """Substitute the ``"x"``/``"-x"`` sentinel anywhere in a params value.

    `RulesEngine._substitute_x` only walks a *flat* built effect list's own
    magnitude attributes — it never reaches into a composition node's still-
    serialized body (`_CompositeEffect.inner_specs`) or a `bind`'s ``amount``
    dict. A node's body is built lazily at `apply` time, by which point the
    spell/ability's announced {X} is already stamped on the source
    (`GameObject.x_paid`, RULE 107.3c — set at cast/activate time), so the
    substitution is done here instead, from that value. Same guard as
    `_substitute_x`: a real int magnitude never equals the literal string.
    """
    if value == "x":
        return x_paid
    if value == "-x":
        return -x_paid
    if isinstance(value, dict):
        return {k: _resolve_x(v, x_paid) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_x(v, x_paid) for v in value]
    return value


def _build(specs: list[dict[str, Any]], source: Optional[GameObject]) -> list[GameEffect]:
    from ..binding.core import build_effects  # function-scoped: effects↔binder cycle
    from ...parser.oracle.spec import EffectSpec

    x_paid = int(getattr(source, "x_paid", 0) or 0)
    return build_effects(
        [
            EffectSpec(
                type=spec["type"],
                params=_resolve_x(dict(spec.get("params") or {}), x_paid),
                condition=spec.get("condition"),
            )
            for spec in specs
        ],
        source,
    )


class _CompositeEffect(GameEffect):
    """Shared body handling for the five nodes.

    ``inner_specs`` stays serialized until the body actually runs: a node
    inside a `for_each` builds fresh per iteration (a `GameEffect` is not
    reliably reusable across passes — several stash per-pass remainders on
    themselves), and plain data survives the `state.clone()` undo takes.
    """

    def __init__(
        self,
        effects: Optional[list[Any]] = None,
        source: Optional[GameObject] = None,
    ) -> None:
        super().__init__(source)
        self.inner_specs = _as_spec_dicts(effects)

    def _run(
        self,
        specs: list[dict[str, Any]],
        context: GameContext,
        targets: Optional[list[Any]],
    ) -> bool:
        """Apply a body, inheriting this resolution's referents and tallies.

        Passing the context's own `previous_targets`/`created_objects`
        through matters: a body is a continuation of the same clause chain,
        so "that creature" inside an `if_else` branch must still mean what
        the clause before the `if_else` chose. `_apply_effects_partitioned`
        resets those to whatever it is handed, so handing it nothing would
        silently blank the referent.
        """
        if not specs:
            return False
        return _apply_effects_partitioned(
            _build(specs, self.source),
            context,
            targets,
            None,
            source=self.source,
            previous_targets=list(getattr(context, "previous_targets", []) or []),
            created_objects=list(getattr(context, "created_objects", []) or []),
            life_lost_this_way=getattr(context, "life_lost_this_way", 0),
            permanents_destroyed_this_way=getattr(
                context, "permanents_destroyed_this_way", 0
            ),
            objects_exiled_this_way=getattr(context, "objects_exiled_this_way", 0),
            damaged_this_way=list(getattr(context, "damaged_this_way", []) or []),
            previous_selector=getattr(context, "previous_selector", None),
            revealed_card=getattr(context, "revealed_card", None),
        )


class SeqEffect(_CompositeEffect):
    """``seq`` — an ordered effect list, as a single effect.

    Trivial on its own (a top-level `AbilitySpec` already runs its list in
    order) and load-bearing everywhere else: it is what lets a *branch* of an
    ``if_else``, or the body of a ``for_each``, be more than one effect
    without inventing a per-node "and also" parameter.

    RULE 601.2c fixes targets when the spell or ability is *put on the
    stack*, before any condition is evaluated or any loop runs — so a node
    may surface its body's requirements only if that body definitely runs, in
    full: `seq` (always), `optional` (a fixed singular body — RULE 601.2b
    decides only *whether*, at resolution) and `bind` (runs its body once,
    unconditionally). `if_else` and `for_each` cannot — one doesn't know
    which branch will run, the other doesn't know how many times — so they
    announce nothing, and a body clause inside them reads a target a
    *sibling* clause announced (the ``target_groups=None`` sharing
    `_apply_effects_partitioned` documents).
    """

    @property
    def target_specs(self) -> list[TargetSpec]:
        # Built lazily: `build_effects` refuses an unregistered type, so this
        # is also where a malformed body surfaces at announce time rather
        # than mid-resolution.
        specs: list[TargetSpec] = []
        for effect in _build(self.inner_specs, self.source):
            specs.extend(effect.target_specs)
        return specs

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        self._run(self.inner_specs, context, targets)


class IfElseEffect(_CompositeEffect):
    """``if_else`` — RULE 603.4's intervening-if with a real "otherwise".

    The IR could gate an effect (`EffectSpec.condition`) but not *branch*, so
    every printed "…, otherwise …" shipped as two complementary conditionals
    whose complementarity nothing recorded — the exact shape
    `ring_tempted_at_least`/`ring_tempted_at_most` and the `clash_won`
    True/False pair were invented for.

    Three-valued, via `effect_conditions.condition_state`: a condition whose
    referent doesn't exist runs **neither** branch. RULE 701.30d's
    "otherwise" must not fire because no clash happened, and "if that
    creature is a Goat … otherwise …" must not fire because no creature was
    chosen. That is precisely why ENG-36's evaluator distinguishes "no" from
    "unanswerable"; a two-valued gate would make `else` the catch-all for
    every unmodelled condition, which is fail-*open*.
    """

    def __init__(
        self,
        condition: Optional[dict[str, Any]] = None,
        then_effects: Optional[list[Any]] = None,
        else_effects: Optional[list[Any]] = None,
        source: Optional[GameObject] = None,
    ) -> None:
        super().__init__(None, source)
        self.condition = condition
        self.then_specs = _as_spec_dicts(then_effects)
        self.else_specs = _as_spec_dicts(else_effects)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        state = effect_conditions.condition_state(
            self.condition, context, self.source, targets
        )
        if state is None:
            return
        self._run(self.then_specs if state else self.else_specs, context, targets)


class OptionalEffect(_CompositeEffect):
    """``optional`` — RULE 601.2b's "You may `<effect>`." as a wrapper.

    Dozens of registered effects carry their own ``optional`` boolean, each
    with its own prompt text and its own decline handling, because "you may"
    could only be expressed *inside* an effect. As a node it wraps any body,
    including a multi-effect one — "You may sacrifice a creature. If you do,
    draw two cards." is this node around a `seq`, not a new fused type.

    The question goes through `RulesEngine.open_choice`, so it is answerable
    by the only surface a client has (ENG-35), and the body runs from the
    registered continuation once the answer arrives.
    """

    #: `continuations` kind — the handler lives on `RulesEngine` (see
    #: `game/rules/casting_mixin.py`), because answering is engine work.
    CHOICE_KIND = "composite_optional"

    @property
    def target_specs(self) -> list[TargetSpec]:
        """RULE 601.2c: an optional effect still announces its targets.

        One of three nodes that can honestly do this (`seq` and `bind` are
        the others), and for a different reason than `SeqEffect`'s. `if_else`
        and `for_each` can't because they don't know *what* will run — which
        branch, how many times. Here the body is fixed and singular; the only
        open question is *whether* it happens, and RULE 601.2b answers that at
        resolution, long after RULE 601.2c has fixed the targets on
        announcement. "When you cycle this card, you may tap target creature."
        (Choking Tethers) targets when the trigger goes on the stack; the
        player is asked on resolution.

        Found by PAR-62: routing a mid-body "you may" through this node made
        such a card `MODELED` while it silently resolved to nothing, because
        the tap got no announced target — the half-modeling the coverage gate
        exists to prevent, reached from the engine side instead of the parser
        side.
        """
        specs: list[TargetSpec] = []
        for effect in _build(self.inner_specs, self.source):
            specs.extend(effect.target_specs)
        return specs

    def __init__(
        self,
        effects: Optional[list[Any]] = None,
        prompt: str = "",
        player: str = "you",
        source: Optional[GameObject] = None,
    ) -> None:
        super().__init__(effects, source)
        self.prompt = str(prompt or "")
        #: Who is asked. "you" (the ability's controller) is every printed
        #: "you may"; ``"target"`` is "target player may …".
        self.player = player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if not self.inner_specs:
            return
        if self.player == "target":
            chooser = targets[0] if targets else None
            if chooser is None or getattr(chooser, "instance_id", None) is not None:
                return
        else:
            chooser = effect_conditions._player_by_id(
                context, effect_conditions._controller_id(self.source, context)
            )
        if chooser is None:
            return
        source_name = getattr(self.source, "name", None)
        prompt = self.prompt or (
            f"{source_name}: Effekt anwenden?" if source_name else "Effekt anwenden?"
        )
        context.engine.open_choice({
            "kind": self.CHOICE_KIND,
            "player_id": chooser.id,
            "prompt": prompt,
            "options": [
                {"id": "yes", "label": "Ja"},
                {"id": "decline", "label": "Nein"},
            ],
            "effect_specs": [dict(spec) for spec in self.inner_specs],
            "source_id": getattr(self.source, "instance_id", None),
            # RULE 601.2c: the targets were fixed when the ability went on the
            # stack (see `target_specs` above), but the body does not run until
            # this question is answered — so they have to survive the pause the
            # same way the ``previous_target_ids`` referent does, or the body
            # resumes with nothing to act on and the effect silently does
            # nothing (PAR-62).
            "target_ids": [
                getattr(obj, "instance_id", None)
                for obj in (targets or [])
                if getattr(obj, "instance_id", None) is not None
            ],
            # RULE 608.2h: the referent an earlier clause chose has to survive
            # the pause, since the resolution that established it is over by
            # the time this is answered.
            "previous_target_ids": [
                getattr(obj, "instance_id", None)
                for obj in (getattr(context, "previous_targets", []) or [])
                if getattr(obj, "instance_id", None) is not None
            ],
            # Same, for a `reveal_top` clause's stashed card — "you may put
            # **that card** onto the battlefield" (Nissa) is the body here.
            "revealed_card_id": getattr(
                getattr(context, "revealed_card", None), "instance_id", None
            ),
        })


class ForEachEffect(_CompositeEffect):
    """``for_each`` — RULE 101.4 iteration over players or selected objects.

    ``over`` names the items: ``{"players": "each_player"|"each_opponent"|
    "you"}`` (APNAP order, `GameState.living_players`), ``{"selector":
    "<name>"}`` (the one `continuous.group_selector_objects` vocabulary — this
    module defines no selectors of its own), or ``{"targets": true}`` (the
    ability's own chosen targets).

    Each item is handed to the body **as its targets**, so an ordinary
    registered effect works as a loop body with no idea it is in a loop, and
    is also exposed as `GameContext.iteration_item` for a body clause that
    needs to name it without targeting it. The iteration itself is ENG-35's
    `RulesEngine.defer_iteration`, so a body that asks a question asks it once
    per item, in order.
    """

    def __init__(
        self,
        effects: Optional[list[Any]] = None,
        over: Optional[dict[str, Any]] = None,
        source: Optional[GameObject] = None,
    ) -> None:
        super().__init__(effects, source)
        self.over = dict(over or {})

    def _items(self, context: GameContext, targets: Optional[list[Any]]) -> list[Any]:
        if self.over.get("targets"):
            return list(targets or [])
        scope = self.over.get("players")
        if scope is not None:
            if scope not in PLAYER_SCOPES:
                return []  # fail closed, like every other whitelisted name
            controller_id = effect_conditions._controller_id(self.source, context)
            living = list(context.state.living_players())
            if scope == "each_opponent":
                return [p for p in living if p.id != controller_id]
            if scope == "you":
                return [p for p in living if p.id == controller_id]
            return living
        selector = self.over.get("selector")
        if selector:
            from ..continuous import group_selector_objects  # function-scoped: cycle

            return list(group_selector_objects(
                context.state,
                effect_conditions._controller_id(self.source, context),
                str(selector), {}, src=self.source,
            ))
        return []

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        items = self._items(context, targets)
        if not items or not self.inner_specs:
            return
        # Park the whole loop and run it here: `resume_deferred_effects`
        # drains an iteration frame one item at a time, and draining it now
        # (rather than leaving it for `resolve_until_stable`) is what keeps
        # the loop *inside* this effect's own position in the enclosing list.
        context.engine.defer_iteration(
            [], items, source=self.source,
            specs=[dict(spec) for spec in self.inner_specs], item_as_target=True,
        )
        while (
            not context.state.pending_choice
            and context.state.deferred_effects
            and context.state.deferred_effects[-1].get("kind")
            == context.engine.DEFERRED_ITERATION
        ):
            context.engine.resume_deferred_effects()


class BindEffect(_CompositeEffect):
    """``bind`` — RULE 608.2's "…equal to", measured once for the body.

    "Exile target creature. You gain life equal to its power."; "Discard any
    number of cards, then draw that many." The number has to be measured
    between the two halves, which is why every one of these shipped as a
    single fused effect type: there was nowhere to *put* the measurement.

    ``amount`` is an `effect_amounts` measurement, taken once when this node
    runs, and substituted into the body wherever the sentinel ``"$<name>"``
    appears as a parameter value. The sentinel spelling follows
    `RulesEngine._substitute_x`'s established reasoning — a real magnitude
    parameter is an int and never equals a string — with a name, so nested
    binds don't collide.

    RULE 601.2c: a `bind` runs its body **exactly once, unconditionally** (an
    empty body aside), so — like `seq`, and unlike `if_else`/`for_each` — it
    can honestly announce that body's targets. "~ deals X damage to any
    target. You gain life equal to the damage dealt, but not more than the
    target's toughness/loyalty/life before the damage" (Drain Life) is a
    `bind` whose body's first clause carries the RULE 115 requirement and
    whose ``amount`` measures the target's pre-damage defensive stat.
    """

    def __init__(
        self,
        effects: Optional[list[Any]] = None,
        name: str = "n",
        amount: Any = None,
        source: Optional[GameObject] = None,
    ) -> None:
        super().__init__(effects, source)
        self.name = str(name or "n")
        self.amount = amount

    @property
    def target_specs(self) -> list[TargetSpec]:
        specs: list[TargetSpec] = []
        for effect in _build(self.inner_specs, self.source):
            specs.extend(effect.target_specs)
        return specs

    @staticmethod
    def _substitute(value: Any, sentinel: str, measured: int) -> Any:
        """Replace ``sentinel`` anywhere in a params value, at any depth."""
        if value == sentinel:
            return measured
        if isinstance(value, dict):
            return {k: BindEffect._substitute(v, sentinel, measured) for k, v in value.items()}
        if isinstance(value, list):
            return [BindEffect._substitute(v, sentinel, measured) for v in value]
        return value

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if not self.inner_specs:
            return
        # The measurement can itself be {X}-scaled — "…but not more than X"
        # (Drain Life's cap). `_substitute_x` never reaches this dict; do it
        # here from the source's announced {X} (see `_resolve_x`).
        x_paid = int(getattr(self.source, "x_paid", 0) or 0)
        amount_spec = _resolve_x(self.amount, x_paid) if x_paid else self.amount
        measured = effect_amounts.amount_of(amount_spec, context, self.source, targets)
        sentinel = f"${self.name}"
        bound = [
            {**spec, "params": self._substitute(
                dict(spec.get("params") or {}), sentinel, measured
            )}
            for spec in self.inner_specs
        ]
        self._run(bound, context, targets)


EffectRegistry.register(
    # A list as a value — see `SeqEffect`.
    "seq",
    lambda p: SeqEffect(effects=p.get("effects")),
)
EffectRegistry.register(
    # RULE 603.4 / 701.30d — "if <condition>, A. Otherwise, B."
    "if_else",
    lambda p: IfElseEffect(
        condition=p.get("condition"),
        then_effects=p.get("then"),
        else_effects=p.get("else"),
    ),
)
EffectRegistry.register(
    # RULE 601.2b — "You may <effect>."
    "optional",
    lambda p: OptionalEffect(
        effects=p.get("effects"),
        prompt=p.get("prompt", ""),
        player=p.get("player", "you"),
    ),
)
EffectRegistry.register(
    # RULE 101.4 — "For each <player/permanent>, <effect>."
    "for_each",
    lambda p: ForEachEffect(effects=p.get("effects"), over=p.get("over")),
)
EffectRegistry.register(
    # RULE 608.2 — "<effect> equal to <measurement>."
    "bind",
    lambda p: BindEffect(
        effects=p.get("effects"), name=p.get("name", "n"), amount=p.get("amount"),
    ),
)
