"""Arni Metalbrow's declared attacks and attacking entries."""
from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _arni_metalbrow():
    """Whenever a creature you control attacks or enters attacking, you may pay {1}{R}. If you do, you may put a creature card with mana value less than that creature's mana value from your hand onto the battlefield tapped and attacking."""
    return [AbilitySpec('triggered', [EffectSpec('pay_cost_then', {
        'cost': '{1}{R}', 'effects': [{'type': 'arni_put_attacking', 'params': {}}],
    })], trigger={'event': event, 'condition': {
        'subject': 'group', 'type': 'creature', 'controller': 'you',
    }}) for event in (EventType.ATTACKS, EventType.ENTERS_ATTACKING)]


register('Arni Metalbrow', _arni_metalbrow)
