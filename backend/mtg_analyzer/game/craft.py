"""RULE 702.167: announce, pay and remember the selected Craft materials."""
from itertools import permutations

from . import continuous
from .effects.core import GameEffect
from ..models.game.game_object import Zone


def material_pool(state, player, source, material):
    battlefield = [obj for obj in state.permanents_controlled_by(player.id) if obj is not source]
    word = material["word"]
    if word == "red_instant_sorcery_card":
        return [obj for obj in player.graveyard if "R" in obj.colors and (obj.is_instant or obj.is_sorcery)]
    pool = battlefield + list(player.graveyard)
    if word in {"any", "shared_type", "four_tribes"}:
        return pool
    if word == "nonland_activated":
        return [obj for obj in pool if not obj.is_land and obj.activated_abilities]
    return [obj for obj in pool if continuous.matches_permanent_word(obj, word)]


def _completion(material, selected, available):
    """Find one completion of the announced prefix, including assignment to typed slots."""
    count = material["minimum"]
    word = material["word"]
    if len(selected) > count and not material.get("variable"):
        return None
    if word == "shared_type":
        group = selected + available
        for other in group:
            first = selected[0] if selected else other
            for second in group:
                if first is not second and first.type_words & second.type_words and all(
                    obj in (first, second) for obj in selected
                ):
                    return [first, second]
        return None
    if word == "four_tribes":
        tribes = ("dinosaur", "merfolk", "pirate", "vampire")
        for positions in permutations(range(len(tribes)), len(selected)):
            if not all(continuous.has_subtype(obj, tribes[pos]) for obj, pos in zip(selected, positions)):
                continue
            remaining = [tribe for i, tribe in enumerate(tribes) if i not in positions]
            solution = _assign_tribes(remaining, available)
            if solution is not None:
                return selected + solution
        return None
    needed = max(0, count - len(selected))
    return selected + available[:needed] if needed <= len(available) else None


def _assign_tribes(tribes, available):
    if not tribes:
        return []
    tribe, *rest = tribes
    for obj in available:
        if continuous.has_subtype(obj, tribe):
            later = _assign_tribes(rest, [other for other in available if other is not obj])
            if later is not None:
                return [obj, *later]
    return None


def resolve_materials(state, player, source, material, picks=None):
    pool = material_pool(state, player, source, material)
    if picks is None:
        return _completion(material, [], pool)
    by_id = {obj.instance_id: obj for obj in pool}
    if len(set(picks)) != len(picks) or any(iid not in by_id for iid in picks):
        return None
    selected = [by_id[iid] for iid in picks]
    if len(selected) < material["minimum"]:
        return None
    return _completion(material, selected, [])


def offer_materials(rules, player, source, index, material, picks=()):
    pool = material_pool(rules.state, player, source, material)
    selected = [obj for obj in pool if obj.instance_id in picks]
    available = [obj for obj in pool if obj.instance_id not in picks]
    options = []
    if resolve_materials(rules.state, player, source, material, picks) is not None:
        options.append({"id": "done", "label": "Confirm"})
    for obj in available:
        if _completion(material, [*selected, obj], [other for other in available if other is not obj]) is not None:
            options.append({"id": str(obj.instance_id), "label": f"{obj.name} ({obj.zone.value})"})
    rules.open_choice({
        "kind": "craft_materials", "prompt": "Craft", "player_id": player.id, "source_id": source.instance_id,
        "source_visit": source.zone_incarnation, "ability_index": index, "picks": list(picks),
        "visits": {str(obj.instance_id): obj.zone_incarnation for obj in pool},
        "options": [*options, {"id": "decline", "label": "Cancel"}],
    })


class CraftReturnEffect(GameEffect):
    """Return exactly the exile visit paid for the ability and link its materials."""

    def apply(self, context, targets=None):
        source = self.source
        event = context.trigger_event or {}
        visit = event.get("cost_exiled_source_incarnation")
        if (source.zone != Zone.EXILE or source.zone_incarnation != visit
                or source.is_token or context.engine._cannot_enter_transformed(source)):
            return
        records = [(iid, incarnation) for iid, incarnation in event.get("cost_exiled_incarnations", {}).items()
                   if (obj := context.state.find_object(iid)) is not None and obj.zone == Zone.EXILE
                   and obj.zone_incarnation == incarnation and not obj.is_token]
        key = (source.instance_id, visit + 1)
        context.state.linked_exile_visits[key] = records
        context.engine.return_from_exile(source, visit, transformed=True)
        if source.zone != Zone.BATTLEFIELD and not context.state.pending_choice:
            context.state.linked_exile_visits.pop(key, None)
