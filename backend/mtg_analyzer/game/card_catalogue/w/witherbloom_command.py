from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _witherbloom_command() -> list[AbilitySpec]:
    """Choose two —
    • Target player mills three cards, then you return a land card from your
      graveyard to your hand.
    • Destroy target noncreature, nonland permanent with mana value 2 or less.
    • Target creature gets -3/-1 until end of turn.
    • Target opponent loses 2 life and you gain 2 life.

    Mode 1 is a `mill` (targeted player) followed by a `return_from_graveyard`
    of a land to hand — non-targeted on the card, modeled as a
    ``graveyard_land`` target in the controller's own graveyard (accepted
    RULE 115 precision loss). Mode 2 uses the new
    ``noncreature_nonland_permanent`` target kind (`nonland_permanent` minus
    creatures) with a ``max_mana_value`` cap. Modes 3-4 are exactly what
    `match_clause` emits, mode 4 split into its `lose_life` + `gain_life`
    halves."""
    WITHERBLOOM_MILL = 3
    WITHERBLOOM_DESTROY_MV = 2
    WITHERBLOOM_DRAIN = 2
    return [
        AbilitySpec(
            "spell_effect",
            [],
            modes={
                "choose": 2,
                "options": [
                    [
                        EffectSpec("mill", {"count": WITHERBLOOM_MILL, "target_kind": "player"}),
                        EffectSpec("return_from_graveyard", {
                            "target_kind": "graveyard_land", "destination": "hand",
                        }),
                    ],
                    [EffectSpec("destroy", {
                        "target_kind": "noncreature_nonland_permanent",
                        "max_mana_value": WITHERBLOOM_DESTROY_MV,
                    })],
                    [EffectSpec("pump", {"power": -3, "toughness": -1, "target_kind": "creature"})],
                    [
                        EffectSpec("lose_life", {"amount": WITHERBLOOM_DRAIN, "target_kind": "opponent"}),
                        EffectSpec("gain_life", {"amount": WITHERBLOOM_DRAIN}),
                    ],
                ],
                "descriptions": [
                    "Ein Zielspieler legt drei Karten von seiner Bibliothek in seinen Friedhof, dann bringst du eine Landkarte aus deinem Friedhof auf deine Hand zurück.",
                    "Zerstöre eine bleibende Nichtkreatur-Nichtland-Zielkarte mit Manawert 2 oder weniger.",
                    "Eine Zielkreatur erhält -3/-1 bis zum Ende des Zuges.",
                    "Ein Zielgegner verliert 2 Lebenspunkte und du erhältst 2 Lebenspunkte.",
                ],
            },
        )
    ]


register("Witherbloom Command", _witherbloom_command)
