from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _leyline_of_the_guildpact() -> list[AbilitySpec]:
    'If this card is in your opening hand, you may begin the game with it on the battlefield.\nEach nonland permanent you control is all colors.\nLands you control are every basic land type in addition to their other types.'
    return [
        AbilitySpec(
            'static',
            [EffectSpec('type_change', {"affects": 'lands_you_control', "add_subtypes": ['plains', 'island', 'swamp', 'mountain', 'forest']})],
            raw_text='lands you control are every basic land type in addition to their other types.',
        ),
        AbilitySpec(
            'static',
            [EffectSpec('color_change', {"affects": 'nonland_permanents_you_control', "colors": ['W', 'U', 'B', 'R', 'G'], "set": True})],
            raw_text='',
        ),
    ]


register('Leyline of the Guildpact', _leyline_of_the_guildpact)
