from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _disciple_of_bolas() -> list[AbilitySpec]:
    """When this creature enters, sacrifice another creature. You gain X life
    and draw X cards, where X is that creature's power.

    — PLAY-ALL Step 2 (Wick Snail Boom). `sacrifice_chosen_then` (MEC-103's
    "sacrifice … when you do, that many") with three new parameters:
    ``optional: False`` (the sacrifice is mandatory), ``exclude_self`` ("another")
    and ``measure: "power"``, which binds the follow-up's ``"x"`` to the
    sacrificed creature's power — read before it leaves the battlefield
    (`RulesEngine._that_many_value`). The follow-up is the gain and the draw.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice_chosen_then", {
                "what": "creature", "count": 1, "optional": False, "exclude_self": True, "measure": "power",
                "effects": [
                    {"type": "gain_life", "params": {"amount": "x"}},
                    {"type": "draw", "params": {"count": "x"}},
                ],
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        )
    ]


register("Disciple of Bolas", _disciple_of_bolas)
