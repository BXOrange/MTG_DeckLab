from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _dazzling_theater() -> list[AbilitySpec]:
    "Creature spells you cast have convoke. (Your creatures can help cast those spells. Each creature you tap while casting a creature spell pays for {1} or one mana of that creature's color.)\n(You may cast either half. That door unlocks on the battlefield. As a sorcery, you may pay the mana cost of a locked door to unlock it.)"
    return [
        AbilitySpec(
            'static',
            [EffectSpec('grant_help_pay_to_spells', {"keyword": 'convoke', "include_card_type": 'creature'})],
            raw_text='',
        ),
    ]


register('Dazzling Theater', _dazzling_theater)


def _prop_room() -> list[AbilitySpec]:
    "Untap each creature you control during each other player's untap step.\n(You may cast either half. That door unlocks on the battlefield. As a sorcery, you may pay the mana cost of a locked door to unlock it.)"
    return [
        AbilitySpec(
            'static',
            [EffectSpec('untap_each_untap_step', {"affects": 'creatures_you_control'})],
            raw_text='',
        ),
    ]


register('Prop Room', _prop_room)
