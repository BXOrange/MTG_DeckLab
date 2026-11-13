"""Scrambleverse."""
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _scrambleverse():
    """For each nonland permanent, choose a player at random. Then each player gains control of each permanent for which they were chosen. Untap those permanents."""
    return [AbilitySpec("spell_effect", [EffectSpec("random_nonland_control", {})])]


register("Scrambleverse", _scrambleverse)
