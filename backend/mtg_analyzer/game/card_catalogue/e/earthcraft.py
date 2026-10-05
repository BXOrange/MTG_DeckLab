from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _earthcraft() -> list[AbilitySpec]:
    """Tap an untapped creature you control: Untap target basic land.

    — MEC-43. `ActivationCost.tap_others`'s existing bare-main-type
    matching (``(1, "creature")`` — RULE 118.9-style "an untapped creature
    you control" as a cost, already recognized for Dark Triumph's own
    "cycle" siblings) into `TapEffect`'s ``untap=True`` mode, targeting the
    new ``"basic_land"`` kind (the inverse filter of the existing
    ``"nonbasic_land"``).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("tap", {"untap": True, "target_kind": "basic_land"})],
            cost={"tap_others": [1, "creature"]},
        ),
    ]


register("Earthcraft", _earthcraft)
