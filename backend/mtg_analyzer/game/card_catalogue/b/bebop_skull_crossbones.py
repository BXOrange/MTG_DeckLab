from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _bebop_skull_crossbones() -> list[AbilitySpec]:
    """Partner with Rocksteady, Mutant Marauder (When this creature enters, target player may put Rocksteady into their hand from their library, then shuffle.)
    Deathtouch
    Whenever Bebop deals combat damage to a player, you may draw X cards, where X is the number of counters on Bebop. If you do, you lose X life.

    — PLAY-ALL (Turtle Power!). Partner-with and deathtouch are keywords. The trigger is an `optional` `bind` of the source's total counters (``counters_on``) into `draw` and `lose_life`.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("optional", {"prompt": "X Karten ziehen und X Leben verlieren?", "effects": [{
                "type": "bind", "params": {
                    "name": "x", "amount": {"kind": "count_selector", "selector": {"counters_on": "source"}},
                    "effects": [
                        {"type": "draw", "params": {"count": "$x"}},
                        {"type": "lose_life", "params": {"amount": "$x"}},
                    ],
                },
            }]})],
            trigger={"event": "DAMAGE", "condition": {"subject": "self"}, "filter": {"combat": True, "is_player": True}},
        ),
    ]


register("Bebop, Skull & Crossbones", _bebop_skull_crossbones)
