from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Animist's Awakening (reveal top X, take all lands) — PAR-60
# ===========================================================================
# New `animists_awakening` effect (a *fixed*-X reveal that takes every land,
# mastery (RULE 702.101a) untap folded in.


def _animists_awakening() -> list[AbilitySpec]:
    """Reveal the top X cards of your library. Put all land cards from among
    them onto the battlefield tapped and the rest on the bottom of your
    library in a random order.
    Spell mastery — If there are two or more instant and/or sorcery cards in
    your graveyard, untap those lands."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("animists_awakening", {"count": "x"})],
        ),
    ]


register("Animist's Awakening", _animists_awakening)
