
from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _painbringer() -> list[AbilitySpec]:
    '{T}, Exile any number of cards from your graveyard: Target creature gets -X/-X until end of turn, where X is the number of cards exiled this way.'
    return [AbilitySpec('activated', [EffectSpec('pump', {
        'power': '-x', 'toughness': '-x', 'target_kind': 'creature',
    })], cost={'taps_self': True, 'exile_from_graveyard': {'count': 'x'}})]



register('Painbringer', _painbringer)
