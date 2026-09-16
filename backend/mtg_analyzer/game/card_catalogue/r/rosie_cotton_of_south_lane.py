from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _rosie_cotton_of_south_lane() -> list[AbilitySpec]:
    """When Rosie Cotton enters, create a Food token.
    Whenever you create a token, put a +1/+1 counter on target creature
    you control other than Rosie Cotton.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "token_name": "Food"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"target_kind": "other_creature_you_control"})],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {
                    "subject": "group", "type": "permanent",
                    "controller": "you", "other": False,
                },
                "filter": {"is_token": True},
            },
        ),
    ]


register("Rosie Cotton of South Lane", _rosie_cotton_of_south_lane)
