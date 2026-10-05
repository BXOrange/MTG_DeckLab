from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _overwhelming_stampede() -> list[AbilitySpec]:
    """Until end of turn, creatures you control gain trample and get +X/+X, where X is the greatest
    power among creatures you control.

    — Tramplesaurus Rex deck batch. Pathbreaker Ibex's group `pump` (trample + the
    ``greatest_power_among_creatures_you_control`` amount), here as a spell. X is read once, as the
    spell resolves, before any creature has been pumped.
    """
    return [
        AbilitySpec("spell_effect", [EffectSpec("pump", {
            "selector": "creatures_you_control", "keywords": ["trample"],
            "amount_from_count_selector": "greatest_power_among_creatures_you_control",
        })]),
    ]


register("Overwhelming Stampede", _overwhelming_stampede)
