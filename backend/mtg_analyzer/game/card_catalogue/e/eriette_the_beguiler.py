from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _eriette_the_beguiler() -> list[AbilitySpec]:
    """Lifelink
    Whenever an Aura you control becomes attached to a nonland permanent an opponent controls with mana value less than or equal to that Aura's mana value, gain control of that permanent for as long as that Aura is attached to it.
    """
    return [AbilitySpec('triggered', [EffectSpec('eriette_attachment_control', {})], trigger={
        'event': EventType.ATTACHED_TO_PERMANENT,
        'condition': {'subject': 'group', 'controller': 'you', 'subtypes': ['Aura']},
        'attach_host': {'nonland': True, 'controller': 'opponent', 'max_mana_value': 'attachment'},
    })]


register('Eriette, the Beguiler', _eriette_the_beguiler)
