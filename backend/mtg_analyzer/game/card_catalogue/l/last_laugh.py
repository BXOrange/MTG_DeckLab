from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _last_laugh() -> list[AbilitySpec]:
    """Whenever a permanent other than this enchantment is put into a graveyard from the battlefield, this enchantment deals 1 damage to each creature and each player.
    When no creatures are on the battlefield, sacrifice this enchantment.
    """
    return [
        AbilitySpec('triggered', [EffectSpec('damage', {
            'group': {'zone': 'battlefield', 'of': 'any', 'filter': {'card_type': 'creature'}},
            'group_and_players': 'each_player', 'amount': 1,
        })], trigger={
            'event': EventType.DIES,
            'condition': {'subject': 'group', 'controller': 'any', 'other': True, 'type': 'permanent'},
        }),
        AbilitySpec('triggered', [EffectSpec('sacrifice_self', {'require_source_incarnation': True})], trigger={
            'event': EventType.STATE_CHECK,
            'state_condition': {'kind': 'control_count', 'selector': {
                'zone': 'battlefield', 'of': 'any', 'filter': {'card_type': 'creature'},
            }, 'max': 0},
        }),
    ]


register('Last Laugh', _last_laugh)
