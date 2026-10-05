from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _drakuseth_maw_of_flames() -> list[AbilitySpec]:
    """Flying
    Whenever Drakuseth attacks, Drakuseth deals 4 damage to any target and 3 damage to each of up to two
    other targets.

    — Reign of Dragons deck batch. Flying is a keyword. The attack trigger is two `damage` effects, each
    announcing its own targets (RULE 601.2c): any target for the 4, and up to two more for the 3, the
    latter marked ``distinct_from_others`` ("other targets", RULE 109.5).
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("damage", {"amount": 4, "target_kind": "any"}),
                EffectSpec("damage", {"amount": 3, "target_kind": "any", "count": 2, "optional": True,
                                      "distinct_from_others": True}),
            ],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Drakuseth, Maw of Flames", _drakuseth_maw_of_flames)
