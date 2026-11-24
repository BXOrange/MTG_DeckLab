from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ....models.game.events import EventType
from ...card_registry.core import register


def _t_pring_never_parted() -> list[AbilitySpec]:
    """Kal-if-fee — When T'Pring enters, choose another target creature you control and target creature an opponent controls. You may have the chosen creatures fight each other. Whenever a creature that fought this way dies this turn, you draw a card."""
    return [AbilitySpec('triggered', [EffectSpec('optional', {
        'effects': [{'type': 'fight', 'params': {
            'fighter_kind': 'creature_you_control', 'fighter_exclude_source': True,
            'other_kind': 'creature_you_dont_control',
            'dies_this_turn_effects': [{'type': 'draw', 'params': {'count': 1}}],
        }}],
    })], trigger={'event': EventType.ENTERS_BATTLEFIELD, 'condition': {'subject': 'self'}})]


register("T'Pring, Never Parted", _t_pring_never_parted)
