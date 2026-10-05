from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "Your maximum hand size is twenty" — the base hand size (RULE 402.2) plus this much.
TWENTY_HAND_SIZE_BONUS = 13


def _twenty_toed_toad() -> list[AbilitySpec]:
    """Your maximum hand size is twenty.
    Whenever you attack with two or more creatures, put a +1/+1 counter on this creature and draw a card.
    Whenever this creature attacks, you win the game if there are twenty or more counters on it or you have
    twenty or more cards in hand.

    — Peace Offering deck batch. The counter/draw trigger is the parser's claim. "Maximum hand size is
    twenty" is `hand_size_modifier` raising the printed seven by 13 (same result absent other hand-size
    effects). The win is `win_game` gated on either condition (counters of any kind on it, or hand size).
    """
    return [
        AbilitySpec("static", [EffectSpec("hand_size_modifier", {
            "affects": "you", "amount": TWENTY_HAND_SIZE_BONUS, "increase": True,
        })]),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "+1/+1"}), EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.ATTACKERS_DECLARED, "condition": {"subject": "you"},
                "attackers_declared": {"filter": {"card_type": "creature"}, "min": 2},
            },
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("win_game", {}, condition={"kind": "any", "conditions": [
                {"kind": "source_counters", "min": 20},
                {"kind": "cards_in_hand_at_least", "amount": 20},
            ]})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Twenty-Toed Toad", _twenty_toed_toad)
