from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _phenomenon_investigators() -> list[AbilitySpec]:
    """As this creature enters, choose Believe or Doubt.
    • Believe — Whenever a nontoken creature you control dies, create a 2/2 black Horror enchantment creature token.
    • Doubt — At the beginning of your end step, you may return a nonland permanent you own to your hand. If you do, draw a card.

    — PLAY-ALL (Miracle Worker). Struggle for Project Purity's `choose_named_mode` enter choice, then one trigger per mode gated by the
    ``named_mode`` trigger key. Believe is the parser's dies trigger over a token that is now also an enchantment (`create_token`
    ``is_enchantment``). Doubt is `choose_objects` (an optional bounce of a nonland permanent you control) with a draw "if you do".
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("choose_named_mode", {"options": ["Believe", "Doubt"]})],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 2, "toughness": 2, "colors": ["B"], "subtypes": ["Horror"], "keywords": [],
                "token_name": "Horror", "is_enchantment": True,
            })],
            trigger={
                "event": EventType.DIES, "named_mode": "believe",
                "condition": {"subject": "group", "controller": "you", "other": False,
                              "filter": {"nontoken": True, "card_type": "creature"}},
            },
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("choose_objects", {
                "card_types_any": ["artifact", "creature", "enchantment", "planeswalker", "battle"],
                "action": "return_to_hand", "optional": True, "prompt": "Nichtland-Permanent auf die Hand nehmen?",
                "then": [{"type": "draw", "params": {"count": 1}}],
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you", "named_mode": "doubt"},
        ),
    ]


register("Phenomenon Investigators", _phenomenon_investigators)
