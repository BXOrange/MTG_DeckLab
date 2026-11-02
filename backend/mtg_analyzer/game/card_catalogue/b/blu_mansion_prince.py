from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _blu_mansion_prince() -> list[AbilitySpec]:
    "Whenever this creature enters or attacks, investigate.\nWhenever you sacrifice a Clue, choose a Room card at random. Create a token that's a copy of one of its halves, then unlock it. (There are currently 30 Room cards.)"
    return [
        AbilitySpec(
            'triggered',
            [EffectSpec('create_token', {"count": 1, "token_name": 'Clue'})],
            trigger={"event": [EventType.ENTERS_BATTLEFIELD, EventType.ATTACKS], "condition": {'subject': 'self'}},
            raw_text='whenever ~ enters or attacks, investigate.',
        ),
        AbilitySpec(
            'triggered',
            # RULE 706 (random choice) + RULE 707.2 (token copy of a half) + RULE 709.5f (unlock):
            # `random_room_half_token` draws the Room card with the seeded RNG, asks the controller
            # which half to copy and unlocks the token's door (game/effects/room_tokens.py).
            [EffectSpec('random_room_half_token', {})],
            trigger={
                "event": EventType.SACRIFICE,
                "condition": {"subject": "you"},
                "sacrifice_type": "clue",
            },
            raw_text="whenever you sacrifice a clue, choose a room card at random. create a token that's a copy of 1 of its halves, then unlock it.",
        ),
    ]


register('Blu, Mansion Prince', _blu_mansion_prince)
