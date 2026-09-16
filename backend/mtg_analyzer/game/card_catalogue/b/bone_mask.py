from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _bone_mask() -> list[AbilitySpec]:
    """{2}, {T}: The next time a source of your choice would deal damage
    to you this turn, prevent that damage. Exile cards from the top of
    your library equal to the damage prevented this way.

    — Bone Mask (MEC-30, Phase 8). The trailing sentence is a new
    `RulesEngine.apply_prevent_rider` kind, ``"exile_top_of_library_
    scaled"`` — `mill`'s exile-instead-of-graveyard sibling, since no
    existing primitive exiled a fixed count off the top of the library in
    one call.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "amount": "all", "rider": {"kind": "exile_top_of_library_scaled"},
            })],
            cost={"text": "{2}, {T}"},
        ),
    ]


register("Bone Mask", _bone_mask)
