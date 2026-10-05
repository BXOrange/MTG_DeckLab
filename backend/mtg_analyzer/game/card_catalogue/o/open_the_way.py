from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Open the Way (reveal-until-N-lands ramp) — PAR-60
# ===========================================================================
# New `RulesEngine.reveal_until_matching` (the `card_query`-predicate
# sibling of `reveal_until_creature_type`) + a ``reveal_until`` effect.


def _open_the_way() -> list[AbilitySpec]:
    """X can't be greater than the number of players in the game.
    Reveal cards from the top of your library until you reveal X land cards.
    Put those land cards onto the battlefield tapped and the rest on the
    bottom of your library in a random order.

    Documented simplification: the "X can't be greater than the number of
    players" cap is not enforced."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("reveal_until", {
                "criteria": {"type": "land"}, "count": "x",
                "hit_destination": "battlefield", "tapped": True,
                "rest_destination": "library_bottom_random",
            })],
        ),
    ]


register("Open the Way", _open_the_way)
