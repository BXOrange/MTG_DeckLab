from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _felothar_the_steadfast() -> list[AbilitySpec]:
    """Each creature you control assigns combat damage equal to its toughness rather than its power.
    Creatures you control can attack as though they didn't have defender.
    {3}, {T}, Sacrifice another creature: Draw cards equal to the sacrificed creature's toughness, then discard cards equal to its power.

    — PLAY-ALL (Abzan Armor). The toughness-damage static is the parser's. The defender permission is the standing
    ``attacks_as_though_no_defender`` `combat_restriction` over your creatures. The ability draws by the sacrificed
    creature's toughness and discards by its power: two `bind`s over ``sacrificed_cost_toughness`` / ``sacrificed_cost_power``
    (stamped by the cost, last-known information).
    """
    return [
        AbilitySpec("static", [EffectSpec("combat_restriction", {
            "kind": "damage_uses_toughness", "affects": "creatures_you_control",
        })]),
        AbilitySpec("static", [EffectSpec("combat_restriction", {
            "kind": "attacks_as_though_no_defender", "affects": "creatures_you_control",
        })]),
        AbilitySpec(
            "activated",
            [
                EffectSpec("bind", {
                    "name": "toughness",
                    "amount": {"kind": "count_selector", "selector": "sacrificed_cost_toughness"},
                    "effects": [{"type": "draw", "params": {"count": "$toughness"}}],
                }),
                EffectSpec("bind", {
                    "name": "power", "amount": {"kind": "count_selector", "selector": "sacrificed_cost_power"},
                    "effects": [{"type": "discard", "params": {"count": "$power"}}],
                }),
            ],
            cost={"text": "{3}, {T}, Sacrifice another creature"},
        ),
    ]


register("Felothar the Steadfast", _felothar_the_steadfast)
