"""Announced payments for granted Replicate instances (RULE 702.56)."""
from contextlib import contextmanager
from functools import wraps
from inspect import signature

from ..models.mana.mana_cost import ManaCost


def costs_for(engine, player, obj, face="front"):
    """Consult the spell's announced face and live ability-granting sources."""
    from . import continuous

    card = engine._face_card(obj, face) or obj.card
    if not card.is_artifact:
        return []
    return [ManaCost.parse(ability.params["cost"])
            for ability in continuous._battlefield_static_abilities(engine.state)
            if ability.layer == "grant_replicate"
            and ability.source.controller_id == player.id
            and not continuous._static_ability_ceased(ability)]


def has_added_cost(obj):
    return any(getattr(obj, name, None) is not None for name in ("_splice_cost", "_replicate_cost"))


@contextmanager
def announced(engine, player, obj, counts, face="front", free=False, alt_cost=False):
    costs = costs_for(engine, player, obj, face)
    if (not isinstance(counts, (list, tuple)) or len(counts) != len(costs)
            or any(type(n) is not int or n < 0 for n in counts)):
        raise ValueError("Choose a nonnegative Replicate payment count for each instance")
    total = ManaCost()
    for cost, count in zip(costs, counts):
        for _ in range(count):
            total = total.add(cost)
    values = {"_replicate_cost": total, "_replicate_counts": tuple(counts),
              "_replicate_free_mana": free, "_replicate_alternative": alt_cost}
    old = {name: getattr(obj, name) for name in values if hasattr(obj, name)}
    for name, value in values.items():
        setattr(obj, name, value)
    try:
        yield
    finally:
        for name in values:
            if name in old:
                setattr(obj, name, old[name])
            elif hasattr(obj, name):
                delattr(obj, name)


def with_replicate(method):
    """Keep one announcement active through legality, pricing and the cast event."""
    sig = signature(method)

    @wraps(method)
    def wrapped(engine, player, obj, *args, replicate=None, **kwargs):
        if replicate is None:
            return method(engine, player, obj, *args, **kwargs)
        args_by_name = sig.bind_partial(engine, player, obj, *args, **kwargs).arguments
        try:
            with announced(engine, player, obj, replicate, args_by_name.get("face", "front"),
                           args_by_name.get("free", False), args_by_name.get("alt_cost", False)):
                return method(engine, player, obj, *args, **kwargs)
        except ValueError:
            if method.__name__ == "can_cast":
                return False
            raise
    return wrapped


def offer_payments(method):
    sig = signature(method)

    @wraps(method)
    def wrapped(engine, player, obj, *args, **kwargs):
        action = method(engine, player, obj, *args, **kwargs)
        face = sig.bind_partial(engine, player, obj, *args, **kwargs).arguments.get("face", "front")
        costs = costs_for(engine, player, obj, face)
        if costs:
            action["replicate_costs"] = [cost.raw for cost in costs]
            if action.get("kicker_variant"):
                action["kicker_variant"]["replicate_costs"] = list(action["replicate_costs"])
        return action
    return wrapped
