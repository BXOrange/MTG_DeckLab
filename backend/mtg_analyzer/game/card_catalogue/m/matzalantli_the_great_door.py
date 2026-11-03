from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _matzalantli_the_great_door() -> list[AbilitySpec]:
    '{T}: Draw a card, then discard a card.\n{4}, {T}: Transform Matzalantli. Activate only if there are four or more permanent types among cards in your graveyard. (Artifact, battle, creature, enchantment, land, and planeswalker are permanent types.)'
    return [
        AbilitySpec(
            'activated',
            [EffectSpec('draw', {"count": 1}), EffectSpec('discard', {"count": 1})],
            cost={"text": '{t}'},
            raw_text='{t}: draw a card, then discard a card.',
        ),
        AbilitySpec(
            'activated',
            [EffectSpec('transform', {"source_only": True})],
            cost={"text": '{4}, {T}', "activation_condition": {'kind': 'control_count', 'selector': {'zone': 'graveyard', 'of': 'you', 'distinct': 'permanent_type'}, 'min': 4}},
            raw_text='',
        ),
    ]


register('Matzalantli, the Great Door', _matzalantli_the_great_door)
