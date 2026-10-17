from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _obzedat_ghost_council():
    """When Obzedat enters, target opponent loses 2 life and you gain 2 life.
    At the beginning of your end step, you may exile Obzedat. If you do, return it to the battlefield under its owner's control at the beginning of your next upkeep. It gains haste.
    """
    return [
        AbilitySpec('triggered', [EffectSpec('lose_life', {'amount': 2, 'target_kind': 'opponent'}),
                                 EffectSpec('gain_life', {'amount': 2})],
                    trigger={'event': EventType.ENTERS_BATTLEFIELD, 'condition': {'subject': 'self'}}),
        AbilitySpec('triggered', [EffectSpec('blink', {
            'subject': 'source', 'return_step': 'upkeep', 'return_scope': 'controller',
            'return_if_successful': True,
            'return_effects': [{'type': 'grant_until', 'params': {
                'static': {'type': 'grant_keyword', 'params': {'keywords': ['haste']}},
                'duration': 'rest_of_game', 'previous_subject': True,
            }}],
        })], optional=True,
                    trigger={'event': EventType.STEP_BEGIN, 'filter': {'step': 'end'}, 'phase_relation': 'you'}),
    ]


register('Obzedat, Ghost Council', _obzedat_ghost_council)
