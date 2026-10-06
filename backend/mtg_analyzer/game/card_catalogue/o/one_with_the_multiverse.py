from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _one_with_the_multiverse() -> list[AbilitySpec]:
    """You may look at the top card of your library any time.
    You may play lands and cast spells from the top of your library.
    Once during each of your turns, you may cast a spell from your hand or the top of your library without paying its mana cost.

    — PLAY-ALL (Miracle Worker). The first two lines are the parser's `top_library_permission`. The third is Aluren's
    `free_cast_permission` limited to the ``hand`` and ``library`` zones and ``once_per_turn`` (spent by the first free cast).
    """
    return [
        AbilitySpec("static", [EffectSpec("top_library_permission", {"look": True})]),
        AbilitySpec(
            "static",
            [EffectSpec("top_library_permission", {"look": True, "play_lands": True, "cast_spells": True})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("free_cast_permission", {"once_per_turn": True, "zones": ["hand", "library"]})],
        ),
    ]


register("One with the Multiverse", _one_with_the_multiverse)
