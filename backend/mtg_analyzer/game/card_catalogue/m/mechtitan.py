from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mechtitan() -> list[AbilitySpec]:
    """Mechtitan, the legendary 10/10 token Mechtitan Core makes.
    When this token leaves the battlefield, return all cards exiled with Mechtitan Core except that card to the battlefield tapped under their owners' control.

    — PLAY-ALL (Shorikai Vehicles). A token has no catalogue entry of its own; this registers the *token's name* so the bind-on-load path gives it its
    leaves-the-battlefield trigger. The cards live in the token's `exiled_with_ids` (copied there by `transfer_exiled_with_to_created`).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_all_exiled_with", {"tapped": True})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Mechtitan", _mechtitan)
