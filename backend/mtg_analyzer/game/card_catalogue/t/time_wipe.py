from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _time_wipe() -> list[AbilitySpec]:
    """Return a creature you control to its owner's hand, then destroy all
    creatures.

    — Time Wipe. The return is `choose_objects`' ``return_to_hand`` pick over
    the controller's own creatures (a choice, not a target — RULE 115 never
    applies), and the board wipe rides it twice over: as the "if you did"
    tail and as the "nothing to return" tail (`else_effects`), because the
    wipe is unconditional even when the controller has no creature to save.
    """
    wipe = {"type": "destroy", "params": {"selector": "all_creatures", "can_be_regenerated": True}}
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("choose_objects", {
                "action": "return_to_hand", "what": "creature", "count": 1,
                "prompt": "Wähle eine Kreatur, die auf deine Hand zurückkehrt",
                "then": [dict(wipe)], "else_effects": [dict(wipe)],
            })],
        )
    ]


register("Time Wipe", _time_wipe)
