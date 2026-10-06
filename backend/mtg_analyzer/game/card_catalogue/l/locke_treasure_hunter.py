from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _specs() -> list[AbilitySpec]:
    """Locke can't be blocked by creatures with greater power.
    Mug — Whenever Locke attacks, each player mills a card. If a land card was milled this way, create a Treasure token. Until end of turn, you may cast a spell from among those cards.
    """
    return [
        AbilitySpec(
            'static',
            [
                EffectSpec(
                    'combat_restriction',
                    {
                        'kind': 'cant_be_blocked_by',
                        'filter': {'power_vs_reference': 'greater'},
                        'affects': 'self',
                    },
                ),
            ],
        ),
        AbilitySpec(
            'triggered',
            [EffectSpec('mill_each_player_may_cast_milled', {})],
            trigger={'event': EventType.ATTACKS, 'condition': {'subject': 'self'}},
        ),
    ]


register('Locke, Treasure Hunter', _specs)
