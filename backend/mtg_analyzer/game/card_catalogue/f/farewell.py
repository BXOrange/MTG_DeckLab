from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _farewell() -> list[AbilitySpec]:
    """Choose one or more —
    • Exile all artifacts.
    • Exile all creatures.
    • Exile all enchantments.
    • Exile all graveyards.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [],
            modes={
                "choose": 1,
                "at_least": True,
                "options": [
                    [EffectSpec("exile", {"selector": "all_artifacts"})],
                    [EffectSpec("exile", {"selector": "all_creatures"})],
                    [EffectSpec("exile", {"selector": "all_enchantments"})],
                    [EffectSpec("exile_all_graveyards", {})],
                ],
                "descriptions": [
                    "Exiliere alle Artefakte.",
                    "Exiliere alle Kreaturen.",
                    "Exiliere alle Verzauberungen.",
                    "Exiliere alle Friedhöfe.",
                ],
            },
        )
    ]


register("Farewell", _farewell)
