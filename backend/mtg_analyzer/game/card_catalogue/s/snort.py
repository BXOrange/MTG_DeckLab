from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "draw 5 cards" and "5 damage".
_SNORT_AMOUNT = 5


def _snort() -> list[AbilitySpec]:
    """Each player may discard their hand and draw five cards. Then Snort deals 5 damage to each opponent who discarded their hand this way.
    Flashback {4}{R}

    — PLAY-ALL (Revival Trance). Flashback is a keyword. Kwain's per-player free `pay_cost_then` (Ja/Nein) inside a
    `for_each`: the controller's loop discards and draws; the opponents' loop adds the 5 damage to the player who said yes.
    **Simplification:** the controller answers first and the damage is dealt right after each opponent's own draw, not after
    every player has drawn (same totals).
    """
    take = [
        {"type": "discard", "params": {"whole_hand": True, "target_kind": "player"}},
        {"type": "draw", "params": {"count": _SNORT_AMOUNT, "target_kind": "player"}},
    ]
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("for_each", {"over": {"players": "you"}, "effects": [{"type": "pay_cost_then", "params": {
                    "cost": "", "payer": "target", "prompt": "Hand abwerfen und 5 Karten ziehen?", "effects": take,
                }}]}),
                EffectSpec("for_each", {"over": {"players": "each_opponent"}, "effects": [{"type": "pay_cost_then", "params": {
                    "cost": "", "payer": "target", "prompt": "Hand abwerfen und 5 Karten ziehen?",
                    "effects": take + [{"type": "damage", "params": {"amount": _SNORT_AMOUNT, "target_kind": "player"}}],
                }}]}),
            ],
        ),
    ]


register("Snort", _snort)
