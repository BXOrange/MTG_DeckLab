from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _timetwister() -> list[AbilitySpec]:
    """Each player shuffles their hand and graveyard into their library,
    then draws seven cards.

    — Timetwister. ENG-37 B7 retired the fused `wheel` type: the printed
    line is a `seq` of the RULE 701.20 shuffle (`scope="each_player"`) and a
    mass `draw` (`selector="each_player"`). Written generically (not
    Timetwister-specific) since Time Reversal / Echo of Eons print the same
    line.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("seq", {"effects": [
                {"type": "shuffle_hand_and_graveyard_into_library",
                 "params": {"scope": "each_player"}},
                {"type": "draw", "params": {"selector": "each_player", "count": 7}},
            ]})],
        )
    ]


register("Timetwister", _timetwister)
