from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _arcane_lighthouse() -> list[AbilitySpec]:
    """{T}: Add {C}.
    {1}, {T}: Until end of turn, creatures your opponents control lose
    hexproof and shroud and can't have hexproof or shroud.

    Documented simplification: the "can't have" clause (a prohibition on
    *re-gaining* those keywords this turn) is not modeled — the keywords are
    stripped for the turn."""
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("grant_until", {
                "duration": "end_of_turn", "target_kind": None,
                "static": {"type": "remove_keyword", "params": {
                    "affects": "creatures_opponents_control",
                    "keywords": ["hexproof", "shroud"],
                }},
            })],
            cost={"mana": "{1}", "taps_self": True},
        ),
    ]


register("Arcane Lighthouse", _arcane_lighthouse)
