from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _leadership_vacuum() -> list[AbilitySpec]:
    """Target player returns each commander they control from the battlefield
    to the command zone.
    Draw a card.

    — PLAY-ALL Step 2 (yshtola). A `seq` of the new
    `return_commanders_to_command_zone` (RULE 903.3, targeting a player —
    `library.ReturnCommandersToCommandZoneEffect`) and the controller's own
    draw; the draw isn't targeted, only the first clause is.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("seq", {"effects": [
                {"type": "return_commanders_to_command_zone", "params": {}},
                {"type": "draw", "params": {"count": 1}},
            ]})],
        )
    ]


register("Leadership Vacuum", _leadership_vacuum)
