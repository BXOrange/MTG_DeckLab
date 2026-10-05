from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sokenzan_crucible_of_defiance() -> list[AbilitySpec]:
    """{T}: Add {R}.
    Channel — {3}{R}, Discard this card: Create two 1/1 colorless Spirit
    creature tokens. They gain haste until end of turn. This ability
    costs {1} less to activate for each legendary creature you control.

    (The mana ability is bound automatically off the printed "{T}: Add
    {R}." text.) Simplified: the "{1} less for each legendary creature"
    cost reduction isn't modeled (`continuous.activation_cost_reduction_
    for` has no per-count scaling for a hand-zone Channel-style cost yet,
    only a flat subtype-scoped one) — Channel itself (offered and payable
    from hand, discarding this card as its cost) is fully modeled at its
    full printed price.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("create_token", {
                "count": 2, "power": 1, "toughness": 1, "colors": [],
                "subtypes": ["Spirit"], "keywords": ["haste"], "token_name": "Spirit",
            })],
            cost={"mana": "{3}{R}", "discard_self": True},
        ),
    ]


register("Sokenzan, Crucible of Defiance", _sokenzan_crucible_of_defiance)
