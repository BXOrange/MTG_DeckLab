from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _spinerock_knoll():
    return [AbilitySpec("activated", [EffectSpec("play_hideaway_card", {
        "condition": {"kind": "opponent_was_dealt_damage_this_turn", "min": 7},
    })], cost={"mana": "{R}", "taps_self": True}, raw_text="{R}, {T}: You may play the exiled card without paying its mana cost if an opponent was dealt 7 or more damage this turn.")]


register("Spinerock Knoll", _spinerock_knoll)
