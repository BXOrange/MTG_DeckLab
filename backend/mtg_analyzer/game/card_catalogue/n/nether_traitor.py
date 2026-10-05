from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _nether_traitor() -> list[AbilitySpec]:
    """Haste
    Shadow
    Whenever another creature is put into your graveyard from the
    battlefield, you may pay {B}. If you do, return this card from your
    graveyard to the battlefield.

    Documented simplification: "into your graveyard" (ownership) is modeled
    as "another creature you control dies" (control) — the common case."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "{B}",
                "effects": [{"type": "return_self_from_graveyard", "params": {}}],
            })],
            trigger={"event": EventType.DIES,
                     "condition": {"subject": "group", "type": "creature",
                                   "controller": "you", "other": True}},
        ),
    ]


register("Nether Traitor", _nether_traitor)
