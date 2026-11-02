from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _freyalise_supplicant() -> list[AbilitySpec]:
    "{T}, Sacrifice a red or white creature: This creature deals damage to any target equal to half the sacrificed creature's power, rounded down."
    return [
        AbilitySpec(
            'activated',
            [EffectSpec('damage', {"target_kind": 'any', "amount": {'kind': 'count_selector', 'selector': 'sacrificed_cost_power', 'divide': 2}})],
            cost={"taps_self": True, "sacrifice": 'red_creature_or_white_creature'},
            raw_text='',
        ),
    ]


register('Freyalise Supplicant', _freyalise_supplicant)
