from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _rebbec_architect_of_ascension() -> list[AbilitySpec]:
    """Artifacts you control have protection from each mana value among artifacts you control.
    Partner (You can have two commanders if both have partner.)

    — PLAY-ALL (Shorikai Vehicles). Partner is a keyword. The static is `grant_protection_static` over ``artifacts_you_control`` with the new
    ``protection_from_mana_values_among_artifacts``: one ``mv:N`` quality per distinct mana value among your artifacts, re-derived every layer pass
    (`combat._quality_matches_type` matches it against the source's printed mana value), so an artifact is protected from any source whose mana value
    equals one of theirs.
    """
    return [
        AbilitySpec("static", [EffectSpec("grant_protection_static", {
            "affects": "artifacts_you_control", "protection_from_mana_values_among_artifacts": True,
        })]),
    ]


register("Rebbec, Architect of Ascension", _rebbec_architect_of_ascension)
