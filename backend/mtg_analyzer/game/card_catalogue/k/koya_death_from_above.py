from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ....models.game.events import EventType
from ...card_registry.core import register


def _koya():
    """Flying
    When Koya enters, exile up to one other target creature. At the beginning of the next end step, you may pay {3}{B}. If you don't, return that card to the battlefield under its owner's control.
    """
    return [AbilitySpec('triggered', [EffectSpec('conditional_flicker', {
        'policy': 'unless_paid', 'cost': '{3}{B}', 'target_kind': 'creature',
        'optional': True,
    })], trigger={'event': EventType.ENTERS_BATTLEFIELD})]


register('Koya, Death from Above', _koya)
