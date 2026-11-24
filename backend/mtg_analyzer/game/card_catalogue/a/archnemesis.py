from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _archnemesis() -> list[AbilitySpec]:
    """Enchant opponent
    Whenever you attack enchanted player, that player loses 2 life. You draw a card and gain 2 life.
    Whenever a player attacks you, you may attach this Aura to that player.
    """
    return [
        AbilitySpec('triggered', [
            EffectSpec('lose_life', {'amount': 2, 'player': {'of': 'attacked_player', 'as': 'self'}}),
            EffectSpec('draw', {'count': 1}),
            EffectSpec('gain_life', {'amount': 2}),
        ], trigger={
            'event': EventType.PLAYER_ATTACKED,
            'condition': {'subject': 'group', 'controller': 'you', 'attacks_enchanted_player': True},
        }),
        AbilitySpec('triggered', [EffectSpec('trigger_subject_referent', {
            'referent': 'attacking_player',
            'effects': [{'type': 'optional', 'params': {
                'effects': [{'type': 'archnemesis_attach', 'params': {}}],
            }}],
        })], trigger={
            'event': EventType.PLAYER_ATTACKED,
            'condition': {'subject': 'group', 'attacks_you': True},
        }),
    ]


register('Archnemesis', _archnemesis)
