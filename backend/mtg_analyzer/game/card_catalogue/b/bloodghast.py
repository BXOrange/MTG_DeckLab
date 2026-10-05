from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _bloodghast() -> list[AbilitySpec]:
    """This creature can't block.
    This creature has haste as long as an opponent has 10 or less life.
    Landfall — Whenever a land you control enters, you may return this card
    from your graveyard to the battlefield."""
    BLOODGHAST_LIFE_THRESHOLD = 10
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {"keywords": ["cant_block"], "affects": "self"})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "keywords": ["haste"], "affects": "self",
                "active_if": {"kind": "opponent_life_at_most", "amount": BLOODGHAST_LIFE_THRESHOLD},
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_self_from_graveyard", {"tapped": False})],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "type": "land", "controller": "you",
                              "other": False},
            },
            optional=True,
        ),
    ]


register("Bloodghast", _bloodghast)
