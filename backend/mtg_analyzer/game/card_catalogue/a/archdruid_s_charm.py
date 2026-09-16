from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _archdruids_charm() -> list[AbilitySpec]:
    """Choose one —
    • Search your library for a creature or land card and reveal it. Put it
      onto the battlefield tapped if it's a land card. Otherwise, put it
      into your hand. Then shuffle.
    • Put a +1/+1 counter on target creature you control. It deals damage
      equal to its power to target creature you don't control.
    • Exile target artifact or enchantment.

    — Archdruid's Charm. The second mode announces two independent targets
    (`add_counters`'s ``creature_you_control`` + `damage_equal_to_power`'s
    ``creature_you_dont_control``). ENG-37 B4: it is now a plain two-clause
    list, not the fused ``counter_then_fightlike_damage`` — `AddCountersEffect`
    recomputes at the end of its own `apply` (RULE 613.1, like every other
    P/T one-shot), so the `damage_equal_to_power` clause reads the boosted
    power off `GameContext.previous_targets` (``dealer_kind="previous_target"``).

    The first mode's *conditional* destination is `SearchLibraryEffect`'s
    ``destination_if``: unlike the positional ``destinations`` list (which
    is fixed when the search opens — Cultivate's "one tapped, one to hand"),
    this branches on the card the player actually found, which is the only
    way to express "onto the battlefield tapped **if it's a land card**.
    Otherwise, put it into your hand."
    """
    return [
        AbilitySpec(
            "spell_effect",
            [],
            modes={
                "options": [
                    [EffectSpec("search", {
                        "criteria": {"type": ["Creature", "Land"]},
                        "destination": "hand",
                        "destination_if": [
                            {"criteria": {"type": "Land"},
                             "destination": "battlefield_tapped"},
                        ],
                        "count": 1,
                    })],
                    [
                        EffectSpec("add_counters", {
                            "kind": "+1/+1", "amount": 1,
                            "target_kind": "creature_you_control",
                        }),
                        EffectSpec("damage_equal_to_power", {
                            "dealer_kind": "previous_target",
                            "target_kind": "creature_you_dont_control",
                        }),
                    ],
                    [EffectSpec("exile", {"target_kind": "artifact_or_enchantment"})],
                ],
                "descriptions": [
                    "Durchsuche deine Bibliothek nach einer Kreaturen- oder Landkarte.",
                    "Lege eine +1/+1-Marke auf eine Zielkreatur, die du kontrollierst. "
                    "Sie fügt einer Zielkreatur, die du nicht kontrollierst, Schaden "
                    "in Höhe ihrer Stärke zu.",
                    "Exiliere ein Zielartefakt oder eine Zielverzauberung.",
                ],
            },
        ),
    ]


register("Archdruid's Charm", _archdruids_charm)
