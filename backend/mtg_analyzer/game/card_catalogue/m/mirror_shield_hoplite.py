from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mirror_shield_hoplite() -> list[AbilitySpec]:
    """Vigilance
    Whenever a creature you control becomes the target of a backup ability, copy that ability. You may choose new targets for the copy. This ability triggers only once each turn.
    """
    return [AbilitySpec('triggered', [EffectSpec('copy_ability', {
        'ability_from_trigger_event': 'stack_id', 'choose_new_targets': True,
    })], trigger={
        'event': EventType.BECOMES_TARGET,
        'condition': {'subject': 'global'},
        'filter': {'item_kind': 'ability', 'ability_keyword': 'backup',
                   'target_creature_you_control': True},
        'limit': True,
    })]


register('Mirror-Shield Hoplite', _mirror_shield_hoplite)
