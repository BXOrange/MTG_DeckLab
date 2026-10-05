from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _juxtapose() -> list[AbilitySpec]:
    """You and target player exchange control of the creature you each
    control with the greatest mana value. Then exchange control of
    artifacts the same way. If two or more permanents a player controls
    are tied for greatest, their controller chooses one of them.

    — See `JuxtaposeEffect`'s own docstring for the two selection+exchange
    rounds and its documented tie-break simplification.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("juxtapose", {})],
        ),
    ]


register("Juxtapose", _juxtapose)
