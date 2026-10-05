from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _forgotten_creation() -> list[AbilitySpec]:
    """Skulk
    At the beginning of your upkeep, you may discard all the cards in your hand. If you do, draw that many cards.

    — PLAY-ALL Step 2 (Eternal Might). Skulk is a printed keyword. The upkeep trigger is an `optional` `bind`: the hand
    size is measured first, the whole hand discarded, then that many cards drawn ("if you do, draw that many").
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("optional", {"effects": [{"type": "bind", "params": {
                "name": "n",
                "amount": {"kind": "resource", "resource": "hand_size"},
                "effects": [
                    {"type": "discard", "params": {"whole_hand": True}},
                    {"type": "draw", "params": {"count": "$n"}},
                ],
            }}]})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"},
        ),
    ]


register("Forgotten Creation", _forgotten_creation)
