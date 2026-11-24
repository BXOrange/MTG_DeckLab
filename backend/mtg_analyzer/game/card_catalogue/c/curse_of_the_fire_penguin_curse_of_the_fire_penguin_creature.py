from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _curse_of_the_fire_penguin() -> list[AbilitySpec]:
    """Enchant creature
    This enchantment consumes and confuses enchanted creature.

    Official Unhinged FAQ: overlay everything below the art, preserving
    name, mana cost, colors and illustration. The overlay is not a flip.
    """
    return [AbilitySpec('static', [
        EffectSpec('type_change', {'affects': 'attached_permanent',
            'set_types': ['creature'], 'set_subtypes': ['Penguin'],
            'remove_types': ['legendary', 'snow', 'basic', 'world'],
            'power': 6, 'toughness': 5,
            'printing_override': {'set_code': 'unh', 'artist': 'Matt Thompson', 'rarity': 'rare'},
        }),
        EffectSpec('remove_all_abilities', {'affects': 'attached_permanent'}),
        EffectSpec('grant_keyword', {'affects': 'attached_permanent', 'keywords': ['trample']}),
        EffectSpec('grant_triggered_ability', {'affects': 'attached_permanent',
            'trigger_event': EventType.DIES,
            'grant_effects': [{'type': 'fire_penguin_return', 'params': {}}],
        }),
    ])]


register('Curse of the Fire Penguin', _curse_of_the_fire_penguin)
