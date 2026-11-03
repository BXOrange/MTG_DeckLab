
from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _colorless_ultimatum() -> list[AbilitySpec]:
    'Each opponent exiles half the cards in their library, rounded up. Until end of turn, creatures you control gain annihilator 1.'
    return [
        AbilitySpec("spell_effect", [
            EffectSpec("for_each", {"over": {"players": "each_opponent"}, "effects": [
                {"type": "exile_top_of_library", "params": {"player_selector": "target", "count": {
                    "kind": "resource", "resource": "library_size", "of": "iteration", "divide": 2, "round_up": True,
                }}},
            ]}),
            EffectSpec("grant_until", {"target_kind": None, "lock_group": True, "duration": "end_of_turn",
                "static": {"type": "grant_keyword", "params": {"affects": "creatures_you_control",
                    "parametric_keywords": [{"name": "annihilator", "n": 1}]}}}),
        ]),
    ]


register('Colorless Ultimatum', _colorless_ultimatum)
