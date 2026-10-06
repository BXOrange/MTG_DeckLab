from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "Mill 3 cards."
_MILL = 3


def _rejoin_the_fight() -> list[AbilitySpec]:
    """Mill three cards. Then starting with the next opponent in turn order, each opponent chooses a creature card in your graveyard that hasn't been chosen. Return each card chosen this way to the battlefield under your control.

    — PLAY-ALL (Revival Trance). A `seq` of the mill and `return_from_graveyard` ``pick_mode="each_opponent_from_yours"``
    (each opponent, in turn order, picks from the controller's graveyard; a chosen card has already left it, so none is
    chosen twice).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("seq", {"effects": [
                {"type": "mill", "params": {"count": _MILL}},
                {"type": "return_from_graveyard", "params": {
                    "pick_mode": "each_opponent_from_yours", "under_your_control": True, "destination": "battlefield",
                }},
            ]})],
        ),
    ]


register("Rejoin the Fight", _rejoin_the_fight)
