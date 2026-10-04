from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _weathered_sentinels() -> list[AbilitySpec]:
    """Keywords bind independently; retain the parser's own attack trigger."""
    return [
        AbilitySpec("static", [EffectSpec("combat_restriction", {
            "kind": "attacks_as_though_no_defender", "affects": "self",
            "defender_kind": "player",
            "condition": {"kind": "opponent_attacked_you_last_turn"},
        })], raw_text="This creature can attack players who attacked you during their last turn as though it didn't have defender."),
        AbilitySpec("triggered", [EffectSpec("pump", {
            "power": 3, "toughness": 3, "keywords": ["indestructible"],
        })], trigger={"event": "ATTACKS", "condition": {"subject": "self"}},
            raw_text="Whenever this creature attacks, it gets +3/+3 and gains indestructible until end of turn."),
    ]


register("Weathered Sentinels", _weathered_sentinels)
