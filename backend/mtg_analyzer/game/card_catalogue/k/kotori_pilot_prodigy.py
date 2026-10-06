from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _kotori_pilot_prodigy() -> list[AbilitySpec]:
    """Vehicles you control have crew 2.
    At the beginning of combat on your turn, target artifact creature you control gains lifelink and vigilance until end of turn.

    — PLAY-ALL (Shorikai Vehicles). The combat trigger is the parser's `pump`. "Have crew 2" is the layer-6 `grant_activated_ability` Swift
    Reconfiguration uses for its granted Crew 5, here over every Vehicle you control (``subtype: vehicle``): the Crew cost (``crew_power: 2``),
    then the Vehicle's own animation (``pt_selector: vehicle`` — it keeps its printed Vehicle P/T) and the `crewed_event` RULE 702.122e fires.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_activated_ability", {
                "affects": "permanents_you_control", "subtype": "vehicle",
                "cost": {"crew_power": 2},
                "grant_effects": [
                    {"type": "grant_until", "params": {
                        "target_kind": None, "duration": "end_of_turn",
                        "static": {"type": "type_change", "params": {"add_types": ["creature"], "pt_selector": "vehicle"}},
                    }},
                    {"type": "crewed_event", "params": {}},
                ],
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("pump", {"keywords": ["lifelink", "vigilance"], "target_kind": "creature_you_control",
                                 "creature_filter": {"card_type": "artifact"}})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"}, "phase_relation": "you"},
        ),
    ]


register("Kotori, Pilot Prodigy", _kotori_pilot_prodigy)
