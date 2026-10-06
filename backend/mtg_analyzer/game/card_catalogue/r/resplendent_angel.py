from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "if you gained 5 or more life this turn".
_LIFE_GAINED_THRESHOLD = 5


def _resplendent_angel() -> list[AbilitySpec]:
    """Flying
    At the beginning of each end step, if you gained 5 or more life this turn, create a 4/4 white Angel creature token with flying and vigilance.
    {3}{W}{W}{W}: Until end of turn, this creature gets +2/+2 and gains lifelink.

    — PLAY-ALL (Hope to the last). Flying and the end-step trigger are the parser's (its `gained_life_this_turn`
    intervening-if). The firebreathing-shaped ability is a self `pump` carrying the lifelink grant.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 4, "toughness": 4, "colors": ["W"], "subtypes": ["Angel"],
                "keywords": ["flying", "vigilance"], "token_name": "Angel",
            }, condition={"kind": "gained_life_this_turn", "amount": _LIFE_GAINED_THRESHOLD})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("pump", {"power": 2, "toughness": 2, "keywords": ["lifelink"]})],
            cost={"text": "{3}{w}{w}{w}"},
        ),
    ]


register("Resplendent Angel", _resplendent_angel)
