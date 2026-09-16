from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Nexus Mentality (modal counter shuffle) — PAR-60
# ===========================================================================
# `MoveCountersEffect` gained ``move_all_kinds`` and `RemoveCountersEffect`
# gained ``draw_per_removed``.


def _nexus_mentality() -> list[AbilitySpec]:
    """Choose one. If you control a commander as you cast this spell, you may
    choose both instead.
    • Move all counters from target nonland permanent you control onto
      another target nonland permanent you control.
    • Remove all counters from target nonland permanent you control. Draw a
      card for each counter removed this way.

    Documented simplification: the "choose both" upside is modeled as an
    unconditional ``or_both`` (a Commander player virtually always controls
    or has cast their commander), rather than gating it on live commander
    control."""
    return [
        AbilitySpec(
            "spell_effect",
            [],
            modes={
                "choose": 1,
                "or_both": True,
                "options": [
                    [EffectSpec("move_counters", {
                        "source_target_kind": "nonland_permanent_you_control",
                        "dest_target_kind": "nonland_permanent_you_control",
                        "move_all_kinds": True,
                    })],
                    [EffectSpec("remove_counters", {
                        "target_kind": "nonland_permanent_you_control",
                        "draw_per_removed": True,
                    })],
                ],
                "descriptions": [
                    "Bewege alle Marken von einer bleibenden Nichtland-Zielkarte, die du "
                    "kontrollierst, auf eine andere.",
                    "Entferne alle Marken von einer bleibenden Nichtland-Zielkarte, die du "
                    "kontrollierst. Ziehe eine Karte fuer jede so entfernte Marke.",
                ],
            },
        )
    ]


register("Nexus Mentality", _nexus_mentality)
