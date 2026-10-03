from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _hazels_brewmaster() -> list[AbilitySpec]:
    """Menace
    Whenever this creature enters or attacks, exile up to one target card from a graveyard and create a Food token.
    Foods you control have all activated abilities of all creature cards exiled with this creature.
    """
    return [
        AbilitySpec(
            'keyword',
            [
            ],
            keyword={'name': 'menace'},
        ),
        AbilitySpec(
            'triggered',
            [
                EffectSpec('exile', {'target_kind': 'any_graveyard_card',
                            'optional': True,
                            'track_exiled_with': True}),
                EffectSpec('create_token', {'count': 1, 'token_name': 'Food'}),
            ],
            trigger={'event': ['ENTERS_BATTLEFIELD', 'ATTACKS'],
                     'condition': {'subject': 'self'}},
        ),
        AbilitySpec(
            'static',
            [
                EffectSpec('grant_borrowed_activated_ability', {'affects': 'permanents_you_control',
                            'subtype': 'Food',
                            'creature_only': True}),
            ],
        ),
    ]


register("Hazel's Brewmaster", _hazels_brewmaster)
