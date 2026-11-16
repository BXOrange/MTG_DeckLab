
from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _the_archimandrite() -> list[AbilitySpec]:
    'At the beginning of your upkeep, you gain X life, where X is the number of cards in your hand minus 4.\nWhenever you gain life, each Advisor, Artificer, and Monk you control gains vigilance and gets +X/+0 until end of turn, where X is the amount of life you gained.\nTap three untapped Advisors, Artificers, and/or Monks you control: Draw a card.'
    return [
        AbilitySpec(
            'triggered',
            [EffectSpec('bind', {"name": 'n', "amount": {'kind': 'count_selector', 'selector': {'zone': 'hand', 'of': 'you'}, 'minus': 4, 'minimum': 0}, "effects": [{'type': 'gain_life', 'params': {'amount': '$n'}}]})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {'step': 'upkeep'}, "phase_relation": 'you'},
            raw_text='at the beginning of your upkeep, you gain x life, where x is the number of cards in your hand minus 4.',
        ),
        AbilitySpec('triggered', [EffectSpec('bind', {
            'name': 'gained', 'amount': {'kind': 'trigger_event', 'field': 'amount'},
            'effects': [{'type': 'pump', 'params': {'power': '$gained', 'toughness': 0,
                'keywords': ['vigilance'], 'selector': {'zone': 'battlefield', 'of': 'you',
                    'filter': {'subtype_any': ['Advisor', 'Artificer', 'Monk']}}}}],
        })], trigger={'event': EventType.LIFE_GAINED, 'condition': {'subject': 'you'}}),
        AbilitySpec('activated', [EffectSpec('draw', {'count': 1})],
                    cost={'tap_others': [3, 'advisor_or_artificer_or_monk']}),
    ]


register('The Archimandrite', _the_archimandrite)
