from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _march_of_otherworldly_light() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, you may exile any
    number of white cards from your hand. This spell costs {2} less to
    cast for each card exiled this way.
    Exile target artifact, creature, or enchantment with mana value X
    or less.

    — MEC-43. The additional cost is an exact recolor of March of
    Swirling Mist's own `exile_discount_cost` static (MEC-42) — white
    instead of blue, otherwise identical. The exile clause is an
    ordinary targeted `ExileEffect` with an MV filter, off the spell's
    own announced X (`max_mana_value_selector`-style — read fresh via
    the same `_substitute_x` sentinel machinery already generalized in
    MEC-41 for Bring to Light).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("exile_discount_cost", {"color": "W", "generic_per_card": 2})],
        ),
        AbilitySpec(
            "spell_effect",
            [EffectSpec("exile", {
                "target_kind": "artifact_creature_or_enchantment", "max_mana_value": "x",
            })],
        ),
    ]


register("March of Otherworldly Light", _march_of_otherworldly_light)
