"""How much — one structured vocabulary for a measured quantity (ENG-37).

The quantity sibling of `effect_conditions.py`. Where that answers "does this
hold", this answers "how many", against the same referents
(`effect_conditions.subject_of`), so "that creature" means the same thing to
both.

Why it exists
-------------
`bind` — RULE 608.2's "…equal to its power", "…that many", "…equal to the
number of X" — is the one composition operator that cannot be built out of
the others: it has to *measure* something and hand the number to its body.
There was no vocabulary to measure with. The engine instead grew one boolean
parameter per measurement per effect: `amount_from_source_power`,
`amount_from_target_power`, `amount_from_trigger_source_toughness`,
`amount_from_half_own_life`, `amount_from_count_selector`,
`amount_from_created_object_mana_value`, `count_from_subject`,
`count_from_context`, … — 25 distinct `amount_from_*`/`count_from_*` names
across `effects/core.py`, each meaning "read *this* number off *that* thing",
and each needing its own `__init__` parameter, its own branch, and a repeat
of the whole set on the next effect that wants the same reading.

`_characteristic_of_subject`'s ``"<who>_<char>"`` mini-grammar (``self_power``
/ ``previous_subject_power`` / ``trigger_subject_mana_value``) was the first
attempt at factoring that, and it is the right shape — a reading times a
referent. This is that shape written out properly, with the referent axis
shared with the condition vocabulary instead of being its own three-name list.

Reading it
----------
``{"kind": <what to measure>, "of": <referent>, …}`` → an ``int``. Unknown or
unmeasurable is **0**, not an error: this runs inside a resolution, and the
fail-safe direction for a magnitude is "nothing happens", matching
`_characteristic_of_subject`'s own documented default.

Not to be confused with `continuous.count_selector`, which this *uses*: that
is the vocabulary of "which permanents", and stays the single place board
counts are defined.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from . import effect_conditions

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .effects.core import GameContext


#: The characteristics a ``characteristic`` amount may read (RULE 109.3).
#: ``power``/``toughness`` are the layer engine's *derived* values, so a pump
#: that already resolved counts; ``mana_value`` is read off the printed card
#: (RULE 202.3), which is what every "equal to its mana value" card means.
CHARACTERISTICS: frozenset[str] = frozenset({"power", "toughness", "mana_value"})

#: Player resources a ``resource`` amount may read.
RESOURCES: frozenset[str] = frozenset(
    {"life", "hand_size", "graveyard_size", "library_size", "ring_level"}
)

#: `GameContext`'s within-one-resolution tallies — "…for each creature
#: destroyed **this way**", "…equal to the life lost **this way**" (RULE
#: 608.2). Maintained by `_apply_effects_partitioned` and reset per
#: resolution, which is exactly the scope "this way" means.
THIS_WAY_TALLIES: frozenset[str] = frozenset(
    {"life_lost_this_way", "permanents_destroyed_this_way", "objects_exiled_this_way"}
)

#: Every recognized ``kind``. An amount naming anything else is 0.
AMOUNT_KINDS: frozenset[str] = frozenset(
    {
        # A plain number, so a body can be written uniformly whether its
        # magnitude is measured or printed.
        "fixed",  # + ``amount``
        # RULE 109.3 off a referent — the ``<who>_<char>`` grammar
        # `_characteristic_of_subject` introduced, with the referent axis now
        # shared with `effect_conditions`.
        "characteristic",  # + ``characteristic``, ``of``
        # A board count, deferring to the one selector vocabulary rather than
        # restating any of it here.
        "count_selector",  # + ``selector``
        # A player's own resources, scoped by ``of`` (a referent that
        # resolves to a player) or the ability's controller by default.
        "resource",  # + ``resource``, ``of``
        # RULE 107.3c — the {X} this spell/ability was announced for.
        "x_paid",  # + ``of``
        # "…this way" (see `THIS_WAY_TALLIES`).
        "this_way",  # + ``tally``
        # The number of players a `for_each`-style player scope covers, which
        # is what "equal to the number of opponents you have" measures.
        "player_count",  # + ``scope`` ("each_player"/"each_opponent")
        # MEC-83: a named counter on a permanent — "for each +1/+1 counter on
        # it", "…for each charge counter on ~". Reads `GameObject.counters`
        # directly (counters aren't a continuous effect), scoped by ``of``.
        "counters",  # + ``counter`` (the counter's name), ``of``
        # MEC-83 / RULE 702.42a Domain — "for each basic land type among lands
        # you control". Distinct basic land types (RULE 305.6's five) among
        # the ``of`` player's lands; defers to the one selector that already
        # defines this so nothing is restated.
        "domain",  # + ``of`` (a player referent; the controller by default)
        # The referent's *defensive* stat — a player's life total, a
        # planeswalker's loyalty, or a creature's toughness (Drain Life's
        # life-gain cap, measured *before* the damage). A battle (RULE
        # 115.4's fourth "any target") has no cap the printed card names, so
        # it reads 0.
        "target_defense",  # + ``of`` (an object/player referent)
        # A numeric field of the firing trigger's own event
        # (`GameContext.trigger_event`) — "…if it has the same mana value as
        # the revealed card" (Counterbalance) reads ``mana_value`` off the
        # `SPELL_CAST` event. Non-numeric / absent field → 0.
        "trigger_event",  # + ``field`` (the event key to read)
    }
)

#: Arithmetic every amount may carry, applied in this order. Named rather
#: than left to per-card kinds because "half its power, rounded up" and "one
#: more than the number of Elves" are printed on cards constantly, and each
#: was otherwise a new ``amount_from_half_*`` parameter.
#: ``divide`` rounds **down** unless ``round_up`` is set — RULE 107.2's
#: default.
_MODIFIER_KEYS = ("multiply", "divide", "round_up", "plus", "minus", "minimum", "maximum")


def _players(context: "GameContext", controller_id: Optional[str], scope: str) -> list[Any]:
    """The players ``scope`` covers, in APNAP order (RULE 101.4)."""
    living = list(context.state.living_players())
    if scope == "each_opponent":
        return [p for p in living if p.id != controller_id]
    if scope == "you":
        return [p for p in living if p.id == controller_id]
    return living


def _as_player(context: "GameContext", subject: Any, controller_id: Optional[str]) -> Any:
    """``subject`` as a player: itself if it is one, else its controller."""
    if subject is None:
        return effect_conditions._player_by_id(context, controller_id)
    if getattr(subject, "instance_id", None) is None:
        return subject  # already a `Player`
    return effect_conditions._player_by_id(
        context, getattr(subject, "controller_id", None)
    )


def _base(
    amount: dict[str, Any],
    context: "GameContext",
    source: Any,
    targets: Optional[list[Any]],
) -> int:
    kind = amount.get("kind")
    controller_id = effect_conditions._controller_id(source, context)

    if kind == "fixed":
        value = amount.get("amount", 0)
        return int(value) if isinstance(value, int) and not isinstance(value, bool) else 0

    if kind == "count_selector":
        from .continuous import count_selector  # function-scoped: import cycle

        selector = amount.get("selector")
        if not selector:
            return 0
        return int(count_selector(context.state, controller_id, str(selector), source=source) or 0)

    if kind == "player_count":
        return len(_players(context, controller_id, str(amount.get("scope", "each_player"))))

    if kind == "this_way":
        tally = str(amount.get("tally", ""))
        if tally not in THIS_WAY_TALLIES:
            return 0
        return int(getattr(context, tally, 0) or 0)

    if kind == "trigger_event":
        field = str(amount.get("field", ""))
        if not field:
            return 0
        raw = (getattr(context, "trigger_event", None) or {}).get(field)
        if isinstance(raw, bool) or not isinstance(raw, int):
            return 0
        return int(raw)

    subject = effect_conditions.subject_of(
        str(amount.get("of") or "source"), context, source, targets
    )

    if kind == "counters":  # MEC-83
        counter = str(amount.get("counter", ""))
        if not counter or subject is None:
            return 0
        return int((getattr(subject, "counters", None) or {}).get(counter, 0) or 0)

    if kind == "domain":  # MEC-83 / RULE 702.42a — distinct basic land types
        from .continuous import count_selector  # function-scoped: import cycle

        player = _as_player(context, subject, controller_id)
        player_id = getattr(player, "id", None) or controller_id
        if player_id is None:
            return 0
        return int(count_selector(
            context.state, player_id, "basic_land_types_among_lands_you_control",
            source=source,
        ) or 0)

    if kind == "characteristic":
        characteristic = str(amount.get("characteristic", ""))
        if characteristic not in CHARACTERISTICS or subject is None:
            return 0
        if characteristic == "mana_value":
            # RULE 202.3 is read off the printed card, where the field is
            # named ``converted_mana_cost`` — the same read
            # `_characteristic_of_subject` makes. (Getting this wrong is why
            # Feed the Swarm silently lost 0 life on the first migration: a
            # missing attribute is 0 under this module's fail-safe rule, so
            # it failed quietly rather than raising.)
            card = getattr(subject, "card", None)
            return int(getattr(card, "converted_mana_cost", 0) or 0)
        return int(getattr(subject, characteristic, 0) or 0)

    if kind == "target_defense":
        # RULE 119.3-adjacent: how much "damage" the target can absorb —
        # life for a player, loyalty for a planeswalker, toughness for a
        # creature. Read live (the caller times the measurement, e.g. a
        # `bind` takes it before its body deals the damage).
        if subject is None:
            return 0
        if getattr(subject, "instance_id", None) is None:
            return int(getattr(subject, "life", 0) or 0)  # a Player
        if getattr(subject, "is_planeswalker", False):
            return int((getattr(subject, "counters", None) or {}).get("loyalty", 0) or 0)
        if getattr(subject, "is_creature", False):
            return int(getattr(subject, "toughness", 0) or 0)
        return 0  # a battle, or something with no defensive stat

    if kind == "x_paid":
        return int(getattr(subject, "x_paid", 0) or 0)

    if kind == "resource":
        resource = str(amount.get("resource", ""))
        if resource not in RESOURCES:
            return 0
        player = _as_player(context, subject, controller_id)
        if player is None:
            return 0
        if resource == "life":
            return int(getattr(player, "life", 0) or 0)
        if resource == "ring_level":
            return int(getattr(player, "ring_level", 0) or 0)
        zone = {"hand_size": "hand", "graveyard_size": "graveyard",
                "library_size": "library"}[resource]
        return len(getattr(player, zone, []) or [])

    return 0  # fail-safe: an unmodelled measurement contributes nothing


def amount_of(
    amount: Optional[dict[str, Any]],
    context: "GameContext",
    source: Any = None,
    targets: Optional[list[Any]] = None,
) -> int:
    """Measure ``amount`` right now. No amount, or an unmodelled one, is 0.

    A plain ``int`` is accepted in place of a dict, so a node's parameter can
    be written as the literal it usually is without a ``fixed`` wrapper.
    """
    if amount is None:
        return 0
    if isinstance(amount, bool):
        return 0
    if isinstance(amount, int):
        return amount
    if not isinstance(amount, dict) or amount.get("kind") not in AMOUNT_KINDS:
        return 0

    value = _base(amount, context, source, targets)

    multiply = amount.get("multiply")
    if isinstance(multiply, int) and not isinstance(multiply, bool):
        value *= multiply
    divide = amount.get("divide")
    if isinstance(divide, int) and not isinstance(divide, bool) and divide > 0:
        # RULE 107.2: rounded down unless the card says otherwise.
        value = -(-value // divide) if amount.get("round_up") else value // divide
    plus = amount.get("plus")
    if isinstance(plus, int) and not isinstance(plus, bool):
        value += plus
    minus = amount.get("minus")
    if isinstance(minus, int) and not isinstance(minus, bool):
        value -= minus
    minimum = amount.get("minimum")
    if isinstance(minimum, int) and not isinstance(minimum, bool):
        value = max(value, minimum)
    maximum = amount.get("maximum")
    if isinstance(maximum, int) and not isinstance(maximum, bool):
        value = min(value, maximum)
    return value
