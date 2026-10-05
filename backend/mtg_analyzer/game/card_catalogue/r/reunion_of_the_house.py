from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "total power 10 or less".
_TOTAL_POWER = 10


def _reunion_of_the_house() -> list[AbilitySpec]:
    """Return any number of target creature cards with total power 10 or less from your graveyard to the battlefield. Exile Reunion of the House.

    — PLAY-ALL (Abzan Armor). `return_creatures_total_mana_value` with ``measure: power`` over your own graveyard (a choice at
    resolution), then the spell exiles itself (`exile` with no target, as "Exile ~." parses).
    """
    return [
        AbilitySpec("spell_effect", [
            EffectSpec("return_creatures_total_mana_value", {
                "budget": _TOTAL_POWER, "measure": "power", "own_graveyard": True,
            }),
            EffectSpec("exile", {"target_kind": None}),
        ]),
    ]


register("Reunion of the House", _reunion_of_the_house)
