from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _kardur_doomscourge() -> list[AbilitySpec]:
    """When Kardur enters, until your next turn, creatures your opponents control attack each combat if able and attack a player other than you if able.
    Whenever an attacking creature dies, each opponent loses 1 life and you gain 1 life.

    — PLAY-ALL (Endless Punishment). The dies head is the parser's (``attacking`` filter). The enters trigger is the mass Goad (`goad` over
    ``creatures_opponents_control``, RULE 701.15a — exactly "attacks each combat if able and attacks a player other than the goader if able, until your next turn").
    **Simplification**: goad marks the creatures present as it resolves; an opponent's creature that enters later this round is not forced.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("goad", {"selector": "creatures_opponents_control"})],
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
