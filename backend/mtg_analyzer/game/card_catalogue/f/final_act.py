from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _final_act() -> list[AbilitySpec]:
    """Choose one or more —
    • Destroy all creatures.
    • Destroy all planeswalkers.
    • Destroy all battles.
    • Exile all graveyards.
    • Each opponent loses all counters.

    "Destroy all battles" is a structured ``group`` over battles (ENG-61)."""
    return [
        AbilitySpec(
            "spell_effect", [],
            modes={
                "choose": 1, "at_least": True,
                "options": [
                    [EffectSpec("destroy", {"group": {"zone": "battlefield", "of": "any", "filter": {"card_type": "creature"}}})],
                    [EffectSpec("destroy", {"group": {"zone": "battlefield", "of": "any", "filter": {"card_type": "planeswalker"}}})],
                    [EffectSpec("destroy", {"group": {"zone": "battlefield", "of": "any", "filter": {"card_type": "battle"}}})],
                    [EffectSpec("exile_all_graveyards", {})],
                    [EffectSpec("lose_all_player_counters", {"selector": "each_opponent"})],
                ],
                "descriptions": [
                    "Zerstoere alle Kreaturen.",
                    "Zerstoere alle Planeswalker.",
                    "Zerstoere alle Kaempfe.",
                    "Exiliere alle Friedhoefe.",
                    "Jeder Gegner verliert alle Marken.",
                ],
            },
        ),
    ]


register("Final Act", _final_act)
