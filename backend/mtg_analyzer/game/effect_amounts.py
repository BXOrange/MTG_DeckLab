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

#: How a ``resource`` amount collapses a `scope`-worth of players to one
#: number, when ``aggregate`` is set instead of a single-player ``of``.
#: "…equal to the greatest number of cards a player discarded this way"
#: (Windfall, every player discarding their whole hand) is
#: ``aggregate="max"`` over ``hand_size`` measured before the discard.
_RESOURCE_AGGREGATES: dict[str, Any] = {"max": max, "min": min, "sum": sum}

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
        # PAR-67: how many counters this activated ability's own cost just
        # removed (`costs.REMOVE_COUNTERS_ALL`/X/ANY) — the cost-paid
        # sibling of ``this_way``'s resolve-time tallies.
        "counters_removed_as_cost",  # + ``of``
        # "…this way" (see `THIS_WAY_TALLIES`).
        "this_way",  # + ``tally``
        # How many targets the resolving ability's targeting effect(s) chose — "…then put a counter for each
        # opponent drawn for this way" (Communal Brewing: one card per chosen opponent).
        "targets_count",
        # The number of players a `for_each`-style player scope covers, which
        # is what "equal to the number of opponents you have" measures.
        "player_count",  # + ``scope`` ("each_player"/"each_opponent")
        # MEC-83: a named counter on a permanent — "for each +1/+1 counter on
        # it", "…for each charge counter on ~". Reads `GameObject.counters`
        # directly (counters aren't a continuous effect), scoped by ``of``.
        "counters",  # + ``counter`` (the counter's name), ``of``
        # "…for each kind of counter on it" (Blitzball Stadium): how many distinct counter kinds the referent has.
        "counter_kinds",  # + ``of``
        # Every kind of counter among creatures controlled by a player.
        "counters_among_creatures",  # + ``of`` (a player referent)
        # Every counter among a named group of the controller's permanents (+ ``scope``, a key of
        # `_COUNTER_SCOPES`).
        "counters_among_permanents",
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
        # RULE 508.3a: this trigger head's filtered count, captured at declaration.
        "attackers_declared",
        # "N, or M if <condition>" — the override every "…instead" card prints
        # ("~ deals 2 damage. If this spell was kicked, it deals 4 damage instead.").
        # The condition is an `effect_conditions` one, evaluated against the same source and
        # targets as the amount; both branches are themselves amounts.
        "if",  # + ``condition``, ``then``, ``otherwise``
        # A named counter on the firing DIES event's snapshot (RULE 400.7 — the object is gone):
        # "draw a card for each -1/-1 counter on it" (Dusk Urchins). Without ``counter``, every
        # kind summed — "put that number of +1/+1 counters on target creature" after "if it
        # had one or more counters on it" (Yuna, Grand Summoner, PAR-120).
        "trigger_event_counter",  # + ``counter`` (optional)
        # How many of the source's chosen colours (`GameObject.chosen_colors`) the firing event's spell is —
        # "you gain 1 life for each of the chosen colors it is" (Tablet of the Guilds).
        "chosen_colors_shared_with_trigger_spell",
        # How many spells the ``of`` player has cast this turn, this one included —
        # "they lose 1 life for each spell they've cast this turn" (Rug of Smothering).
        "spells_cast_this_turn",  # + ``of`` (a player referent)
        # RULE 120.3: the total damage dealt to the ``of`` player this turn, from any source,
        # combat or not — "Target player loses life equal to the damage already dealt to that
        # player this turn." (Final Punishment). Read off the turn's event log.
        "damage_dealt_this_turn",  # + ``of`` (a player referent)
        # The total characteristic of cards a preceding zone-change moved:
        # "the total mana value of cards milled/exiled this way".
        "moved_sum",  # + ``characteristic`` (usually mana_value)
        # How many cards a preceding zone-change moved, optionally only those of one card type —
        # "for each creature card put into a graveyard this way" (Dread Summons).
        "moved_count",  # + optional ``card_type``
        "created_count",  # actual preceding creations/exiles in this resolution
        "damaged_creatures_since_mark",  # actual damage after mark_event_log
        # The larger of two measurements — ``left`` / ``right`` are themselves amounts.
        "greater_of",
        # "the difference between that creature's power and its toughness" (Jaws of Defeat) — |left - right|.
        "abs_diff",
        # RULE 706.3a: this resolution's most recent `RollDieEffect` total
        # (`GameContext.die_result`) — "…where X is the result." (Growth
        # Spurt, PAR-80). MEC-90's own missing half of the dice subsystem.
        "die_result",
        # RULE 706's other randomization — "a number from A to B chosen at
        # random" (Hapato's Might, PAR-80): deliberately a *separate* field
        # from ``die_result`` (`GameContext.random_result`, set by
        # `RandomNumberEffect`) since RULE 706.11 only treats literal
        # "roll a die" text as a die roll subject to dice-replacement
        # effects — this must stay invisible to those.
        "random_result",
    }
)

#: Arithmetic every amount may carry, applied in this order. Named rather
#: than left to per-card kinds because "half its power, rounded up" and "one
#: more than the number of Elves" are printed on cards constantly, and each
#: was otherwise a new ``amount_from_half_*`` parameter.
#: ``divide`` rounds **down** unless ``round_up`` is set — RULE 107.2's
#: default.
_MODIFIER_KEYS = ("power_of", "multiply", "divide", "round_up", "plus", "minus", "minimum", "maximum")

#: Largest exponent ``power_of`` will raise its base to. "Target player draws
#: 2^X cards" (Mathemagics) is unbounded on the card, but nothing can draw more
#: than the library holds and a runaway X must not build a huge integer; 30
#: keeps 2^30 (~1.07 billion) far above any library while staying cheap.
MAX_POWER_OF_EXPONENT = 30


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


def _resource_of(player: Any, resource: str) -> int:
    """One player's ``resource`` (see `RESOURCES`) as an int."""
    if player is None:
        return 0
    if resource == "life":
        return int(getattr(player, "life", 0) or 0)
    if resource == "ring_level":
        return int(getattr(player, "ring_level", 0) or 0)
    zone = {"hand_size": "hand", "graveyard_size": "graveyard",
            "library_size": "library"}.get(resource)
    if zone is None:
        return 0
    return len(getattr(player, zone, []) or [])


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

    if kind == "greater_of":
        # "…the number of Zombies you control or the number of Zombie cards in your graveyard, whichever is
        # greater" (Prophet of the Scarab) — the larger of two measurements.
        return max(
            amount_of(amount.get("left"), context, source, targets),
            amount_of(amount.get("right"), context, source, targets),
        )

    if kind == "if":
        holds = effect_conditions.condition_holds(amount.get("condition"), context, source, targets)
        return amount_of(amount.get("then") if holds else amount.get("otherwise"), context, source, targets)

    if kind == "count_selector":
        from .continuous import count_selector  # function-scoped: import cycle

        selector = amount.get("selector")
        if not selector:
            return 0
        if amount.get("of"):
            # "…the number of Islands **target opponent** controls" — the count is taken as
            # that player, not as the ability's controller.
            counted_for = _as_player(
                context, effect_conditions.subject_of(str(amount["of"]), context, source, targets),
                controller_id,
            )
            controller_id = getattr(counted_for, "id", None) or controller_id
        reference = source
        if amount.get("reference"):
            # PAR-123: "for each creature blocking **it**" / "for each **other** attacking creature that
            # shares a creature type with **it**" — the counted-against object is the one a pronoun
            # names (the group trigger's firing object), not the ability's own source.
            reference = effect_conditions.subject_of(str(amount["reference"]), context, source, targets)
            if reference is None:
                return 0
        return int(
            count_selector(
                context.state, controller_id,
                selector if isinstance(selector, dict) else str(selector), source=reference,
            ) or 0
        )

    if kind == "abs_diff":
        # "…the difference between that creature's power and its toughness." (Jaws of Defeat) — RULE 107.1, the
        # non-negative difference of two measurements.
        return abs(
            amount_of(amount.get("left"), context, source, targets)
            - amount_of(amount.get("right"), context, source, targets)
        )

    if kind == "targets_count":
        return len([t for t in (targets or []) if t is not None])

    if kind == "player_count":
        return len(_players(context, controller_id, str(amount.get("scope", "each_player"))))

    if kind == "this_way":
        tally = str(amount.get("tally", ""))
        if tally not in THIS_WAY_TALLIES:
            return 0
        return int(getattr(context, tally, 0) or 0)

    if kind == "attackers_declared":
        return int((getattr(context, "trigger_event", None) or {}).get("matching_attacker_count", 0))

    if kind == "trigger_event":
        field = str(amount.get("field", ""))
        if not field:
            return 0
        raw = (getattr(context, "trigger_event", None) or {}).get(field)
        if isinstance(raw, (list, tuple, set, frozenset)):
            return len(raw)  # "for each of that spell's colors" (Ramos): a collection counts its members
        if isinstance(raw, bool) or not isinstance(raw, int):
            return 0
        return int(raw)

    if kind == "chosen_colors_shared_with_trigger_spell":
        event = getattr(context, "trigger_event", None) or {}
        spell = context.state.find_object(event.get("instance_id")) if event.get("instance_id") is not None else None
        picked = {str(c).upper() for c in (getattr(source, "chosen_colors", None) or [])}
        return len(picked & {str(c).upper() for c in (getattr(spell, "colors", None) or set())})

    if kind == "trigger_event_counter":
        counters = (getattr(context, "trigger_event", None) or {}).get("counters") or {}
        if not amount.get("counter"):
            return sum(int(value or 0) for value in counters.values())
        return int(counters.get(str(amount["counter"]), 0) or 0)

    if kind == "moved_sum":
        characteristic = str(amount.get("characteristic", "mana_value"))
        if characteristic not in CHARACTERISTICS:
            return 0
        total = 0
        for obj in getattr(context, "moved_objects", []) or []:
            if characteristic == "mana_value":
                total += int(getattr(getattr(obj, "card", None), "converted_mana_cost", 0) or 0)
            else:
                total += int(getattr(obj, characteristic, 0) or 0)
        return total

    if kind == "damaged_creatures_since_mark":
        start = getattr(source, "window_event_mark", len(context.state.event_log))
        return len({e.get("target_id") for e in context.state.event_log[start:]
                    if e.type == "DAMAGE" and e.get("target_is_creature")
                    and e.get("source_id") == getattr(source, "instance_id", None)
                    and e.get("amount", 0) > 0})
    if kind == "created_count":
        return len(context.created_objects)
    if kind == "moved_count":
        wanted = str(amount.get("card_type") or "").lower()
        return sum(
            1 for obj in getattr(context, "moved_objects", []) or []
            if not wanted or wanted in {w.lower() for w in obj.type_words}
        )

    if kind == "die_result":
        result = getattr(context, "die_result", None)
        if result is None:
            result = (getattr(context, "trigger_event", None) or {}).get("die_result")
        return int(result) if isinstance(result, int) else 0

    if kind == "random_result":
        result = getattr(context, "random_result", None)
        return int(result) if isinstance(result, int) else 0

    subject = effect_conditions.subject_of(
        str(amount.get("of") or "source"), context, source, targets
    )

    if kind == "counters":  # MEC-83
        counter = str(amount.get("counter", ""))
        if not counter or subject is None:
            return 0
        counters = getattr(subject, "counters", None) or {}
        # RULE 603.10a: a leaves-the-battlefield / dies trigger about ``subject``
        # itself counts the counters it had *then* — the object is already in
        # another zone by the time the ability resolves, with its counters gone.
        event = getattr(context, "trigger_event", None) or {}
        if (
            event.get("counters") is not None
            and event.get("instance_id") == getattr(subject, "instance_id", None)
        ):
            counters = event.get("counters")
        return int(counters.get(counter, 0) or 0)

    if kind == "counter_kinds":
        return sum(1 for v in (getattr(subject, "counters", None) or {}).values() if v and v > 0)

    if kind == "counters_among_creatures":
        player_id = getattr(subject, "id", None)
        if player_id is None:
            return 0
        return sum(
            sum(v for v in (getattr(obj, "counters", None) or {}).values() if v and v > 0)
            for obj in context.state.battlefield
            if getattr(obj, "is_creature", False) and obj.controller_id == player_id
        )

    if kind == "counters_among_permanents":
        # "counters among artifacts and creatures you control" (Lux Artillery): every counter of every
        # kind on the permanents ``scope`` names, the controller's own. An artifact creature is one
        # permanent, so it is counted once.
        if scope_types := _COUNTER_SCOPES.get(str(amount.get("scope", ""))):
            return sum(
                sum(v for v in (getattr(obj, "counters", None) or {}).values() if v and v > 0)
                for obj in context.state.battlefield
                if obj.controller_id == controller_id and any(has(obj) for has in scope_types)
            )
        return 0

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

    if kind == "spells_cast_this_turn":
        player = _as_player(context, subject, controller_id)
        return int(context.state.spells_cast_this_turn.get(getattr(player, "id", None), 0))

    if kind == "damage_dealt_this_turn":
        player = _as_player(context, subject, controller_id)
        return int(context.state.damage_dealt_to_players_this_turn.get(getattr(player, "id", None), 0))

    if kind == "characteristic":
        characteristic = str(amount.get("characteristic", ""))
        if characteristic not in CHARACTERISTICS:
            return 0
        if str(amount.get("of")) == "trigger_subject" and characteristic in ("power", "toughness"):
            # RULE 400.7: for a dies/leaves trigger the subject is gone by now, so its firing
            # event's snapshot of ``power``/``toughness`` beats a stale re-lookup.
            snapshot = (getattr(context, "trigger_event", None) or {}).get(characteristic)
            if snapshot is not None:
                return int(snapshot or 0)
        if getattr(subject, "kind", None) == "spell":
            subject = getattr(subject, "obj", None)  # a targeted spell is its `StackItem`
        if subject is None:
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

    if kind == "counters_removed_as_cost":
        # PAR-67 (Sage of Hours): "Remove all +1/+1 counters from this
        # creature: for each five counters removed this way, take an extra
        # turn after this one." — the removal happened as this ability's own
        # *cost*, not a resolving effect, so it has no `GameContext`
        # accumulator to read the way `this_way`'s tallies do; the amount is
        # stamped on the source directly at payment time instead (see
        # `activation_mixin._pay_activation_cost`), the `x_paid` sibling of
        # "remember what this activation just paid".
        return int(getattr(subject, "counters_removed_as_cost", 0) or 0)

    if kind == "resource":
        resource = str(amount.get("resource", ""))
        if resource not in RESOURCES:
            return 0
        reduce = _RESOURCE_AGGREGATES.get(str(amount.get("aggregate", "")))
        if reduce is not None:
            # A `scope`-worth of players collapsed to one number (Windfall's
            # "greatest number a player discarded this way").
            players = _players(
                context, controller_id, str(amount.get("scope", "each_player"))
            )
            values = [_resource_of(p, resource) for p in players]
            return int(reduce(values)) if values else 0
        player = _as_player(context, subject, controller_id)
        if player is None:
            return 0
        return _resource_of(player, resource)

    return 0  # fail-safe: an unmodelled measurement contributes nothing


#: `counters_among_permanents`'s ``scope`` vocabulary: the predicates (any one matching) a permanent must pass.
_COUNTER_SCOPES: dict[str, tuple[Any, ...]] = {
    "artifacts_and_creatures_you_control": (
        lambda o: bool(getattr(o, "is_creature", False)),
        lambda o: bool(getattr(o.card, "is_artifact", False)),
    ),
}


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

    # "2^X" — the measured value becomes the exponent of an integer base.
    power_of = amount.get("power_of")
    if isinstance(power_of, int) and not isinstance(power_of, bool) and power_of >= 0:
        value = power_of ** max(0, min(value, MAX_POWER_OF_EXPONENT))
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
    elif isinstance(minus, dict):
        # "…equal to the number of cards in defending player's hand **minus** the number of cards in your hand"
        # (Mr. Foxglove) — the subtrahend is itself a measured amount.
        value -= amount_of(minus, context, source, targets)
    minimum = amount.get("minimum")
    if isinstance(minimum, int) and not isinstance(minimum, bool):
        value = max(value, minimum)
    maximum = amount.get("maximum")
    if isinstance(maximum, int) and not isinstance(maximum, bool):
        value = min(value, maximum)
    return value
