"""RULE 603.4 / 702.33b resolution-time effect conditions — one structured
vocabulary for "if `<predicate>`, `<effect>`" (ENG-36).

Why this module exists
----------------------
`parser/oracle/spec.py`'s `EffectSpec.condition` grew one flat boolean key
per printed phrasing — 44 of them — and `effects.ConditionalEffect.
_condition_holds` grew one ``if`` per key, 554 lines of them. The keys were
never 44 different questions. They were a handful of predicates written out
once per *referent* (``source_has_subtype`` and
``previous_target_has_subtype``), once per *threshold*
(``ring_tempted_at_least`` and ``ring_tempted_at_most``,
``no_spells_cast_last_turn`` and ``two_or_more_spells_cast_last_turn``), and
once per *attribute* (eight separate keys that all read a boolean the engine
had already stamped on the object). That is the hand-filled cross-product
`docs/concepts/14_PARSER_GRAMMAR_DESIGN.md` describes, one layer below the
one ENG-34 inventoried.

The structured form factors it back apart:

* **which predicate** — ``kind``
* **about what** — ``of``, a referent name (`CONDITION_SUBJECTS`)
* **how many** — ``min``/``max`` on the counted rows
* **combined how** — ``all`` / ``not``

Where the split lives
---------------------
Almost every predicate needs nothing but the game state, so almost every
predicate lives in `static_conditions.py`, which already *was* the shared
state-predicate vocabulary (a RULE 613.6 static's ``active_if``, a RULE
603.4 trigger's intervening-if, a replacement's generic gate). This module
holds only the two things that vocabulary cannot express:

1. **The referents a resolving ability has and a standing one doesn't** —
   the clause's own target, the previous clause's target, the object the
   firing event names. `condition_holds` resolves those and then hands
   `static_conditions.condition_holds` a condition already pointed at that
   object, so there is one implementation of "is it a Detective", not one
   per referent.
2. **The five predicates that read `GameContext` itself** rather than the
   state (`CONTEXT_CONDITION_KINDS`).

So a condition may name any `STATIC_CONDITION_KINDS` row — the resolution
vocabulary is a superset, not a sibling — and a new state predicate written
for a static is immediately usable as an effect gate with no work here.

Three-valued on purpose
-----------------------
`_evaluate` returns ``None`` for "the referent this asks about doesn't
exist", distinct from ``False`` ("it exists and the answer is no"). Only
that distinction makes ``not`` correct: "if that creature **isn't**
suspected" must not fire when no creature was chosen at all, and RULE
701.30d's "**otherwise**, …" must not fire when no clash happened. The flat
vocabulary encoded this by hand where it mattered (the ``previous_target_*``
family shared one "no previous target → false" guard; ``clash_won`` checked
``outcome is None`` before comparing) and had no way to say it where it
didn't. `condition_holds` collapses the three values to a bool at the
boundary, so an unanswerable condition simply never applies — the same
fail-closed direction as an unrecognized ``kind``.

Legacy spellings still work, untranslated, in every shipped `AbilitySpec`
and catalogue entry: `condition_from_legacy` maps them onto the structured
vocabulary at evaluation time so there is one evaluator, not two — the same
move `static_conditions.condition_from_legacy_params` already made for the
statics.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Optional

from ..models.game.events import EventType
from . import static_conditions

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .effects.core import GameContext


#: Referents an effect condition's ``of`` may name, beyond the ones
#: `static_conditions.CONDITION_SUBJECTS` already resolves (``source``,
#: ``attached``, ``affected``), which are passed through untouched.
#:
#: ``target``            — this ability's own resolved target. A
#:                         `ConditionalEffect` declares no `TargetSpec` of
#:                         its own, so a ``target_groups=None`` ability hands
#:                         it whichever target a *sibling* clause announced.
#: ``previous_target``   — what an earlier clause of this same resolution
#:                         chose (`GameContext.previous_targets`), the
#:                         referent behind "that creature" in a rider.
#: ``chosen``            — ``target`` if this clause has one, else
#:                         ``previous_target``. RULE 701.60c's "if it's
#:                         suspected, exile it. Otherwise, suspect it." is
#:                         two complementary clauses where only the first
#:                         carries the target.
#: ``entering``          — the object the firing event names by
#:                         ``instance_id``, i.e. a group trigger's own
#:                         subject rather than the ability's source.
#: ``counter_recipient`` — the `EventType.COUNTER` event's
#:                         ``recipient_controller_id``, as a `Player`.
#: ``revealed``          — the card a `reveal_top` clause earlier in this
#:                         same resolution revealed (`GameContext.
#:                         revealed_card`), still in its owner's library.
#:                         RULE 701.20 — "reveal the top card … if it's a
#:                         land card, …".
#:
#: ``previous_target`` and ``chosen`` resolve only to *objects*: a player in
#: that slot means the earlier clause chose something these predicates can't
#: talk about, which is the guard the flat ``previous_target_*`` family
#: shared by hand.
#:
#: `GameContext.created_objects` is deliberately **not** a referent yet. It
#: is `previous_targets`' sibling and would be a one-row addition here, but
#: no predicate and no printed card needs it today, and choosing between
#: "the first token made" and "the most recent" with nothing to validate the
#: choice against would be a guess baked into a whitelisted vocabulary.
EFFECT_SUBJECTS: frozenset[str] = frozenset(
    {"target", "previous_target", "chosen", "entering", "counter_recipient", "revealed"}
)

#: Every referent a condition may name here, static-resolved ones included.
CONDITION_SUBJECTS: frozenset[str] = (
    EFFECT_SUBJECTS | static_conditions.CONDITION_SUBJECTS
)

#: The predicates that read `GameContext` rather than `GameState`, and so
#: cannot live in `static_conditions`. Everything else an effect condition
#: can ask is a `STATIC_CONDITION_KINDS` row.
CONTEXT_CONDITION_KINDS: frozenset[str] = frozenset(
    {
        # RULE 701.30d — the outcome an earlier `ClashEffect` in this same
        # resolution stashed on `GameContext.clash_won`, or the firing
        # `CLASHED` event's own ``won`` when the clash *is* the trigger.
        # Unanswerable (``None``) when no clash is in scope, so neither the
        # "if you win" nor the "otherwise" branch fires.
        "clash_won",
        # RULE 702.142a — the firing `EXERTED` event's own snapshot. Read
        # from the event and not `GameObject.exerted_this_turn`, which is
        # already `True` by the time the trigger resolves; only the event's
        # pre-set value still distinguishes a first exert from a repeat.
        "already_exerted",
        "source_cast_via_flashback",
        # Cemetery Gatekeeper — the played land/cast spell the firing event
        # names, against the card this source remembered exiling
        # (`GameObject.linked_exile_id`), sharing a RULE 205.2a card type.
        "shares_type_with_linked_exile",
        # Guardian Project — the entering creature (a *group* trigger's
        # subject, off the firing event) is nontoken and shares its name
        # with nothing else you control or have in your graveyard.
        "entering_object_unique_name",
        # RULE 701.6x — every bending keyword action in the controller's
        # `GameState.bends_this_turn`. Needs `RulesEngine.BEND_KINDS`, which
        # is why it reads the context's engine rather than just the state.
        "did_all_bends_this_turn",
        # ENG-37 B5 — compare two `effect_amounts` measurements: ``left`` and
        # ``right`` amount specs + ``op`` ("lt"/"le"/"gt"/"ge"/"eq"/"ne").
        # "if it's a creature card with mana value less than or equal to the
        # number of loyalty counters on ~" (Nissa, Steward of Elements). The
        # only predicate here that reads a *number* off two referents rather
        # than asking a yes/no about one.
        "amount_compare",
    }
)

#: Combinators, handled here rather than delegated: their sub-conditions may
#: name an effect-only referent, so the recursion has to stay in this module.
#: ``any`` is OR to ``all``'s AND, three-valued the same way (True if any sub
#: is True; None if none is True but any is unanswerable; else False).
COMBINATOR_KINDS: frozenset[str] = frozenset({"all", "any", "not"})

#: Every ``kind`` an effect condition may name.
EFFECT_CONDITION_KINDS: frozenset[str] = (
    CONTEXT_CONDITION_KINDS | COMBINATOR_KINDS | static_conditions.STATIC_CONDITION_KINDS
)


def _controller_id(source: Any, context: "GameContext") -> Optional[str]:
    """The player "you" means (RULE 109.4), falling back to the active player.

    An untargeted effect affects its own controller; an effect with no source
    yet (a fixture, a direct call) falls back the same way
    `effects._controller_of` does, which is what every controller-scoped key
    in the flat vocabulary read.
    """
    controller_id = getattr(source, "controller_id", None)
    if controller_id is not None:
        return controller_id
    return getattr(getattr(context, "active_player", None), "id", None)


def _player_by_id(context: "GameContext", player_id: Optional[str]) -> Any:
    for player in getattr(context.state, "players", []):
        if player.id == player_id:
            return player
    return None


def _object_or_none(candidate: Any) -> Any:
    """``candidate`` if it is a game object, else ``None`` (e.g. a player)."""
    return candidate if getattr(candidate, "instance_id", None) is not None else None


def subject_of(
    of: str, context: "GameContext", source: Any, targets: Optional[list[Any]] = None
) -> Any:
    """The referent ``of`` names — see `EFFECT_SUBJECTS`. ``None`` if absent.

    Public because the referent axis is not a condition-only idea: ENG-37's
    `game/effect_amounts.py` asks "how much" about the same referents this
    asks "is it" about, and both must agree on what "that creature" means.
    ``source`` is handled here too (unlike inside `_evaluate`, which lets
    `static_conditions` resolve it), so a caller with no state vocabulary
    behind it still gets a complete answer.
    """
    if of in ("source", "", None):
        return source
    if of == "target":
        return targets[0] if targets else None
    if of == "previous_target":
        previous = getattr(context, "previous_targets", None) or []
        return _object_or_none(previous[0]) if previous else None
    if of == "chosen":
        chosen = _object_or_none(targets[0]) if targets else None
        if chosen is not None:
            return chosen
        return subject_of("previous_target", context, source, targets)
    if of == "entering":
        event = getattr(context, "trigger_event", None) or {}
        instance_id = event.get("instance_id")
        return context.state.find_object(instance_id) if instance_id is not None else None
    if of == "counter_recipient":
        event = getattr(context, "trigger_event", None) or {}
        return _player_by_id(context, event.get("recipient_controller_id"))
    if of == "revealed":
        return getattr(context, "revealed_card", None)
    return None


def _context_holds(
    kind: str,
    condition: dict[str, Any],
    context: "GameContext",
    source: Any,
    targets: Optional[list[Any]],
) -> Optional[bool]:
    """The `CONTEXT_CONDITION_KINDS` rows. ``None`` = no referent in scope."""
    if kind == "clash_won":
        outcome = getattr(context, "clash_won", None)
        if outcome is None:
            event = getattr(context, "trigger_event", None)
            if event is not None and getattr(event, "type", None) == EventType.CLASHED:
                outcome = event.get("won")
        return None if outcome is None else bool(outcome)

    if kind == "amount_compare":
        from . import effect_amounts  # function-scoped: effect_amounts imports this module

        left = effect_amounts.amount_of(condition.get("left"), context, source, targets)
        right = effect_amounts.amount_of(condition.get("right"), context, source, targets)
        return {
            "lt": left < right, "le": left <= right,
            "gt": left > right, "ge": left >= right,
            "eq": left == right, "ne": left != right,
        }.get(str(condition.get("op", "eq")))  # unknown op → None (fail-closed)

    if kind == "already_exerted":
        event = getattr(context, "trigger_event", None) or {}
        return bool(event.get("already_exerted"))

    if kind == "source_cast_via_flashback":
        return None if source is None else bool(getattr(source, "cast_via_flashback", False))

    if kind == "shares_type_with_linked_exile":
        event = getattr(context, "trigger_event", None) or {}
        played_id = event.get("instance_id")
        played = context.state.find_object(played_id) if played_id is not None else None
        exiled_id = getattr(source, "linked_exile_id", None)
        exiled = context.state.find_object(exiled_id) if exiled_id is not None else None
        if played is None or exiled is None:
            return None
        # RULE 205.2a's real card types only — `type_words` always carries
        # the synthetic "permanent" marker too, which would make every
        # comparison trivially true.
        real_types = {
            "creature", "artifact", "enchantment", "instant", "sorcery",
            "planeswalker", "land", "battle",
        }
        return bool(played.type_words & exiled.type_words & real_types)

    if kind == "entering_object_unique_name":
        entering = subject_of("entering", context, source, targets)
        if entering is None:
            # The trigger fired but its subject is no longer findable; there
            # is nothing to compare names against, and the shipped behaviour
            # is to let the payoff through rather than swallow it.
            return True
        if getattr(entering, "is_token", False):
            # "…a **nontoken** creature you control enters…" — the trigger
            # condition's own ``nontoken`` flag only ever combines with a
            # ``subtypes`` filter in `binding`, so it is checked here.
            return False
        player = _player_by_id(context, _controller_id(source, context))
        if player is None:
            return True
        name = entering.name
        shares = any(
            other is not entering and other.controller_id == player.id
            and other.is_creature and other.name == name
            for other in context.state.permanents()
        ) or any(
            card.card.is_creature and card.name == name
            for card in getattr(player, "graveyard", []) or []
        )
        return not shares

    if kind == "did_all_bends_this_turn":
        done = context.state.bends_this_turn.get(_controller_id(source, context), set())
        return done.issuperset(context.engine.BEND_KINDS)

    return None  # pragma: no cover - CONTEXT_CONDITION_KINDS is total above


def _evaluate(
    condition: Optional[dict[str, Any]],
    context: "GameContext",
    source: Any,
    targets: Optional[list[Any]],
) -> Optional[bool]:
    """``True``/``False``/``None`` (no referent) — see the module docstring."""
    if not condition:
        return True
    kind = condition.get("kind")

    if kind == "all":
        results = [
            _evaluate(sub, context, source, targets)
            for sub in (condition.get("conditions") or [])
        ]
        if any(result is False for result in results):
            return False
        return None if any(result is None for result in results) else True
    if kind == "any":
        results = [
            _evaluate(sub, context, source, targets)
            for sub in (condition.get("conditions") or [])
        ]
        if any(result is True for result in results):
            return True
        return None if any(result is None for result in results) else False
    if kind == "not":
        inner = condition.get("condition")
        if not inner:
            return False  # an empty negation is fail-closed, not vacuously true
        result = _evaluate(inner, context, source, targets)
        return None if result is None else not result

    if kind in CONTEXT_CONDITION_KINDS:
        return _context_holds(str(kind), condition, context, source, targets)

    if kind not in static_conditions.STATIC_CONDITION_KINDS:
        # Unanswerable, not false. Returning ``False`` here would let a
        # ``not`` around an unmodeled predicate invert into a gate that
        # *always* fires — the opposite of failing closed.
        return None

    controller_id = _controller_id(source, context)
    of = condition.get("of") or "source"
    if of not in EFFECT_SUBJECTS:
        # ``source``/``attached``/``affected`` (or an unrecognized name):
        # `static_conditions` resolves those itself, exactly as it does for a
        # standing ability.
        return static_conditions.condition_holds(condition, context.state, source, controller_id)

    subject = subject_of(of, context, source, targets)
    if subject is None:
        return None
    # Point the predicate at the resolved referent and let the one shared
    # implementation answer it.
    return static_conditions.condition_holds(
        {key: value for key, value in condition.items() if key != "of"},
        context.state,
        subject,
        controller_id,
    )


def condition_state(
    condition: Optional[dict[str, Any]],
    context: "GameContext",
    source: Any = None,
    targets: Optional[list[Any]] = None,
) -> Optional[bool]:
    """``condition``'s three-valued answer — ``None`` = unanswerable.

    `condition_holds` is the bool collapse of this and is what a plain gate
    wants. An ``if_else`` composition node needs the third value: RULE
    701.30d's "if you win the clash, A. **Otherwise**, B." must run *neither*
    branch when no clash is in scope, which "not A" cannot express.
    """
    return _evaluate(condition_from_legacy(condition), context, source, targets)


def condition_holds(
    condition: Optional[dict[str, Any]],
    context: "GameContext",
    source: Any = None,
    targets: Optional[list[Any]] = None,
) -> bool:
    """Whether ``condition`` holds for this resolution. No condition = true.

    Accepts either spelling: a structured ``{"kind": …}`` dict, or the flat
    legacy keys every shipped spec still uses (`condition_from_legacy`).
    """
    return _evaluate(condition_from_legacy(condition), context, source, targets) is True


# ---------------------------------------------------------------------------
# The legacy flat vocabulary → the structured one


def _negated(condition: dict[str, Any], positive: bool) -> dict[str, Any]:
    """``condition``, wrapped in ``not`` unless ``positive``.

    Roughly half the flat keys were booleans whose ``False`` spelling meant
    "the same question, negated" — which is a combinator, not a second
    predicate.
    """
    return condition if positive else {"kind": "not", "condition": condition}


def _flag(attribute: str) -> Callable[[Any], dict[str, Any]]:
    """A flat boolean key that only ever read one stamped attribute."""
    return lambda value: _negated({"kind": "flag", "flag": attribute}, bool(value))


#: Each flat `EffectSpec.condition` key → the structured condition it means.
#: ``None`` from a builder means the key carried a falsy value that never had
#: a negative reading (a flag-shaped key only ever set to ``True``), so it
#: contributes no gate at all — exactly as it did before.
_FROM_LEGACY: dict[str, Callable[[Any], Optional[dict[str, Any]]]] = {
    # -- RULE 601.2b optional additional costs, and the flags cast time
    # stamps on the object. One predicate at eight attributes; ``kicked``
    # keeps a row of its own only because it is a *count*, not a flag.
    "kicked": lambda v: {"kind": "kicked", "min": 1} if v else {"kind": "kicked", "max": 0},
    "kicked_at_least": lambda v: {"kind": "kicked", "min": int(v)},
    "bargained": _flag("bargained"),
    "additional_cost_paid": _flag("additional_cost_paid"),
    "source_was_cast": _flag("was_cast"),
    "source_was_foretold": _flag("foretold"),
    "cast_via_escape": _flag("cast_via_escape"),
    "cast_outside_sorcery_speed": _flag("cast_outside_sorcery_speed"),
    "source_is_renowned": _flag("renowned"),
    "previous_target_is_suspected": lambda v: _negated(
        {"kind": "flag", "flag": "is_suspected", "of": "chosen"}, bool(v)
    ),
    # RULE 614.1-adjacent "when ~ enters **untapped**" — the state vocabulary
    # already carried both polarities of this one as named kinds.
    "source_entered_untapped": lambda v: (
        {"kind": "source_untapped"} if v else {"kind": "source_tapped"}
    ),
    "source_x_paid_at_least": lambda v: {"kind": "x_paid", "min": int(v)},
    # -- One predicate, two referents.
    "source_has_subtype": lambda v: {"kind": "is_subtype", "subtype": str(v)},
    "previous_target_has_subtype": lambda v: {
        "kind": "is_subtype", "of": "previous_target", "subtype": str(v),
    },
    "previous_target_is_creature": lambda v: _negated(
        {"kind": "is_card_type", "of": "previous_target", "card_type": "creature"}, bool(v)
    ),
    "previous_target_is_equipped": lambda v: _negated(
        {"kind": "source_equipped", "of": "previous_target"}, bool(v)
    ),
    "target_is_controller": lambda v: _negated({"kind": "is_you", "of": "target"}, bool(v)),
    "counter_recipient_is_you": lambda v: _negated(
        {"kind": "is_you", "of": "counter_recipient"}, bool(v)
    ),
    "target_is_player": lambda v: _negated({"kind": "is_player", "of": "target"}, bool(v)),
    "is_ring_bearer": lambda v: _negated({"kind": "is_ring_bearer"}, bool(v)),
    # -- One quantity, two thresholds.
    "previous_target_power_at_least": lambda v: {
        "kind": "power", "of": "previous_target", "min": int(v),
    },
    "previous_target_power_at_most": lambda v: {
        "kind": "power", "of": "previous_target", "max": int(v),
    },
    "ring_tempted_at_least": lambda v: {"kind": "ring_tempted", "min": int(v)},
    "ring_tempted_at_most": lambda v: {"kind": "ring_tempted", "max": int(v)},
    "no_spells_cast_last_turn": lambda v: (
        {"kind": "spells_cast_last_turn", "max": 0} if v else None
    ),
    "two_or_more_spells_cast_last_turn": lambda v: (
        {"kind": "spells_cast_last_turn", "min": 2} if v else None
    ),
    "is_first_combat_phase": lambda v: (
        {"kind": "combats_this_turn", "max": 1} if v else {"kind": "combats_this_turn", "min": 2}
    ),
    # -- Counts the state vocabulary already knew how to take.
    "life_gained_this_turn_at_least": lambda v: {
        "kind": "gained_life_this_turn", "amount": int(v),
    },
    "opponent_lost_life_this_turn_at_least": lambda v: {
        "kind": "opponent_lost_life_this_turn", "min": int(v),
    },
    "creatures_died_this_turn_at_least": lambda v: {
        "kind": "creatures_died_this_turn", "min": int(v),
    },
    "cards_in_graveyard_at_least": lambda v: {"kind": "graveyard_count", "min": int(v)},
    # RULE 702.71 Spell mastery — the type filter is a `continuous.
    # count_selector` name that existed long before this gate did.
    "instant_sorcery_cards_in_graveyard_at_least": lambda v: {
        "kind": "control_count",
        "selector": "instant_sorcery_or_adventure_cards_in_your_graveyard",
        "min": int(v),
    },
    "graveyard_has_type": lambda v: {"kind": "subtype_in_graveyard", "subtype": str(v).lower()},
    "controls_none_of_type": lambda v: {
        "kind": "not",
        "condition": {"kind": "controls_subtype", "subtype": str(v).lower(), "min": 1},
    },
    "count_selector_at_least": lambda v: {
        "kind": "control_count",
        "selector": str((v or {}).get("selector", "")),
        "min": int((v or {}).get("count", 0)),
    },
    "controls_creature_power_at_least": lambda v: {
        "kind": "control_count", "selector": "creatures_you_control",
        "min_power": int(v), "min": 1,
    },
    "no_creatures_on_battlefield": lambda v: (
        {"kind": "no_creatures_on_battlefield"} if v else None
    ),
    "is_your_turn": lambda v: _negated({"kind": "your_turn"}, bool(v)),
    "opponent_cast_color_this_turn": lambda v: {
        "kind": "opponent_cast_color_this_turn", "colors": list(v or []),
    },
    # -- The rows that genuinely need the resolution context.
    "did_all_bends_this_turn": lambda v: _negated({"kind": "did_all_bends_this_turn"}, bool(v)),
    "clash_won": lambda v: _negated({"kind": "clash_won"}, bool(v)),
    "not_already_exerted": lambda v: (
        {"kind": "not", "condition": {"kind": "already_exerted"}} if v else None
    ),
    "shares_type_with_linked_exile": lambda v: (
        {"kind": "shares_type_with_linked_exile"} if v else None
    ),
    "entering_object_unique_name": lambda v: (
        {"kind": "entering_object_unique_name"} if v else None
    ),
}

#: The flat keys this module can translate — the set
#: `parser/oracle/spec.py`'s `_ALLOWED_CONDITION_KEYS` must stay equal to.
LEGACY_CONDITION_KEYS: frozenset[str] = frozenset(_FROM_LEGACY)


def condition_from_legacy(condition: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """A flat `EffectSpec.condition` → the structured vocabulary.

    Already-structured dicts (anything carrying a ``kind``) pass through
    untouched, so both spellings are legal input everywhere. A dict with
    several flat keys becomes an ``all`` — the flat form's own AND-fold,
    which is how Frodo, Adventurous Hobbit spells "if ~ is your Ring-bearer
    **and** the Ring has tempted you N or more times".

    An unrecognized key contributes nothing rather than raising: this runs
    inside a resolution, and `parser/oracle/spec.py` is the layer that
    rejects an unknown key outright.
    """
    if not condition or "kind" in condition:
        return condition
    parts: list[dict[str, Any]] = []
    for key, value in condition.items():
        builder = _FROM_LEGACY.get(key)
        if builder is None:
            continue
        translated = builder(value)
        if translated is not None:
            parts.append(translated)
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return {"kind": "all", "conditions": parts}
