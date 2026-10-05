from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _reality_scramble() -> list[AbilitySpec]:
    """Put target permanent you own on the bottom of your library. Reveal
    cards from the top of your library until you reveal a card that shares
    a card type with that permanent. Put that card onto the battlefield
    and the rest on the bottom of your library in a random order.
    Retrace (You may cast this card from your graveyard by discarding a
    land card in addition to paying its other costs.)

    — MEC-12 (cEDH Kinnan). `ReturnToLibraryThenDigSharedTypeEffect` reads
    the type-matching predicate live off the just-bottomed permanent's own
    printed type words rather than a fixed criteria (see its own
    docstring). Retrace is a printed keyword (`Card.keywords`), recognized
    independently of this catalogue entry — nothing to model here.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("return_to_library_then_dig_shared_type", {
                "target_kind": "permanent_you_control",
            })],
        ),
    ]


register("Reality Scramble", _reality_scramble)
