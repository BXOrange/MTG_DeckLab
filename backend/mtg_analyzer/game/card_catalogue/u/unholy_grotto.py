from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _unholy_grotto() -> list[AbilitySpec]:
    """{T}: Add {C}.
    {B}, {T}: Put target Zombie card from your graveyard on top of your library.

    — PLAY-ALL Step 2 (Eternal Might). The mana ability is parsed from the printed text. The second is Noxious
    Revival's `return_from_graveyard` with the ``library_top`` destination, over the new graveyard target kind
    ``graveyard_zombie_card`` (a creature subtype read off the printed type line).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("return_from_graveyard", {"target_kind": "graveyard_zombie_card", "destination": "library_top"})],
            cost={"mana": "{B}", "taps_self": True},
        ),
    ]


register("Unholy Grotto", _unholy_grotto)
