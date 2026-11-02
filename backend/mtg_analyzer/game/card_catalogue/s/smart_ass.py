from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _smart_ass() -> list[AbilitySpec]:
    """Whenever this creature attacks, choose a card name. If defending player has no cards with the chosen name in their hand, they may reveal their hand. If they don't reveal their hand, this creature can't be blocked this turn.

    RULE 201.3 naming (`choose_for_source`, stamped on this creature), then an `if_else` on the defender's hand
    (`hand_has_chosen_name`, negated). RULE 608.2d: the defending player (`defending_player`) is the one asked, via
    `optional`; accepting publishes the hand (RULE 701.20, `reveal_hand`), declining is the ``else_effects`` branch.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("seq", {"effects": [
                {"type": "choose_for_source", "params": {"kind": "card_name"}},
                {"type": "if_else", "params": {
                    "condition": {"kind": "not", "condition": {"kind": "hand_has_chosen_name", "of": "defending_player"}},
                    "then": [{"type": "optional", "params": {
                        "player": "defending_player",
                        "prompt": "Hand aufdecken?",
                        "effects": [{"type": "reveal_hand", "params": {"whose": "defending_player"}}],
                        "else_effects": [{"type": "unblockable", "params": {"target_kind": None}}],
                    }}],
                    "else": [],
                }},
            ]})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Smart Ass", _smart_ass)
