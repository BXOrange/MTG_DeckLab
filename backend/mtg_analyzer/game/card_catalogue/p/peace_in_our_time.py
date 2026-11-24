from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ....models.game.events import EventType
from ...card_registry.core import register


def _peace_in_our_time() -> list[AbilitySpec]:
    """At the beginning of combat on each player's turn, that player may draw a card. If they do, they can't attack this turn and you put a peace counter on this enchantment.
    At the beginning of your upkeep, if this enchantment has twelve or more peace counters on it, you win the game.
    """
    return [
        AbilitySpec('triggered',[EffectSpec('optional',{
            'player':{'of':'event_player'}, 'if_you_do_from':1,
            'effects':[
                {'type':'draw','params':{'count':1,'player':{'of':'event_player'}}},
                {'type':'player_cant_attack_this_turn','params':{}},
                {'type':'add_counters','params':{'kind':'peace','count':1}},
            ],
        })],trigger={'event':EventType.STEP_BEGIN,'filter':{'step':'begin_combat'}}),
        AbilitySpec('triggered',[EffectSpec('win_game',{},condition={
            'kind':'source_counters','counter':'peace','min':12})],trigger={
            'event':EventType.STEP_BEGIN,'filter':{'step':'upkeep'},'phase_relation':'you',
            'active_if':{'kind':'source_counters','counter':'peace','min':12}}),
    ]


register('Peace in Our Time',_peace_in_our_time)
