"""Unerring Sling."""
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _unerring_sling():
    """{3}, {T}, Tap an untapped creature you control: This artifact deals damage equal to the tapped creature's power to target attacking or blocking creature with flying."""
    return [AbilitySpec("activated", [EffectSpec("cost_tapped_power_damage", {})], cost={
        "mana": "{3}", "taps_self": True, "tap_others": [1, "creature"],
    })]


register("Unerring Sling", _unerring_sling)
