from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _greenhouse() -> list[AbilitySpec]:
    'Lands you control have "{T}: Add one mana of any color."\n(You may cast either half. That door unlocks on the battlefield. As a sorcery, you may pay the mana cost of a locked door to unlock it.)'
    return [
        AbilitySpec(
            'static',
            [EffectSpec('grant_mana_ability', {"mana": [{'W': 1}, {'U': 1}, {'B': 1}, {'R': 1}, {'G': 1}], "affects": 'lands_you_control'})],
            raw_text='lands you control have "{t}: add 1 mana of any color."',
        ),
    ]


register('Greenhouse', _greenhouse)


def _rickety_gazebo() -> list[AbilitySpec]:
    'When you unlock this door, mill four cards, then return up to two permanent cards from among them to your hand.\n(You may cast either half. That door unlocks on the battlefield. As a sorcery, you may pay the mana cost of a locked door to unlock it.)'
    return [
        AbilitySpec(
            'triggered',
            [EffectSpec('mill', {"count": 4}), EffectSpec('choose_objects', {"pool_zone": 'milled', "card_types_any": ['artifact', 'battle', 'creature', 'enchantment', 'land', 'planeswalker'], "what": 'permanent', "count": 2, "optional": True, "action": 'return_from_graveyard_to_hand'})],
            trigger={"event": EventType.DOOR_UNLOCKED, "condition": {'subject': 'self'}, "filter": {'door': 'this'}},
            raw_text='',
        ),
    ]


register('Rickety Gazebo', _rickety_gazebo)
