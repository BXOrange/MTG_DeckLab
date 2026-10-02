from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _chameleon_master_of_disguise() -> list[AbilitySpec]:
    """You may have Chameleon enter as a copy of a creature you control, except
    his name is Chameleon, Master of Disguise.
    Mayhem {2}{U} (You may cast this card from your graveyard for {2}{U} if you
    discarded it this turn. Timing rules still apply.)

    — PLAY-ALL Step 2 (Wick Snail Boom). `enter_as_copy` over
    ``creature_you_control`` with the new ``set_name`` ("…except his name is ~"):
    the rename happens after the copied abilities are bound, because binding is
    keyed by card name. **Documented gap: Mayhem is not castable** — RULE 702.186
    (cast from the graveyard for {2}{U} if it was discarded this turn) has no
    engine support at all; the creature is only castable from hand at {3}{U}.
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
