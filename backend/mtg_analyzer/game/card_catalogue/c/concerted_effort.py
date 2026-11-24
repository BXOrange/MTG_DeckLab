from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ....models.game.events import EventType
from ...card_registry.core import register


def _concerted_effort() -> list[AbilitySpec]:
    """At the beginning of each upkeep, creatures you control gain flying until end of turn if a creature you control has flying. The same is true for fear, first strike, double strike, landwalk, protection, trample, and vigilance."""
    return [AbilitySpec('triggered', [EffectSpec('share_creature_combat_abilities', {})],
        trigger={'event': EventType.STEP_BEGIN, 'filter': {'step': 'upkeep'}})]


register('Concerted Effort', _concerted_effort)
