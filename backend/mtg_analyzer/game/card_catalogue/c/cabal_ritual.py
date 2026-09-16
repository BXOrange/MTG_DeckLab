from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _cabal_ritual() -> list[AbilitySpec]:
    """Cabal Ritual (Instant, {1}{B})

    "Add {B}{B}{B}.
    Threshold — Add {B}{B}{B}{B}{B} instead if there are seven or more
    cards in your graveyard."

    Modeled as a flat 3 B plus a *conditional extra 2 B* rather than a true
    "instead" override — mathematically identical (5 = 3 + 2) and avoids
    needing the general, still-unbuilt "if kicked, `<effect>` instead"
    override primitive (CLAUDE.md's Notable Gaps) for what is, arithmetically,
    an additive bonus. `EffectSpec.condition`'s new `cards_in_graveyard_at_
    least` key (RULE 702.19 Threshold's own gate) is a plain graveyard-size
    read, reusable by any future Threshold card with the same "Add X
    instead" phrasing.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("add_mana", {"colors": ["B", "B", "B"]}),
                EffectSpec(
                    "add_mana", {"colors": ["B", "B"]},
                    condition={"cards_in_graveyard_at_least": 7},
                ),
            ],
        ),
    ]


register("Cabal Ritual", _cabal_ritual)
