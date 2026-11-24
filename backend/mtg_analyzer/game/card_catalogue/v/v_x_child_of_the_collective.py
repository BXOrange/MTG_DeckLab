from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ....models.game.events import EventType
from ...card_registry.core import register


def _v_x_child_of_the_collective() -> list[AbilitySpec]:
    """When Võx enters and at the beginning of your first main phase, the next artifact creature spell and the next Spacecraft spell you cast this turn have undaunted. (They cost {1} less to cast for each opponent.)"""
    return [
        AbilitySpec('triggered', [EffectSpec('grant_next_undaunted', {})], trigger={
            'event': EventType.ENTERS_BATTLEFIELD, 'condition': {'subject': 'self'},
        }),
        AbilitySpec('triggered', [EffectSpec('grant_next_undaunted', {})], trigger={
            'event': EventType.STEP_BEGIN, 'filter': {'main_phase_number': 1}, 'phase_relation': 'you',
        }),
    ]


register('Võx, Child of the Collective', _v_x_child_of_the_collective)
