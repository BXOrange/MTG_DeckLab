from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mosswort_bridge():
    return [AbilitySpec("activated", [EffectSpec("play_hideaway_card", {
        "condition": {"kind": "control_count", "selector": "total_power_creatures_you_control", "min": 10},
    })], cost={"mana": "{G}", "taps_self": True}, raw_text="{G}, {T}: You may play the exiled card without paying its mana cost if creatures you control have total power 10 or greater.")]


register("Mosswort Bridge", _mosswort_bridge)
