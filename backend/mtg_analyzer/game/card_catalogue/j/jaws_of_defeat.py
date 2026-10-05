from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _jaws_of_defeat() -> list[AbilitySpec]:
    """Whenever a creature you control enters, target opponent loses life equal to the difference between that creature's power and its toughness.

    — PLAY-ALL (Abzan Armor). The group enters trigger drains a target opponent by the new ``abs_diff`` amount (RULE 107.1: the
    non-negative difference) of the entering creature's power and toughness (``trigger_subject``).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("lose_life", {
                "target_kind": "opponent",
                "amount": {
                    "kind": "abs_diff",
                    "left": {"kind": "characteristic", "characteristic": "power", "of": "trigger_subject"},
                    "right": {"kind": "characteristic", "characteristic": "toughness", "of": "trigger_subject"},
                },
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {
                "subject": "group", "controller": "you", "other": False, "type": "creature",
            }},
        ),
    ]


register("Jaws of Defeat", _jaws_of_defeat)
