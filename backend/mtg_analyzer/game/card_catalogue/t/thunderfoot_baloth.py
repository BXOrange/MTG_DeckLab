from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _thunderfoot_baloth() -> list[AbilitySpec]:
    """Trample
    Lieutenant — As long as you control your commander, this creature gets +2/+2 and other creatures you control get +2/+2 and have trample.

    — PLAY-ALL (Jump Scare!). Trample is a keyword. The Lieutenant gate is one ``active_if`` (`control_count` over "your
    commander on the battlefield", Angelic Field Marshal's) on three statics: the self +2/+2, the other creatures'
    +2/+2 and their trample.
    """
    commander = {
        "kind": "control_count", "min": 1,
        "selector": {"zone": "battlefield", "of": "you", "filter": {"is_commander": True}},
    }
    return [
        AbilitySpec("static", [EffectSpec("anthem", {
            "affects": "self", "power": 2, "toughness": 2, "active_if": dict(commander),
        })]),
        AbilitySpec("static", [EffectSpec("anthem", {
            "affects": "other_creatures_you_control", "power": 2, "toughness": 2, "active_if": dict(commander),
        })]),
        AbilitySpec("static", [EffectSpec("grant_keyword", {
            "affects": "other_creatures_you_control", "keywords": ["trample"], "active_if": dict(commander),
        })]),
    ]


register("Thunderfoot Baloth", _thunderfoot_baloth)
