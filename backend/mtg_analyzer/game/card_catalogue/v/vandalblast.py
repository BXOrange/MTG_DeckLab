from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _vandalblast() -> list[AbilitySpec]:
    """Destroy target artifact you don't control.
    Overload {4}{R} (You may cast this spell for its overload cost. If
    you do, change "target" in its text to "each.")

    — Imodane deck batch. The base mode needed a new `artifact_you_dont_
    control` target kind, the artifact-typed mirror of the existing
    `creature_you_dont_control`. **Documented simplification**: Overload
    (RULE 702.96) isn't modeled, matching the standing precedent Winds of
    Abandon/Damn/Cyclonic Rift already set in this catalogue — no
    alternative-cost mechanism stamps "was this spell cast via its
    overload cost" anywhere yet.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("destroy", {"target_kind": "artifact_you_dont_control"})],
        ),
    ]


register("Vandalblast", _vandalblast)
