from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "at least 7 life more than your starting life total".
_LIFE_OVER_STARTING = 7


def _righteous_valkyrie() -> list[AbilitySpec]:
    """Flying
    Whenever another Angel or Cleric you control enters, you gain life equal to that creature's toughness.
    As long as you have at least 7 life more than your starting life total, creatures you control get +2/+2.

    — PLAY-ALL (Calling All Angels). Flying and the life-gain trigger are the parser's. The anthem is gated by the new
    `life_over_starting_at_least` (`Player.starting_life`).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("gain_life", {"amount_from_subject": "trigger_subject_toughness"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {
                "subject": "group", "controller": "you", "other": True, "subtypes": ["angel", "cleric"], "nontoken": False,
            }},
        ),
        AbilitySpec("static", [EffectSpec("anthem", {
            "affects": "creatures_you_control", "power": 2, "toughness": 2,
            "active_if": {"kind": "life_over_starting_at_least", "amount": _LIFE_OVER_STARTING},
        })]),
    ]


register("Righteous Valkyrie", _righteous_valkyrie)
