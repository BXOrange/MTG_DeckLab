from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _soldier_military_program() -> list[AbilitySpec]:
    """At the beginning of combat on your turn, choose one. If you control a commander, you may choose both instead.
    • Create a 1/1 white Soldier creature token.
    • Put a +1/+1 counter on each of up to two Soldiers you control.

    — PLAY-ALL (Limit Break). A modal beginning-of-combat trigger whose ``override`` (``controls_commander_as_cast``, the trigger-side modal-override vocabulary) makes it "choose one or more" while you control a
    commander. Modes: a Soldier `create_token`, and `add_counters` over up to two Soldiers you control.
    """
    return [
        AbilitySpec(
            "triggered", [],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"}, "phase_relation": "you"},
            modes={
                "choose": 1,
                "override": {"condition": {"kind": "controls_commander_as_cast"}, "choose": 1, "at_least": True},
                "options": [
                    [EffectSpec("create_token", {
                        "token_name": "Soldier", "power": 1, "toughness": 1, "colors": ["W"], "subtypes": ["Soldier"],
                    })],
                    [EffectSpec("add_counters", {
                        "count": 1, "kind": "+1/+1", "target_kind": "creature_you_control", "creature_filter": {"subtype": "soldier"},
                        "target_count": 2, "optional": True,
                    })],
                ],
                "descriptions": ["Erschaffe einen 1/1-Soldat-Token.", "Lege eine +1/+1-Marke auf bis zu zwei Soldaten."],
            },
        ),
    ]


register("SOLDIER Military Program", _soldier_military_program)
