from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Redoubled Stormsinger (copy each just-entered token) — PAR-60
# ===========================================================================
# New `redoubled_stormsinger_copies` effect + the existing
# `create_delayed_trigger` ``capture="created_objects"`` + `sacrifice_
# specific` idiom for the "sacrifice those tokens at the next end step" tail.


def _redoubled_stormsinger() -> list[AbilitySpec]:
    """First strike (folds in).
    Whenever this creature attacks, for each creature token you control that
    entered this turn, create a tapped and attacking token that's a copy of
    that token. At the beginning of the next end step, sacrifice those
    tokens."""
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("redoubled_stormsinger_copies", {}),
                EffectSpec("create_delayed_trigger", {
                    "step": "end", "scope": "any", "capture": "created_objects",
                    "effects": [{"type": "sacrifice_specific", "params": {}}],
                    "description": "Redoubled Stormsinger: Spielsteine opfern",
                }),
            ],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Redoubled Stormsinger", _redoubled_stormsinger)
