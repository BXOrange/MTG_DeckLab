from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _specs() -> list[AbilitySpec]:
    """
    {T}, Pay 4 life, Sacrifice Apple of Eden: Look at target opponent's hand and exile those
    cards face down. You may play those cards this turn, and mana of any type can be spent
    to cast them. Until end of turn, whenever you play a land or cast a spell this way, its
    owner draws a card. At the beginning of the next end step, return the exiled cards to
    their owner's hand. Activate only as a sorcery.
    """
    return [
        AbilitySpec(
            'activated',
            [EffectSpec('exile_hand_may_play_owner_draws', {})],
            cost={'text': '{T}, Pay 4 life, Sacrifice ~', 'sorcery_speed_only': True},
        ),
    ]


register('Apple of Eden, Isu Relic', _specs)
