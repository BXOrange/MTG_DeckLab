from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _heartless_hidetsugu() -> list[AbilitySpec]:
    "{T}: Heartless Hidetsugu deals damage to each player equal to half that player's life total, rounded down."
    return [
        AbilitySpec(
            'activated',
            [EffectSpec('damage', {'selector': 'each_player', 'amount_per_recipient': {'kind': 'resource', 'resource': 'life', 'of': 'target', 'divide': 2}})],
            cost={"text": '{T}'},
            raw_text='',
        ),
    ]


register('Heartless Hidetsugu', _heartless_hidetsugu)
