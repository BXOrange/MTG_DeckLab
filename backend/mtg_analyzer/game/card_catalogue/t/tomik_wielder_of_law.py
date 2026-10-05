from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tomik_wielder_of_law() -> list[AbilitySpec]:
    """Affinity for planeswalkers
    Flying, vigilance
    Whenever an opponent attacks with creatures, if two or more of those
    creatures are attacking you and/or planeswalkers you control, that
    opponent loses 3 life and you draw a card.

    Same "attacking you" simplification as Mangara. Affinity for
    planeswalkers folds in from the keyword catalogue."""
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("lose_life", {"amount": 3, "selector": "event_player"}),
                EffectSpec("draw", {"count": 1}),
            ],
            trigger={
                "event": EventType.PLAYER_ATTACKED,
                "condition": {"subject": "group", "controller": "not_you"},
                "defender_is_you": True, "attackers_at_least": 2,
            },
        ),
    ]


register("Tomik, Wielder of Law", _tomik_wielder_of_law)
