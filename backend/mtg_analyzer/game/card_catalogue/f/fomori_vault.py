from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _specs() -> list[AbilitySpec]:
    """
    {T}: Add {C}.
    {3}, {T}, Discard a card: Look at the top X cards of your library, where X is the number
    of artifacts you control. Put one of those cards into your hand and the rest on the
    bottom of your library in a random order.
    """
    return [
        AbilitySpec(
            'activated',
            [
                EffectSpec(
                    'look_top_select',
                    {
                        'count': {'kind': 'count_selector', 'selector': 'artifacts_you_control'},
                        'select_count': 1,
                        'rest_order': 'random',
                    },
                ),
            ],
            cost={'text': '{3}, {T}, Discard a card'},
        ),
    ]


register('Fomori Vault', _specs)
