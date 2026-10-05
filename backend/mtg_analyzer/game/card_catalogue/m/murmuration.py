from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _murmuration() -> list[AbilitySpec]:
    """Birds you control get +1/+1 and have vigilance.
    At the beginning of your end step, for each spell you've cast this turn, create a 1/2 blue Bird creature
    token with flying named Storm Crow.

    — Family Matters deck batch. The Bird anthem is the parser's own claim. The end-step trigger is
    `create_token` counted by the ``spells_cast_this_turn`` selector; the token carries its printed name.
    """
    return [
        AbilitySpec("static", [
            EffectSpec("anthem", {"power": 1, "toughness": 1, "affects": "creatures_you_control", "subtype": "Bird"}),
            EffectSpec("grant_keyword", {"affects": "creatures_you_control", "subtype": "Bird", "keywords": ["vigilance"]}),
        ]),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count_selector": "spells_cast_this_turn", "power": 1, "toughness": 2, "colors": ["U"],
                "subtypes": ["Bird"], "keywords": ["flying"], "token_name": "Storm Crow",
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"},
        ),
    ]


register("Murmuration", _murmuration)
