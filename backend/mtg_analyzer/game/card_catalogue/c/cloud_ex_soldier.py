from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "if Cloud has power 7 or greater".
_TREASURE_POWER = 7


def _cloud_ex_soldier() -> list[AbilitySpec]:
    """Haste
    When Cloud enters, attach up to one target Equipment you control to it.
    Whenever Cloud attacks, draw a card for each equipped attacking creature you control. Then if Cloud has power 7 or greater, create two Treasure tokens.

    — PLAY-ALL (Limit Break). Haste is the keyword. The enters trigger is `attach_equipment` onto the source (an optional single Equipment target). The attack trigger is a `bind` of the new
    ``equipped_attacking_creatures_you_control`` selector into `draw`, then an `if_else` on Cloud's power for two Treasures.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("attach_equipment", {"to_source": True})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("bind", {
                    "name": "n", "amount": {"kind": "count_selector", "selector": "equipped_attacking_creatures_you_control"},
                    "effects": [{"type": "draw", "params": {"count": "$n"}}],
                }),
                EffectSpec("if_else", {
                    "condition": {"kind": "power", "of": "source", "min": _TREASURE_POWER},
                    "then": [{"type": "create_token", "params": {"token_name": "Treasure", "count": 2}}],
                }),
            ],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Cloud, Ex-SOLDIER", _cloud_ex_soldier)
