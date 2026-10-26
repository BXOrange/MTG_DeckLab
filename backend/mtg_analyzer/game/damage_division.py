"""RULE 601.2d: announce damage shares alongside the selected targets.

Composite bodies remain serialized. Walk the already-announced branch and
write allocations into a private stack copy, so rebuilding that body at
resolution preserves the announcement without changing the reusable card.
"""
from __future__ import annotations

import copy

from . import effect_conditions


def _walk(effects):
    from .effects.composition import IfElseEffect, _build

    for effect in effects:
        if isinstance(effect, IfElseEffect):
            decided = effect_conditions.announced_state(effect.condition, effect.source)
            if decided is not None:
                specs = effect.then_specs if decided else effect.else_specs
                yield from _walk_specs(specs, effect.source)
                continue
        elif hasattr(effect, 'inner_specs'):
            yield from _walk_specs(effect.inner_specs, effect.source)
            continue
        elif isinstance(getattr(effect, 'effects', None), list):
            yield from _walk(effect.effects)
            continue
        yield effect, None


def _walk_specs(specs, source):
    from .effects.composition import _build

    for spec in specs:
        built = _build([spec], source)
        for leaf, raw in _walk(built):
            yield leaf, raw if raw is not None else spec


def _is_damage_division(effect):
    # RULE 601.2d applies to damage shares only; counter distribution and
    # divided prevention keep their own resolution-time paths.
    from .effects.damage_draw import DealDamageEffect

    return isinstance(effect, DealDamageEffect) and getattr(effect, 'divided', False)


def requirements(effects):
    """Division metadata indexed by the ordinary target requirement."""
    index = 0
    result = []
    for effect, _ in _walk(effects):
        targets = effect.target_specs
        if _is_damage_division(effect) and targets:
            total = effect.amount
            if isinstance(total, int) and not isinstance(total, bool):
                if effect.double_at is not None and total >= effect.double_at:
                    total *= 2
                result.append({'requirement_index': index, 'total': total, 'min_each': 1})
        index += len(targets)
    return result


def _copy_effect(effect):
    cloned = copy.copy(effect)
    for field in ('then_specs', 'else_specs', 'inner_specs'):
        if hasattr(effect, field):
            setattr(cloned, field, copy.deepcopy(getattr(effect, field)))
    if isinstance(getattr(effect, 'effects', None), list):
        cloned.effects = [_copy_effect(child) for child in effect.effects]
    return cloned


def prepare(effects, targets, groups, announced):
    """Validate every pool, and return independently allocated stack effects."""
    from .targeting import effects_target_specs, partition_targets

    pools = requirements(effects)
    if announced is None and not any(_is_damage_division(effect) and getattr(effect, 'division_required', False) for effect, _ in _walk(effects)):
        return effects
    payload = {} if announced is None else announced
    if not isinstance(payload, dict):
        raise ValueError('damage_divisions must map requirement indices to integer shares')
    expected = {str(pool['requirement_index']) for pool in pools}
    if set(payload) != expected:
        raise ValueError('announce exactly one damage division per divided requirement')
    if not pools:
        return effects
    specs = effects_target_specs(effects)
    groups = groups if groups is not None else ([targets or []] if len(specs) == 1 else partition_targets(specs, targets))
    if (not isinstance(groups, (list, tuple)) or len(groups) != len(specs)
            or any(not isinstance(group, (list, tuple)) for group in groups)):
        raise ValueError('damage divisions require one target group per requirement')
    for pool in pools:
        index = pool['requirement_index']
        shares = payload[str(index)]
        picked = groups[index]
        keys = [(type(target), getattr(target, 'instance_id', getattr(target, 'id', getattr(target, 'stack_id', None))))
                for target in picked]
        if len(set(keys)) != len(keys):
            raise ValueError('a divided requirement cannot target the same object or player twice')
        if (not isinstance(shares, list) or len(shares) != len(picked)
                or any(not isinstance(n, int) or isinstance(n, bool) or n < 1 for n in shares)
                or (picked and sum(shares) != pool['total'])):
            raise ValueError('damage shares must give each target at least one and sum to the damage total')
    cloned = [_copy_effect(effect) for effect in effects]
    index = 0
    for effect, raw in _walk(cloned):
        if _is_damage_division(effect) and effect.target_specs:
            shares = list(payload[str(index)])
            if raw is None:
                effect.division = shares
            else:
                raw.setdefault('params', {})['division'] = shares
        index += len(effect.target_specs)
    def preserve_bound_announcements(effect):
        # RULE 707.10: copies rebind the saved spec, so the announcement
        # belongs in that private spec as well as the lazy runtime body.
        bound = getattr(effect, '_bound_spec', None)
        if bound is not None:
            bound = copy.deepcopy(bound)
            for field, key in (('then_specs', 'then'), ('else_specs', 'else'), ('inner_specs', 'effects')):
                if hasattr(effect, field):
                    bound.params[key] = copy.deepcopy(getattr(effect, field))
            if getattr(effect, 'division', None) is not None:
                bound.params['division'] = list(effect.division)
            effect._bound_spec = bound
        for child in getattr(effect, 'effects', []) or []:
            preserve_bound_announcements(child)
    for effect in cloned:
        preserve_bound_announcements(effect)
    return cloned
