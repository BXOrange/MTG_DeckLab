"""Riot's pre-entry characteristics and lasting haste (RULE 702.136)."""
from __future__ import annotations

import copy

from . import combat, continuous
from .effects.core import StaticAbility
from ..models.game.game_object import Zone


def entry_instances(state, obj, controller_id=None):
    """RULE 614.12: include existing grants without admitting a real permanent.

    Evaluate on an isolated position: layer evaluation can rebind abilities,
    change control and populate caches, so a shallow battlefield view is unsafe.
    Other members of a simultaneous entry batch are deliberately still absent.
    """
    abilities = [*continuous._battlefield_static_abilities(state), *obj.static_effects]
    if not ('riot' in obj.intrinsic_keywords or combat.keyword_instances(obj, 'riot') or any(
        'riot' in ability.params.get('keywords', []) for ability in abilities
        if isinstance(ability, StaticAbility)
    )):
        return 0
    view = state.clone()
    entrant = view.find_object(obj.instance_id)
    if entrant is None:
        entrant = copy.deepcopy(obj)
    for player in view.players:
        for zone in (player.hand, player.library, player.graveyard, player.exile, player.command):
            zone[:] = [card for card in zone if card.instance_id != obj.instance_id]
    if controller_id is not None:
        entrant.controller_id = controller_id
    entrant.zone = Zone.BATTLEFIELD
    entrant.timestamp = view.next_timestamp()
    view.battlefield = [o for o in view.battlefield if o.instance_id != obj.instance_id] + [entrant]
    continuous.recompute(view)
    return combat.keyword_instances(entrant, 'riot')


def apply_entry_haste(state, obj):
    """RULE 702.136a / 611.2a: no duration, independent of the Riot grantor.

    Pin the next battlefield visit: the grant survives cleanup and control
    changes but must never follow the same card through a later zone change.
    """
    if not obj.riot_entry_haste:
        return
    obj.riot_entry_haste = False
    incarnation = obj.zone_incarnation + int(obj.zone != Zone.BATTLEFIELD)
    ability = StaticAbility('ability', affects='objects', source=obj,
        params={'keywords': ['haste'], 'object_incarnations': {obj.instance_id: incarnation}},
        duration='rest_of_game', description='Riot — Haste')
    ability.object_ids = [obj.instance_id]
    ability.timestamp = state.next_timestamp()
    state.floating_statics.append(ability)
