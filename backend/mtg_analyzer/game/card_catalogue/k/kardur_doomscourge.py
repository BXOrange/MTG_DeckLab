from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _kardur_doomscourge() -> list[AbilitySpec]:
    """When Kardur enters, until your next turn, creatures your opponents control attack each combat if able and attack a player other than you if able.
    Whenever an attacking creature dies, each opponent loses 1 life and you gain 1 life.

    — PLAY-ALL (Endless Punishment). The dies head uses the ``attacking`` filter. The enters trigger creates
    a floating combat requirement until the controller's next turn. It modifies game rules, so later arrivals
    are affected too (RULE 611.2c); it does not give creatures the goaded designation.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("grant_until", {
                "target_kind": None, "duration": "your_next_turn",
                "static": {"type": "combat_restriction", "params": {
                    "affects": "creatures_opponents_control", "kind": "attacks_other_player_if_able",
                }},
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("lose_life", {"amount": 1, "selector": "each_opponent"}), EffectSpec("gain_life", {"amount": 1})],
            trigger={"event": EventType.DIES, "condition": {
                "subject": "group", "controller": "any", "other": False, "filter": {"attacking": True, "card_type": "creature"},
            }},
        ),
    ]


register("Kardur, Doomscourge", _kardur_doomscourge)
