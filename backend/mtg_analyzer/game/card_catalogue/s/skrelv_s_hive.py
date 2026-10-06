from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _card() -> list[AbilitySpec]:
    return [
        AbilitySpec('triggered', [
            EffectSpec('lose_life', {'amount': 1}),
            EffectSpec('create_token', {'token_name': 'Phyrexian Mite', 'count': 1,
                'power': 1, 'toughness': 1, 'colors': [], 'subtypes': ['Phyrexian', 'Mite'],
                'is_artifact': True, 'parametric_keywords': [{'name': 'toxic', 'n': 1}],
                'keywords': ['cant_block'], 'oracle_text': "Toxic 1\nThis token can't block."}),
        ], trigger={'event': 'STEP_BEGIN', 'filter': {'step': 'upkeep'}, 'phase_relation': 'you'}),
        AbilitySpec('static', [EffectSpec('grant_keyword', {
            'affects': 'creatures_you_control', 'object_filter': {'keyword_any': ['toxic']},
            'keywords': ['lifelink'], 'active_if': {'kind': 'opponent_poison_at_least', 'amount': 3},
        })]),
    ]


register("Skrelv's Hive", _card)
