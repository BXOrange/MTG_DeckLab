from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _narsets_reversal() -> list[AbilitySpec]:
    """Copy target instant or sorcery spell, then return it to its owner's
    hand. You may choose new targets for the copy.

    — Narset's Reversal. The copy half was already shipped
    (`CopySpellEffect`); the *bounce* half needed a new engine primitive:
    every existing "return to hand" moves a battlefield permanent, and this
    one pulls a `StackItem` off the stack entirely (`RulesEngine.
    return_spell_to_hand`, RULE 400.1). Practically that's a counter that
    leaves the card in hand instead of the graveyard — which is why it beats
    "can't be countered".

    Kept as one atomic effect rather than two composed ones for the same
    reason `GainControlUntilEndOfTurnEffect` is: both clauses act on the
    *same* chosen spell, and two separate targeting effects would prompt for
    it twice. Order matters and is the card's whole trick — the copy is made
    **first**, so it survives the original being picked up.

    The controller finishes the copy's optional target choices before
    the next instruction returns the original spell to its owner's hand.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("copy_spell", {"card_types": ["instant", "sorcery"]}),
                EffectSpec("return_to_hand", {
                    "previous_subject": True, "spell_or_permanent": True,
                }),
            ],
        ),
    ]


register("Narset's Reversal", _narsets_reversal)
