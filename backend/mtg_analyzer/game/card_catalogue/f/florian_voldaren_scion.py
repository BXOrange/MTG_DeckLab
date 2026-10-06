from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _florian_voldaren_scion() -> list[AbilitySpec]:
    """First strike
    At the beginning of each of your postcombat main phases, look at the top X cards of your library, where X is the total amount of life your opponents lost this turn. Exile one of those cards and put the rest on the bottom of your library in a random order. You may play the exiled card this turn.

    — PLAY-ALL (Endless Punishment). First strike is a keyword. The head is the second main phase of your turn. The body is `impulsive_draw` (``choose_one``, ``same_turn_only``) counted by
    the new ``opponents_life_lost_this_turn`` selector, with ``rest_to_bottom`` so the cards not picked return to the bottom at random instead of staying exiled.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("impulsive_draw", {
                "count": {"kind": "count_selector", "selector": "opponents_life_lost_this_turn"},
                "same_turn_only": True, "choose_one": True, "rest_to_bottom": True,
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "main2"}, "phase_relation": "you"},
        ),
    ]


register("Florian, Voldaren Scion", _florian_voldaren_scion)
