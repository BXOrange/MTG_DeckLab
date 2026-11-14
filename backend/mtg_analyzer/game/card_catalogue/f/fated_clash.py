from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _fated_clash() -> list[AbilitySpec]:
    """You may cast this spell as though it had flash if a creature is attacking and a creature is blocking.
    Target creature you control and target creature an opponent controls each gain indestructible until end of turn. Then destroy all creatures.
    """
    return [AbilitySpec('spell_effect', [
        EffectSpec('pump', {'target_kind': 'creature_you_control', 'keywords': ['indestructible']}),
        EffectSpec('pump', {'target_kind': 'creature_you_dont_control', 'keywords': ['indestructible']}),
        EffectSpec('destroy', {'selector': 'all_creatures'}),
    ], conditional_flash={'active_if': {'kind': 'all', 'conditions': [
        {'kind': 'control_count', 'selector': {'zone': 'battlefield', 'of': 'any',
            'filter': {'card_type': 'creature', 'attacking': True}}, 'min': 1},
        {'kind': 'control_count', 'selector': {'zone': 'battlefield', 'of': 'any',
            'filter': {'card_type': 'creature', 'blocking': True}}, 'min': 1},
    ]}})]


register('Fated Clash', _fated_clash)
