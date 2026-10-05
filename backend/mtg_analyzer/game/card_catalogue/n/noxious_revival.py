from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _noxious_revival() -> list[AbilitySpec]:
    """Put target card from a graveyard on top of its owner's library.

    — Noxious Revival. `return_from_graveyard` with the new ``library_top``
    destination (the card goes to its *owner's* library top, the engine
    default when no controller override is given).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "any_graveyard_card",
                "destination": "library_top",
            })],
        )
    ]


register("Noxious Revival", _noxious_revival)
