
from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ....models.game.events import EventType
from ...card_registry.core import register, register_ability_line


COPY_LINE = ('The first time each turn an ability of this creature is activated or triggered, '
             'copy it. You may choose new targets for the copy')


def _copy_trigger():
    return [AbilitySpec('triggered', [EffectSpec('copy_ability', {
        'ability_from_trigger_event': 'stack_id', 'choose_new_targets': True,
    })], trigger={'event': [EventType.ACTIVATED_ABILITY, EventType.ABILITY_TRIGGERED,
                           EventType.MANA_ABILITY_ACTIVATED],
                  'condition': {'subject': 'self'}, 'first_source_ability_each_turn': True},
        raw_text=COPY_LINE)]


def _the_cosplayzer() -> list[AbilitySpec]:
    'You may have The Cosplayzer enter as a copy of any creature on the battlefield, except it has "The first time each turn an ability of this creature is activated or triggered, copy it. You may choose new targets for the copy" and the first letter of its name is Z. (This is both stylish AND makes it a different name for the legend rule!)'
    return [AbilitySpec('enter_replacement', [EffectSpec('enter_as_copy', {
        'target_kind': 'creature', 'name_first_letter': 'Z', 'add_ability_lines': [COPY_LINE],
    })])]


register_ability_line(COPY_LINE, _copy_trigger)
register('The Cosplayzer', _the_cosplayzer)
