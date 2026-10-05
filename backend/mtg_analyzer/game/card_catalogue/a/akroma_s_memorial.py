from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _akromas_memorial() -> list[AbilitySpec]:
    """Legendary Artifact
    Creatures you control have flying, first strike, vigilance, trample,
    haste, and protection from black and from red.

    — PLAY-ALL Step 2 (Raggadragga). The one sentence is two statics the
    parser claims separately: `grant_keyword` for the five keywords and
    `grant_protection_static` for "protection from black and from red"
    (each probed on its own; only the combined sentence was unclaimed).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "creatures_you_control",
                "keywords": ["flying", "first_strike", "vigilance", "trample", "haste"],
            })],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_protection_static", {
                "affects": "creatures_you_control", "protections": ["black", "red"],
            })],
        ),
    ]


register("Akroma's Memorial", _akromas_memorial)
