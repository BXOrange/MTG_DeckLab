from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _maddening_hex() -> list[AbilitySpec]:
    """Enchant player
    Whenever enchanted player casts a noncreature spell, roll a d6. This Aura deals damage to that player equal to the result. Then attach this Aura to another one of your opponents chosen at random.
    """
    return [AbilitySpec('triggered', [
        EffectSpec('roll_die', {'sides': 6}),
        EffectSpec('maddening_hex_damage', {}),
        EffectSpec('maddening_hex_attach', {}),
    ], trigger={
        'event': EventType.SPELL_CAST,
        'condition': {'subject': 'player', 'scope': 'enchanted'},
        'spell_exclude_card_types': ['creature'],
    })]


register('Maddening Hex', _maddening_hex)
