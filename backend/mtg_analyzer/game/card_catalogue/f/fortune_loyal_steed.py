"""Fortune, Loyal Steed — recorded saddlers are exact battlefield visits."""
from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _fortune_loyal_steed():
    return [
        AbilitySpec('triggered', [EffectSpec('scry', {'count': 2})],
                    trigger={'event': EventType.ENTERS_BATTLEFIELD, 'condition': {'subject': 'self'}}),
        AbilitySpec('triggered', [EffectSpec('flicker_fortune_delayed')],
                    trigger={'event': EventType.ATTACKS, 'condition': {'subject': 'self'},
                             'requires_saddled': True}),
        AbilitySpec('keyword', [], keyword={'name': 'saddle', 'n': 1}),
    ]


register('Fortune, Loyal Steed', _fortune_loyal_steed)
