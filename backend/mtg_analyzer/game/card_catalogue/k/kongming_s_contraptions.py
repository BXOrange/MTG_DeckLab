"""Kongming's Contraptions."""
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _kongming_s_contraptions():
    """{T}: This creature deals 2 damage to target attacking creature. Activate only during the declare attackers step and only if you've been attacked this step."""
    return [AbilitySpec("activated", [EffectSpec("damage", {
        "amount": 2, "target_kind": "creature", "creature_filter": {"attacking": True},
    })], cost={"taps_self": True, "activation_condition": {"kind": "all", "conditions": [
        {"kind": "during_step", "step": "declare_attackers"},
        {"kind": "you_were_attacked_this_step"},
    ]}})]


register("Kongming's Contraptions", _kongming_s_contraptions)
