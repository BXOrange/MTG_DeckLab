from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _priest_of_the_crossing() -> list[AbilitySpec]:
    """Flying
    At the beginning of each end step, put X +1/+1 counters on each creature you control, where X is the number of creatures that died under your control this turn.
    Embalm {4}{W}

    — PLAY-ALL Step 2 (Eternal Might). Flying/Embalm are printed keywords. A `STEP_BEGIN` end head with no
    `phase_relation` (every player's end step), a `bind` over the new per-controller count selector
    ``creatures_you_controlled_died_this_turn`` and a group `add_counters` over your creatures.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("bind", {
                "name": "n",
                "amount": {"kind": "count_selector", "selector": "creatures_you_controlled_died_this_turn"},
                "effects": [{"type": "add_counters", "params": {
                    "kind": "+1/+1", "amount": "$n", "selector": "each_creature_you_control",
                }}],
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}},
        ),
    ]


register("Priest of the Crossing", _priest_of_the_crossing)
