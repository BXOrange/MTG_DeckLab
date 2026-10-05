from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _scrawling_crawler() -> list[AbilitySpec]:
    """At the beginning of your upkeep, each player draws a card.
    Whenever an opponent draws a card, that player loses 1 life.

    — Keen Engineering deck batch. The upkeep draw is the parser's own claim; the second line is a
    `DRAW` trigger by a player who is not the controller (the Faerie Mastermind head) whose
    `lose_life` hits ``event_player`` (the drawing player).
    """
    return [
        AbilitySpec(
            "triggered", [EffectSpec("draw", {"count": 1, "selector": "each_player"})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"},
        ),
        AbilitySpec(
            "triggered", [EffectSpec("lose_life", {"amount": 1, "selector": "event_player"})],
            trigger={"event": EventType.DRAW, "condition": {"subject": "group", "controller": "not_you"}},
        ),
    ]


register("Scrawling Crawler", _scrawling_crawler)
