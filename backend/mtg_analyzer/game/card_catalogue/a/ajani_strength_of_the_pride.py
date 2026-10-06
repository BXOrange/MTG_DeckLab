from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "at least 15 life more than your starting life total".
_LIFE_OVER_STARTING = 15


def _ajani_strength_of_the_pride() -> list[AbilitySpec]:
    """+1: You gain life equal to the number of creatures you control plus the number of planeswalkers you control.
    −2: Create a 2/2 white Cat Soldier creature token named Ajani's Pridemate with "Whenever you gain life, put a +1/+1 counter on this token."
    0: If you have at least 15 life more than your starting life total, exile Ajani and each artifact and creature your opponents control.

    — PLAY-ALL (Hope to the last). The +1 is the parser's (`bind` over a two-term count selector). The −2 token carries its
    life-gain trigger as oracle text (Garruk's Wolf token idiom). The 0 gates three exiles on `life_over_starting_at_least`:
    the source itself, then ``opponents_creatures`` and ``opponents_artifacts``.
    """
    over_starting = {"kind": "life_over_starting_at_least", "amount": _LIFE_OVER_STARTING}
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("bind", {
                "name": "n",
                "amount": {"kind": "count_selector", "selector": {"terms": [
                    {"zone": "battlefield", "of": "you", "filter": {"card_type": "creature"}},
                    {"zone": "battlefield", "of": "you", "filter": {"card_type": "planeswalker"}},
                ]}},
                "effects": [{"type": "gain_life", "params": {"amount": "$n"}}],
            })],
            cost={"loyalty": 1},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("create_token", {
                "count": 1, "power": 2, "toughness": 2, "colors": ["W"], "subtypes": ["Cat", "Soldier"],
                "token_name": "Ajani's Pridemate",
                "oracle_text": "Whenever you gain life, put a +1/+1 counter on this creature.",
            })],
            cost={"loyalty": -2},
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("exile", {"target_kind": None}, condition=dict(over_starting)),
                EffectSpec("exile", {"selector": "opponents_creatures"}, condition=dict(over_starting)),
                EffectSpec("exile", {"selector": "opponents_artifacts"}, condition=dict(over_starting)),
            ],
            cost={"loyalty": 0},
        ),
    ]


register("Ajani, Strength of the Pride", _ajani_strength_of_the_pride)
