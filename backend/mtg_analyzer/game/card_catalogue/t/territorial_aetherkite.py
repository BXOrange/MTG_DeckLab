from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _territorial_aetherkite() -> list[AbilitySpec]:
    """Flying, haste
    When this creature enters, you get {E}{E} (two energy counters). Then you may pay one or more {E}. When you do, this creature deals that much damage to each other creature.

    — PLAY-ALL (Living Energy). The entry trigger grants two energy and
    offers a variable payment. Paying queues a separate respondable reflexive
    damage trigger with the paid amount captured as X (RULE 603.12).
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("add_player_counters", {"amount": 2, "kind": "energy"}),
                EffectSpec("pay_energy_then", {"amount": 1, "variable": True, "effects": [
                    {"type": "reflexive_trigger", "params": {"then_trigger": [
                        {"type": "damage", "params": {"amount": "x", "selector": "each_other_creature"}},
                    ]}},
                ]}),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Territorial Aetherkite", _territorial_aetherkite)
