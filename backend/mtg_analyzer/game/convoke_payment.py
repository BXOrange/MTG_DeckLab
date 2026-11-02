"""RULE 702.51: choose creature contributions without manufacturing mana."""
from __future__ import annotations

from typing import Any, Callable

from ..models.mana.mana_cost import GENERIC, MONO_HYBRID, ManaCost, ManaSymbol


def _signature(cost: ManaCost) -> tuple:
    return tuple(sorted((s.kind, s.color or '', s.amount) for s in cost.symbols))


def _contributions(cost: ManaCost, colors: set[str]):
    """One creature pays one generic or one matching colored mana symbol."""
    seen = set()
    if any(s.kind == GENERIC and s.amount > 0 for s in cost.symbols):
        reduced = cost.reduce_generic(1)
        seen.add(_signature(reduced))
        yield reduced
    for index, symbol in enumerate(cost.symbols):
        options = symbol.payment_options()
        if any(color in colors and generic == 0 and life == 0
               for color, generic, life in options):
            reduced = ManaCost(cost.symbols[:index] + cost.symbols[index + 1:])
            key = _signature(reduced)
            if key not in seen:
                seen.add(key)
                yield reduced
        if symbol.kind == MONO_HYBRID:
            # RULE 107.4e/601.2b: choose the generic half before paying it.
            symbols = cost.symbols[:index] + [ManaSymbol(GENERIC, amount=symbol.amount)] + cost.symbols[index + 1:]
            reduced = ManaCost(symbols).reduce_generic(1)
            key = _signature(reduced)
            if key not in seen:
                seen.add(key)
                yield reduced


def plan_convoke(cost: ManaCost, creatures: list[Any], can_pay: Callable[[ManaCost], bool]):
    """Return a payable remainder and the smallest creature set, or best capacity.

    Prefix DP keeps one minimal plan per remaining cost. Every plan at a prefix
    has the same future creatures available, so discarded plans cannot improve
    a later payment. This preserves a multicolored helper for a scarce color.
    """
    if can_pay(cost):
        return cost, ()
    states = {_signature(cost): (cost, ())}
    best = None
    for creature in creatures:
        next_states = dict(states)
        colors = set(creature.colors) & set('WUBRG')
        for remaining, helpers in states.values():
            if best is not None and len(helpers) + 1 >= len(best[1]):
                continue
            for reduced in _contributions(remaining, colors):
                plan = helpers + (creature,)
                key = _signature(reduced)
                previous = next_states.get(key)
                if previous is not None and len(previous[1]) <= len(plan):
                    continue
                next_states[key] = (reduced, plan)
                if can_pay(reduced):
                    best = (reduced, plan)
        states = next_states
        if best is not None and len(best[1]) == 1:
            break
    if best is not None:
        return best
    return min(states.values(), key=lambda item: (item[0].converted_mana_cost, len(item[1])))
