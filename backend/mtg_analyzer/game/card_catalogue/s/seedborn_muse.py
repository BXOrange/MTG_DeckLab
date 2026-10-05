from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _seedborn_muse() -> list[AbilitySpec]:
    """Untap all permanents you control during each other player's untap
    step.

    — Seedborn Muse. A new ``"not_you"`` group-trigger controller scope
    (`effect_binder._group_ok`, the mirror image of the existing ``"you"``
    scope) plus a new `TapEffect` ``"permanents_you_control"`` selector
    (`continuous.group_selector_objects` already supported the selector
    itself; only `effects._TAP_SELECTORS`'s whitelist was missing it).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("tap", {"untap": True, "selector": "permanents_you_control"})],
            trigger={
                "event": EventType.UNTAP,
                "condition": {"subject": "group", "controller": "not_you"},
            },
        )
    ]


register("Seedborn Muse", _seedborn_muse)
