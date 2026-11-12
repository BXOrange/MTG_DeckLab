"""Sonar Strike."""
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sonar_strike():
    """Sonar Strike deals 4 damage to target attacking, blocking, or tapped creature. You gain 3 life if you control a Bat."""
    return [AbilitySpec("spell_effect", [
        EffectSpec("damage", {"amount": 4, "target_kind": "creature", "creature_filter": {
            "any_of": [{"attacking": True}, {"blocking": True}, {"tapped": True}],
        }}),
        EffectSpec("gain_life", {"amount": 3}, condition={"kind": "control_count", "selector": {
            "zone": "battlefield", "of": "you", "filter": {"card_type": "creature", "subtype": "Bat"},
        }, "min": 1}),
    ])]


register("Sonar Strike", _sonar_strike)
