from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _natural_order() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, sacrifice a green
    creature.
    Search your library for a green creature card, put it onto the
    battlefield, then shuffle.

    — MEC-43. The search half is already fully `MODELED` by the
    oracle-text parser; reused as-is. The additional cost needed a new
    color+type compound sacrifice-cost sentinel — `_matches_sacrifice_
    type`'s new ``"<color>_creature"`` branch (a catalogue-chosen
    sentinel, not derived from printed text by a parser handler),
    matched against the object's own layer-5 derived colours.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("search", {
                "criteria": {"type": "Creature", "color": "G"}, "destination": "battlefield",
            })],
            additional_cost={"sacrifice": "green_creature"},
        ),
    ]


register("Natural Order", _natural_order)
