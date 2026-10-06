from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _specs() -> list[AbilitySpec]:
    """
    When Dack Fayden enters, reveal cards from the top of your library until you reveal X
    creature cards, where X is the number of opponents you have. Put those creature cards
    onto the battlefield, then shuffle. They're goaded for the rest of the game. For each of
    those permanents, choose a different opponent. Each opponent gains control of the
    permanent for which they were chosen.

    Known limitation: creatures enter through sequential entry chooser calls, rather than
    one simultaneous entry batch.
    """
    return [
        AbilitySpec(
            'triggered',
            [EffectSpec('reveal_creatures_give_opponents', {})],
            trigger={'event': EventType.ENTERS_BATTLEFIELD, 'condition': {'subject': 'self'}},
        ),
    ]


register('Dack Fayden, Helping Hand', _specs)
