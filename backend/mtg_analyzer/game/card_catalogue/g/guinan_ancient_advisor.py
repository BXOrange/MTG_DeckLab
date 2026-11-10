from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


#: Creatures that must receive a counter for Guinan's draw ("two or more").
GUINAN_DRAW_THRESHOLD = 2


def _guinan_ancient_advisor() -> list[AbilitySpec]:
    """{1}, {T}: Put a +1/+1 counter on each creature you control that entered this turn. If you put two or more +1/+1 counters on creatures this way, draw a card.

    RULE 608.2c: the draw is gated on how many creatures received a
    counter. Every creature that entered this turn gets exactly one
    counter, so the number of such creatures you control is that count.
    """
    entered_this_turn = {"zone": "battlefield", "of": "you", "filter": {"card_type": "creature", "entered_this_turn": True}}
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("add_counters", {"count": 1, "kind": "+1/+1", "group": dict(entered_this_turn)}),
                EffectSpec("if_else", {
                    "condition": {"kind": "control_count", "selector": dict(entered_this_turn),
                                  "min": GUINAN_DRAW_THRESHOLD},
                    "then": [{"type": "draw", "params": {"count": 1}}],
                }),
            ],
            cost={"text": "{1}, {t}"},
        ),
    ]


register("Guinan, Ancient Advisor", _guinan_ancient_advisor)
