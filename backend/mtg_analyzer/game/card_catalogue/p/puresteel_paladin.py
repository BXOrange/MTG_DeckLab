from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: Metalcraft — "three or more artifacts".
_METALCRAFT = 3


def _puresteel_paladin() -> list[AbilitySpec]:
    """Whenever an Equipment you control enters, you may draw a card.
    Metalcraft — Equipment you control have equip {0} as long as you control three or more artifacts.

    — PLAY-ALL (Limit Break). The draw is the parser's claim. ENG-68: "have equip {0}" is a second, granted Equip ability (RULE 702.6, 113.2c) next to each Equipment's printed one, not
    a change to its cost: `grant_equip_ability` over your Equipment while the ``control_count`` (metalcraft) gate holds.
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
            [EffectSpec("grant_equip_ability", {
                "affects": {"zone": "battlefield", "of": "you", "filter": {"subtype": "equipment"}},
                "entries": [{"cost": "{0}"}],
                "active_if": {"kind": "control_count", "selector": "artifacts_you_control", "min": _METALCRAFT},
            })],
        ),
    ]


register("Puresteel Paladin", _puresteel_paladin)
