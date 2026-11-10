from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register
from ...creature_type_counts import CREATURE_TYPES_AMONG_NON_BORG_CREATURES_YOU_CONTROL

#: "for every five creature types": one card per full group of this many (RULE 107.2 rounds the division down).
CREATURE_TYPES_PER_CARD = 5
#: "If you draw three or more cards this way": the draw count that turns the counters on.
CARDS_FOR_COUNTERS = 3
#: "put two +1/+1 counters on each creature you control".
COUNTERS_PER_CREATURE = 2


def _sarek_federation_ambassador() -> list[AbilitySpec]:
    """Federation — At the beginning of combat on your turn, draw a card for every five creature types among non-Borg
    creatures you control. If you draw three or more cards this way, put two +1/+1 counters on each creature you control.

    — MEC-143. A `bind` measures the distinct-creature-types count once (RULE 608.2h), divided by five and rounded down,
    and draws that many. The counter rider compares the same measurement against three: the cards drawn are exactly that
    number, except when the library runs short, in which case the player loses at the next state-based action check
    before the counters could matter (RULE 704.5b). Documented simplification: no per-resolution "cards drawn this way"
    tally exists, so the rider reads the measurement instead.
    """
    drawn = {
        "kind": "count_selector", "selector": CREATURE_TYPES_AMONG_NON_BORG_CREATURES_YOU_CONTROL,
        "divide": CREATURE_TYPES_PER_CARD,
    }
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("bind", {
                    "name": "n", "amount": drawn,
                    "effects": [{"type": "draw", "params": {"count": "$n"}}],
                }),
                EffectSpec("add_counters", {
                    "kind": "+1/+1", "selector": "each_creature_you_control", "count": COUNTERS_PER_CREATURE,
                }, condition={
                    "kind": "amount_compare", "op": "ge", "left": drawn,
                    "right": {"kind": "fixed", "amount": CARDS_FOR_COUNTERS},
                }),
            ],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"}, "phase_relation": "you"},
        ),
    ]


register("Sarek, Federation Ambassador", _sarek_federation_ambassador)
