from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _access_maze() -> list[AbilitySpec]:
    """Once during each of your turns, you may cast a spell from your hand by paying life equal to its mana value rather than paying its mana cost.
    (You may cast either half. That door unlocks on the battlefield. As a sorcery, you may pay the mana cost of a locked door to unlock it.)

    — MEC-111, the right door of Cramped Vents // Access Maze. Demon of Fate's Design's `granted_alt_cast_cost` (``pay_life_equal_mv``,
    ``once_per_turn``) without its ``card_type``, plus ``from_hand`` (the spell's own zone, read where the alternative cost is looked up).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("granted_alt_cast_cost", {"pay_life_equal_mv": True, "once_per_turn": True, "from_hand": True})],
        ),
    ]


register("Access Maze", _access_maze)
