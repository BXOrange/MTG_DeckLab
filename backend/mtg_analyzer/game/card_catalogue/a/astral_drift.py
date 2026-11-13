from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _astral_drift() -> list[AbilitySpec]:
    """Whenever you cycle this card or cycle another card while this enchantment is on the battlefield, you may exile target creature. If you do, return that card to the battlefield under its owner's control at the beginning of the next end step.
    Cycling {2}{W} ({2}{W}, Discard this card: Draw a card.)
    """
    return [AbilitySpec('triggered', [EffectSpec('blink', {
        'target_kind': 'creature', 'return_step': 'end',
    })], trigger={
        'event': EventType.CYCLED, 'condition': condition,
        **({'active_if': {'kind': 'control_count', 'selector': {
            'zone': 'battlefield', 'of': 'any', 'filter': {'is_reference': True},
        }, 'min': 1}} if battlefield_only else {}),
    }, optional=True) for condition, battlefield_only in (
        ({'subject': 'self'}, False), ({'subject': 'you'}, True),
    )]


register('Astral Drift', _astral_drift)
