from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "if you control twenty or more artifacts" — the alternate win condition.
_ARTIFACTS_TO_WIN = 20


def _hellkite_tyrant() -> list[AbilitySpec]:
    """Flying, trample
    Whenever this creature deals combat damage to a player, gain control of all artifacts that player controls.
    At the beginning of your upkeep, if you control twenty or more artifacts, you win the game.

    — PLAY-ALL (Limit Break). Flying and trample are keywords. The steal is `gain_control_until_eot` with ``duration="permanent"`` over every artifact of the damaged player
    (``mass_of_target_player`` + the new ``player_from_trigger_event``). The upkeep trigger is `win_game` behind a RULE 603.4 ``control_count`` intervening-if.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("gain_control_until_eot", {
                "mass_of_target_player": "artifact", "player_from_trigger_event": "target_id",
                "duration": "permanent", "untap": False, "haste": False,
            })],
            trigger={"event": "DAMAGE", "condition": {"subject": "self"}, "filter": {"combat": True, "is_player": True}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("win_game", {})],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you",
                "active_if": {"kind": "control_count", "selector": "artifacts_you_control", "min": _ARTIFACTS_TO_WIN},
            },
        ),
    ]


register("Hellkite Tyrant", _hellkite_tyrant)
