"""Bind `AbilitySpec` data into live `GameEffect` objects (docs/09 back-end).

Reference: docs/concepts/09_ORACLE_EFFECT_PARSER.md ("RUNTIME LINKING: parse-on-load,
bind-per-game" and the two-stage compiler).

This is the parser *back-end*: it takes the pure `AbilitySpec` IR the
front-end produced and turns it into the engine's `GameEffect` objects,
using only the whitelisted `EffectRegistry`. It is the one place allowed to
bridge `parser.oracle` (pure data) and `game.effects` (behaviour).

Binding is **per game instance** (each `GameEffect` carries its own
`source`), so it runs when a `GameObject` is created — never persisted.
Unknown effect types are refused here (`BindError`) rather than executing
anything derived from card text: the security boundary from docs/09.
"""

from __future__ import annotations

from typing import Any, Callable, Optional, Union

from ..models.events import EventType
from ..parser.oracle.spec import AbilitySpec, EffectSpec
from .costs import parse_activation_cost
from .effects import (
    ActivatedAbility,
    AttachEffect,
    EffectRegistry,
    GameEffect,
    LoseLifeEffect,
    PumpEffect,
    ReplacementEffect,
    ReplacementRegistry,
    SacrificeEffect,
    StaticAbility,
    TriggeredAbility,
)

#: Ability kinds `bind_ability` realizes into `GameEffect` objects. Keyword
#: abilities don't produce effects — flag keywords dock onto the object's
#: `intrinsic_keywords` in `attach_to_object` instead — so they're handled
#: there, not here.
_SUPPORTED_KINDS: frozenset[str] = frozenset(
    {"spell_effect", "triggered", "activated", "static", "replacement", "enter_replacement"}
)

#: Params that make a keyword *parametric* (kicker cost, annihilator N,
#: protection quality). Every parametric keyword's parameter is carried onto
#: `GameObject.parametric_keywords`; landwalk, annihilator/afflict/bushido
#: (`_keyword_triggered_abilities`) and equip/fortify/reconfigure
#: (`_keyword_activated_ability`) also get real behaviour wired in at bind
#: time. The rest (kicker/ward/rampage/protection quality/…) are still
#: carried-but-inert — see `ToDo_Backend.md` "Rules Engine … M2".
_PARAMETRIC_KEYWORD_KEYS: frozenset[str] = frozenset({"n", "cost", "quality"})


class BindError(ValueError):
    """A spec could not be bound to a `GameEffect` (e.g. unknown effect type)."""


def build_effects(effects: list[EffectSpec], source: Optional[Any] = None) -> list[GameEffect]:
    """Instantiate one-shot `GameEffect`s from their specs via the registry.

    Refuses any effect ``type`` the `EffectRegistry` doesn't know — nothing
    from card text ever becomes behaviour outside the whitelist.
    """
    built: list[GameEffect] = []
    for spec in effects:
        if not EffectRegistry.is_registered(spec.type):
            raise BindError(f"no registered effect for type {spec.type!r}")
        effect = EffectRegistry.create(spec.type, dict(spec.params))
        effect.source = source
        built.append(effect)
    return built


def build_replacements(
    effects: list[EffectSpec], source: Optional[Any] = None
) -> list[ReplacementEffect]:
    """Instantiate `ReplacementEffect`s from their specs via the whitelist.

    A ``replacement`` `AbilitySpec` carries its family in each `EffectSpec`'s
    ``type`` (e.g. ``"prevent_damage"``) — only names in the
    `ReplacementRegistry` bind, so nothing from card text becomes an arbitrary
    callable (docs/09 security boundary)."""
    built: list[ReplacementEffect] = []
    for spec in effects:
        if not ReplacementRegistry.is_registered(spec.type):
            raise BindError(f"no registered replacement for type {spec.type!r}")
        effect = ReplacementRegistry.create(spec.type, dict(spec.params))
        effect.source = source
        built.append(effect)
    return built


#: RULE 603.1's "you control" scoping reads a different event-data key
#: depending on the event: `ENTERS_BATTLEFIELD`/`DIES` carry `controller_id`,
#: while `ATTACKS`/`BLOCKS` carry `player_id` — always that permanent's
#: controller (RULE 508.1a/509.1b — you can only attack/block with creatures
#: you control) — instead; see the firing sites in `game/game_engine.py`.
_GROUP_CONTROLLER_EVENT_KEYS: dict[str, str] = {
    "ATTACKS": "player_id",
    "BLOCKS": "player_id",
}


def _subject_condition(
    trigger: dict[str, Any], source: Optional[Any]
) -> Optional[Callable[[Any, Any], bool]]:
    """RULE 603.1's trigger *subject* → its predicate, from the ``condition``
    dict the oracle-text segmenter emits (`parser/oracle/segmenter.py`'s
    `_trigger_condition`) — ``None`` when the spec carries no such dict (a
    hand-authored `ability_catalogue.py` entry, or an older/synthetic spec),
    so those keep their pre-existing unscoped behaviour.

    ``{"subject": "self"}`` — the event must be about this ability's own
    source, matched by ``instance_id``. Missing ``instance_id`` on the event
    → fail-closed ``False``, never "fires for everything" (the over-firing
    bug this grammar exists to close: "when ~ enters the battlefield, draw a
    card" must not fire when *some other* permanent enters).

    ``{"subject": "group", "type", "controller", "other"}`` — the event must
    be about *some* battlefield object matching the filter: ``type`` checks
    `GameObject.type_words`, preferring the event's own ``object_types`` the
    firing site stamped at fire time (a `DIES` object has already left the
    battlefield by the time this runs, so a live lookup wouldn't see it),
    falling back to `GameState.find_object` when the event predates that
    payload (e.g. a hand-built test event); ``controller`` ``"you"`` checks
    the event's controller against the source's; ``other`` excludes the
    source's own instance (fail-closed ``False`` if the event carries no
    ``instance_id`` to check against).
    """
    condition = trigger.get("condition")
    if not condition:
        return None
    subject = condition.get("subject")
    instance_id = getattr(source, "instance_id", None)

    if subject == "self":

        def _self_ok(event: Any, context: Any, iid=instance_id) -> bool:
            event_instance = event.get("instance_id")
            return event_instance is not None and event_instance == iid

        return _self_ok

    if subject == "group":
        controller_id = getattr(source, "controller_id", None)
        type_word = condition.get("type")
        wants_you = condition.get("controller") == "you"
        other_only = bool(condition.get("other"))
        controller_key = _GROUP_CONTROLLER_EVENT_KEYS.get(trigger.get("event"), "controller_id")

        def _group_ok(
            event: Any,
            context: Any,
            iid=instance_id,
            cid=controller_id,
            tword=type_word,
            you=wants_you,
            other=other_only,
            ckey=controller_key,
        ) -> bool:
            event_instance = event.get("instance_id")
            if other and (event_instance is None or event_instance == iid):
                return False
            if you and event.get(ckey) != cid:
                return False
            if tword and tword != "permanent":
                types = event.get("object_types")
                if types is None and event_instance is not None:
                    state = getattr(context, "state", None)
                    obj = state.find_object(event_instance) if state is not None else None
                    types = sorted(obj.type_words) if obj is not None else None
                if not types or tword not in types:
                    return False
            return True

        return _group_ok

    return None


def _trigger_condition(
    trigger: dict[str, Any], source: Optional[Any]
) -> Optional[Callable[[Any, Any], bool]]:
    """The extra `TriggeredAbility.check_trigger` predicate a trigger spec needs.

    Composes independent predicates so a trigger can be scoped by any
    combination the spec sets:

    * ``"condition"`` — RULE 603.1's trigger subject ("self" or a "group"
      filter), the oracle-text segmenter's own scoping — see
      `_subject_condition`.
    * ``"chapter"`` — a Saga (or Class) chapter/level ability must fire only
      for *its own* source (scoped by the event's ``instance_id``, the same
      convention `continuous._granted_trigger_condition` uses) and only at
      the specific counter number(s) its chapter/level line names — a single
      ``SAGA_CHAPTER``/``CLASS_LEVEL`` event otherwise looks identical for
      every instance on the battlefield and every chapter/level on the card.
    * ``"min_level"``/``"max_level"``/``"level_counter"`` — a Leveler tier's
      own triggered ability (RULE 711, e.g. "whenever ~ attacks, it gets
      +1/+0" restricted to ``LEVEL 2-6``) must fire only while the source's
      own counter (``level`` by default) is currently in that tier's range —
      unlike ``chapter``, this checks the source's *current* state, not the
      triggering event's payload.
    """
    predicates: list[Callable[[Any, Any], bool]] = []

    subject_ok = _subject_condition(trigger, source)
    if subject_ok is not None:
        predicates.append(subject_ok)

    chapters = trigger.get("chapter")
    if chapters:
        chapter_set = frozenset(chapters)
        instance_id = getattr(source, "instance_id", None)

        def _chapter_ok(event: Any, context: Any, iid=instance_id, cs=chapter_set) -> bool:
            return event.get("instance_id") == iid and event.get("chapter") in cs

        predicates.append(_chapter_ok)

    min_level = trigger.get("min_level")
    max_level = trigger.get("max_level")
    if min_level is not None or max_level is not None:
        counter_kind = trigger.get("level_counter") or "level"

        def _level_ok(event: Any, context: Any, kind=counter_kind, lo=min_level, hi=max_level) -> bool:
            n = getattr(source, "counters", {}).get(kind, 0)
            return (lo is None or n >= lo) and (hi is None or n <= hi)

        predicates.append(_level_ok)

    if not predicates:
        return None
    if len(predicates) == 1:
        return predicates[0]

    def _all(event: Any, context: Any) -> bool:
        return all(p(event, context) for p in predicates)

    return _all


def bind_ability(
    spec: AbilitySpec, source: Optional[Any] = None
) -> Union[list[GameEffect], list[ReplacementEffect], TriggeredAbility, ActivatedAbility]:
    """Bind one validated `AbilitySpec` into its engine representation.

    Returns:
      * ``spell_effect`` → the list of one-shot effects (goes on a spell's
        ``spell_effects`` / a stack item),
      * ``triggered``    → a `TriggeredAbility`,
      * ``static``       → the list of `StaticAbility` effects,
      * ``replacement``  → the list of `ReplacementEffect`s,
      * ``enter_replacement`` → the list of `EnterAsCopyReplacement`-style
        effects (RULE 614.1c/614.12 "as ~ enters" — a different family from
        ``replacement``'s event-transform `ReplacementEffect`s, bound
        through `EffectRegistry` instead of `ReplacementRegistry`),
      * ``activated``    → an `ActivatedAbility`.

    ``source`` is the `GameObject` the ability belongs to (used as each
    effect's source and to default a trigger's controller).
    """
    spec.validate()
    if spec.ability_kind not in _SUPPORTED_KINDS:
        raise BindError(f"binder does not support ability_kind {spec.ability_kind!r} yet")

    if spec.ability_kind == "replacement":
        # A different whitelist (ReplacementRegistry, not EffectRegistry) —
        # each `EffectSpec.type` here names a replacement family (e.g.
        # "prevent_damage"), not a one-shot effect.
        replacements = build_replacements(spec.effects, source)
        for effect in replacements:
            if not effect.description:
                effect.description = spec.raw_text
        return replacements

    if spec.ability_kind == "enter_replacement":
        # RULE 614.1c/614.12: bound through `EffectRegistry` (unlike
        # "replacement"'s `ReplacementRegistry`) since these aren't pure
        # event-transform `ReplacementEffect`s.
        effects = build_effects(spec.effects, source)
        for effect in effects:
            if not effect.description:
                effect.description = spec.raw_text
        return effects

    effects = build_effects(spec.effects, source)

    if spec.ability_kind == "spell_effect":
        return effects

    if spec.ability_kind == "triggered":
        assert spec.trigger is not None  # validate() guarantees this
        modes = _build_mode_entries(spec.modes, source) if spec.modes else None
        return TriggeredAbility(
            trigger_event=spec.trigger["event"],
            effects=effects,
            modes=modes,
            modes_or_both=bool(spec.modes.get("or_both", False)) if spec.modes else False,
            condition=_trigger_condition(spec.trigger, source),
            optional=spec.optional,
            controller_id=getattr(source, "controller_id", None),
            source=source,
            description=spec.raw_text,
        )

    if spec.ability_kind == "static":
        # Each effect is a `StaticAbility` (from the anthem/grant_keyword/…
        # registry factories); the continuous-effects engine reads them off
        # the battlefield. Label any that arrived without their own text.
        for effect in effects:
            if isinstance(effect, StaticAbility) and not effect.description:
                effect.description = spec.raw_text
        return effects

    # activated: recognize the full cost (mana, {T}/{Q}, sacrifice, pay life,
    # discard, remove counters) from the spec's cost dict / text.
    return ActivatedAbility(
        effects=effects,
        cost=parse_activation_cost(spec.cost),
        source=source,
        description=spec.raw_text,
    )


def attach_keyword(obj: Any, spec: AbilitySpec) -> bool:
    """Dock a ``keyword`` spec onto the object (RULE 702).

    Returns ``True`` if the keyword was docked. Flag (parameterless) keywords —
    ``flying``, ``deathtouch``, … — join ``obj.intrinsic_keywords``, where the
    combat engine reads them. Parametric keywords are also docked now, each in
    the form the engine that consumes it expects:

    * **landwalk** (``{"name": "landwalk", "quality": "island"}``) → the
      specific variant slug ``"islandwalk"`` joins ``intrinsic_keywords``,
      which `combat.landwalk_subtypes` reads (RULE 702.14);
    * every parametric keyword's full parameter is also kept on
      ``obj.parametric_keywords`` (``name`` → ``{n|cost|quality}``) so the
      cost/combat-math consumers (kicker, annihilator, ward, protection
      quality) can read it — a carried record, behaviour where wired.
    """
    spec.validate()
    keyword = spec.keyword or {}
    name = keyword.get("name")
    if not name:
        return False
    if not hasattr(obj, "intrinsic_keywords"):
        obj.intrinsic_keywords = set()

    is_parametric = bool(_PARAMETRIC_KEYWORD_KEYS & keyword.keys())
    if not is_parametric:
        obj.intrinsic_keywords.add(str(name))
        return True

    # Parametric: keep the parameter, and dock the shape combat/cost expects.
    params = {k: v for k, v in keyword.items() if k != "name"}
    if not hasattr(obj, "parametric_keywords"):
        obj.parametric_keywords = {}
    obj.parametric_keywords[str(name)] = params
    if name == "landwalk" and keyword.get("quality"):
        # e.g. "island" → the "islandwalk" slug the combat engine recognizes.
        variant = str(keyword["quality"]).strip().lower().split()[0]
        obj.intrinsic_keywords.add(f"{variant}walk")
    return True


def _keyword_activated_ability(obj: Any, spec: AbilitySpec) -> Optional[ActivatedAbility]:
    """Create a live activated ability for attach-style keywords like Equip."""
    keyword = spec.keyword or {}
    name = str(keyword.get("name") or "")
    if name not in {"equip", "fortify", "reconfigure"}:
        return None

    cost_text = keyword.get("cost") or "{0}"
    target_kind = "permanent"
    # RULE 301.5c/306.2/702.151b: none of Equip/Fortify/Reconfigure tap the
    # source as part of their cost — it's exactly the printed cost, payable
    # (and re-payable) any number of times at sorcery speed. Don't graft a
    # {T} onto it: that would tap the permanent and block re-activation.
    cost = parse_activation_cost(cost_text)
    return ActivatedAbility(
        effects=[AttachEffect(target_kind=target_kind)],
        cost=cost,
        source=obj,
        description=spec.raw_text or f"{name}"
    )


def _self_only_condition(instance_id: Optional[int]) -> Callable[[Any, Any], bool]:
    """A trigger condition matching only events about ``instance_id`` itself —
    the same "self" scoping `_subject_condition` gives an oracle-parsed
    trigger, for the hand-synthesized combat-math keyword abilities below
    (which carry no oracle-text ``condition`` dict to read one from)."""

    def _check(event: Any, context: Any, iid=instance_id) -> bool:
        return event.get("instance_id") == iid

    return _check


def _keyword_triggered_abilities(obj: Any, spec: AbilitySpec) -> list[TriggeredAbility]:
    """Synthesize real triggered abilities for combat-math keywords whose
    RULE 702 text *is* a triggered ability — annihilator (702.86), afflict
    (702.130), bushido (702.45) — mirroring `_keyword_activated_ability`'s
    Equip/Fortify/Reconfigure treatment: these route through the ordinary
    stack/priority/response pipeline like any parsed "when ~ attacks..."
    trigger, rather than being special-cased procedurally in `game/combat.py`
    alongside the purely-static evasion keywords (flying, trample, ...),
    since a player can actually respond to any of the three.

    Rampage (702.23) is deliberately *not* built here: its pump amount
    scales with the *specific* block's final blocker count, which a
    bind-on-load `TriggeredAbility` (one fixed `effects` list, reused for
    every firing) can't carry. It's built directly instead — the identical
    "per-firing dynamic amount" problem Ward solves the same way — by
    `RulesEngine.check_rampage`, called from `GameEngine.declare_blockers`
    right where `BECOMES_BLOCKED` fires (which already carries a
    `blocker_count` payload for exactly this).
    """
    keyword = spec.keyword or {}
    name = str(keyword.get("name") or "")
    n = keyword.get("n")
    if n is None:
        return []
    n = int(n)
    condition = _self_only_condition(getattr(obj, "instance_id", None))

    if name == "annihilator":
        return [
            TriggeredAbility(
                trigger_event=EventType.ATTACKS,
                effects=[SacrificeEffect(count=n, selector="defending_player")],
                condition=condition,
                source=obj,
                description=spec.raw_text or f"Annihilator {n}",
            )
        ]
    if name == "afflict":
        return [
            TriggeredAbility(
                trigger_event=EventType.BECOMES_BLOCKED,
                effects=[LoseLifeEffect(amount=n, selector="defending_player")],
                condition=condition,
                source=obj,
                description=spec.raw_text or f"Afflict {n}",
            )
        ]
    if name == "bushido":
        # RULE 702.45a: bushido triggers both when this creature blocks
        # (BLOCKS, this object as the blocker) and when it becomes blocked
        # (BECOMES_BLOCKED, this object as the attacker) — two abilities,
        # each pumping only in the combat where its own event fired.
        return [
            TriggeredAbility(
                trigger_event=EventType.BLOCKS,
                effects=[PumpEffect(power=n, toughness=n)],
                condition=condition,
                source=obj,
                description=spec.raw_text or f"Bushido {n}",
            ),
            TriggeredAbility(
                trigger_event=EventType.BECOMES_BLOCKED,
                effects=[PumpEffect(power=n, toughness=n)],
                condition=condition,
                source=obj,
                description=spec.raw_text or f"Bushido {n}",
            ),
        ]
    return []


def _build_mode_entries(modes: dict[str, Any], source: Any) -> list[dict[str, Any]]:
    """Bind each mode's effects (RULE 700.2) into ``{"effects": [GameEffect,
    ...], "description": str}`` entries, one per printed mode — shared by a
    modal spell's ``obj.spell_modes`` (`_attach_modes`) and a modal
    triggered ability's own ``TriggeredAbility.modes``
    (`bind_ability`'s ``triggered`` branch)."""
    return [
        {"effects": build_effects(option, source), "description": description}
        for option, description in zip(
            modes.get("options", []), modes.get("descriptions") or []
        )
    ]


def _attach_modes(obj: Any, modes: dict[str, Any]) -> None:
    """Bind a modal spell's "Choose one —" options onto ``obj`` (RULE 700.2).

    Each option becomes its own entry in ``obj.spell_modes`` — a flat list
    of ``{"effects": [GameEffect, ...], "description": str}`` dicts, one
    per printed mode — plus ``obj.spell_modes_or_both`` (RULE 700.2e). The
    engine (`game/game_engine.py`) offers one cast action per mode, plus a
    combined "both" action when ``or_both`` is set, the same per-face-offer
    treatment MDFC/Adventure casting already uses; casting temporarily
    swaps `obj.spell_effects` to the chosen mode(s) so the existing
    targeting/resolution machinery (which reads that attribute) needs no
    change to be modal-aware.
    """
    entries = _build_mode_entries(modes, obj)
    existing = list(getattr(obj, "spell_modes", None) or [])
    obj.spell_modes = existing + entries
    obj.spell_modes_or_both = bool(modes.get("or_both", False))


def attach_to_object(obj: Any, specs: list[AbilitySpec]) -> None:
    """Bind each spec and attach it to the `GameObject`'s effect lists.

    ``spell_effect`` specs populate ``obj.spell_effects`` (the hook
    `RulesEngine._effects_for_spell` reads when the spell resolves) — or,
    for a modal spell (RULE 700.2, a ``modes`` block), ``obj.spell_modes``
    instead/as well (see `_attach_modes`); ``triggered``/``activated`` go on
    the matching `GameObject` ability list; ``static``/``replacement``
    extend the matching effect list; ``keyword`` specs dock onto
    ``obj.intrinsic_keywords`` (flag keywords).

    RULE 601.2b/604.3's "as an additional cost to cast this spell, <cost>."
    is its own oracle-text line — the parser emits it as a standalone spec
    carrying no effects of its own (`parser/oracle/segmenter.py`), so it's
    picked up here by scanning every spec for ``additional_cost`` rather than
    by whichever spec happens to carry the spell's "real" effects, keeping
    the parser/binder split simple regardless of line order on the card.
    """
    for spec in specs:
        if spec.additional_cost:
            spec.validate()
            obj.additional_cast_cost = parse_activation_cost(spec.additional_cost)
        if spec.ability_kind == "keyword":
            attach_keyword(obj, spec)
            keyword_ability = _keyword_activated_ability(obj, spec)
            if keyword_ability is not None:
                obj.activated_abilities.append(keyword_ability)
            obj.triggered_abilities.extend(_keyword_triggered_abilities(obj, spec))
            continue
        bound = bind_ability(spec, source=obj)
        if spec.ability_kind == "spell_effect":
            existing = list(getattr(obj, "spell_effects", []))
            obj.spell_effects = existing + bound  # type: ignore[union-attr]
            if spec.modes:
                _attach_modes(obj, spec.modes)
        elif spec.ability_kind == "triggered":
            obj.triggered_abilities.append(bound)
        elif spec.ability_kind == "activated":
            obj.activated_abilities.append(bound)
        elif spec.ability_kind == "static":
            obj.static_effects.extend(bound)
        elif spec.ability_kind == "replacement":
            obj.replacement_effects.extend(bound)
        elif spec.ability_kind == "enter_replacement":
            obj.enter_as_copy_effects.extend(bound)
        else:  # pragma: no cover - bind_ability already refused it
            raise BindError(f"cannot attach ability_kind {spec.ability_kind!r}")


def bind_from_catalogue(obj: Any) -> None:
    """Bind a `GameObject`'s abilities from the catalogue (bind-on-load).

    The single hook the game builder calls for every object it creates, so a
    card's activated/triggered/static abilities are live the moment it exists —
    the "binding on load" that connects card text to behaviour. A no-op for a
    card with no known specs. Import is function-local to avoid an import cycle
    (`ability_catalogue` builds specs, this module binds them)."""
    from .ability_catalogue import specs_for

    specs = specs_for(getattr(obj, "card", None))
    if specs:
        attach_to_object(obj, specs)
