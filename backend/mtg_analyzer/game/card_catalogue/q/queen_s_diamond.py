from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _queen_s_diamond() -> list[AbilitySpec]:
    """{T}: Choose a color. Add one mana of that color for each charge counter on Queen's Diamond. Spend this mana only to cast your commander.
    Station (Tap another creature you control: Put charge counters equal to its power on this Spacecraft. Station only as a sorcery. It's an artifact creature at 8+.)
    8+ | Flying, vigilance, haste
    """
    return [
        AbilitySpec('static', [EffectSpec('grant_mana_ability', {'affects': 'self',
            'mana': [{color: 1} for color in ['W', 'U', 'B', 'R', 'G']],
            'amount_selector': {'kind': 'counters_on_self', 'counter': 'charge'},
            'mana_restriction': {'kind': 'commander_spell', 'your_commander': True},
        })]),
        AbilitySpec('static', [EffectSpec('grant_keyword', {'keywords': ['flying','vigilance','haste'],
            'affects': 'self', 'min_level': 8, 'level_counter': 'charge'})]),
        AbilitySpec('static', [EffectSpec('type_change', {'add_types': ['creature'], 'affects': 'self',
            'min_level': 8, 'level_counter': 'charge', 'power': 5, 'toughness': 5})]),
    ]


register("Queen's Diamond", _queen_s_diamond)
