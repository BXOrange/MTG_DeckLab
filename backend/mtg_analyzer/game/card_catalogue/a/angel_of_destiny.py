from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "at least 15 life more than your starting life total".
_LIFE_OVER_STARTING = 15


def _angel_of_destiny() -> list[AbilitySpec]:
    """Flying, double strike
    Whenever a creature you control deals combat damage to a player, you and that player each gain that much life.
    At the beginning of your end step, if you have at least 15 life more than your starting life total, each player this creature attacked this turn loses the game.

    — PLAY-ALL (Hope to the last). Keywords are the catalogue's. The damage trigger is Bident of Thassa's group head
    (`DAMAGE`, combat, to a player): two `gain_life` over the event's ``amount`` — one for the controller, one with the new
    ``event_damaged_player`` selector. The end-step trigger gates `lose_game` on `life_over_starting_at_least`, widened with
    ``players="attacked_by_source_this_turn"`` (the ATTACKS events this creature declared against a player this turn).
    """
    gained = {"kind": "trigger_event", "field": "amount"}
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("gain_life", {"amount": dict(gained)}),
                EffectSpec("gain_life", {"amount": dict(gained), "selector": "event_damaged_player"}),
            ],
            trigger={
                "event": EventType.DAMAGE,
                "condition": {"subject": "group", "controller": "you", "other": False, "filter": {"card_type": "creature"}},
                "filter": {"combat": True, "is_player": True},
            },
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("lose_game", {"players": "attacked_by_source_this_turn", "reason": "angel_of_destiny"}, condition={
                "kind": "life_over_starting_at_least", "amount": _LIFE_OVER_STARTING,
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"},
        ),
    ]


register("Angel of Destiny", _angel_of_destiny)
