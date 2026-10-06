from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tidus_yuna_s_guardian() -> list[AbilitySpec]:
    """At the beginning of combat on your turn, you may move a counter from target creature you control onto a second target creature you control.
    Cheer — Whenever one or more creatures you control with counters on them deal combat damage to a player, you may draw a card and proliferate. Do this only once each turn.

    — PLAY-ALL (Counter Blitz). The combat trigger is Nesting Grounds' `move_counters` over two creatures you control (optional trigger;
    **simplification** shared with it: the counter kind is the first one by iteration order). Cheer is the parser's own claim (the
    batch `CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER` head, `draw` + `proliferate` + the once-per-turn marker).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("move_counters", {
                "source_target_kind": "creature_you_control", "dest_target_kind": "creature_you_control",
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"}, "phase_relation": "you"},
            optional=True,
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("draw", {"count": 1}),
                EffectSpec("proliferate", {}),
                EffectSpec("action_once_per_turn_marker", {}),
            ],
            trigger={
                "event": EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER,
                "condition": {
                    "subject": "group", "controller": "you", "other": False,
                    "filter": {"card_type": "creature", "has_counter": True},
                },
                "contributors": {"min": 1},
            },
            optional=True,
        ),
    ]


register("Tidus, Yuna's Guardian", _tidus_yuna_s_guardian)
