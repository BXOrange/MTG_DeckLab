from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _bathe_in_light() -> list[AbilitySpec]:
    """Radiance — Choose a color. Target creature and each other creature that shares a color with it gain
    protection from the chosen color until end of turn.

    — MEC-126. One target is announced; the colour is chosen once (RULE 702.16 protection, `temp_protections`,
    cleared at cleanup) and given to the target and every other creature sharing a colour with it at
    resolution (`composition.shared_characteristic_group`).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("grant_protection", {
                "target_kind": "creature",
                "group": {"shares": "color", "filter": {"card_type": "creature"}},
            })],
        )
    ]


register("Bathe in Light", _bathe_in_light)
