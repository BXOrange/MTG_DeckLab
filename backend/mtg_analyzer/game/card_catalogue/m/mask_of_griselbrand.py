from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mask_of_griselbrand() -> list[AbilitySpec]:
    """Equipped creature has flying and lifelink.
    Whenever equipped creature dies, you may pay X life, where X is its power. If you do, draw X cards.
    Equip {3}

    — PLAY-ALL (Endless Punishment). Equip is the keyword; the grant and the ``attached_permanent`` dies head are the parser's. The payment is G'raha Tia's
    `pay_cost_then` with ``pay_life_x`` priced from the firing event's own ``power`` (the dying creature's last-known power, RULE 603.10a) and the draw counted by
    the same X.
    """
    return [
        AbilitySpec("static", [EffectSpec("grant_keyword", {"affects": "attached_permanent", "keywords": ["flying", "lifelink"]})]),
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "", "pay_life_x": True, "x_from_trigger_event": "power",
                "effects": [{"type": "draw", "params": {"count": "$x"}}],
            })],
            trigger={"event": EventType.DIES, "condition": {"subject": "attached_permanent"}},
        ),
    ]


register("Mask of Griselbrand", _mask_of_griselbrand)
