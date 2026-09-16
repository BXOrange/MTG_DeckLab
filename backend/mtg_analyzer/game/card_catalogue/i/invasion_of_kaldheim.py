from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _invasion_of_kaldheim() -> list[AbilitySpec]:
    """(As a Siege enters, choose an opponent to protect it. You and
    others can attack it. When it's defeated, exile it, then cast it
    transformed.)
    When this Siege enters, exile all cards from your hand, then draw
    that many cards. Until the end of your next turn, you may play cards
    exiled this way.

    — Imodane deck batch. The RULE 310 battle mechanics (protector
    choice, attackability, defeat/transform cycle) are all engine-level
    and need no hand-authoring. ENG-37 B7 retired the fused
    `exile_hand_then_draw_that_many` type: the ETB is a `bind` whose
    ``amount`` measures ``resource: hand_size`` (the controller's, before
    the body runs — the spell is on the stack, not in hand), body
    `[exile_hand, draw $n]`. See `ExileHandEffect` for the documented
    "you may play cards exiled this way" simplification.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("bind", {
                "name": "n",
                "amount": {"kind": "resource", "resource": "hand_size"},
                "effects": [
                    {"type": "exile_hand", "params": {}},
                    {"type": "draw", "params": {"count": "$n"}},
                ],
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Invasion of Kaldheim", _invasion_of_kaldheim)
register("Invasion of Kaldheim // Pyre of the World Tree", _invasion_of_kaldheim)
