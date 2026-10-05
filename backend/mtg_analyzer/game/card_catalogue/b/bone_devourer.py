from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _bone_devourer() -> list[AbilitySpec]:
    """Flash
    Flying
    This creature enters with a number of +1/+1 counters on it equal to the number of creatures that died this turn.
    When this creature dies, you draw X cards and you lose X life, where X is the number of +1/+1 counters on it.

    — Bone Devourer. Flash/Flying come from the keyword catalogue. The entry counters are Boss's Chauffeur's
    `enters_with_counters_count` over the existing `creatures_died_this_turn` selector (every player's creatures,
    RULE 700.4). The dies trigger measures the counters as it dies (last-known information, RULE 603.10a) with
    `bind`, then draws and loses that many.
    """
    return [
        AbilitySpec("static", [EffectSpec("enters_with_counters_count", {
            "kind": "+1/+1", "base": 0, "count_selector": "creatures_died_this_turn",
        })]),
        AbilitySpec(
            "triggered",
            [EffectSpec("bind", {
                "name": "n", "amount": {"kind": "counters", "counter": "+1/+1", "of": "source"},
                "effects": [
                    {"type": "draw", "params": {"count": "$n"}},
                    {"type": "lose_life", "params": {"amount": "$n"}},
                ],
            })],
            trigger={"event": EventType.DIES, "condition": {"subject": "self"}},
        ),
    ]


register("Bone Devourer", _bone_devourer)
