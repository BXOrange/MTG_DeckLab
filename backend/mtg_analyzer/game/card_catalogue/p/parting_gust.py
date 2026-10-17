from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _parting_gust():
    """Gift a tapped Fish (You may promise an opponent a gift as you cast this spell. If you do, they create a tapped 1/1 blue Fish creature token before its other effects.)
    Exile target nontoken creature. If the gift wasn't promised, return that card to the battlefield under its owner's control with a +1/+1 counter on it at the beginning of the next end step.
    """
    return [AbilitySpec('spell_effect', [EffectSpec('conditional_flicker', {
        'policy': 'unless_gift_promised', 'target_kind': 'creature',
        'creature_filter': {'nontoken': True},
    })])]


register('Parting Gust', _parting_gust)
