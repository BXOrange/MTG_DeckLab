from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# modal "choose one [or more]" spells
# ===========================================================================
# Engine: `_mass_wipe_objects` ``token`` filter (Perplexing Test).


def _casualties_of_war() -> list[AbilitySpec]:
    """Choose one or more —
    • Destroy target artifact.
    • Destroy target creature.
    • Destroy target enchantment.
    • Destroy target land.
    • Destroy target planeswalker."""
    return [
        AbilitySpec(
            "spell_effect", [],
            modes={
                "choose": 1, "at_least": True,
                "options": [
                    [EffectSpec("destroy", {"target_kind": "artifact"})],
                    [EffectSpec("destroy", {"target_kind": "creature"})],
                    [EffectSpec("destroy", {"target_kind": "enchantment"})],
                    [EffectSpec("destroy", {"target_kind": "land"})],
                    [EffectSpec("destroy", {"target_kind": "planeswalker"})],
                ],
                "descriptions": [
                    "Zerstoere ein Ziel-Artefakt.",
                    "Zerstoere eine Zielkreatur.",
                    "Zerstoere eine Zielverzauberung.",
                    "Zerstoere ein Zielland.",
                    "Zerstoere einen Zielplaneswalker.",
                ],
            },
        ),
    ]


register("Casualties of War", _casualties_of_war)
