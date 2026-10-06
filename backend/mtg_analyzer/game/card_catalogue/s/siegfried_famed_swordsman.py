from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "X is twice the number of creature cards in your graveyard".
_COUNTERS_PER_CREATURE_CARD = 2
#: "mill three cards".
_MILL = 3


def _siegfried_famed_swordsman() -> list[AbilitySpec]:
    """Menace
    When this creature enters, mill three cards. Then put X +1/+1 counters on this creature, where X is twice the number of creature cards in your graveyard.

    — PLAY-ALL (Revival Trance). Menace is a keyword. A `seq`: the mill, then a `bind` measuring
    ``creature_cards_in_your_graveyard`` (×2) *after* the mill into a self `add_counters`.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("seq", {"effects": [
                {"type": "mill", "params": {"count": _MILL}},
                {"type": "bind", "params": {
                    "name": "n",
                    "amount": {
                        "kind": "count_selector", "selector": "creature_cards_in_your_graveyard",
                        "multiply": _COUNTERS_PER_CREATURE_CARD,
                    },
                    "effects": [{"type": "add_counters", "params": {
                        "amount": "$n", "kind": "+1/+1", "target_kind": None,
                    }}],
                }},
            ]})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Siegfried, Famed Swordsman", _siegfried_famed_swordsman)
