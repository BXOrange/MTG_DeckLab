from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _card() -> list[AbilitySpec]:
    "As this enchantment enters, you lose life equal to your life total.\nYou don't lose the game for having 0 or less life.\nIf you would gain life, draw that many cards instead.\nWhenever you're dealt damage, sacrifice that many nontoken permanents. If you can't, you lose the game.\nWhen this enchantment is put into a graveyard from the battlefield, you lose the game."
    return [
        AbilitySpec(
            'triggered',
            [EffectSpec('lose_game', {})],
            trigger={"event": EventType.DIES, "condition": {'subject': 'self'}},
            raw_text='when ~ dies, you lose the game.',
        ),
        AbilitySpec(
            'enter_replacement',
            [EffectSpec('entry_effect', {'effects': [{'type': 'lose_life', 'params': {'amount': {'kind': 'resource', 'resource': 'life'}}}]})],
            raw_text='',
        ),
        AbilitySpec(
            'static',
            [EffectSpec('cant_lose_game', {"reason": 'life'})],
            raw_text='',
        ),
        AbilitySpec(
            'replacement',
            [EffectSpec('life_gain_to_draw', {})],
            raw_text='',
        ),
        AbilitySpec(
            'triggered',
            [EffectSpec('sacrifice_with_riders', {"what": 'nontoken_permanent', "from_damage": True, "failure": [{'type': 'lose_game', 'params': {}}]})],
            trigger={"event": EventType.DAMAGE, "condition": {'subject': 'player', 'scope': 'you', 'recipient': True}},
            raw_text='',
        ),
    ]


register('Lich', _card)
