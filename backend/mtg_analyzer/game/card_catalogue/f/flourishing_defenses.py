from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _flourishing_defenses() -> list[AbilitySpec]:
    """Whenever a -1/-1 counter is put on a creature, you may create a 1/1
    green Elf Warrior creature token.

    — Eliferate deck batch. Unscoped (any creature, any controller) —
    filtered straight off the `COUNTER` event's own payload
    (``kind``/``recipient_is_creature``), no "group" subject needed at
    all since there's no controller/identity restriction to check.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 1, "toughness": 1, "colors": ["G"],
                "subtypes": ["Elf", "Warrior"], "keywords": [], "token_name": "Elf Warrior",
            })],
            trigger={
                "event": EventType.COUNTER,
                "filter": {"kind": "-1/-1", "recipient_is_creature": True},
            },
            optional=True,
        ),
    ]


register("Flourishing Defenses", _flourishing_defenses)
