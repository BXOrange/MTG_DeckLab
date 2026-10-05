from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec
from ...card_registry.core import register


def _mox_diamond() -> list[AbilitySpec]:
    """If this artifact would enter, you may discard a land card instead.
    If you do, put this artifact onto the battlefield. If you don't, put
    it into its owner's graveyard.
    {T}: Add one mana of any color.

    — MEC-12 (sixth pass): RULE 614.12's own worked example, confirmed a
    singleton template cache-wide (a raw-text grep for "would enter, you
    may" turns up only this card). `AbilitySpec.enter_or_graveyard_discard_
    land` (`RulesEngine._offer_enter_or_graveyard`, offered *before* every
    other battlefield-entry step, since declining means this never becomes
    a permanent at all) is a new, genuinely general RULE 614.12 primitive
    even though only one card needs it today — a bare marker flag, not a
    parametrized cost, since a second card of this shape would almost
    certainly print the identical "discard a land card" cost anyway. The
    mana ability itself needs no hand-authoring: a plain "{T}: Add one
    mana of any color." is recognized generically by `mana_abilities_for`.
    """
    return [
        AbilitySpec(
            "static", [],
            enter_or_graveyard_discard_land=True,
        ),
    ]


register("Mox Diamond", _mox_diamond)
