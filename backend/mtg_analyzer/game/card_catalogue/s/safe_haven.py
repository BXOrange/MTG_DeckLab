from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _safe_haven() -> list[AbilitySpec]:
    """{2}, {T}: Exile target creature you control.
    At the beginning of your upkeep, you may sacrifice this land. If you do, return each card exiled with this land to the battlefield under its owner's control.
    """
    return [
        AbilitySpec('activated', [EffectSpec('exile', {
            'target_kind': 'creature_you_control', 'track_exiled_with': True,
        })], cost='{2}, {T}'),
        AbilitySpec('triggered', [EffectSpec('return_all_exiled_with', {
            'sacrifice_source': True,
        })], trigger={'event': EventType.STEP_BEGIN, 'filter': {'step': 'upkeep'},
                     'phase_relation': 'you'}, optional=True),
    ]


register('Safe Haven', _safe_haven)
