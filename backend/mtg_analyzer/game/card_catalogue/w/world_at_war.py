from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _world_at_war() -> list[AbilitySpec]:
    """After the second main phase this turn, there's an additional combat phase followed by an additional main phase. At the beginning of that combat, untap all creatures that attacked this turn.
    Rebound (If you cast this spell from your hand, exile it as it resolves. At the beginning of your next upkeep, you may cast this card from exile without paying its mana cost.)"""
    return [AbilitySpec('spell_effect', [EffectSpec('extra_combat_phase', {
        'main_phase_too': True, 'after_second_main': True, 'untap_attacked_this_turn': True,
    })], rebound=True)]


register('World at War', _world_at_war)
