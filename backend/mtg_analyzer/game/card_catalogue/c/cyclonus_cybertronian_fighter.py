from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _cyclonus_cybertronian_fighter() -> list[AbilitySpec]:
    """Living metal (During your turn, this Vehicle is also a creature.)
    Flying
    Whenever Cyclonus deals combat damage to a player, convert it. If you do, there is an additional beginning
    phase after this phase. (The beginning phase includes the untap, upkeep, and draw steps.)

    -- MEC-137. Back face of Cyclonus, the Saboteur. The new ``additional_beginning_phase`` effect (RULE 500.8)
    queues a beginning phase right after the combat phase in progress; "If you do" is `seq`'s ``if_you_do_from``
    (RULE 608.2c), which now also sees a transform as a change.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("seq", {
                "effects": [
                    {"type": "transform", "params": {}},
                    {"type": "additional_beginning_phase", "params": {}},
                ],
                "if_you_do_from": 1,
            })],
            trigger={"event": EventType.DAMAGE, "condition": {"subject": "self"},
                     "filter": {"combat": True, "is_player": True}},
            raw_text="whenever ~ deals combat damage to a player, convert it. if you do, there is an additional "
                     "beginning phase after this phase.",
        ),
    ]


register("Cyclonus, Cybertronian Fighter", _cyclonus_cybertronian_fighter)
