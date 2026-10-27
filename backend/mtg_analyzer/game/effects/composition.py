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

from ...models.game.player import Player

from typing import Any, Optional

from ...models.cards import card_query
from ...models.game.game_object import GameObject
from .. import effect_amounts, effect_conditions
from ..targeting import TargetSpec
from .core import EffectRegistry, GameContext, GameEffect, _apply_effects_partitioned

#: How a `for_each` names the players it iterates, in APNAP order (RULE
#: 101.4). Deliberately the same three words `SacrificeEffect.selector` and
#: `MillEffect.player_selector` already use, rather than a fourth spelling.
PLAYER_SCOPES: frozenset[str] = frozenset({"each_player", "each_opponent", "each_other_player", "you", "each_opponent_except_defending"})


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


def _resolve_chosen(value: Any, source: Optional[GameObject]) -> Any:
    """PAR-203 (RULE 608.2d): swap the "the chosen type/color/name" placeholders for what the ``choose_for_source``
    effect stamped on ``source`` earlier in this resolution. A placeholder with no answer stays as it is, so the
    filter that carries it matches nothing rather than everything."""
    from ...parser.oracle.spec import CHOSEN_COLOR_SENTINEL, CHOSEN_NAME_SENTINEL, CHOSEN_TYPE_SENTINEL

    answers = {
        CHOSEN_TYPE_SENTINEL: getattr(source, "chosen_type", None),
        CHOSEN_COLOR_SENTINEL: getattr(source, "chosen_color", None),
        CHOSEN_NAME_SENTINEL: getattr(source, "chosen_card_name", None),
    }

    def walk(node: Any) -> Any:
        if isinstance(node, str):
            # "$chosen_type" in a filter key is the lowercase subtype word the filters compare with.
            if node == CHOSEN_TYPE_SENTINEL and answers[node]:
                return str(answers[node]).lower()
            return answers.get(node) or node
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(value)


def _build(specs: list[dict[str, Any]], source: Optional[GameObject]) -> list[GameEffect]:
    from ..binding.core import build_effects  # function-scoped: effects↔binder cycle
    from ...parser.oracle.spec import EffectSpec

    x_paid = int(getattr(source, "x_paid", 0) or 0)

    def params_of(spec: dict[str, Any]) -> dict[str, Any]:
        params = _resolve_x(dict(spec.get("params") or {}), x_paid)
        if spec["type"] == "seq":
            # A nested ``seq`` builds its own body when *it* runs. Resolving the "$chosen_*" placeholders in that body
            # here would read whatever an earlier use of the source left stamped, before this resolution's choice (a
            # sibling ahead of it in this list) has been answered (PAR-203).
            return {**_resolve_chosen({k: v for k, v in params.items() if k != "effects"}, source),
                    **({"effects": params["effects"]} if "effects" in params else {})}
        return _resolve_chosen(params, source)

    return build_effects(
        [
            EffectSpec(
                type=spec["type"],
                params=params_of(spec),
                condition=spec.get("condition"),
            )
            for spec in specs
        ],
        source,
    )


def antecedent_impossible(antecedent: list[dict[str, Any]], source: Optional[GameObject], context: GameContext) -> bool:
    """An "if you do" antecedent that cannot be performed in full is not offered (RULE 609.3 applies to the
    instruction, but the question is only worth asking when "if you do" can come true): "exile two cards from
    your graveyard" needs two."""
    for spec in antecedent:
        if spec.get("type") == "choose_objects":
            # "tap two other untapped creatures": fewer than two to pick cannot do it, so "if you do" cannot hold.
            chooser = _build([spec], source)[0]
            pooled = chooser.pool_candidates(context)
            needed = chooser.count
            if pooled is None or (isinstance(needed, int) and len(pooled[1]) < needed):
                return True
        if spec.get("type") == "exile_own_graveyard_cards":
            controller = effect_conditions._player_by_id(context, effect_conditions._controller_id(source, context))
            params = spec.get("params") or {}
            needed = max(1, int(params.get("count", 1)))
            card_type = str(params.get("card_type") or "").lower()
            pool = [o for o in (controller.graveyard if controller is not None else [])
                    if not card_type or card_type in (o.card.type_line or "").lower().split("—")[0]]
            if controller is None or len(pool) < needed:
                return True
    return False


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

    @property
    def created_objects_are_referent(self) -> bool:
        # Copy-producing compositions retain the copy effect's existing referent contract.
        if not self.inner_specs:
            return False
        last = _build(self.inner_specs[-1:], self.source)
        return bool(last and getattr(last[-1], "created_objects_are_referent", False))

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
            _build(effect_conditions.pin_source_reference(
                specs, self.source, context.resolving_source_incarnation,
            ), self.source),
            context,
            targets,
            None,
            source=self.source,
            previous_targets=list(getattr(context, "previous_targets", []) or []),
            created_objects=list(getattr(context, "created_objects", []) or []),
            life_lost_this_way=getattr(context, "life_lost_this_way", 0),
            excess_damage_this_way=getattr(context, "excess_damage_this_way", 0),
            permanents_destroyed_this_way=getattr(
                context, "permanents_destroyed_this_way", 0
            ),
            objects_exiled_this_way=getattr(context, "objects_exiled_this_way", 0),
            counters_removed_this_way=getattr(context, "counters_removed_this_way", 0),
            damaged_this_way=list(getattr(context, "damaged_this_way", []) or []),
            previous_selector=getattr(context, "previous_selector", None),
            revealed_card=getattr(context, "revealed_card", None),
            # What the body made is a referent for the clauses after this node too: "create X tokens …, where X is
            # …. Exile the tokens at the beginning of the next end step." (Nacatl War-Pride's `bind`).
            created_sink=context.created_objects,
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

    def __init__(
        self,
        effects: Optional[list[Any]] = None,
        source: Optional[GameObject] = None,
        if_you_do_from: Optional[int] = None,
        else_effects: Optional[list[Any]] = None,
    ) -> None:
        super().__init__(effects, source)
        #: PAR-208 (RULE 608.2c): "A. If you do, B. **Otherwise / If you don't**, C." -- C runs when A could not be
        #: performed or changed nothing. Only meaningful beside ``if_you_do_from``.
        self.else_specs = _as_spec_dicts(else_effects) if if_you_do_from else []
        #: RULE 608.2c / 603.12 "A. **When/If you do**, B." with no "you may" of its own: the number of leading
        #: ``effects`` that are A. B (the rest) waits behind `IfYouDoEffect`'s check that A changed the game --
        #: the unconditional sibling of `OptionalEffect.if_you_do_from` (the optional question is the ability's).
        self.if_you_do_from = (
            if_you_do_from if isinstance(if_you_do_from, int) and 0 < if_you_do_from < len(self.inner_specs) else None
        )

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        split = self.if_you_do_from
        if not split:
            self._run(self.inner_specs, context, targets)
            return
        antecedent, payoff = self.inner_specs[:split], self.inner_specs[split:]
        if antecedent_impossible(antecedent, self.source, context):
            # "exile 5 cards from your graveyard" with 3 there cannot come true: B never runs, C ("otherwise") does.
            self._run(self.else_specs, context, targets)
            return
        built = _build(effect_conditions.pin_source_reference(
            antecedent, self.source, context.resolving_source_incarnation), self.source)
        if not all(spec.get("type") in ALWAYS_DONE_ANTECEDENTS for spec in antecedent):
            built.append(IfYouDoEffect(game_fingerprint(context, self.source), payoff, self.source, self.else_specs))
        else:
            built += _build(payoff, self.source)
        _apply_effects_partitioned(
            built, context, targets, None, source=self.source,
            previous_targets=list(getattr(context, "previous_targets", []) or []),
            created_objects=list(getattr(context, "created_objects", []) or []),
            created_sink=context.created_objects,
        )


#: `TriggerSubjectReferentEffect.event_key` naming the remembered subject rather than an event field.
REMEMBERED_EVENT_KEY = "remembered"


class EntryEffect(SeqEffect):
    """A sequence expanded into before-entry instructions by the binder."""
    is_enter_effect = True
    description = ""


class TriggerSubjectReferentEffect(_CompositeEffect):
    """PAR-123: the object that fired a RULE 603.1 group trigger as the referent of "it"/"that
    creature" — and, given a body, the thing that body acts on.

    "Whenever a creature you control enters, **it** explores" / "…put a +1/+1 counter on **that
    creature**" name the firing object, which is not a RULE 115 target: nothing was chosen and
    nothing can become illegal. This seeds `GameContext.previous_targets` with it, so every effect
    that already reads that referent for its pronoun (explore, endure, phase out, fight, connive,
    goad, …) works under a group trigger without each growing its own trigger-event read.

    With a ``body`` the effects run against that object as their ``targets`` — the parser reads
    "destroy it" as the targeted "destroy target permanent" and wraps it, so *every* effect that
    has a targeted form gains the firing-object reading, and the body's own target requirement is
    deliberately not announced (this node exposes none; the object was never chosen).
    ``event_key`` names the event field carrying the object's id (the binder resolves the group
    sentinel per event type). An object that is gone leaves the referent empty, so a following
    pronoun clause does nothing rather than reaching for another permanent.
    """

    def __init__(
        self, effects: Optional[list[Any]] = None, event_key: Optional[str] = None,
        acting: Optional[str] = None, source: Optional[GameObject] = None,
        referent: str = 'trigger_subject',
    ) -> None:
        super().__init__(effects, source)
        # "attached" is RULE 303.4/301.5's host of an Aura/Equipment source (`subject_of` resolves it); it stays out of
        # EFFECT_SUBJECTS so a standing condition's ``of: attached`` keeps resolving through `static_conditions`.
        if referent not in effect_conditions.EFFECT_SUBJECTS and referent != 'attached':
            raise ValueError('Unknown body referent')
        self.referent = referent
        self.event_key = event_key or "instance_id"
        #: ``"controller"`` runs the body *as* the firing object's controller ("its controller
        #: creates a token"): every "you" in it — who creates, draws, sacrifices, whose lands
        #: "you control" — is that player (`GameContext.acting_player_id`, RULE 109.5).
        #: ``"event_player"`` is the same for a *player* event ("that attacking player …"): the
        #: acting player is the one the event names and no firing object is looked up.
        #: ``"active_player"`` does the same for phase events (RULE 504), which
        #: identify the step rather than carrying a player_id.
        self.acting = acting if acting in ("controller", "event_player", "active_player") else None

    @property
    def target_specs(self) -> list[TargetSpec]:
        # RULE 601.2c: a targeted body always runs once for its announced
        # subject. Event-derived subjects continue to announce no targets.
        if self.referent != 'target':
            return []
        return [spec for effect in _build(self.inner_specs, self.source) for spec in effect.target_specs]

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.acting in ("event_player", "active_player"):
            # "Whenever a player attacks …, **that attacking player** creates a Treasure token"
            # (Jolene, the Curses): there is no firing *object*, only the player the event names
            # (`player_id`); the body is the second-person clause run as that player (RULE 109.5).
            event = context.trigger_event or {}
            player_id = (getattr(context.state.active_player, "id", None)
                         if self.acting == "active_player"
                         else event.get("player_id") or event.get("attacking_player_id"))
            if player_id is None or not self.inner_specs:
                return
            outer = context.acting_player_id
            context.acting_player_id = player_id
            try:
                self._run(self.inner_specs, context, targets)
            finally:
                context.acting_player_id = outer
            return
        if self.referent != 'trigger_subject':
            subject = effect_conditions.subject_of(self.referent, context, self.source, targets)
            object_id = getattr(subject, 'instance_id', None)
        elif self.event_key == REMEMBERED_EVENT_KEY:
            # A body that runs after the trigger's window closed (a payment's "if you do"): the
            # object `PayCostThenEffect(remember_trigger_subject)` stamped on the source.
            object_id = getattr(self.source, "remembered_instance_id", None)
        else:
            object_id = (context.trigger_event or {}).get(self.event_key)
        firing = (subject if self.referent != 'trigger_subject'
                  else context.state.find_object(object_id) if object_id is not None else None)
        # RULE 400.7: a damage recipient / targeted host that left and returned is a new object.
        incarnation_key = {"target_id": "target_zone_incarnation", "instance_id": "instance_zone_incarnation"}.get(self.event_key)
        incarnation = (context.trigger_event or {}).get(incarnation_key) if incarnation_key else None
        if firing is not None and incarnation is not None and firing.zone_incarnation != incarnation:
            firing = None
        context.previous_targets = [firing] if firing is not None else []
        if firing is None or not self.inner_specs:
            return
        if self.acting is None:
            self._run(self.inner_specs, context, [firing])
            return
        outer = context.acting_player_id
        context.acting_player_id = getattr(firing, "controller_id", None)
        try:
            self._run(self.inner_specs, context, [firing])
        finally:
            context.acting_player_id = outer


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

    @property
    def target_specs(self) -> list[TargetSpec]:
        """RULE 601.2c: announce only what *either* branch would target.

        Not knowing which branch runs is why this node normally announces
        nothing. "Put a +1/+1 counter on target creature … double the counters
        on that creature instead" (Scythecat Cub) targets the same creature
        either way, so identical requirements on both sides are announced.
        """
        then_targets = [spec for effect in _build(self.then_specs, self.source)
                        for spec in effect.target_specs]
        else_targets = [spec for effect in _build(self.else_specs, self.source)
                        for spec in effect.target_specs]
        # RULE 702.174m: when the cast already decided the condition (a promised gift),
        # only the branch that will run announces its targets.
        decided = effect_conditions.announced_state(self.condition, self.source)
        if decided is not None:
            return then_targets if decided else else_targets
        return then_targets if then_targets == else_targets else []

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
        player: Any = "you",
        source: Optional[GameObject] = None,
        else_effects: Optional[list[Any]] = None,
        if_you_do_from: Optional[int] = None,
    ) -> None:
        super().__init__(effects, source)
        #: "You may X. **If you do**, Y." (RULE 608.2c): the number of leading ``effects`` that are X. Y (the rest)
        #: runs only when X actually changed the game (`IfYouDoEffect`), not whenever the question was answered
        #: "yes". ``None`` is the older "you may do all of this" body with no outcome test.
        self.if_you_do_from = if_you_do_from if isinstance(if_you_do_from, int) and 0 < if_you_do_from < len(self.inner_specs) else None
        #: "…may sacrifice it. **If they don't**, ~ deals 5 damage to that player." (Star Athlete, Enchanter's Bane) — the body
        #: that runs when the question is declined; carried on the pending choice like ``effect_specs``.
        self.else_specs = _as_spec_dicts(else_effects)
        self.prompt = str(prompt or "")
        #: Who is asked. "you" (the ability's controller) is every printed
        #: "you may"; ``"target"`` is "target player may …"; a
        #: ``{"of": …, "as": "controller"}`` referent dict (PAR-117) is
        #: "**its controller** may …" — the RULE 603.1 group-subject firing
        #: object's own controller, not this ability's source's (Edric,
        #: Spymaster of Trest/Brood Sliver/Synapse Sliver: "whenever a
        #: creature [you control] deals combat damage to a player, its
        #: controller may draw a card."). Resolved through the same
        #: `game/effect_operands.py` vocabulary `GainLifeEffect`/
        #: `DrawCardEffect`'s own referent operand already reads, rather than
        #: a fourth hardcoded string alongside "you"/"target" — the
        #: engine's "who" answer already has to agree for the mandatory
        #: sibling of this same clause ("its controller gains that much
        #: life."), so the optional one asking a different question ("may
        #: they?") of the same referent should read it the same way.
        self.player = player

    def _antecedent_impossible(self, context: GameContext) -> bool:
        return antecedent_impossible(self.inner_specs[: self.if_you_do_from], self.source, context)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if not self.inner_specs and not self.else_specs:
            return
        if self.if_you_do_from and self._antecedent_impossible(context):
            # PAR-208: an antecedent that cannot come true is not offered, and "if you don't" then holds.
            self._run(self.else_specs, context, targets)
            return
        referent_subject_id = None
        if self.player == "target":
            chooser = targets[0] if targets else None
            if chooser is None or getattr(chooser, "instance_id", None) is not None:
                return
        elif isinstance(self.player, dict):
            # PAR-117: "its controller may …" — the referent vocabulary's
            # own player resolution (function-scoped import: effects↔
            # effect_operands cycle, the same reason `GameEffect.
            # _operand_player` imports it this way).
            from .. import effect_operands

            chooser = effect_operands.player_for(self.player, context, self.source, targets)
            # RULE 603.1: "its controller" both *asks* and, once answered,
            # *acts* — Edric, Spymaster of Trest's own "may draw a card" is
            # the same referent doing both. `context.trigger_event` (what
            # the resolution above just read to find that referent) is
            # gone by the time the choice comes back — it's only ever live
            # for the resolution that opened it — so the inner body's own
            # identical ``{"of": "entering", …}`` referent (its own
            # "player"/`CreateTokenEffect.creators="trigger_subject_
            # controller"` field) has nothing to re-resolve against unless
            # the *object* this referent named is captured now, while it's
            # still known, and restored around the inner body at resume
            # time (`_resume_composite_optional`) — same idea as
            # ``target_ids``/``previous_target_ids`` below, one step
            # earlier in the referent chain. `effect_conditions` is already
            # imported at module level (not function-scoped here, unlike
            # `effect_operands` above — re-importing it locally would shadow
            # that module-level name for this whole function, breaking the
            # plain "you"/`_controller_id` branch below).
            subject = effect_conditions.subject_of(
                str(self.player.get("of") or "source"), context, self.source, targets,
            )
            referent_subject_id = getattr(subject, "instance_id", None)
        else:
            chooser = effect_conditions._player_by_id(
                context, effect_conditions._controller_id(self.source, context)
            )
        if chooser is None:
            return
        if referent_subject_id is None:
            # MEC-99: the *body* can need the RULE 603.1 group-subject firing
            # object even when "you" (not "its controller") is who's asked —
            # "whenever a creature you control attacks and isn't blocked, you
            # may have **it** deal damage equal to its power to target
            # creature." (Gaze of Pain) asks the controller, but the inner
            # `dealer_kind`/`subject="trigger_subject"` effects still need to
            # act as the attacker, not the ability's own (nonexistent, for a
            # turn-scoped trigger) source. Same capture-now/restore-at-resume
            # reasoning as the dict branch above, just not gated on ``player``
            # being the referent that's asked.
            referent_subject_id = (getattr(context, "trigger_event", None) or {}).get("instance_id")
        source_name = getattr(self.source, "name", None)
        prompt = self.prompt or (
            f"{source_name}: Effekt anwenden?" if source_name else "Effekt anwenden?"
        )
        context.engine.open_choice({
            "referent_subject_id": referent_subject_id,
            "kind": self.CHOICE_KIND,
            "source_incarnation": (getattr(context, "resolving_source_incarnation", None)
                                   if getattr(context, "resolving_source_incarnation", None) is not None
                                   else getattr(self.source, "zone_incarnation", None)),
            "copiable_stack_id": (context.trigger_event or {}).get("copiable_stack_id"),
            "player_id": chooser.id,
            "prompt": prompt,
            "options": [
                {"id": "yes", "label": "Ja"},
                {"id": "decline", "label": "Nein"},
            ],
            "effect_specs": [dict(spec) for spec in self.inner_specs],
            "else_specs": [dict(spec) for spec in self.else_specs],
            "if_you_do_from": self.if_you_do_from,
            "source_id": getattr(self.source, "instance_id", None),
            # RULE 601.2c: the targets were fixed when the ability went on the
            # stack (see `target_specs` above), but the body does not run until
            # this question is answered — so they have to survive the pause the
            # same way the ``previous_target_ids`` referent does, or the body
            # resumes with nothing to act on and the effect silently does
            # nothing (PAR-62).
            "target_player_ids": [obj.id for obj in (targets or []) if isinstance(obj, Player)],
            "target_ids": [
                getattr(obj, "instance_id", None)
                for obj in (targets or [])
                if getattr(obj, "instance_id", None) is not None
            ],
            # RULE 608.2h: the referent an earlier clause chose has to survive
            # the pause, since the resolution that established it is over by
            # the time this is answered.
            "previous_player_ids": [
                obj.id for obj in (getattr(context, "previous_targets", []) or [])
                if isinstance(obj, Player)
            ],
            "previous_target_ids": [
                getattr(obj, "instance_id", None)
                for obj in (getattr(context, "previous_targets", []) or [])
                if getattr(obj, "instance_id", None) is not None
            ],
            # RULE 400.7: an optional rider keeps the creations' exact zone visits across its question.
            "created_object_visits": [
                {"instance_id": obj.instance_id, "zone_incarnation": obj.zone_incarnation}
                for obj in context.created_objects
            ],
            # Same, for a `reveal_top` clause's stashed card — "you may put
            # **that card** onto the battlefield" (Nissa) is the body here.
            "revealed_card_id": getattr(
                getattr(context, "revealed_card", None), "instance_id", None
            ),
            # RULE 109.5: a body run *as* another player ("that attacking player may create a
            # token") has to still be that player's once the question is answered.
            "acting_player_id": (getattr(context, "acting_player_id", None)
                                 or getattr(context, "resolving_controller_id", None)),
        })


#: Antecedent effect types whose "if you do" is satisfied by *attempting* them: a search that finds nothing was
#: still a search (RULE 701.23), though it leaves the zones unchanged. Every other antecedent must change the game.
ALWAYS_DONE_ANTECEDENTS: frozenset[str] = frozenset({"search"})


def game_fingerprint(context: GameContext, source: Optional[GameObject]) -> tuple:
    """What an antecedent instruction could have changed: every zone's membership, life, the permanents' tapped
    state and counters, and where the source is. Order within a zone is ignored (a shuffle is not progress)."""
    state = context.state
    players = tuple(
        (
            player.id, player.life, frozenset(o.instance_id for o in player.hand),
            len(player.library), frozenset(o.instance_id for o in player.graveyard),
            frozenset(o.instance_id for o in getattr(player, "exile", []) or []),
        )
        for player in state.players
    )
    battlefield = frozenset(
        (o.instance_id, bool(o.tapped), tuple(sorted((getattr(o, "counters", None) or {}).items())),
         getattr(o, "attached_to", None), getattr(o, "damage_marked", 0))
        for o in state.battlefield
    )
    return (players, battlefield, getattr(source, "zone", None), getattr(source, "zone_incarnation", None),
            len(state.stack))


class IfYouDoEffect(_CompositeEffect):
    """RULE 608.2c: "You may X. **If you do**, Y." -- Y runs only if X was actually performed.

    ``before`` is `game_fingerprint` taken just before X; this node sits right after X in the same effect list
    (so X's pauses, referents and tallies flow through unchanged) and compares. X that did nothing -- a draw from
    an empty library, tapping what is already tapped, exiling a card that has left -- leaves Y undone.
    """

    def __init__(
        self, before: tuple, effects: Optional[list[Any]] = None, source: Optional[GameObject] = None,
        else_effects: Optional[list[Any]] = None,
    ) -> None:
        super().__init__(effects, source)
        self.before = before
        #: PAR-208: the "otherwise / if you don't" branch, run when X changed nothing.
        self.else_specs = _as_spec_dicts(else_effects)

    @property
    def target_specs(self) -> list[TargetSpec]:
        return []  # Y's targets were announced with the enclosing ability (`OptionalEffect.target_specs`).

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if game_fingerprint(context, self.source) != self.before:
            self._run(self.inner_specs, context, targets)
        elif self.else_specs:
            self._run(self.else_specs, context, targets)


class ForEachEffect(_CompositeEffect):
    """``for_each`` — RULE 101.4 iteration over players or selected objects.

    ``over`` names the items: ``{"players": "each_player"|"each_opponent"|
    "you"}`` (APNAP order, `GameState.living_players`), ``{"selector":
    "<name>"|<structured dict>}`` (the one `continuous.group_selector_objects`
    vocabulary — this module defines no selectors of its own),
    ``{"targets": true}`` (the ability's own chosen targets), or ``{"batch_members":
    true}`` (the matched members of the firing RULE 603.2c batch).

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
        if self.over.get("created_objects"):
            return list(context.created_objects)
        if self.over.get("previous_targets"):
            return list(context.previous_targets)
        if self.over.get("targets"):
            return list(targets or [])
        if self.over.get("batch_members"):
            # RULE 603.2c (PAR-119): "for each of them" — the firing batch's members that
            # matched the head, as captured when it triggered (`matching_ids`).
            event = getattr(context, "trigger_event", None) or {}
            found = (context.state.find_object(i) for i in event.get("matching_ids") or [])
            return [obj for obj in found if obj is not None]
        this_way = self.over.get("this_way")
        if this_way is not None:
            return self._this_way_items(context, str(this_way))
        scope = self.over.get("players")
        if scope is not None:
            if scope not in PLAYER_SCOPES:
                return []  # fail closed, like every other whitelisted name
            controller_id = effect_conditions._controller_id(self.source, context)
            living = list(context.state.living_players_apnap())
            if scope == "each_opponent":
                return [p for p in living if p.id != controller_id]
            if scope == "each_other_player":
                # RULE 608.2c: "other" excludes the player just named (e.g. the
                # caster in Zenith Chronicler), otherwise the ability's controller.
                ref = self.over.get("except_player_ref")
                excluded = effect_conditions.subject_of(ref or "trigger_player", context, self.source, targets)
                excluded_id = getattr(excluded, "id", None) if excluded is not None else controller_id
                return [p for p in living if p.id != excluded_id]
            if scope == "each_opponent_except_defending":
                # RULE 702.116a (Myriad): "each opponent other than defending player".
                defending = (getattr(context, "trigger_event", None) or {}).get("defending_player_id")
                return [p for p in living if p.id not in (controller_id, defending)]
            if scope == "you":
                return [p for p in living if p.id == controller_id]
            return living
        if self.over.get("previous_selector"):
            from .attachments_transforms import previous_group_objects

            return previous_group_objects(context, self.source, context.previous_selector)
        selector = self.over.get("selector")
        controller_id = effect_conditions._controller_id(self.source, context)
        if isinstance(selector, dict) and selector.get("of") == "context":
            # RULE 608.2h: the earlier player, or the earlier permanent's controller.
            subject = effect_conditions.subject_of(selector.get("controller_ref"), context, self.source, targets)
            controller_id = (getattr(subject, "id", None) if hasattr(subject, "life")
                             else getattr(subject, "controller_id", None))
            if controller_id is None:
                return []
            selector = {**selector, "of": "you"}
        if isinstance(selector, dict) and selector.get("zone", "battlefield") != "battlefield":
            # PAR-153: "for each creature card you own in exile with a memory counter on it" (Altaïr) — a card
            # zone, which `group_selector_objects` (battlefield statics) does not read.
            from ..continuous import _structured_selector_objects  # function-scoped: cycle

            return list(_structured_selector_objects(
                context.state, controller_id, selector, self.source,
            ))
        if selector:
            from ..continuous import group_selector_objects  # function-scoped: cycle

            return list(group_selector_objects(
                context.state,
                controller_id,
                selector, {}, src=self.source,
            ))
        return []

    def _this_way_items(self, context: GameContext, verb: str) -> list[Any]:
        """RULE 608.2c: the objects an earlier instruction of this resolution destroyed / exiled — "for each
        creature exiled this way". ``this_way_type`` / ``this_way_nontoken`` narrow it ("each nontoken creature")."""
        pool = {"destroyed": "destroyed_objects", "exiled": "exiled_objects"}.get(verb)
        if pool is None:
            return []  # fail closed on an unlisted verb
        wanted = self.over.get("this_way_type")
        if isinstance(wanted, str):
            wanted = [wanted]
        items = []
        for obj in getattr(context, pool, []) or []:
            if self.over.get("this_way_nontoken") and getattr(obj, "is_token", False):
                continue
            if wanted and not card_query.matches(obj.card, {"type": [str(w) for w in wanted]}):
                continue
            items.append(obj)
        return items

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        items = self._items(context, targets)
        if not items or not self.inner_specs:
            return
        # RULE 603.2c: a plural object action is one instruction even if a member opens a choice.
        owns_hold = bool(self.over.get("simultaneous")) and not context.state._batch_hold
        if owns_hold:
            context.state.hold_batches()
            context.state.deferred_effects.append({"kind": context.engine.DEFERRED_BATCH_END})
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
            in (context.engine.DEFERRED_ITERATION, context.engine.DEFERRED_BATCH_END)
        ):
            context.engine.resume_deferred_effects()
        if self.over.get("remember"):
            context.previous_targets = list(items)
            if isinstance(self.over.get("selector"), dict) and self.over["selector"].get("of") == "context":
                # RULE 400.7: later "those creatures" remembers the selected zone visits,
                # not a controller reference which the loop's body may have overwritten.
                context.previous_selector = {"zone_visits": [(o.instance_id, o.zone_incarnation) for o in items]}


#: `TargetGroupEffect.shares` vocabulary → the `combat.matches_object_filter` relative key that implements it.
#: Closed like every other whitelisted name; an unlisted word makes the node do nothing (fail closed).
TARGET_GROUP_SHARES: dict[str, str] = {"color": "shares_color_with_reference", "name": "named_as_reference"}

#: The `TargetGroupEffect.then_effects` sentinel for the total damage the group's loop actually dealt
#: ("You gain life equal to the damage dealt this way" — Brightflame). Substituted like a `bind` name.
DAMAGE_DEALT_SENTINEL = "$damage_dealt"


def shared_characteristic_group(
    context: GameContext, seed: Any, shares: str, filt: Optional[dict[str, Any]] = None,
) -> list[Any]:
    """``seed`` plus every *other* battlefield object matching ``filt`` that shares the ``shares``
    characteristic with it (RULE 105.2 colour) — "target X and each other Y that shares a color with it".
    The seed leads the list; an unlisted ``shares`` word or a non-object seed gives ``[]`` (fail closed)."""
    from .. import combat  # function-scoped: combat imports effects lazily too

    key = TARGET_GROUP_SHARES.get(shares)
    if key is None or not hasattr(seed, "instance_id"):
        return []
    wanted = {**(filt or {}), key: True}
    others = [
        obj for obj in context.state.permanents()
        if obj is not seed
        and combat.matches_object_filter(obj, wanted, reference=seed, state=context.state)
    ]
    return [seed, *others]


class TargetGroupEffect(_CompositeEffect):
    """``target_group`` — "<effect> target X **and each other Y that shares a color with it**" (RULE 105.2).

    One target is announced (RULE 601.2c: the body's *first* effect's requirement is this node's only
    one — the "it"/"those" of any later body effect is that group, not another target). At resolution the
    group is the target plus every other permanent matching ``filter`` that shares the named characteristic
    with it *as it is now* (RULE 608.2h: a group is "each other Y", determined on resolution), and the body
    runs once per member with that member as its target (`ForEachEffect`'s ``item_as_target`` machinery).
    The group's other members are not targets, so hexproof/protection from the *spell* does not exclude
    them (the damage/protection rules of the body still apply to each).

    RULE 608.2b: if the one target is illegal on resolution the spell/ability does not resolve at all, so no
    group is formed (the engine's fizzle check already runs before `apply`); a target that has since
    stopped being a creature of the right kind is simply not a seed (`targets` empty → no-op). A colourless
    target shares no colour: the group is the target alone.

    ``then_effects`` run once after the loop with `DAMAGE_DEALT_SENTINEL` replaced by the damage the loop
    dealt from this node's source (RULE 120.4: damage actually dealt, after prevention).
    """

    def __init__(
        self,
        effects: Optional[list[Any]] = None,
        shares: str = "color",
        filter: Optional[dict[str, Any]] = None,  # noqa: A002 - the spec param is spelled `filter` everywhere
        then_effects: Optional[list[Any]] = None,
        source: Optional[GameObject] = None,
    ) -> None:
        super().__init__(effects, source)
        self.shares = shares
        self.filter = dict(filter or {})
        self.then_specs = _as_spec_dicts(then_effects)

    @property
    def target_specs(self) -> list[TargetSpec]:
        for effect in _build(self.inner_specs[:1], self.source):
            return list(effect.target_specs)
        return []

    def _group(self, context: GameContext, seed: Any) -> list[Any]:
        return shared_characteristic_group(context, seed, self.shares, self.filter)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ...models.game.events import EventType  # function-scoped: models/game import cycle guard

        if not targets or not self.inner_specs:
            return
        items = self._group(context, targets[0])
        if not items:
            return
        log_start = len(context.state.event_log)
        # RULE 603.2c: all members of this single instruction move as one batch.
        if not context.state._batch_hold:
            context.state.hold_batches()
            context.state.deferred_effects.append({"kind": context.engine.DEFERRED_BATCH_END})
        context.engine.defer_iteration(
            [], items, source=self.source,
            specs=[dict(spec) for spec in self.inner_specs], item_as_target=True,
        )
        while (
            not context.state.pending_choice
            and context.state.deferred_effects
            and context.state.deferred_effects[-1].get("kind") in (
                context.engine.DEFERRED_ITERATION, context.engine.DEFERRED_BATCH_END)
        ):
            context.engine.resume_deferred_effects()
        if not self.then_specs:
            return
        source_id = getattr(self.source, "instance_id", None)
        dealt = sum(
            int(e.get("amount", 0) or 0) for e in context.state.event_log[log_start:]
            if e.type == EventType.DAMAGE and e.get("source_id") == source_id
        )
        bound = [
            {**spec, "params": BindEffect._substitute(dict(spec.get("params") or {}), DAMAGE_DEALT_SENTINEL, dealt)}
            for spec in self.then_specs
        ]
        self._run(bound, context, targets)


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
        if value == f"-{sentinel}":
            return -measured  # "gets -X/-X until end of turn, where X is …"
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
    lambda p: SeqEffect(
        effects=p.get("effects"), if_you_do_from=p.get("if_you_do_from"), else_effects=p.get("else_effects"),
    ),
)
EffectRegistry.register("entry_effect", lambda p: EntryEffect(effects=p.get("effects")))
EffectRegistry.register(
    # PAR-123 — a group trigger's firing object as the referent of "it"/"that creature".
    "trigger_subject_referent",
    lambda p: TriggerSubjectReferentEffect(
        effects=p.get("effects"), event_key=p.get("event_key"), acting=p.get("acting"),
        referent=p.get('referent', 'trigger_subject'),
    ),
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
        else_effects=p.get("else_effects"),
        if_you_do_from=p.get("if_you_do_from"),
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
EffectRegistry.register(
    # RULE 105.2 / 608.2 — "<effect> target X and each other Y that shares a color with it."
    "target_group",
    lambda p: TargetGroupEffect(
        effects=p.get("effects"), shares=str(p.get("shares", "color")),
        filter=p.get("filter"), then_effects=p.get("then_effects"),
    ),
)
