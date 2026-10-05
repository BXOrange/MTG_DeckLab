from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _legion_warboss() -> list[AbilitySpec]:
    """Mentor (Whenever this creature attacks, put a +1/+1 counter on target attacking creature with lesser power.)
    At the beginning of combat on your turn, create a 1/1 red Goblin creature token. That token gains haste until end of turn and attacks this combat if able.

    — Legion Warboss. Mentor comes from the keyword catalogue. The token is made and then "that token"
    (`of: "created"`) receives haste plus the synthetic ``attacks_if_able`` flag keyword
    (`GameEngine._enforce_attacks_if_able`) until end of turn.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("create_token", {
                    "count": 1, "power": 1, "toughness": 1, "colors": ["R"], "subtypes": ["Goblin"],
                    "token_name": "Goblin",
                }),
                EffectSpec("pump", {
                    "power": 0, "toughness": 0, "keywords": ["haste", "attacks_if_able"],
                    "target_operand": {"of": "created"},
                }),
            ],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"}, "phase_relation": "you"},
        ),
    ]


register("Legion Warboss", _legion_warboss)
