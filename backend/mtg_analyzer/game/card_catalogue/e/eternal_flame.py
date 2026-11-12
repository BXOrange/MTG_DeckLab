"""Eternal Flame."""
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _eternal_flame():
    """Eternal Flame deals X damage to target opponent or planeswalker and half X damage, rounded up, to you, where X is the number of Mountains you control."""
    return [AbilitySpec("spell_effect", [EffectSpec("mountain_recoil", {})])]


register("Eternal Flame", _eternal_flame)
