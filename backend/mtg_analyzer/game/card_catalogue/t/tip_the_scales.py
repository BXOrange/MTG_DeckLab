from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tip_the_scales() -> list[AbilitySpec]:
    """Sacrifice a creature. When you do, all creatures get -X/-X until end of turn, where X is the sacrificed creature's toughness.

    — PLAY-ALL (Abzan Armor). `choose_objects` (sacrifice a creature of your choice) whose ``then`` — "when you do", run right
    after the sacrifice rather than as a separate trigger — is a `bind` over ``sacrificed_cost_toughness`` (stamped by the
    sacrifice, last-known information) feeding a `-X/-X` `pump` over every creature.
    """
    return [
        AbilitySpec("spell_effect", [EffectSpec("choose_objects", {
            "action": "sacrifice", "what": "creature", "count": 1, "prompt": "Kreatur opfern",
            "then": [{"type": "bind", "params": {
                "name": "x", "amount": {"kind": "count_selector", "selector": "sacrificed_cost_toughness"},
                "effects": [{"type": "pump", "params": {
                    "power": "-$x", "toughness": "-$x", "selector": "all_creatures",
                }}],
            }}],
        })]),
    ]


register("Tip the Scales", _tip_the_scales)
