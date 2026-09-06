"""Blight Curse Commander deck catalogue entries.

Cards in this module have card-specific casting/amount semantics that the
fail-closed oracle parser must not guess.  Each factory remains pure so a
second object of the card receives fresh specs.
"""

from __future__ import annotations

from ...parser.oracle.spec import AbilitySpec, EffectSpec

from .core import register


def _cathartic_reunion() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, discard two cards.
    Draw three cards."""
    return [
        AbilitySpec(
            "spell_effect", [EffectSpec("draw", {"count": 3})],
            additional_cost={"discard": 2},
            raw_text="as an additional cost to cast this spell, discard 2 cards. draw 3 cards.",
        )
    ]


register("Cathartic Reunion", _cathartic_reunion)


def _chain_reaction() -> list[AbilitySpec]:
    """Chain Reaction deals X damage to each creature, where X is the
    number of creatures on the battlefield."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {
                "amount": 0, "selector": "each_creature",
                "amount_from_count_selector": "all_creatures",
            })],
            raw_text="~ deals x damage to each creature, where x is the number of creatures on the battlefield.",
        )
    ]


register("Chain Reaction", _chain_reaction)
