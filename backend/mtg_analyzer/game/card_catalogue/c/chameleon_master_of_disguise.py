from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _chameleon_master_of_disguise() -> list[AbilitySpec]:
    """You may have Chameleon enter as a copy of a creature you control, except
    his name is Chameleon, Master of Disguise.
    Mayhem {2}{U} (You may cast this card from your graveyard for {2}{U} if you
    discarded it this turn. Timing rules still apply.)

    — PLAY-ALL (Wick Snail Boom). `enter_as_copy` preserves Chameleon's
    name. RULE 702.187 Mayhem uses the ordinary graveyard cast path at its
    alternative cost after discarding this graveyard incarnation this turn;
    normal timing applies and no exile-on-resolution replacement is added.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("enter_as_copy", {
                "target_kind": "creature_you_control", "set_name": "Chameleon, Master of Disguise",
            })],
        ),
    ]


register("Chameleon, Master of Disguise", _chameleon_master_of_disguise)
