from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _destiny_spinner() -> list[AbilitySpec]:
    """Creature and enchantment spells you control can't be countered.
    {3}{G}: Target land you control becomes an X/X Elemental creature with
    trample and haste until end of turn, where X is the number of
    enchantments you control. It's still a land.

    — MEC-43. Only the first clause is authored here (`GrantCantBeCountered
    Effect`'s new ``"creature_or_enchantment_spells_you_control"`` scope,
    the two-type union sibling of the existing creature-only one); the
    land-animation activated ability is the recurring "animate a
    noncreature permanent into an X/Y creature" gap `BACKLOG.md` already
    tracks as its own open item, deliberately left unbound rather than
    stubbed here.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_cant_be_countered", {"scope": "creature_or_enchantment_spells_you_control"})],
        ),
    ]


register("Destiny Spinner", _destiny_spinner)
