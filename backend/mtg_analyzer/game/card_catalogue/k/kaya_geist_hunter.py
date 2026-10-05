from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _kaya_geist_hunter() -> list[AbilitySpec]:
    """+1: Creatures you control gain deathtouch until end of turn. Put a +1/+1 counter on up to one target creature token you control.
    −2: Until end of turn, if one or more tokens would be created under your control, twice that many of those tokens are created instead.
    −6: Exile all cards from all graveyards, then create a 1/1 white Spirit creature token with flying for each card exiled this way.

    — Kaya, Geist Hunter. +1 is the keyword-granting group `pump` plus an optional `add_counters` whose target
    is a creature you control narrowed to tokens (``creature_filter``). −2 is the new `double_tokens_this_turn`
    (the turn-scoped sibling of `double_tokens`). −6 is `exile_all_graveyards` followed by a `bind` over the
    ``objects_exiled_this_way`` tally (Crypt Incursion's idiom) that creates that many Spirits.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("pump", {
                    "power": 0, "toughness": 0, "keywords": ["deathtouch"], "selector": "creatures_you_control",
                }),
                EffectSpec("add_counters", {
                    "count": 1, "kind": "+1/+1", "target_kind": "creature_you_control",
                    "creature_filter": {"token": True}, "optional": True,
                }),
            ],
            cost={"loyalty": 1},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("double_tokens_this_turn", {})],
            cost={"loyalty": -2},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("seq", {"effects": [
                {"type": "exile_all_graveyards", "params": {}},
                {"type": "bind", "params": {
                    "name": "n",
                    "amount": {"kind": "this_way", "tally": "objects_exiled_this_way"},
                    "effects": [{"type": "create_token", "params": {
                        "count": "$n", "power": 1, "toughness": 1, "colors": ["W"], "subtypes": ["Spirit"],
                        "keywords": ["flying"], "token_name": "Spirit",
                    }}],
                }},
            ]})],
            cost={"loyalty": -6},
        ),
    ]


register("Kaya, Geist Hunter", _kaya_geist_hunter)
