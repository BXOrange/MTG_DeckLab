from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# reveal-until-a-type impulse cast (PAR-60)
# ===========================================================================
# `RulesEngine.dig_until` (the generalized cascade dig) already does
# "reveal from the top until <predicate>, free-cast the hit, rest to the
# bottom in a random order". Creative Technique is exactly that with a
# ``shuffle`` prologue.


def _creative_technique() -> list[AbilitySpec]:
    """Demonstrate (folds in from the RULE 702 keyword catalogue).
    Shuffle your library, then reveal cards from the top of it until you
    reveal a nonland card. Exile that card and put the rest on the bottom of
    your library in a random order. You may cast the exiled card without
    paying its mana cost."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("shuffle", {}),
             EffectSpec("dig_until", {
                 "criteria": {"without_type": "land"},
                 "hit_destination": "cast_free_window",
                 "rest_destination": "library_bottom_random",
             })],
        ),
    ]


register("Creative Technique", _creative_technique)
