from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sudden_substitution() -> list[AbilitySpec]:
    """Split second (As long as this spell is on the stack, players can't
    cast spells or activate abilities that aren't mana abilities.)
    Exchange control of target noncreature spell and target creature. Then
    the spell's controller may choose new targets for it.

    — `ExchangeControlSpellEffect`'s two-independent-targets mode
    (``permanent_target_kind="creature"``, ``spell_filter={"noncreature":
    True}``); Split Second is a plain flag keyword, already parsed off the
    printed text.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("exchange_control_spell", {
                "permanent_target_kind": "creature",
                "spell_filter": {"noncreature": True},
            })],
        ),
    ]


register("Sudden Substitution", _sudden_substitution)
