"""Another Round — choose a fresh set for each of X+1 flicker instructions."""
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _another_round():
    return [AbilitySpec('spell_effect', [EffectSpec('flicker_repeated_rounds')])]


register('Another Round', _another_round)
