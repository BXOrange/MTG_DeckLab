from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _fell_the_mighty() -> list[AbilitySpec]:
    """Destroy all creatures with power greater than target creature's
    power.

    Simplified: the dynamic threshold (the target creature's own power,
    read fresh at resolution) isn't modeled — widened to a fixed "power 4
    or greater" mass destroy (`min_power`, the same filter Dusk // Dawn
    uses), a reasonable typical-target approximation without a real
    "compare to the resolved target's own characteristic" mass-selector
    primitive.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("destroy", {"selector": "all_creatures", "filter": {"min_power": 4}})],
        ),
    ]


register("Fell the Mighty", _fell_the_mighty)
