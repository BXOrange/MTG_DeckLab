from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _rampaging_aetherhood() -> list[AbilitySpec]:
    """Trample, ward {2}
    At the beginning of your upkeep, you get an amount of {E} (energy counters) equal to this creature's power. Then you may pay one or more {E}. If you do, put that many +1/+1 counters on this creature.

    — PLAY-ALL (Living Energy). Keywords are the catalogue's. One upkeep trigger: `add_player_counters` measuring the
    source's power, then the variable `pay_energy_then` over `add_counters` (the paid amount binds ``"x"``).
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("add_player_counters", {
                    "amount": {"kind": "characteristic", "characteristic": "power", "of": "self"}, "kind": "energy",
                }),
                EffectSpec("pay_energy_then", {"amount": 1, "variable": True, "effects": [
                    {"type": "add_counters", "params": {"count": "x", "kind": "+1/+1"}},
                ]}),
            ],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"},
        ),
    ]


register("Rampaging Aetherhood", _rampaging_aetherhood)
