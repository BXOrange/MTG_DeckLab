from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mirkwood_bats() -> list[AbilitySpec]:
    """Flying
    Whenever you create or sacrifice a token, each opponent loses 1 life.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("lose_life", {"amount": 1, "selector": "each_opponent"})],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {
                    "subject": "group", "type": "permanent",
                    "controller": "you", "other": False,
                },
                "filter": {"is_token": True},
            },
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("lose_life", {"amount": 1, "selector": "each_opponent"})],
            trigger={
                "event": EventType.SACRIFICE,
                "condition": {"subject": "you"},
                "filter": {"is_token": True},
            },
        ),
    ]


register("Mirkwood Bats", _mirkwood_bats)
