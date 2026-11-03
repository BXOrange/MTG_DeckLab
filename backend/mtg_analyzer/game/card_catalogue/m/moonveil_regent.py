from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _moonveil_regent() -> list[AbilitySpec]:
    """Flying
Whenever you cast a spell, you may discard your hand. If you do, draw a card for each of that spell's colors.
When this creature dies, it deals X damage to any target, where X is the number of colors among permanents you control."""
    return [
        AbilitySpec("keyword", [], keyword={"name": "flying"}),
        AbilitySpec("triggered", [EffectSpec("bind", {
            "name": "colors", "amount": {"kind": "trigger_event", "field": "colors"},
            "effects": [{"type": "optional", "params": {"effects": [
                {"type": "discard", "params": {"whole_hand": True}},
                {"type": "draw", "params": {"count": "$colors"}},
            ]}}],
        })], trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "you"}}),
        AbilitySpec("triggered", [EffectSpec("damage", {
            "amount_from_count_selector": "colors_among_permanents_you_control",
            "target_kind": "any",
        })], trigger={"event": EventType.DIES, "condition": {"subject": "self"}}),
    ]


register("Moonveil Regent", _moonveil_regent)
