from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


#: Cards in hand at which an opponent takes the damage (the card's "four or more").
FEVERED_HAND_THRESHOLD = 4
#: Damage dealt to that opponent.
FEVERED_DAMAGE = 2


def _fevered_visions() -> list[AbilitySpec]:
    """At the beginning of each player's end step, that player draws a card. If the player is your opponent and has four or more cards in hand, this enchantment deals 2 damage to that player.

    RULE 603.1: the acting player is the active player whose end step
    begins (``trigger_subject_referent``); the draw is read before the
    "If" clause, so the hand count includes the drawn card (RULE 608.2c).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("trigger_subject_referent", {
                "acting": "active_player",
                "effects": [
                    {"type": "draw", "params": {"count": 1}},
                    {"type": "damage", "params": {"amount": FEVERED_DAMAGE, "selector": "controller"},
                     "condition": {"kind": "all", "conditions": [
                         {"kind": "not", "condition": {"kind": "is_you"}},
                         {"kind": "cards_in_hand_at_least", "amount": FEVERED_HAND_THRESHOLD},
                     ]}},
                ],
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}},
        ),
    ]


register("Fevered Visions", _fevered_visions)
