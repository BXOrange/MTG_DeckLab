
from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _nezumi_shortfang_stabwhisker_the_odious() -> list[AbilitySpec]:
    '{1}{B}, {T}: Target opponent discards a card. Then if that player has no cards in hand, flip this creature.'
    return [
        AbilitySpec("activated", [
            EffectSpec("discard", {"target_kind": "opponent", "count": 1}),
            EffectSpec("if_else", {"condition": {"kind": "amount_compare", "op": "eq",
                "left": {"kind": "resource", "resource": "hand_size", "of": "previous_player"}, "right": {"kind": "fixed", "amount": 0}},
                "then": [{"type": "flip", "params": {}}]}),
        ], cost={"mana": "{1}{B}", "taps_self": True}),
    ]


register('Nezumi Shortfang', _nezumi_shortfang_stabwhisker_the_odious)


def _stabwhisker_the_odious() -> list[AbilitySpec]:
    "At the beginning of each opponent's upkeep, that player loses 1 life for each card fewer than three in their hand."
    return [AbilitySpec("triggered", [EffectSpec("lose_life", {
        "selector": "active_player", "amount": {"kind": "resource", "resource": "hand_size",
            "of": "active_player", "multiply": -1, "plus": 3, "minimum": 0},
    })], trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "not_you"})]


register("Stabwhisker the Odious", _stabwhisker_the_odious)
