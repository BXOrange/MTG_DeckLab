from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _lord_jyscal_guado() -> list[AbilitySpec]:
    """Flying
    At the beginning of each end step, if you put a counter on a creature this turn, investigate. (Create a Clue token. It's an
    artifact with "{2}, Sacrifice this token: Draw a card.")

    — PLAY-ALL (Counter Blitz). Flying is the keyword's. An end-step trigger for every player's turn (no ``phase_relation``) whose RULE
    603.4 intervening-if is the existing ``you_placed_counter_on_creature_this_turn`` condition (`GameState.counter_placed_on_creature_this_turn`),
    over a Clue `create_token`.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "token_name": "Clue"})],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "end"},
                "active_if": {"kind": "you_placed_counter_on_creature_this_turn"},
            },
        ),
    ]


register("Lord Jyscal Guado", _lord_jyscal_guado)
