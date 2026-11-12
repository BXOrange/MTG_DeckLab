"""Shuriken."""
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _shuriken():
    """Equipped creature has "{T}, Unattach Shuriken: Shuriken deals 2 damage to target creature. That creature's controller gains control of Shuriken unless it was unattached from a Ninja."
Equip {2} ({2}: Attach to target creature you control. Equip only as a sorcery.)
"""
    return [AbilitySpec("static", [EffectSpec("grant_activated_ability", {
        "affects": "attached_permanent",
        "cost": {"taps_self": True, "unattach_grant_source": True},
        "grant_effects": [{"type": "unattached_projectile", "params": {}}],
    })])]


register("Shuriken", _shuriken)
