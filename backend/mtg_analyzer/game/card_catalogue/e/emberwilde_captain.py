from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _emberwilde_captain() -> list[AbilitySpec]:
    """When this creature enters, you become the monarch.
    Whenever an opponent attacks you while you're the monarch, this creature deals damage to that player equal to the
    number of cards in their hand.

    — Both abilities are the parser's own clauses, reproduced (the gate refused the card only for the "if you're the
    monarch" rider). RULE 725.1: the ETB makes its controller the monarch. The attack trigger is a
    `PLAYER_ATTACKED` (the attacker is the "event player", ``defender_is_you`` restricts it to attacks against
    Emberwilde's controller); the `is_monarch` clause is checked as the damage is dealt (RULE 603.4 simplification:
    checked on resolution, not also on trigger -- a monarchy that changes while the trigger is on the stack
    fizzles the damage, the stricter reading of "while you're the monarch"), and the hand size is counted for the
    attacking player on resolution (RULE 608.2h).
    """
    return [
        AbilitySpec(
            'triggered',
            [EffectSpec('become_monarch', {})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {'subject': 'self'}},
            raw_text='when ~ enters, you become the monarch.',
        ),
        AbilitySpec(
            'triggered',
            [EffectSpec('bind', {"name": 'n', "amount": {'kind': 'count_selector', 'selector': {'zone': 'hand', 'of': 'you'}, 'of': 'event_player'}, "effects": [{'type': 'damage', 'params': {'amount': '$n', 'selector': 'event_player'}, 'condition': {'kind': 'is_monarch'}}]})],
            trigger={"event": EventType.PLAYER_ATTACKED, "condition": {'subject': 'player', 'scope': 'not_you'}, "defender_is_you": True},
            raw_text="whenever an opponent attacks you while you're the monarch, ~ deals damage to that player equal to the number of cards in their hand.",
        ),
    ]


register('Emberwilde Captain', _emberwilde_captain)
