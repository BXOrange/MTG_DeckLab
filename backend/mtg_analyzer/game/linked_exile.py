"""RULE 607.2a linked cards are exact source and exile zone visits."""
from __future__ import annotations

from ..models.game.game_object import Zone


def linked_cards(state, source, incarnation=None):
    if source is None:
        return []
    if incarnation is None:
        incarnation = source.zone_incarnation
    return [obj for iid, visit in state.linked_exile_visits.get((source.instance_id, incarnation), [])
            if (obj := state.find_object(iid)) is not None
            and obj.zone == Zone.EXILE and obj.zone_incarnation == visit]


def play_grant(state, player, obj, *, land=False, card=None, feature=None):
    """Read a standing permission live; leaving or losing the ability ends it."""
    from .continuous import _battlefield_static_abilities
    from .combat import matches_object_filter
    from .static_conditions import condition_holds
    from copy import copy

    if obj.zone != Zone.EXILE or obj.face_down_in_exile:
        return None
    candidate = obj
    if card is not None and card is not obj.card:
        candidate = copy(obj)
        candidate.card = card
        candidate.reset_derived()
    for ability in _battlefield_static_abilities(state):
        if (ability.layer != 'linked_exile_permission' or ability.source.controller_id != player.id
                or ability.source.loses_all_abilities):
            continue
        params = ability.params
        if feature and not params.get(feature):
            continue
        if land and params.get('only_spells'):
            continue
        if params.get('only_lands') and not land:
            continue
        if params.get('active_if') and not condition_holds(params['active_if'], state, ability.source, player.id):
            continue
        if not any(obj is linked for linked in linked_cards(state, ability.source)):
            continue
        if params.get('own_only') and obj.owner_id != player.id:
            continue
        if not matches_object_filter(candidate, params.get('card_filter'), state=state, reference=ability.source):
            continue
        return ability
    return None


def mana_wildcard(state, player, obj):
    grant = play_grant(state, player, obj, feature="mana_wildcard")
    return grant.params.get('mana_wildcard') if grant is not None else None


def remembered_cards(state, source, context=None):
    """Legacy single-slot imprint/O-Ring readers, restricted to recorded visits."""
    if source is None:
        return []
    ids = set(getattr(source, 'linked_exile_ids', None) or [])
    ids.add(getattr(source, 'linked_exile_id', None))
    incarnation = getattr(context, 'resolving_source_incarnation', None)
    return [obj for obj in linked_cards(state, source, incarnation) if obj.instance_id in ids]


def remembered_card(state, source, context=None):
    cards = remembered_cards(state, source, context)
    return cards[-1] if cards else None
