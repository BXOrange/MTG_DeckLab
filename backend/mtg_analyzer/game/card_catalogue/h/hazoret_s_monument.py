from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _hazoret_s_monument() -> list[AbilitySpec]:
    """Red creature spells you cast cost {1} less to cast.
    Whenever you cast a creature spell, you may discard a card. If you do, draw a card.

    — Reign of Dragons deck batch. The loot trigger is the parser's own claim; the discount is the
    Rhonas's Monument shape (`cost_reduction` over creature spells narrowed by ``spell_color``).
    """
    return [
        AbilitySpec("static", [EffectSpec("cost_reduction", {
            "affects": "your_spells", "generic": 1, "spell_type": "creature", "spell_color": "R",
        })]),
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {"cost": "discard a card",
                                          "effects": [{"type": "draw", "params": {"count": 1}}]})],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "you"},
                     "spell_filter": {"card_type": "creature"}},
        ),
    ]


register("Hazoret's Monument", _hazoret_s_monument)
