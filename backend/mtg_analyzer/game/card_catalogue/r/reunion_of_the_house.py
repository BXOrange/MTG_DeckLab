from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "total power 10 or less".
_TOTAL_POWER = 10


def _reunion_of_the_house() -> list[AbilitySpec]:
    """Return any number of target creature cards with total power 10 or less from your graveyard to the battlefield. Exile Reunion of the House.

    Announced targets share a total-power bound; returns use the ordinary primitive.
    """
    return [
        AbilitySpec("spell_effect", [
            EffectSpec("return_from_graveyard", {
                "target_kind": "graveyard_creature", "any_number": True, "optional": True,
                "total_power_max": _TOTAL_POWER,
            }),
            EffectSpec("exile", {"target_kind": None}),
        ]),
    ]


register("Reunion of the House", _reunion_of_the_house)
