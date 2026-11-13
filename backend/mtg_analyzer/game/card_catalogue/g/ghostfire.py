"""Ghostfire: its color-defining text is applied by card_colors in every zone."""
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ghostfire():
    """Ghostfire is colorless.
Ghostfire deals 3 damage to any target.
"""
    return [AbilitySpec("spell_effect", [EffectSpec("damage", {"amount": 3, "target_kind": "any"})])]


register("Ghostfire", _ghostfire)
