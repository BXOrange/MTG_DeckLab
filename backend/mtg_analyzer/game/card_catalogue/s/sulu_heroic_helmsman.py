from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sulu_heroic_helmsman() -> list[AbilitySpec]:
    """Sulu stations Spacecraft and crews Vehicles as though his power were tripled."""
    return [AbilitySpec('static', [EffectSpec('combat_restriction', {
        'kind': 'crew_station_power_multiplier', 'affects': 'self', 'count': 3,
    })])]


register('Sulu, Heroic Helmsman', _sulu_heroic_helmsman)
