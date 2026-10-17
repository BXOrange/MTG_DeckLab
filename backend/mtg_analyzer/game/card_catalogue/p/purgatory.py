from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _purgatory() -> list[AbilitySpec]:
    """Whenever a nontoken creature is put into your graveyard from the battlefield, exile that card.
    At the beginning of your upkeep, you may pay {4} and 2 life. If you do, return a card exiled with this enchantment to the battlefield.
    """
    return [
        AbilitySpec('triggered', [EffectSpec('exile', {
            'target_kind': 'trigger_subject', 'trigger_event_key': '__group_subject__',
            'track_exiled_with': True,
        })], trigger={'event': EventType.DIES, 'condition': {
            'subject': 'group', 'controller': 'any', 'owner': 'you',
            'other': False, 'filter': {'card_type': 'creature', 'nontoken': True},
        }}),
        AbilitySpec('triggered', [EffectSpec('linked_pool_return_one', {'cost': '{4}, Pay 2 life'})],
                    trigger={'event': EventType.STEP_BEGIN, 'filter': {'step': 'upkeep'},
                             'phase_relation': 'you'}),
    ]


register('Purgatory', _purgatory)
