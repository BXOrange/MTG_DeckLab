from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _vanish_into_memory():
    """Exile target creature. You draw cards equal to that creature's power. At the beginning of your next upkeep, return that card to the battlefield under its owner's control. If you do, discard cards equal to that creature's toughness."""
    return [AbilitySpec('spell_effect', [EffectSpec('vanish_into_memory')])]


register('Vanish into Memory', _vanish_into_memory)
