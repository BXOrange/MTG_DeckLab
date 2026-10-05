from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _robe_of_stars() -> list[AbilitySpec]:
    """Equipped creature gets +0/+3.
    Astral Projection — {1}{W}: Equipped creature phases out.
    Equip {1}

    — Robe of Stars. Astral Projection is now real (RULE 702.26 phasing,
    `game/effects/core.py`'s `PhaseOutEffect`, scoped to the single-permanent
    case this card needs — no "phase out together" attachment chain).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"affects": "attached_permanent", "power": 0, "toughness": 3})],
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("phase_out", {})],
            cost={"mana": "{1}{W}"},
        ),
    ]


register("Robe of Stars", _robe_of_stars)
