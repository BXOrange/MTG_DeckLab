from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tip_the_scales() -> list[AbilitySpec]:
    """Sacrifice a creature. When you do, all creatures get -X/-X until end of turn, where X is the sacrificed creature's toughness.

    — PLAY-ALL (Abzan Armor). The chosen sacrifice captures its last-known
    toughness immediately. A separate respondable reflexive trigger then
    applies the captured -X/-X to all creatures (RULE 603.12).
    """
    return [
        AbilitySpec("spell_effect", [EffectSpec("choose_objects", {
            "action": "sacrifice", "what": "creature", "count": 1, "prompt": "Kreatur opfern",
            "then": [{"type": "bind", "params": {
                "name": "x", "amount": {"kind": "count_selector", "selector": "sacrificed_cost_toughness"},
                "effects": [{"type": "reflexive_trigger", "params": {"then_trigger": [
                    {"type": "pump", "params": {
                        "power": "-$x", "toughness": "-$x", "selector": "all_creatures",
                    }},
                ]}}],
            }}],
        })]),
    ]


register("Tip the Scales", _tip_the_scales)
