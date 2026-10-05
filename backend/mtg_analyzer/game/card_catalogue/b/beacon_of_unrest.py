from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _beacon_of_unrest() -> list[AbilitySpec]:
    """Put target artifact or creature card from a graveyard onto the
    battlefield under your control. Shuffle Beacon of Unrest into its
    owner's library.

    — MEC-43 round 2, the reanimation-family batch. ``target_kind=
    "graveyard_artifact_or_creature"`` is the new combined graveyard-
    target filter; ``shuffle_self_into_library`` (Green Sun's Zenith) is
    reused verbatim for the second clause.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("return_from_graveyard", {
                    "target_kind": "graveyard_artifact_or_creature", "under_your_control": True,
                }),
                EffectSpec("shuffle_self_into_library", {}),
            ],
        )
    ]


register("Beacon of Unrest", _beacon_of_unrest)
