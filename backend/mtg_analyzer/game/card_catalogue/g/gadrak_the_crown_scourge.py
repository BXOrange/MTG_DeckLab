from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _gadrak_the_crown_scourge() -> list[AbilitySpec]:
    """Flying
    This creature can't attack unless you control four or more artifacts.
    At the beginning of your end step, create a Treasure token for each nontoken creature that died this turn.

    — PLAY-ALL Step 2 (Temur Roar). The attack restriction is the parser's own claim. The end-step trigger
    sizes a `create_token` by the new `nontoken_creatures_died_this_turn` count selector (every player's
    creatures, tokens excluded by the DIES event's own ``is_token`` snapshot — RULE 700.4).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("combat_restriction", {
                "kind": "cant_attack_unless",
                "condition": {"kind": "you_control", "min": 4, "filter": {"card_type": "artifact"}},
                "affects": "self",
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "token_name": "Treasure",
                "count": {"kind": "count_selector", "selector": "nontoken_creatures_died_this_turn"},
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"},
        ),
    ]


register("Gadrak, the Crown-Scourge", _gadrak_the_crown_scourge)
