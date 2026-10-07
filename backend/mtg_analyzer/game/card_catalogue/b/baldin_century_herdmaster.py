from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "up to one hundred target creatures".
_MAX_TARGETS = 100


def _baldin_century_herdmaster() -> list[AbilitySpec]:
    """During your turn, each creature assigns combat damage equal to its toughness rather than its power.
    Whenever Baldin attacks, up to one hundred target creatures each get +0/+X until end of turn, where X is the number of cards in your hand.

    — PLAY-ALL (Abzan Armor). The turn-gated toughness-damage static is the parser's. The attack trigger is a `pump` over up to
    100 targets (``target_count``) whose toughness is the new ``cards_in_your_hand`` count (`dynamic_amount`, toughness
    axis only). RULE 608.2h: X is measured once as the trigger resolves and
    applies equally to each target.
    """
    return [
        AbilitySpec("static", [EffectSpec("combat_restriction", {
            "kind": "damage_uses_toughness", "affects": "creatures", "active_if": {"kind": "your_turn"},
        })]),
        AbilitySpec(
            "triggered",
            [EffectSpec("pump", {
                "power": 0, "toughness": 0, "target_kind": "creature", "target_count": _MAX_TARGETS, "optional": True,
                "dynamic_amount": {"kind": "count_selector", "selector": "cards_in_your_hand"},
                "amount_from_count_selector_axis": "toughness",
            })],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Baldin, Century Herdmaster", _baldin_century_herdmaster)
