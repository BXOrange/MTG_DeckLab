from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _quantum_reduction() -> list[AbilitySpec]:
    """Teamwork 2 (As an additional cost to cast this spell, you may tap any number of creatures you control with total power 2 or more.)
    You may cast this spell as though it had flash if it's cast using teamwork.
    Enchant creature
    Enchanted creature gets -5/-0 and loses all abilities.
    """
    return [AbilitySpec('static', [
        EffectSpec('anthem', {'power': -5, 'toughness': 0, 'affects': 'attached_permanent'}),
        EffectSpec('remove_all_abilities', {'affects': 'attached_permanent'}),
    ], conditional_flash={'active_if': {'kind': 'flag', 'flag': 'teamwork_paid'}})]


register('Quantum Reduction', _quantum_reduction)
