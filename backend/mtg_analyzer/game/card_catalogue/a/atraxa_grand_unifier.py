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
    no two picks may share a card type (`RulesEngine._resume_choose_objects`).
    Documented simplification: the printed rule lets two multi-type cards each
    cover a *different* type of theirs (an artifact creature for "artifact"
    and a creature card for "creature" is fine only if they don't overlap);
    here any two picks that share a type are refused.
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
