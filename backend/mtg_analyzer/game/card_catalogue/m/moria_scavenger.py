
from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _moria_scavenger() -> list[AbilitySpec]:
    """Deathtouch, haste
    {T}, Discard a card: Draw a card. If the discarded card was a creature card, amass Orcs 1.

    RULE 602.2b: the ``{T}`` and discard are the activation's cost. The "if the discarded card was a creature card"
    gate reads `GameObject.discarded_cost_card_types`, which the activation cost path now stamps (the same record the
    spell-cost path keeps for Grab the Prize), so the amass is checked against the card the cost actually threw away
    (RULE 608.2c, resolution). Deathtouch and haste are printed keywords the engine already recognises.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("draw", {"count": 1}),
                EffectSpec(
                    "amass", {"subtype": "Orc", "count": 1},
                    condition={"kind": "discarded_cost_card_is", "card_type": "creature"},
                ),
            ],
            cost={"taps_self": True, "discard": 1},
        ),
    ]


register("Moria Scavenger", _moria_scavenger)
