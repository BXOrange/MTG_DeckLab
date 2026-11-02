from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _licia_sanguine_tribune() -> list[AbilitySpec]:
    'This spell costs {1} less to cast for each 1 life you gained this turn.\nFirst strike, lifelink\nPay 5 life: Put three +1/+1 counters on Licia. Activate only during your turn and only once each turn.'
    return [
        AbilitySpec(
            'activated',
            [EffectSpec('add_counters', {"count": 3, "kind": '+1/+1'}), EffectSpec('only_during_your_turn_marker', {}), EffectSpec('once_per_turn_marker', {})],
            cost={"text": 'pay 5 life'},
            raw_text='pay 5 life: put 3 +1/+1 counters on ~. activate only during your turn and only once each turn.',
        ),
        AbilitySpec(
            'static',
            [EffectSpec('cost_reduction', {"affects": 'self', "generic": 1, "per": 'life_gained_this_turn'})],
            raw_text='',
        ),
    ]


register('Licia, Sanguine Tribune', _licia_sanguine_tribune)
