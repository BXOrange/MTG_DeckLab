from __future__ import annotations

from ...costs import SACRIFICE_COUNT_X
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _radiant_lotus() -> list[AbilitySpec]:
    """{T}, Sacrifice one or more artifacts: Choose a color. Target player adds
    three mana of the chosen color for each artifact sacrificed this way.

    — MEC-103. "Sacrifice one or more artifacts" is the announced-X sacrifice
    cost Grim Hireling already uses (`costs.SACRIFICE_COUNT_X`, RULE 601.2b), so
    "each artifact sacrificed" is simply X. The mana is one colour decision
    (`AddManaEffect`'s ``colors=["ANY"]`` branch → `add_mana_any_color`), sized
    ``any_amount="x"`` × ``any_amount_multiplier=3`` and paid to the targeted
    player (``recipient="target_player"``).

    Documented simplification: X = 0 is not refused (the printed "one or more"
    minimum), which merely lets the Lotus be tapped for nothing.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("add_mana", {
                "colors": ["ANY"], "any_amount": "x", "any_amount_multiplier": 3,
                "target_kind": "player", "recipient": "target_player",
            })],
            cost={"text": "{T}", "sacrifice_count": (SACRIFICE_COUNT_X, "artifact")},
        ),
    ]


register("Radiant Lotus", _radiant_lotus)
