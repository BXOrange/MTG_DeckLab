from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _archetype_of_imagination() -> list[AbilitySpec]:
    """Creatures you control have flying.
    Creatures your opponents control lose flying and can't have or gain flying.

    — PLAY-ALL (Miracle Worker). The first line is the parser's `grant_keyword`. The second is a layer-6 `remove_keyword`
    over ``creatures_opponents_control``: removal is read off every keyword source, so a creature that could gain flying later
    still loses it ("can't have or gain").
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {"affects": "creatures_you_control", "keywords": ["flying"]})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("remove_keyword", {"affects": "creatures_opponents_control", "keywords": ["flying"]})],
        ),
    ]


register("Archetype of Imagination", _archetype_of_imagination)
