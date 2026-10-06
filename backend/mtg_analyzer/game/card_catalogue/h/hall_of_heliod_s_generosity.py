from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _hall_of_heliod_s_generosity() -> list[AbilitySpec]:
    """{T}: Add {C}.
    {1}{W}, {T}: Put target enchantment card from your graveyard on top of your library.

    — PLAY-ALL (Miracle Worker). The mana ability is auto-bound; the second is Academy Ruins' return-to-library-top over the own-graveyard
    ``graveyard_enchantment`` kind.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("return_from_graveyard", {"target_kind": "graveyard_enchantment", "destination": "library_top"})],
            cost={"mana": "{1}{W}", "taps_self": True},
        ),
    ]


register("Hall of Heliod's Generosity", _hall_of_heliod_s_generosity)
