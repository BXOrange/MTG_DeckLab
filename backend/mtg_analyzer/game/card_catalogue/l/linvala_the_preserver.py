from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: The printed life gain.
_LIFE_GAINED = 5


def _linvala_the_preserver() -> list[AbilitySpec]:
    """Flying
    When Linvala enters, if an opponent has more life than you, you gain 5 life.
    When Linvala enters, if an opponent controls more creatures than you, create a 3/3 white Angel creature token with flying.

    — PLAY-ALL (Calling All Angels). Flying is the keyword's. The token trigger is the parser's `opponent_has_more` over
    creatures; the life trigger is the same gate over the ``your_life_total`` selector.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("gain_life", {"amount": _LIFE_GAINED}, condition={
                "kind": "opponent_has_more", "selector": "your_life_total",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 3, "toughness": 3, "colors": ["W"], "subtypes": ["Angel"], "keywords": ["flying"],
                "token_name": "Angel",
            }, condition={
                "kind": "opponent_has_more",
                "selector": {"zone": "battlefield", "of": "you", "filter": {"card_type": "creature"}},
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Linvala, the Preserver", _linvala_the_preserver)
