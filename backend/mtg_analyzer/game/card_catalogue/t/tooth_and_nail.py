from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tooth_and_nail() -> list[AbilitySpec]:
    """Choose one —
    • Search your library for up to two creature cards, reveal them, put
      them into your hand, then shuffle.
    • Put up to two creature cards from your hand onto the battlefield.
    Entwine {2}

    — Tooth and Nail. The second mode needed the one genuinely new shape:
    every "put onto the battlefield" in the engine moves a card out of a
    *library* (a search) or a *graveyard* (reanimation), never an open pick
    from hand. `PutFromHandOntoBattlefieldEffect` reuses `RulesEngine.
    _request_search`'s interactive one-at-a-time choice against a new
    ``"hand"`` search zone, so the prompt, the undo snapshots and the "up to
    N" semantics match every other pick rather than needing a parallel
    choice kind wired through the session and frontend. `_request_search`
    already keys its shuffle and its `LIBRARY_SEARCHED` event to
    ``"library"``, so a hand pick correctly does neither.

    **Entwine (RULE 702.42a)** is now a real additional cost rather than the
    free RULE 700.2e ``or_both`` flag it used to borrow: the ``entwine`` key
    on the modes block prices the combined offer, so "choose all" costs
    {2} more and is *locked* when that {2} isn't available — which matters,
    because the both-modes line (tutor two creatures, then put them onto the
    battlefield) is the entire reason the card is played, and getting it for
    free made the spell strictly better than printed.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [],
            modes={
                "entwine": "{2}",
                "options": [
                    [EffectSpec("search", {
                        "criteria": {"type": "Creature"},
                        "destination": "hand",
                        "count": 2,
                    })],
                    [EffectSpec("put_from_hand_onto_battlefield", {
                        "criteria": {"type": "Creature"},
                        "count": 2,
                    })],
                ],
                "descriptions": [
                    "Durchsuche deine Bibliothek nach bis zu zwei Kreaturenkarten "
                    "und nimm sie auf die Hand.",
                    "Bringe bis zu zwei Kreaturenkarten aus deiner Hand ins Spiel.",
                ],
            },
        ),
    ]


register("Tooth and Nail", _tooth_and_nail)
