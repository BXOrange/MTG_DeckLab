from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _trinisphere() -> list[AbilitySpec]:
    """As long as this artifact is untapped, each spell that would cost
    less than three mana to cast costs three mana to cast instead.

    — MEC-12 (cEDH Kinnan). The new `cost_floor_for`/``min_generic``
    "costs no less than N" primitive — a floor, not the existing
    ``increase``/``generic`` additive tax (see `continuous.cost_floor_for`'s
    own docstring for why the two are kept apart). ``active_if:
    source_untapped`` is the existing RULE 613.6 gate vocabulary, reused
    as-is.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "affects": "all_spells", "min_generic": 3,
                "active_if": {"kind": "source_untapped"},
            })],
        ),
    ]


register("Trinisphere", _trinisphere)
