from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tell_me_what_you_see() -> list[AbilitySpec]:
    """When this enchantment enters, target opponent may have you draw a card. If they don't, they lose 4 life and you surveil 1.
    Whenever you face a dilemma, you may return this enchantment to its owner's hand. (You face a dilemma as you choose one or more modes for a spell or ability.)

    — MEC-141. The enters trigger is Combustible Gearhulk's shape: `pay_cost_then` with ``payer="target"`` and a free
    (empty) cost, so the targeted opponent answers yes/no. "Yes" runs the draw for you; "no" makes that opponent lose 4
    life and surveils 1 for you. The dilemma trigger is the parser's `FACED_DILEMMA` head (RULE 700.17) with an
    optional self-bounce.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "", "payer": "target", "target_kind": "opponent",
                "prompt": "Soll der Gegner dich eine Karte ziehen lassen?",
                "effects": [{"type": "draw", "params": {"count": 1}}],
                "else_effects": [
                    {"type": "lose_life", "params": {"amount": 4, "target_kind": "opponent"}},
                    {"type": "surveil", "params": {"count": 1}},
                ],
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_to_hand", {"target_kind": None})],
            trigger={"event": EventType.FACED_DILEMMA, "condition": {"subject": "you"}},
            optional=True,
        ),
    ]


register("Tell Me What You See", _tell_me_what_you_see)
