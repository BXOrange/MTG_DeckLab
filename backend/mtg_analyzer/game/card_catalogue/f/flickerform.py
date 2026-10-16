from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _flickerform():
    """Enchant creature
    {2}{W}{W}: Exile enchanted creature and all Auras attached to it. At the beginning of the next end step, return that card to the battlefield under its owner's control. If you do, return the other cards exiled this way to the battlefield under their owners' control attached to that creature.
    """
    return [AbilitySpec('activated', [EffectSpec('exile_attached_group', {
        'attached_host': True, 'release': 'end',
    })], cost={'text': '{2}{W}{W}'})]


register('Flickerform', _flickerform)
