from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tireless_provisioner() -> list[AbilitySpec]:
    """Landfall — Whenever a land you control enters, create a Food token
    or a Treasure token.

    Simplified: narrowed to always creating a Food token — the "or a
    Treasure" choice isn't modeled (no interactive "choose one of two
    token types" primitive for a plain trigger body exists yet).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "token_name": "Food"})],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "type": "land", "controller": "you", "other": False},
            },
        ),
    ]


register("Tireless Provisioner", _tireless_provisioner)
