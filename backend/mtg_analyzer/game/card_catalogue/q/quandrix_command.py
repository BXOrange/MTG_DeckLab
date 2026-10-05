from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ---------------------------------------------------------------------------
# The Charm / Command modal spells (STX). The fail-closed parser claims most
# modes on their own but each spell has one mode built on a family the
# grammar can't yet reach, so the whole "choose N —" block fail-closes.
# Authored wholesale; every mode below is an ordinary parser-shaped
# EffectSpec bar the one noted per card. See PAR-60.
# ---------------------------------------------------------------------------


def _quandrix_command() -> list[AbilitySpec]:
    """Choose two —
    • Return target creature or planeswalker to its owner's hand.
    • Counter target artifact or enchantment spell.
    • Put two +1/+1 counters on target creature.
    • Target player shuffles up to three target cards from their graveyard
      into their library.

    Modes 1-3 are exactly what `match_clause` already emits. Mode 4 is the
    new `ShuffleTargetGraveyardCardsIntoLibraryEffect`
    ("shuffle_target_graveyard_cards_into_library") — the spell's controller
    picks up to three cards in the targeted player's graveyard at
    resolution (RULE 601.2c) and each returns to that player's library,
    which is then shuffled (RULE 701.20). Modeled with a
    `_request_choose_objects` rather than three separate card targets, an
    accepted RULE 115 precision loss."""
    QUANDRIX_COUNTERS = 2
    QUANDRIX_GY_CARD_CAP = 3
    return [
        AbilitySpec(
            "spell_effect",
            [],
            modes={
                "choose": 2,
                "options": [
                    [EffectSpec("return_to_hand", {"target_kind": "creature_or_planeswalker"})],
                    [EffectSpec("counter", {"card_types": ["artifact", "enchantment"]})],
                    [EffectSpec("add_counters", {
                        "count": QUANDRIX_COUNTERS, "kind": "+1/+1", "target_kind": "creature",
                    })],
                    [EffectSpec("shuffle_target_graveyard_cards_into_library", {
                        "count_max": QUANDRIX_GY_CARD_CAP,
                    })],
                ],
                "descriptions": [
                    "Bringe eine Zielkreatur oder einen Zielplaneswalker auf die Hand ihres Besitzers zurück.",
                    "Neutralisiere einen Ziel-Artefakt- oder -Verzauberungszauberspruch.",
                    "Lege zwei +1/+1-Marken auf eine Zielkreatur.",
                    "Ein Zielspieler mischt bis zu drei Zielkarten aus seinem Friedhof in seine Bibliothek.",
                ],
            },
        )
    ]


register("Quandrix Command", _quandrix_command)
