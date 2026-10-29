"""Resolve name operands once for searches, live for filters and prohibitions."""
from __future__ import annotations

from ..models.cards.card_query import names_overlap
from ..models.game.game_object import Zone


def reference_names(spec, state, source, candidate=None, context=None, targets=None):
    kind = spec.get('kind')
    objects = []
    if kind == 'source':
        objects = [source]
    elif kind == 'attached' and source is not None:
        objects = [state.find_object(source.attached_to)]
    elif kind == 'linked_exile' and source is not None:
        # RULE 607.2a / 400.7: only the linked source visit and the linked
        # exile visits count. A card leaving exile severs the reference.
        incarnation = getattr(context, 'resolving_source_incarnation', None) if context is not None else None
        if incarnation is None:
            incarnation = source.zone_incarnation
        from .linked_exile import linked_cards
        objects = linked_cards(state, source, incarnation)
    elif kind == 'set':
        zone, scope = spec.get('zone'), spec.get('of')
        zone_owner_id = (getattr(source, 'controller_id', None) if scope == 'you'
                    else getattr(candidate, 'controller_id', None) or getattr(candidate, 'owner_id', None))
        if zone == 'battlefield':
            objects = list(state.battlefield)
        else:
            objects = [obj for player in state.players
                       if scope == 'any' or (zone_owner_id is not None and player.id == zone_owner_id)
                       for obj in getattr(player, zone, [])]
        if spec.get('nontoken'):
            objects = [obj for obj in objects if not obj.is_token]
    elif context is not None:
        from .effect_conditions import subject_of
        obj = subject_of(kind, context, source, targets)
        objects = [getattr(obj, 'obj', None) or obj]
    return [obj.name for obj in objects if obj is not None and obj.name]


def matches_name_reference(candidate, spec, state, source):
    return any(names_overlap(candidate.name, name)
               for name in reference_names(spec, state, source, candidate))


def resolve_search_names(criteria, context, source, targets=None):
    """Freeze the comparison before opening a serializable search choice."""
    if not isinstance(criteria, dict):
        return criteria
    result = {key: resolve_search_names(value, context, source, targets)
              if isinstance(value, dict) else
              [resolve_search_names(item, context, source, targets) for item in value]
              if isinstance(value, list) else value for key, value in criteria.items()}
    spec = result.pop('name_reference', None)
    if spec:
        names = reference_names(spec, context.state, source, context=context, targets=targets)
        # An undefined name must match nothing (RULE 701.23c).
        alternatives = result.pop('or', None)
        branches = [{'same_name_as': name} for name in names] or [{'same_name_as': ''}]
        if alternatives is not None:
            branches = [{**branch, 'or': alternatives} for branch in branches]
        result['or'] = branches
    return result
