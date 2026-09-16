from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _djinn_of_infinite_deceits() -> list[AbilitySpec]:
    """Flying
    {T}: Exchange control of two target nonlegendary creatures. You can't
    activate this ability during combat.

    — The multi-target `count=2` mode's own shared filter (`second_
    creature_filter={"nonlegendary": True}`, new `combat.matches_object_
    filter` key) plus the new `ActivationCost.not_during_combat` timing
    flag (RULE 602.5d's converse of `sorcery_speed_only`).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("exchange_control", {
                "target_kind": "creature", "count": 2,
                "second_creature_filter": {"nonlegendary": True},
            })],
            cost={"text": "{T}", "not_during_combat": True},
        ),
    ]


register("Djinn of Infinite Deceits", _djinn_of_infinite_deceits)
