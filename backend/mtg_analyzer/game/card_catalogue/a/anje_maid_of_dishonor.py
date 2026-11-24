
from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _anje_maid_of_dishonor() -> list[AbilitySpec]:
    'Whenever Anje and/or one or more other Vampires you control enter, create a Blood token. This ability triggers only once each turn. (It\'s an artifact with "{1}, {T}, Discard a card, Sacrifice this token: Draw a card.")\n{2}, Sacrifice another creature or a Blood token: Each opponent loses 2 life and you gain 2 life.'
    return [AbilitySpec('triggered', [EffectSpec('create_token', {'token_name': 'Blood', 'count': 1})],
                        trigger={'event': 'EVENT_BATCH', 'batch': {'of': 'ENTERS_BATTLEFIELD', 'min': 1},
                                 'condition': {'subject': 'self_or_group', 'controller': 'you',
                                               'filter': {'subtype': 'Vampire'}}, 'limit': True}),
            AbilitySpec('activated', [EffectSpec('lose_life', {'amount': 2, 'selector': 'each_opponent'}),
                                      EffectSpec('gain_life', {'amount': 2})],
                        cost={'mana': '{2}', 'sacrifice': 'blood_token_or_other_creature'})]



register('Anje, Maid of Dishonor', _anje_maid_of_dishonor)
