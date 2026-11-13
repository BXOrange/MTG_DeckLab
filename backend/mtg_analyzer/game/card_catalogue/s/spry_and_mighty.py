from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _spry_and_mighty() -> list[AbilitySpec]:
    """Choose exactly two creatures you control. You draw X cards and the chosen creatures get +X/+X and gain trample until end of turn, where X is the difference between the chosen creatures' powers."""
    return [AbilitySpec("spell_effect", [EffectSpec("choose_objects", {
        "what": "creature", "count": 2, "action": "select_only", "all_or_nothing": True,
        "then": [{"type": "bind", "params": {
            "name": "difference", "amount": {"kind": "abs_diff",
                "left": {"kind": "characteristic", "of": "previous_subject", "index": 0, "characteristic": "power"},
                "right": {"kind": "characteristic", "of": "previous_subject", "index": 1, "characteristic": "power"}},
            "effects": [{"type": "draw", "params": {"count": "$difference"}},
                        {"type": "pump", "params": {"power": "$difference", "toughness": "$difference",
                                                     "keywords": ["trample"], "previous_subject": True}}],
        }}],
    })])]


register("Spry and Mighty", _spry_and_mighty)
