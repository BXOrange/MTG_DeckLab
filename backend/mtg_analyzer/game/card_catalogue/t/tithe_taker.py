from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tithe_taker() -> list[AbilitySpec]:
    """During your turn, spells your opponents cast cost {1} more to cast
    and abilities your opponents activate cost {1} more to activate unless
    they're mana abilities.
    Afterlife 1 (When this creature dies, create a 1/1 white and black
    Spirit creature token with flying.)

    — MEC-12 (cEDH staples 2). Combines Defense Grid's tax shape (spells)
    and Suppression Field's (activations) with the *ordinary*,
    ability-source-relative "during your turn" gate (`active_if={"kind":
    "your_turn"}`, unlike Defense Grid's own caster-relative rider) and the
    opponents-only scope both `cost_reduction_for`/`activation_cost_
    reduction_for` already had for a reduction (Grand Arbiter Augustin IV/
    Training Grounds-shaped) but had never combined with a tax before.
    Afterlife is a plain already-bound keyword — hand-authoring this card's
    other two clauses doesn't drop it (keyword binding runs independently
    of `specs_for`'s registry precedence).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "affects": "opponents_spells", "generic": 1, "increase": True,
                "active_if": {"kind": "your_turn"},
            })],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "scope": "activation", "affects": "opponents_permanents",
                "generic": 1, "increase": True, "except_mana_abilities": True,
                "active_if": {"kind": "your_turn"},
            })],
        ),
    ]


register("Tithe Taker", _tithe_taker)
