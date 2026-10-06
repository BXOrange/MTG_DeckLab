from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "they mill that many cards plus four instead".
_EXTRA_MILL = 4


def _the_water_crystal() -> list[AbilitySpec]:
    """If an opponent would mill one or more cards, they mill that many cards plus four instead.
    {4}{U}{U}, {T}: Each opponent mills cards equal to the number of cards in your hand.

    — PLAY-ALL (Hope to the last). The replacement is the new `mill_replacement` (``WOULD_MILL`` event, opponents of the
    controller, ``plus`` 4). The ability is Ruin Crab's per-opponent `for_each` over `mill`, sized by
    ``cards_in_your_hand`` (the controller's hand, not the milled player's); its mill is itself replaced by the first line.
    """
    return [
        AbilitySpec("replacement", [EffectSpec("mill_replacement", {"plus": _EXTRA_MILL, "scope": "opponents"})]),
        AbilitySpec(
            "activated",
            [EffectSpec("for_each", {"over": {"players": "each_opponent"}, "effects": [
                {"type": "mill", "params": {"target_kind": "player", "count_selector": "cards_in_your_hand"}},
            ]})],
            cost={"text": "{4}{u}{u}, {t}"},
        ),
    ]


register("The Water Crystal", _the_water_crystal)
