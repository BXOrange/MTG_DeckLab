from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _massacre_girl() -> list[AbilitySpec]:
    """Menace
    When Massacre Girl enters, each other creature gets -1/-1 until end of turn. Whenever a creature dies this turn, each creature other than Massacre Girl gets -1/-1 until end of turn.

    — PLAY-ALL (Endless Punishment). Menace is a keyword. Both halves use what the parser already claims for each sentence on its own: the mass ``not_reference`` pump
    ("each other creature") and `create_turn_trigger` ("whenever a creature dies this turn, …") whose body is the same mass pump, so every death this turn shrinks
    everything but Massacre Girl again.
    """
    pump = {"type": "pump", "params": {
        "power": -1, "toughness": -1,
        "selector": {"zone": "battlefield", "of": "any", "filter": {"card_type": "creature", "not_reference": True}},
    }}
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("pump", dict(pump["params"])),
                EffectSpec("create_turn_trigger", {
                    "trigger": {"event": "DIES", "condition": {"subject": "group", "controller": "any", "other": False, "type": "creature"}},
                    "effects": [dict(pump)], "optional": False,
                    "description": "Massacre Girl: Wann immer eine Kreatur stirbt, erhält jede andere Kreatur -1/-1",
                }),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Massacre Girl", _massacre_girl)
