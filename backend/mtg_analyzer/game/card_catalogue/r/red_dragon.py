
from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _red_dragon() -> list[AbilitySpec]:
    'Flying\nFire Breath — When this creature enters, it deals 4 damage to each opponent.'
    return [
        AbilitySpec("triggered", [EffectSpec("damage", {"amount": 4, "selector": "each_opponent"})], trigger={"event": EventType.ENTERS_BATTLEFIELD}),
    ]


register('Red Dragon', _red_dragon)
