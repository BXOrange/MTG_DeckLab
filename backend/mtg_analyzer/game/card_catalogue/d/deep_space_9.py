from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _deep_space_9() -> list[AbilitySpec]:
    """When Deep Space 9 enters and at the beginning of your upkeep, exile the top four cards of your library. Put all permanent cards exiled this way onto the battlefield.
    Station (Tap another creature you control: Put charge counters equal to its power on this Spacecraft. Station only as a sorcery.)
    9+ | Creatures you control get +3/+3.
    """
    def entry_effects():
        return [EffectSpec("exile_top_of_library", {"count": 4}),
                EffectSpec("put_latest_exiled_onto_battlefield", {})]

    return [
        AbilitySpec("triggered", entry_effects(), trigger={
            "event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"},
        }),
        AbilitySpec("triggered", entry_effects(), trigger={
            "event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you",
        }),
        AbilitySpec("static", [EffectSpec("anthem", {
            "power": 3, "toughness": 3, "affects": "creatures_you_control",
            "min_level": 9, "level_counter": "charge",
        })]),
    ]


register("Deep Space 9", _deep_space_9)
