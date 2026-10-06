from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _specs() -> list[AbilitySpec]:
    """(As this Saga enters and after your draw step, add a lore counter. Sacrifice after IV.)
    I — Exile an instant or sorcery card from each graveyard.
    II, III, IV — Add {R} for each lore counter on this Saga. You may cast an instant or sorcery card exiled with this Saga, and mana of any type can be spent to cast that spell.
    Flying, haste
    Known limitations: chapter I selects the newest matching card from each graveyard.
    Chapters II–IV grant turn-long permissions for every linked spell, rather than a
    single cast during the chapter's resolution.
    """
    return [
        AbilitySpec(
            'triggered',
            [EffectSpec('exile_instant_sorcery_from_each_graveyard', {})],
            trigger={'event': EventType.SAGA_CHAPTER, 'chapter': [1]},
        ),
        AbilitySpec(
            'triggered',
            [
                EffectSpec(
                    'bind',
                    {
                        'name': 'n',
                        'amount': {'kind': 'counters', 'of': 'self', 'counter': 'lore'},
                        'effects': [{'type': 'add_mana', 'params': {'amount': '$n', 'color': 'R'}}],
                    },
                ),
                EffectSpec('cast_exiled_with_source', {}),
            ],
            trigger={'event': EventType.SAGA_CHAPTER, 'chapter': [2, 3, 4]},
        ),
    ]


register('Summon: Esper Valigarmanda', _specs)
