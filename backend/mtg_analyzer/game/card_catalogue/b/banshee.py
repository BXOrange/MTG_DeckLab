"""Banshee."""
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _banshee():
    """{X}, {T}: This creature deals half X damage, rounded down, to any target, and half X damage, rounded up, to you."""
    return [AbilitySpec("activated", [EffectSpec("half_x_recoil", {})],
                        cost={"mana": "{X}", "taps_self": True})]


register("Banshee", _banshee)
