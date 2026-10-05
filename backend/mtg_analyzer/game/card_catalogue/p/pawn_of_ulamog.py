from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _pawn_of_ulamog() -> list[AbilitySpec]:
    """Whenever this creature or another nontoken creature you control dies,
    you may create a 0/1 colorless Eldrazi Spawn creature token. It has
    "Sacrifice this token: Add {C}."
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "token_name": "Eldrazi Spawn", "power": 0, "toughness": 1,
                "colors": [], "subtypes": ["Eldrazi", "Spawn"],
            })],
            trigger={
                "event": EventType.DIES,
                "condition": {"subject": "group", "type": "creature", "controller": "you"},
                "filter": {"want_token": False},
            },
            optional=True,
        ),
    ]


register("Pawn of Ulamog", _pawn_of_ulamog)
