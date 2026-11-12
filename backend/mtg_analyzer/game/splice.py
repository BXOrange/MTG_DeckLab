"""Announced hand-card Splice costs and copied spell text (RULE 702.47)."""
from contextlib import contextmanager
from functools import wraps
from inspect import signature

from ..models.mana.mana_cost import ManaCost


def options(player, host_card, exclude_id=None):
    if not (host_card.is_instant or host_card.is_sorcery):
        return []
    return [obj for obj in player.hand if obj.instance_id != exclude_id
            and ((getattr(obj, "parametric_keywords", None) or {}).get("splice") or {}).get("quality")
            == "instant_or_sorcery"]


@contextmanager
def announced(engine, player, obj, ids, face="front", free=False, alt_cost=False):
    from .binding.core import build_effects
    from .card_registry import specs_for

    if not isinstance(ids, (list, tuple)) or len(ids) != len(set(ids)):
        raise ValueError("Choose each Splice card at most once")
    host = engine._face_card(obj, face) or obj.card
    available = {item.instance_id: item for item in options(player, host, obj.instance_id)}
    if any(iid not in available for iid in ids):
        raise ValueError("Splice requires a matching card in your hand")
    cost = ManaCost.parse("{0}")
    effects = []
    for iid in ids:
        card = available[iid]
        cost = cost.add(ManaCost.parse(card.parametric_keywords["splice"]["cost"]))
        for spec in specs_for(card.card):
            if spec.ability_kind == "spell_effect":
                effects.extend(build_effects(spec.effects, obj))
    values = {"_splice_cost": cost, "_splice_effects": effects, "_splice_cards": [available[iid] for iid in ids],
              "_splice_free_mana": free, "_splice_alternative": alt_cost}
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


def with_splice(method):
    """Share one transient announcement across cost, legality, offer and commit calls."""
    sig = signature(method)

    @wraps(method)
    def wrapped(engine, player, obj, *args, splice_ids=None, **kwargs):
        if splice_ids is None or splice_ids == [] or splice_ids == ():
            return method(engine, player, obj, *args, **kwargs)
        arguments = sig.bind_partial(engine, player, obj, *args, **kwargs).arguments
        try:
            with announced(engine, player, obj, splice_ids, arguments.get("face", "front"),
                           arguments.get("free", False), arguments.get("alt_cost", False)):
                result = method(engine, player, obj, *args, **kwargs)
                if method.__name__ == "_cast_action":
                    result["splice_ids"] = list(splice_ids)
                    result["splice_names"] = [item.name for item in obj._splice_cards]
                    if result.get("kicker_variant"):
                        result["kicker_variant"].update(splice_ids=result["splice_ids"], splice_names=result["splice_names"])
                return result
        except ValueError:
            if method.__name__ == "can_cast":
                return False
            raise
    return wrapped


def payment_options(state, player, obj, cost):
    from . import continuous, linked_exile
    from .mana_abilities import restriction_predicate_for_cast
    return {
        "life_available": player.life - getattr(obj, "_cast_pip_life_cost", 0),
        "allows_restriction": restriction_predicate_for_cast(obj, has_x=cost.has_variable),
        "wildcard": (state.mana_wildcard_permission.get(obj.instance_id)
                     or linked_exile.mana_wildcard(state, player, obj)
                     or continuous.standing_mana_wildcard(state, player)),
        "require_source_kind": getattr(obj, "mana_source_kind_restriction", None),
        "extra_life_color": continuous.life_for_mana_pip_color(state, player),
    }


def pay_added_mana(rules, player, obj, cost):
    """Pay Splice on a waived mana cost, retaining the cast's actual mana facts."""
    before = dict(player.mana_pool.pool)
    sources = {kind: sum(pool.values()) for kind, pool in player.mana_pool.pool_by_source.items()
               if kind is not None}
    snow = sum(player.mana_pool.snow_pool.values())
    life = player.mana_pool.pay(cost, **payment_options(rules.state, player, obj, cost))
    if life:
        rules.lose_life(player, life, cause="cost")
    from . import continuous
    continuous.consume_next_spell_cost_reductions(rules.state, player.id, obj)
    source_spends = {kind: sources.get(kind, 0)
                     - sum(player.mana_pool.pool_by_source.get(kind, {}).values())
                     + player.mana_pool.last_payment_by_kind.get(kind, 0)
                     for kind in sources.keys() | player.mana_pool.last_payment_by_kind.keys()}
    return {
        "cost": cost, "colors": frozenset(c for c in "WUBRG" if before.get(c, 0) > player.mana_pool.pool.get(c, 0)),
        "by_color": {c: n - player.mana_pool.pool.get(c, 0) for c, n in before.items()
                     if n > player.mana_pool.pool.get(c, 0)},
        "by_source": source_spends, "snow": snow - sum(player.mana_pool.snow_pool.values()),
        "riders": list(player.mana_pool.last_payment_riders),
    }


def record_payment(item, facts):
    obj = item.obj
    obj.mana_spent_to_cast = facts["cost"].resolved_value
    obj.colors_spent_to_cast = facts["colors"]
    obj.mana_by_color_spent_to_cast = facts["by_color"]
    obj.mana_spent_to_cast_snow = facts["snow"]
    sources = facts["by_source"]
    obj.mana_spent_to_cast_treasure = sources.get("treasure", 0)
    obj.mana_spent_to_cast_creature = sources.get("creature", 0) + sources.get("artifact_creature", 0)
    obj.mana_spent_to_cast_artifact = sources.get("treasure", 0) + sources.get("artifact", 0) + sources.get("artifact_creature", 0)
    item.mana_payment_riders = facts["riders"]
    if item.pending_cast_event is not None:
        item.pending_cast_event.data.update(mana_spent=obj.mana_spent_to_cast,
            colors_spent=sorted(obj.colors_spent_to_cast), mana_spent_by_source=sources,
            creature_mana_spent=obj.mana_spent_to_cast_creature)


def total_cost(engine, player, obj, kwargs):
    if kwargs.get("alt_cost"):
        from . import continuous
        alternative = (getattr(obj, "alt_cast_cost", None)
                       or continuous.granted_alt_cast_cost_for(engine.state, player, obj.card, obj))
        return engine._adjust_cost(alternative.mana, player, obj)
    accepted = signature(engine.effective_cast_cost).parameters
    return engine.effective_cast_cost(player, obj, **{k: v for k, v in kwargs.items() if k in accepted})


def offer_spliced_casts(method):
    @wraps(method)
    def wrapped(engine, actions, player, obj):
        from itertools import combinations
        from . import mana_potential
        start = len(actions)
        method(engine, actions, player, obj)
        bases = list(actions[start:])
        accepted = signature(engine._cast_action).parameters
        for base in bases:
            kwargs = {k: v for k, v in base.items() if k in accepted and k not in {"self", "player", "obj"}}
            face = kwargs.get("face", "front")
            host = engine._face_card(obj, face) or obj.card
            candidates = options(player, host, obj.instance_id)
            # Currently registered Splice cards have the same untargeted text, so
            # ID order suffices for indistinguishable copies of that text.
            for count in range(1, len(candidates) + 1):
                for group in combinations(candidates, count):
                    ids = [o.instance_id for o in group]
                    with announced(engine, player, obj, ids, face, kwargs.get("free", False), kwargs.get("alt_cost", False)):
                        can_kwargs = {k: v for k, v in kwargs.items() if k in signature(engine.can_cast).parameters}
                        if not engine.can_cast(player, obj, **can_kwargs):
                            if (not engine.can_cast(player, obj, assume_mana_available=True, **can_kwargs)
                                    or not mana_potential.is_castable_via_potential(engine, player,
                                        total_cost(engine, player, obj, kwargs))):
                                continue
                        action = engine._cast_action(player, obj, **kwargs)
                        action["splice_ids"] = ids
                        action["splice_names"] = [o.name for o in group]
                        if action.get("kicker_variant"):
                            action["kicker_variant"].update(splice_ids=ids, splice_names=action["splice_names"])
                        action["cost_label"] = total_cost(engine, player, obj, kwargs).raw
                        action["effective_cost"] = action["cost_label"]
                        actions.append(action)
    return wrapped
