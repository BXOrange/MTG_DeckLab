from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _lazav_wearer_of_faces() -> list[AbilitySpec]:
    'Whenever Lazav attacks, exile target card from a graveyard, then investigate. (Create a Clue token. It\'s an artifact with "{2}, Sacrifice this token: Draw a card.")\nWhenever you sacrifice a Clue, you may have Lazav become a copy of a creature card exiled with it until end of turn.'
    return [
        AbilitySpec(
            'triggered',
            # RULE 607.2a: "exiled with it" links the exile to Lazav, so the exile
            # records the card on Lazav (`track_exiled_with`) for the second ability.
            [EffectSpec('exile', {"target_kind": 'any_graveyard_card', "track_exiled_with": True}),
             EffectSpec('create_token', {"count": 1, "token_name": 'Clue'})],
            trigger={"event": EventType.ATTACKS, "condition": {'subject': 'self'}},
            raw_text='whenever ~ attacks, exile target card from a graveyard, then investigate.',
        ),
        AbilitySpec(
            'triggered',
            # RULE 707.2 / 611.2: a copy effect lasting until end of turn. The template
            # is a creature card among the cards linked to Lazav (`template="linked"`
            # keeps creature cards only); with several the controller picks one, and
            # `optional` is the "you may".
            [EffectSpec('copy_for_duration', {
                "recipient": 'source', "template": 'linked',
                "duration": 'end_of_turn', "optional": True,
            })],
            trigger={
                "event": EventType.SACRIFICE,
                "condition": {"subject": "you"},
                "sacrifice_type": "clue",
            },
            raw_text='whenever you sacrifice a clue, you may have ~ become a copy of a creature card exiled with it until end of turn.',
        ),
    ]


register('Lazav, Wearer of Faces', _lazav_wearer_of_faces)
