from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _dark_salvation() -> list[AbilitySpec]:
    'Target player creates X 2/2 black Zombie creature tokens, then up to one target creature gets -1/-1 until end of turn for each Zombie that player controls.'
    return [
        AbilitySpec(
            'spell_effect',
            [EffectSpec('target_player_tokens_then_shrink', {
                "count": "x", "shrink_subtype": "Zombie",
                "token": {"token_name": "Zombie", "power": 2, "toughness": 2, "colors": ["B"], "subtypes": ["Zombie"]},
            })],
            raw_text='target player creates x 2/2 black zombie creature tokens, then up to 1 target creature gets -1/-1 until end of turn for each zombie that player controls.',
        ),
    ]


register('Dark Salvation', _dark_salvation)
