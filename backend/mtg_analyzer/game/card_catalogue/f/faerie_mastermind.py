from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _faerie_mastermind() -> list[AbilitySpec]:
    """Flash
    Flying
    Whenever an opponent draws their second card each turn, you draw a
    card.
    {3}{U}: Each player draws a card.

    — MEC-12 (cEDH Kinnan). Flash/Flying and the activated "each player
    draws" are already parser-claimed for free. Only the second-draw
    trigger needs the new ``is_nth_draw_this_turn`` top-level trigger key.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": "DRAW", "condition": {"subject": "group", "controller": "not_you"},
                "is_nth_draw_this_turn": 2,
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("draw", {"count": 1, "selector": "each_player"})],
            cost={"mana": "{3}{U}"},
        ),
    ]


register("Faerie Mastermind", _faerie_mastermind)
