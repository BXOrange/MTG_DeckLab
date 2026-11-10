from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _geordi_la_forge_innovator() -> list[AbilitySpec]:
    """Geordi La Forge can't be blocked if you control a Spacecraft.
    Whenever Geordi La Forge deals combat damage to a player, draw a card.

    RULE 509.1b: an unblockable keyword granted only while the controller
    controls a Spacecraft (``active_if`` re-evaluated every layer pass).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "keywords": ["cant_be_blocked"], "affects": "self",
                "active_if": {
                    "kind": "control_count",
                    "selector": {"zone": "battlefield", "of": "you", "filter": {"subtype": "spacecraft"}},
                    "min": 1,
                },
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.DAMAGE, "condition": {"subject": "self"},
                "filter": {"combat": True, "is_player": True},
            },
        ),
    ]


register("Geordi La Forge, Innovator", _geordi_la_forge_innovator)
