from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tetsuko_umezawa_fugitive() -> list[AbilitySpec]:
    """Creatures you control with power or toughness 1 or less can't be blocked.

    — Family Matters deck batch. The synthetic ``cant_be_blocked`` flag keyword (Herald of Secret Streams'
    grant) over creatures you control narrowed by an ``any_of`` object filter (power at most 1, or toughness
    at most 1 — "or" across two dimensions).
    """
    return [
        AbilitySpec("static", [EffectSpec("grant_keyword", {
            "affects": "creatures_you_control", "keywords": ["cant_be_blocked"],
            "object_filter": {"any_of": [{"max_power": 1}, {"max_toughness": 1}]},
        })]),
    ]


register("Tetsuko Umezawa, Fugitive", _tetsuko_umezawa_fugitive)
