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
        AbilitySpec('triggered', [EffectSpec('self_exile_upkeep_haste')], optional=True,
                    trigger={'event': EventType.STEP_BEGIN, 'filter': {'step': 'end'}, 'phase_relation': 'you'}),
    ]


register('Obzedat, Ghost Council', _obzedat_ghost_council)
