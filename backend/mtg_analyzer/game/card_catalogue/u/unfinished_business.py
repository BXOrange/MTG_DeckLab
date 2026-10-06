from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _unfinished_business() -> list[AbilitySpec]:
    """Return target creature card from your graveyard to the battlefield, then return up to two target Aura and/or Equipment cards from your graveyard to the battlefield attached to that creature. (If the Auras can't enchant that creature, they remain in your graveyard.)

    — PLAY-ALL (Limit Break). `return_from_graveyard` of the creature, then of one or two ``graveyard_aura_or_equipment`` cards with the new ``attach_to_previous`` (each enters attached to the
    returned creature; an Aura that cannot enchant it stays in the graveyard).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("return_from_graveyard", {"target_kind": "graveyard_creature", "destination": "battlefield"}),
                EffectSpec("return_from_graveyard", {
                    "target_kind": "graveyard_aura_or_equipment", "destination": "battlefield", "count": 1, "count_max": 2,
                    "attach_to_previous": True,
                }),
            ],
        ),
    ]


register("Unfinished Business", _unfinished_business)
