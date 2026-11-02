
from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _kitsune_bonesetter() -> list[AbilitySpec]:
    '{T}: Prevent the next 3 damage that would be dealt to target creature this turn. Activate only if you have more cards in hand than each opponent.'
    return [
        AbilitySpec('activated', [EffectSpec('prevent_damage_shield', {
            'amount': 3, 'target_kind': 'creature', 'duration': 'end_of_turn',
        })], cost={'text': '{T}', 'activation_condition': {
            'kind': 'you_have_most', 'selector': 'cards_in_your_hand',
        }}),
    ]


register('Kitsune Bonesetter', _kitsune_bonesetter)
