from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _specs() -> list[AbilitySpec]:
    """Sketch and Lore — {2}{R}, {T}: Target opponent exiles cards from the top of their library until they exile an instant, sorcery, or creature card. You may cast that card without paying its mana cost. If you cast a creature spell this way, it gains haste and "At the beginning of the end step, sacrifice this creature." Activate only as a sorcery.
    """
    return [
        AbilitySpec(
            'activated',
            [
                EffectSpec(
                    'dig_until',
                    {
                        'criteria': {'type': ['Instant', 'Sorcery', 'Creature']},
                        'target_kind': 'opponent',
                        'digger': 'facing',
                        'caster': 'controller',
                        'hit_destination': 'cast_free_window',
                        'rest_destination': 'exile',
                        'hit_rider': 'haste_sacrifice',
                        'uncast_hit': 'stay',
                    },
                ),
            ],
            cost={'text': '{2}{R}, {T}', 'sorcery_speed_only': True},
        ),
    ]


register('Strago and Relm', _specs)
