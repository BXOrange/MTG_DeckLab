"""RULE 707.10 / 608.2h: last-known stack values for untargeted copy triggers.

The event carries a numeric recipe ID. Recipes belong to GameState so public
choice JSON stays primitive and undo reconnects sources/targets to that state.
Live originals take precedence; registered recipes refresh before departure.
"""
from __future__ import annotations

import copy


def needs_recipe(value):
    if isinstance(value, (list, tuple)):
        return any(needs_recipe(v) for v in value)
    if isinstance(value, dict):
        if value.get("type") in ("copy_ability", "demonstrate_copy"):
            return True
        if value.get("type") == "copy_spell" and (value.get("params") or {}).get("spell_from_trigger_event"):
            return True
        return any(needs_recipe(v) for v in value.values())
    if getattr(value, "spell_from_trigger_event", None) or type(value).__name__ in ("CopyAbilityEffect", "DemonstrateCopyEffect"):
        return True
    return any(needs_recipe(getattr(value, name, None))
               for name in ("effects", "inner", "inner_specs", "else_specs", "modes")) if value is not None else False


def freeze(rules, item):
    snapshot = copy.copy(item)
    snapshot.targets = list(item.targets)
    snapshot.target_groups = [list(group) for group in item.target_groups] if item.target_groups is not None else None
    snapshot.target_incarnations = list(item.target_incarnations)
    if item.obj is not None:
        shadow = copy.copy(item.obj)
        memo = rules._copy_effect_memo(item.obj, shadow, item.targets)
        shadow.__dict__ = copy.deepcopy(item.obj.__dict__, memo)
        snapshot.obj = shadow
    else:
        memo = rules._copy_effect_memo(item.source, targets=item.targets)
    snapshot.effects = copy.deepcopy(item.effects, memo)
    snapshot.deferred_ward_triggers = []
    return snapshot


def capture_firing(rules, ability, event):
    if not needs_recipe(ability.effects):
        return None
    stack_id = event.get("stack_id")
    instance_id = event.get("instance_id")
    item = next((i for i in rules.state.stack if i.stack_id == stack_id), None) if stack_id is not None else None
    if item is None and instance_id is not None:
        item = next((i for i in rules.state.stack if i.obj is not None and i.obj.instance_id == instance_id), None)
    if item is None:
        return None
    if item.stack_id not in rules.state.copiable_stack_recipes:
        rules.state.copiable_stack_recipes[item.stack_id] = freeze(rules, item)
    return item.stack_id


def capture_departure(rules, item):
    if item.stack_id in rules.state.copiable_stack_recipes:
        rules.state.copiable_stack_recipes[item.stack_id] = freeze(rules, item)


def original_or_recipe(rules, stack_id):
    return (next((i for i in rules.state.stack if i.stack_id == stack_id), None)
            or rules.state.copiable_stack_recipes.get(stack_id))
