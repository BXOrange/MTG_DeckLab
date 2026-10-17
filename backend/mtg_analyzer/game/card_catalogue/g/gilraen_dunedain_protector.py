from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _gilraen():
    """{2}, {T}: Exile another target creature you control. You may return that card to the battlefield under its owner's control. If you don't, at the beginning of the next end step, return that card to the battlefield under its owner's control with a vigilance counter and a lifelink counter on it."""
    return [AbilitySpec('activated', [EffectSpec('conditional_flicker', {
        'policy': 'immediate_or_countered', 'target_kind': 'other_creature_you_control',
    })], cost={'text': '{2}, {T}'})]


register('Gilraen, Dúnedain Protector', _gilraen)
