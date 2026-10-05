from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _commander_s_insignia() -> list[AbilitySpec]:
    """Creatures you control get +1/+1 for each time you've cast your commander from the command zone this game.

    — Commander's Insignia. An anthem scaled by the existing `commander_casts_this_game` selector
    (`Player.commander_casts`, the RULE 903.8 tax tally; Thunderclap Drake reads the same one).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "affects": "creatures_you_control", "power": 1, "toughness": 1,
                "power_count": "commander_casts_this_game", "toughness_count": "commander_casts_this_game",
            })],
        )
    ]


register("Commander's Insignia", _commander_s_insignia)
