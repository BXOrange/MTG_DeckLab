from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _atraxa_grand_unifier() -> list[AbilitySpec]:
    """Flying, vigilance, deathtouch, lifelink
    When Atraxa enters, reveal the top ten cards of your library. For each card
    type, you may put a card of that type from among the revealed cards into
    your hand. Put the rest on the bottom of your library in a random order.

    — PLAY-ALL Step 2 (SpongeBob). The four keywords are read from the card.
    The ETB is the PAR-144 dig (`inspect_top_choose`: ten cards, ``max_picks:
    all`` — any number of them — put into hand, the rest to
    ``library_bottom_random``) with the new ``distinct_card_types`` flag:
    each selected card must be assignable to a different card type. Shared
    types are allowed when another assignment exists (RULE 205.2b).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("inspect_top_choose", {
                "count": 10, "action": "library_to_hand", "max_picks": "all", "optional": True,
                "rest_destination": "library_bottom_random", "distinct_card_types": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Atraxa, Grand Unifier", _atraxa_grand_unifier)
