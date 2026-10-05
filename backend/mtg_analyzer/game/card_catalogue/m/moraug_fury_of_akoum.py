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

    — PLAY-ALL Step 2 (World Shaper). The pump is the per-count `anthem` shape
    (``power: 1`` per unit) with the new per-object selector
    ``times_attacked_this_turn_self`` (`GameObject.times_attacked_this_turn`,
    bumped once per attack declaration, reset in the untap step; an extra combat
    makes it 2+). Landfall is the parser's group head over `extra_combat_phase`
    (Combat Celebrant's) and an untap of your creatures, each gated on the new
    ``your_main_phase`` condition ("if it's your main phase" — checked as the
    trigger resolves). **Simplification:** the untap happens as the trigger
    resolves rather than at the beginning of the additional combat — the same
    outcome unless something taps a creature in between.
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
                EffectSpec("extra_combat_phase", {}, condition=dict(_MAIN_PHASE)),
                EffectSpec("tap", {"selector": "creatures_you_control", "untap": True}, condition=dict(_MAIN_PHASE)),
            ],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "controller": "you", "other": False, "type": "land"},
            },
        ),
    ]


register("Moraug, Fury of Akoum", _moraug_fury_of_akoum)
