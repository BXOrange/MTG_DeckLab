from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _wojek_investigator() -> list[AbilitySpec]:
    """Flying, vigilance
    At the beginning of your upkeep, investigate once for each opponent who has more cards in hand than you. (To investigate, create a Clue token. It's an artifact with "{2}, Sacrifice this token: Draw a card.")

    — PLAY-ALL (Calling All Angels). Keywords are the catalogue's. The upkeep trigger makes that many Clues, counted by
    the new ``opponents_with_more_cards_in_hand`` selector (a count of players).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": {"kind": "count_selector", "selector": "opponents_with_more_cards_in_hand"},
                "token_name": "Clue",
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"},
        ),
    ]


register("Wojek Investigator", _wojek_investigator)
