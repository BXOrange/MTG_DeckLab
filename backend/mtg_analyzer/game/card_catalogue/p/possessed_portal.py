from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _card() -> list[AbilitySpec]:
    'If a player would draw a card, that player skips that draw instead.\nAt the beginning of each end step, each player sacrifices a permanent of their choice unless they discard a card.'
    return [
        AbilitySpec(
            'triggered',
            [EffectSpec('each_player_pay_or', {"cost": 'discard a card', "scope": 'each_player', "effects": [{'type': 'sacrifice', 'params': {'target_kind': 'player', 'what': 'permanent', 'count': 1}}]})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {'step': 'end'}},
            raw_text='at the beginning of each end step, each player sacrifices a permanent of their choice unless they discard a card.',
        ),
        AbilitySpec(
            'replacement',
            [EffectSpec('skip_draw', {})],
            raw_text='',
        ),
    ]


register('Possessed Portal', _card)
