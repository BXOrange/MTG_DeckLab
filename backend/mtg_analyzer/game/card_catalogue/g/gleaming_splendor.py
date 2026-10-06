from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _specs() -> list[AbilitySpec]:
    """
    Whenever an opponent draws their second card each turn, you create a Treasure token.
    {2}{W}: Two target players each draw a card.
    """
    return [
        AbilitySpec(
            'triggered',
            [EffectSpec('create_token', {'token_name': 'Treasure', 'count': 1})],
            trigger={
                'event': EventType.DRAW,
                'condition': {'subject': 'player', 'scope': 'not_you'},
                'is_nth_draw_this_turn': 2,
            },
        ),
        AbilitySpec(
            'activated',
            [EffectSpec('draw', {'count': 1, 'target_kind': 'player', 'target_count': 2})],
            cost={'text': '{2}{W}'},
        ),
    ]


register('Gleaming Splendor', _specs)
