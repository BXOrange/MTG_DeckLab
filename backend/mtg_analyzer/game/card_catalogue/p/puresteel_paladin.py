from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: Metalcraft — "three or more artifacts".
_METALCRAFT = 3


def _puresteel_paladin() -> list[AbilitySpec]:
    """Whenever an Equipment you control enters, you may draw a card.
    Metalcraft — Equipment you control have equip {0} as long as you control three or more artifacts.

    — PLAY-ALL (Limit Break). The draw is the parser's claim. Metalcraft is `cost_reduction` with ``scope="activation"`` and the new ``set_to_zero``
    (`continuous.activation_cost_reduction_for`): the equip ability of the controller's Equipment costs {0} while the ``control_count`` gate holds.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {
                "subject": "group", "controller": "you", "other": False, "subtypes": ["equipment"], "nontoken": False,
            }},
            optional=True,
        ),
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "scope": "activation", "set_to_zero": True, "attach_kind": "equip", "subtype": "equipment",
                "active_if": {"kind": "control_count", "selector": "artifacts_you_control", "min": _METALCRAFT},
            })],
        ),
    ]


register("Puresteel Paladin", _puresteel_paladin)
