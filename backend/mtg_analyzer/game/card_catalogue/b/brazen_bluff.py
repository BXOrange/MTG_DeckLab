from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _brazen_bluff() -> list[AbilitySpec]:
    """Choose target noncreature spell an opponent controls. That player may exile it. If they don't, you may cast a noncreature spell from your hand without paying its mana cost."""
    return [AbilitySpec('spell_effect', [EffectSpec('optional', {
        'player': {'of': 'target', 'as': 'controller'},
        'effects': [{'type': 'exile', 'params': {
            'target_kind': 'spell_you_dont_control', 'spell_filter': {'noncreature': True},
            'spell_or_permanent': True,
        }}],
        'else_effects': [{'type': 'free_cast_from_hand', 'params': {
            'noncreature_only': True, 'during_resolution': True,
        }}],
    })])]


register('Brazen Bluff', _brazen_bluff)
