from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _barret_avalanche_leader() -> list[AbilitySpec]:
    """Reach
    Avalanche! — Whenever an Equipment you control enters, create a 2/2 red Rebel creature token.
    At the beginning of combat on your turn, attach up to one target Equipment you control to target Rebel you control.

    — PLAY-ALL (Limit Break). Reach is the keyword. The token trigger is the Equipment group head (Puresteel Paladin's) over `create_token`. The combat trigger is the new
    `attach_equipment` (an Equipment you control onto a Rebel you control; **simplification:** both targets are required, so with no Equipment the ability is not put on the stack).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 2, "toughness": 2, "colors": ["R"], "subtypes": ["Rebel"], "token_name": "Rebel",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {
                "subject": "group", "controller": "you", "other": False, "subtypes": ["equipment"], "nontoken": False,
            }},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("attach_equipment", {"creature_kind": "creature_you_control", "creature_filter": {"subtype": "rebel"}})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"}, "phase_relation": "you"},
        ),
    ]


register("Barret, Avalanche Leader", _barret_avalanche_leader)
