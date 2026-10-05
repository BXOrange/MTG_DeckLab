from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _kwain_itinerant_meddler() -> list[AbilitySpec]:
    """{T}: Each player may draw a card, then each player who drew a card this way gains 1 life.

    — Peace Offering deck batch. `for_each` over every player; each is asked (a free `pay_cost_then`,
    ``payer="target"``, Ja/Nein) and, if they accept, draws and gains 1 life as the target. **Documented
    simplification:** the life gain follows each player's own draw instead of waiting for every player to have
    drawn — the totals are the same.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("for_each", {
                "over": {"players": "each_player"},
                "effects": [{"type": "pay_cost_then", "params": {
                    "cost": "", "payer": "target", "prompt": "Draw a card and gain 1 life?",
                    "effects": [
                        {"type": "draw", "params": {"count": 1, "target_kind": "player"}},
                        {"type": "gain_life", "params": {"amount": 1, "target_kind": "player"}},
                    ],
                }}],
            })],
            cost={"text": "{t}"},
        ),
    ]


register("Kwain, Itinerant Meddler", _kwain_itinerant_meddler)
