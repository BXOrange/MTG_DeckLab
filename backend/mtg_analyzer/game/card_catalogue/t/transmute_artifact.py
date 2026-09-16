from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _transmute_artifact() -> list[AbilitySpec]:
    """Sacrifice an artifact. If you do, search your library for an
    artifact card. If that card's mana value is less than or equal to the
    sacrificed artifact's mana value, put it onto the battlefield. If
    it's greater, you may pay {X}, where X is the difference. If you do,
    put it onto the battlefield. If you don't, put it into its owner's
    graveyard. Then shuffle.

    — MEC-12 (sixth pass). `TransmuteArtifactEffect`/`RulesEngine.
    transmute_artifact` — confirmed a singleton cost-comparison-gated
    placement cache-wide, self-contained (its own three `pending_choice`
    kinds: sacrifice, search, and an optional pay-the-difference) rather
    than composed from the general search/sacrifice/`pay_cost_then`
    primitives, none of which can express a cost computed from what a
    different, just-made choice turned out to be.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("transmute_artifact", {})],
        ),
    ]


register("Transmute Artifact", _transmute_artifact)
