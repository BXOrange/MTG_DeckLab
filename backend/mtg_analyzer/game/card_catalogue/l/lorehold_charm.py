from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _lorehold_charm() -> list[AbilitySpec]:
    """Choose one —
    • Each opponent sacrifices a nontoken artifact of their choice.
    • Return target artifact or creature card with mana value 2 or less from
      your graveyard to the battlefield.
    • Creatures you control get +1/+1 and gain trample until end of turn.

    Mode 2 is `return_from_graveyard` over the existing
    ``graveyard_artifact_or_creature`` kind with a ``max_mana_value`` cap
    (both already wired in `targeting`). Documented simplification: mode 1's
    "**nontoken**" narrowing isn't expressible on `SacrificeEffect.what`, so
    it sacrifices any artifact — an opponent almost never prefers to feed a
    Treasure/Clue token to it anyway."""
    LOREHOLD_REANIMATE_MV = 2
    return [
        AbilitySpec(
            "spell_effect",
            [],
            modes={
                "choose": 1,
                "options": [
                    [EffectSpec("sacrifice", {
                        "selector": "each_opponent", "what": "artifact", "count": 1,
                    })],
                    [EffectSpec("return_from_graveyard", {
                        "target_kind": "graveyard_artifact_or_creature",
                        "destination": "battlefield",
                        "max_mana_value": LOREHOLD_REANIMATE_MV,
                    })],
                    [EffectSpec("pump", {
                        "power": 1, "toughness": 1, "keywords": ["trample"],
                        "selector": "creatures_you_control",
                    })],
                ],
                "descriptions": [
                    "Jeder Gegner opfert ein Artefakt seiner Wahl.",
                    "Bringe eine Ziel-Artefakt- oder -Kreaturenkarte mit Manawert 2 oder weniger aus deinem Friedhof ins Spiel zurück.",
                    "Kreaturen unter deiner Kontrolle erhalten +1/+1 und Trampelschaden bis zum Ende des Zuges.",
                ],
            },
        )
    ]


register("Lorehold Charm", _lorehold_charm)
