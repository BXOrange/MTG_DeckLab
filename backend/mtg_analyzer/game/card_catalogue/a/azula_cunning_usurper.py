from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _azula_cunning_usurper() -> list[AbilitySpec]:
    """Firebending 2 (Whenever this creature attacks, add {R}{R}. This mana lasts until end of combat.)
    When Azula enters, target opponent exiles a nontoken creature they control, then they exile a nonland card from their graveyard.
    During your turn, you may cast cards exiled with Azula and you may cast them as though they had flash. Mana of any type can be spent to cast those spells.
    """
    return [
        AbilitySpec('triggered', [EffectSpec('azula_exile', {})], trigger={
            'event': EventType.ENTERS_BATTLEFIELD, 'condition': {'subject': 'self'},
        }),
        AbilitySpec('static', [EffectSpec('linked_exile_permission', {
            'only_spells': True, 'flash': True, 'mana_wildcard': 'type',
            'active_if': {'kind': 'your_turn'},
        })]),
    ]


register('Azula, Cunning Usurper', _azula_cunning_usurper)
