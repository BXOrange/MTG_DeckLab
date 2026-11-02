from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _cat_collector() -> list[AbilitySpec]:
    """When this creature enters, create a Food token. (It's an artifact with "{2}, {T}, Sacrifice this token: You gain 3 life.")
    Whenever you gain life for the first time during each of your turns, create a 1/1 white Cat creature token.

    The Food ETB is the parser's own claim. The second ability is Nykthos Paragon's once-per-turn life-gain trigger
    (``limit``, RULE 603.2: it triggers only the first time each turn) narrowed to your own turn
    (``during_your_turn``), so life gained on an opponent's turn neither triggers nor uses up the limit.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "token_name": "Food"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="when ~ enters, create a food token.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "token_name": "Cat", "power": 1, "toughness": 1,
                "colors": ["W"], "subtypes": ["Cat"],
            })],
            trigger={
                "event": EventType.LIFE_GAINED, "condition": {"subject": "you"},
                "limit": True, "during_your_turn": True,
            },
        ),
    ]


register("Cat Collector", _cat_collector)
