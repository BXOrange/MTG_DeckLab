from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

_MAIN_PHASE = {"kind": "your_main_phase"}


def _moraug_fury_of_akoum() -> list[AbilitySpec]:
    """Each creature you control gets +1/+0 for each time it has attacked this
    turn.
    Landfall — Whenever a land you control enters, if it's your main phase,
    there's an additional combat phase after this phase. At the beginning of that
    combat, untap all creatures you control.

    — PLAY-ALL (World Shaper). The per-creature anthem reads the number of
    attack declarations this turn. Main-phase landfall schedules a combat
    immediately after that main phase (RULE 500.8), with its own respondable
    untap trigger at the beginning of that specific combat (RULE 603.7).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "affects": "creatures_you_control", "power": 1, "toughness": 0,
                "power_count": "times_attacked_this_turn_self",
            })],
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("extra_combat_phase", {
                    "after_current_phase": True, "untap_at_beginning": True,
                }, condition=dict(_MAIN_PHASE)),
            ],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "active_if": dict(_MAIN_PHASE),
                "condition": {"subject": "group", "controller": "you", "other": False, "type": "land"},
            },
        ),
    ]


register("Moraug, Fury of Akoum", _moraug_fury_of_akoum)
