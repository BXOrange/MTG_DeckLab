from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tinybones_joins_up() -> list[AbilitySpec]:
    """When Tinybones Joins Up enters, any number of target players each discard a card.
    Whenever a legendary creature you control enters, any number of target players each mill a card and lose 1 life.
    """
    return [
        AbilitySpec("triggered", [EffectSpec("for_each", {
            "over": {"targets": True}, "target_kind": "player", "any_number": True,
            "effects": [{"type": "discard", "params": {"count": 1, "target_kind": "player"}}],
        })], trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}}),
        AbilitySpec("triggered", [EffectSpec("for_each", {
            "over": {"targets": True}, "target_kind": "player", "any_number": True,
            "effects": [{"type": "mill", "params": {"count": 1, "target_kind": "player"}},
                        {"type": "lose_life", "params": {"amount": 1, "target_kind": "player"}}],
        })], trigger={"event": "ENTERS_BATTLEFIELD", "condition": {
            "subject": "group", "type": "creature", "controller": "you", "filter": {"legendary": True},
        }}),
    ]


register("Tinybones Joins Up", _tinybones_joins_up)
