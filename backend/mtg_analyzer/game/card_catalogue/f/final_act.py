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

    Documented simplification: "Destroy all battles" is modeled as
    ``selector="all_battles"`` (inert if the mass-wipe helper doesn't know
    the selector — no cached battle in these decks reaches it)."""
    return [
        AbilitySpec(
            "spell_effect", [],
            modes={
                "choose": 1, "at_least": True,
                "options": [
                    [EffectSpec("destroy", {"selector": "all_creatures"})],
                    [EffectSpec("destroy", {"selector": "all_planeswalkers"})],
                    [EffectSpec("destroy", {"selector": "all_battles"})],
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
