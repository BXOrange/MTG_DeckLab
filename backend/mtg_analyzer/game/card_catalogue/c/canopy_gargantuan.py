from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _canopy_gargantuan() -> list[AbilitySpec]:
    """Flying, ward {2}
    At the beginning of your upkeep, put a number of +1/+1 counters on each other creature you control equal to that creature's toughness.

    — PLAY-ALL (Abzan Armor). Flying and ward are keywords. The upkeep trigger is `add_counters` over a structured
    "creatures you control" group excluding itself, with the new ``per_recipient_stat: toughness`` — each creature gets its own
    toughness in counters, all measured before any are placed.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {
                "kind": "+1/+1", "per_recipient_stat": "toughness", "group_other": True,
                "group": {"zone": "battlefield", "of": "you", "filter": {"card_type": "creature"}},
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"},
        ),
    ]


register("Canopy Gargantuan", _canopy_gargantuan)
