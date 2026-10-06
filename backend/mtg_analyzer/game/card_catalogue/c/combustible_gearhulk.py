from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _combustible_gearhulk() -> list[AbilitySpec]:
    """First strike
    When this creature enters, target opponent may have you draw three cards. If the player doesn't, you mill three cards, then this creature deals damage to that player equal to the total mana value of those cards.

    — PLAY-ALL (Living Energy). First strike is the keyword's. Tergrid's Lantern's `pay_cost_then` with ``payer="target"``
    and a free (empty) cost: the targeted opponent answers yes/no. "Yes" runs the draw for you; "no" mills three and
    deals damage to that player equal to the milled cards' total mana value (`moved_sum`, fed by `mill`).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "", "payer": "target", "target_kind": "opponent",
                "prompt": "Soll der Gegner drei Karten ziehen?",
                "effects": [{"type": "draw", "params": {"count": 3}}],
                "else_effects": [
                    {"type": "mill", "params": {"count": 3}},
                    {"type": "damage", "params": {
                        "amount": {"kind": "moved_sum", "characteristic": "mana_value"}, "target_kind": "player",
                    }},
                ],
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Combustible Gearhulk", _combustible_gearhulk)
