from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _angelic_field_marshal() -> list[AbilitySpec]:
    """Flying
    Lieutenant — As long as you control your commander, this creature gets +2/+2 and creatures you control have vigilance.

    — PLAY-ALL (Calling All Angels). Flying is the keyword catalogue's. The Lieutenant gate is one ``active_if``
    (`control_count` over a structured "your commander on the battlefield" selector) on a self anthem and a vigilance grant.
    """
    commander = {
        "kind": "control_count", "min": 1,
        "selector": {"zone": "battlefield", "of": "you", "filter": {"is_commander": True}},
    }
    return [
        AbilitySpec("static", [EffectSpec("anthem", {
            "affects": "self", "power": 2, "toughness": 2, "active_if": dict(commander),
        })]),
        AbilitySpec("static", [EffectSpec("grant_keyword", {
            "affects": "creatures_you_control", "keywords": ["vigilance"], "active_if": dict(commander),
        })]),
    ]


register("Angelic Field Marshal", _angelic_field_marshal)
