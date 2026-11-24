from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _leyline_of_combustion() -> list[AbilitySpec]:
    """If this card is in your opening hand, you may begin the game with it on the battlefield.
    Whenever you and/or at least one permanent you control becomes the target of a spell or ability an opponent controls, this enchantment deals 2 damage to that player.

    The shared pregame engine reads the opening-hand permission from Oracle text.
    """
    return [AbilitySpec('triggered', [EffectSpec('damage', {'amount': 2, 'selector': 'event_player'})], trigger={
        'event': EventType.TARGETS_ANNOUNCED,
        'condition': {'subject': 'global'},
        'caster_relation': 'opponent',
        'targets_you_or_your_permanents': True,
    })]


register('Leyline of Combustion', _leyline_of_combustion)
