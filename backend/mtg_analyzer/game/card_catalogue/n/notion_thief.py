from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _notion_thief() -> list[AbilitySpec]:
    """Flash
    If an opponent would draw a card except the first one they draw in
    each of their draw steps, instead that player skips that draw and you
    draw a card.

    — MEC-32. Flash is the ordinary keyword fold-in. The exemption clause
    ("except the first one … in each of their draw steps") needed a new
    `GameState.first_draw_done_this_step` per-player tracker, reset right
    as a player's own draw step begins (`game/engine/turn_loop_mixin.py`'s
    `_run_step`) — distinct from the existing whole-turn `cards_drawn_
    this_turn`, since a draw from a spell earlier in the same turn must
    not count as the step's own first draw. See `effects.
    _steal_non_first_draw_replacement`.
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("steal_non_first_draw", {})],
        ),
    ]


register("Notion Thief", _notion_thief)
