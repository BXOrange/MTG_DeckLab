from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _restless_spire() -> list[AbilitySpec]:
    """This land enters tapped.
    {T}: Add {U} or {R}.
    {U}{R}: Until end of turn, this land becomes a 2/1 blue and red Elemental
    creature with "During your turn, this creature has first strike." It's
    still a land.
    Whenever this land attacks, scry 1.

    — the Restless Cottage manland template. Documented simplifications: the
    colour change and the "during your turn" narrowing on first strike are
    not modeled (the animated creature keeps first strike unconditionally
    while animated)."""
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("grant_until", {
                    "duration": "end_of_turn", "target_kind": None,
                    "static": {"type": "type_change", "params": {
                        "add_types": ["creature"], "add_subtypes": ["Elemental"],
                        "power": 2, "toughness": 1,
                    }},
                }),
                EffectSpec("grant_until", {
                    "duration": "end_of_turn", "target_kind": None,
                    "static": {"type": "grant_keyword", "params": {"keywords": ["first strike"]}},
                }),
            ],
            cost={"text": "{U}{R}"},
        ),
    ]


register("Restless Spire", _restless_spire)
