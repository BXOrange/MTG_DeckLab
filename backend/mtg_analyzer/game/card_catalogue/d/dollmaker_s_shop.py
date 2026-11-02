from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _dollmaker_s_shop() -> list[AbilitySpec]:
    'Whenever one or more non-Toy creatures you control attack a player, create a 1/1 white Toy artifact creature token.\n(You may cast either half. That door unlocks on the battlefield. As a sorcery, you may pay the mana cost of a locked door to unlock it.)'
    return [
        AbilitySpec(
            'triggered',
            [EffectSpec('create_token', {"count": 1, "power": 1, "toughness": 1, "colors": ['W'], "subtypes": ['Toy'], "keywords": [], "is_artifact": True, "token_name": 'Toy'})],
            trigger={"event": EventType.PLAYER_ATTACKED, "condition": {'subject': 'you', 'group_filter': {'excluded_subtypes': ['toy']}}},
            raw_text='whenever 1 or more non-toy creatures you control attack a player, create a 1/1 white toy artifact creature token.',
        ),
    ]


register("Dollmaker's Shop", _dollmaker_s_shop)


def _porcelain_gallery() -> list[AbilitySpec]:
    'Creatures you control have base power and toughness each equal to the number of creatures you control.\n(You may cast either half. That door unlocks on the battlefield. As a sorcery, you may pay the mana cost of a locked door to unlock it.)'
    return [
        AbilitySpec(
            'static',
            [EffectSpec('pt_set', {"affects": 'creatures_you_control', "power_count": 'creatures_you_control', "toughness_count": 'creatures_you_control'})],
            raw_text='',
        ),
    ]


register('Porcelain Gallery', _porcelain_gallery)
