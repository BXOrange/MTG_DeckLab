from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _champion_of_wits() -> list[AbilitySpec]:
    """When this creature enters, you may draw cards equal to its power. If you do, discard two cards.
    Eternalize {5}{U}{U}

    — PLAY-ALL Step 2 (Eternal Might). Eternalize is a printed keyword (recognized independently). The enter
    trigger is an `optional` pair — a `bind` measuring the source's power into a `draw`, then `discard` 2 — so
    declining skips both halves ("if you do"). Eternalized, the 4/4 token copy draws four.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("optional", {"effects": [
                {"type": "bind", "params": {
                    "name": "n",
                    "amount": {"kind": "characteristic", "characteristic": "power", "of": "source"},
                    "effects": [{"type": "draw", "params": {"count": "$n"}}],
                }},
                {"type": "discard", "params": {"count": 2}},
            ]})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Champion of Wits", _champion_of_wits)
