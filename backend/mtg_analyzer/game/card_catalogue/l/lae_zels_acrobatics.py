"""Lae'zel's Acrobatics — exile first, then use the real d20 roller."""
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _lae_zels_acrobatics():
    return [AbilitySpec('spell_effect', [EffectSpec('flicker_acrobatics')])]


register("Lae'zel's Acrobatics", _lae_zels_acrobatics)
