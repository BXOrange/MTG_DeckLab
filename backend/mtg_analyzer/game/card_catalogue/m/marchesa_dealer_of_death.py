from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _marchesa_dealer_of_death() -> list[AbilitySpec]:
    """Whenever you commit a crime, you may pay {1}. If you do, look at the top
    two cards of your library. Put one of them into your hand and the other into
    your graveyard. (Targeting opponents, anything they control, and/or cards in
    their graveyards is a crime.)

    — PLAY-ALL Step 2 (Oops! All Night's Whispers). The trigger is
    `CRIME_COMMITTED` (RULE 700.13, `RulesEngine._note_crime`) with subject
    ``you`` — the parser has no head for "commit a crime", which is also why this
    is hand-authored. The body is `pay_cost_then` {1} over PAR-144's
    `inspect_top_choose` (two cards, one to hand, the other to the graveyard).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "{1}",
                "effects": [{"type": "inspect_top_choose", "params": {
                    "count": 2, "action": "library_to_hand", "max_picks": 1, "rest_destination": "graveyard",
                }}],
            })],
            trigger={"event": EventType.CRIME_COMMITTED, "condition": {"subject": "you"}},
        ),
    ]


register("Marchesa, Dealer of Death", _marchesa_dealer_of_death)
