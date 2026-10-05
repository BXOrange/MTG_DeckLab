from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Dance with Calamity (MV-budget exile loop) — PAR-60
# ===========================================================================
# New `dance_with_calamity` effect. Documented simplification: the "as many
# times as you choose" gamble is auto-resolved greedily (exile from the top
# while running total MV stays <= 13), and every non-land card exiled gets a
# this-turn free-cast window.


def _dance_with_calamity() -> list[AbilitySpec]:
    """Shuffle your library. As many times as you choose, you may exile the
    top card of your library. If the total mana value of the cards exiled
    this way is 13 or less, you may cast any number of spells from among
    those cards without paying their mana costs."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("dance_with_calamity", {})],
        ),
    ]


register("Dance with Calamity", _dance_with_calamity)
