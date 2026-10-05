from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _kutzil_malamet_exemplar() -> list[AbilitySpec]:
    """Kutzil, Malamet Exemplar (Legendary Creature — Cat Warrior, {1}{G}{W})

    "Your opponents can't cast spells during your turn.
    Whenever one or more creatures you control each with power greater
    than its base power deals combat damage to a player, draw a card."

    The first static is already parser-claimable (``cast_prohibition``
    with an ``active_if: your_turn`` RULE 613.6 gate). The trigger is the
    MEC-29 aggregate combat-damage event with the composed batch head's
    ``contributors`` + a per-contributor ``power_gt_base`` filter (PAR-131).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cast_prohibition", {"scope": "opponents", "active_if": {"kind": "your_turn"}})],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": "CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER",
                # PAR-131: the composed batch head's shape; "each with power
                # greater than its base power" is a per-contributor filter.
                "condition": {"subject": "group", "controller": "you", "other": False,
                              "filter": {"card_type": "creature", "power_gt_base": True}},
                "contributors": {"min": 1},
            },
        ),
    ]


register("Kutzil, Malamet Exemplar", _kutzil_malamet_exemplar)
