from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _homura() -> list[AbilitySpec]:
    """Homura can't block.
    When Homura dies, return it to the battlefield flipped.
    """
    return [
        AbilitySpec('static', [EffectSpec('grant_keyword', {'keywords': ['cant_block'], 'affects': 'self'})]),
        AbilitySpec('triggered', [EffectSpec('homura_return_flipped', {})], trigger={
            'event': EventType.DIES, 'condition': {'subject': 'self'},
        }),
    ]


def _homuras_essence() -> list[AbilitySpec]:
    '''Creatures you control get +2/+2 and have flying and "{R}: This creature gets +1/+0 until end of turn."'''
    return [AbilitySpec('static', [
        EffectSpec('anthem', {'affects': 'creatures_you_control', 'power': 2, 'toughness': 2}),
        EffectSpec('grant_keyword', {'affects': 'creatures_you_control', 'keywords': ['flying']}),
        EffectSpec('grant_activated_ability', {'affects': 'creatures_you_control',
            'cost': {'mana': '{R}'},
            'grant_effects': [{'type': 'pump', 'params': {'power': 1, 'toughness': 0}}],
        }),
    ])]


register('Homura, Human Ascendant', _homura)
register("Homura's Essence", _homuras_essence)
