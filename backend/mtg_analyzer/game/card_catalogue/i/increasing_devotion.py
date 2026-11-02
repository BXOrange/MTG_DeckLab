from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _increasing_devotion() -> list[AbilitySpec]:
    'Create five 1/1 white Human creature tokens. If this spell was cast from a graveyard, create ten of those tokens instead.\nFlashback {7}{W}{W} (You may cast this card from your graveyard for its flashback cost. Then exile it.)'
    return [
        AbilitySpec(
            'spell_effect',
            [EffectSpec('if_else', {"condition": {'kind': 'source_cast_from_zone', 'zone': 'graveyard'}, "then": [{'type': 'create_token', 'params': {'count': 10, 'token_name': 'Human', 'power': 1, 'toughness': 1, 'colors': ['W'], 'subtypes': ['Human']}}], "else": [{'type': 'create_token', 'params': {'count': 5, 'token_name': 'Human', 'power': 1, 'toughness': 1, 'colors': ['W'], 'subtypes': ['Human']}}]})],
            raw_text='',
        ),
    ]


register('Increasing Devotion', _increasing_devotion)
