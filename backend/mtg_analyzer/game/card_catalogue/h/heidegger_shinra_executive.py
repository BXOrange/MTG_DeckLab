from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _heidegger_shinra_executive() -> list[AbilitySpec]:
    """At the beginning of combat on your turn, target creature you control gets +X/+0 until end of turn, where X is the number of Soldiers you control.
    At the beginning of your end step, create a number of 1/1 white Soldier creature tokens equal to the number of opponents who control more creatures than you.

    — PLAY-ALL (Limit Break). The combat trigger is the parser's claim (a `bind` of a Soldier count into `pump`). The end step trigger is `create_token` counted by the new
    ``opponents_controlling_more_creatures`` selector.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("bind", {
                "name": "px",
                "amount": {"kind": "count_selector", "selector": {"zone": "battlefield", "of": "you", "filter": {"subtype": "soldier"}}},
                "effects": [{"type": "pump", "params": {"power": "$px", "toughness": 0, "target_kind": "creature_you_control"}}],
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"}, "phase_relation": "you"},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "token_name": "Soldier", "power": 1, "toughness": 1, "colors": ["W"], "subtypes": ["Soldier"],
                "count_selector": "opponents_controlling_more_creatures",
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"},
        ),
    ]


register("Heidegger, Shinra Executive", _heidegger_shinra_executive)
