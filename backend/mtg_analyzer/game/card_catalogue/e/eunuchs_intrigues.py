"""Eunuchs' Intrigues."""
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _eunuchs_intrigues():
    """Target opponent chooses a creature they control. Other creatures they control can't block this turn."""
    return [AbilitySpec("spell_effect", [EffectSpec("war_cry", {})])]


register("Eunuchs' Intrigues", _eunuchs_intrigues)
