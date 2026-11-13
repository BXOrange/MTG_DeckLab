
from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _slimefoot_and_squee() -> list[AbilitySpec]:
    'Whenever Slimefoot and Squee enters or attacks, create a 1/1 green Saproling creature token.\n{1}{B}{R}{G}, Sacrifice a Saproling: Return this card and up to one other target creature card from your graveyard to the battlefield. Activate only as a sorcery.'
    return [
        AbilitySpec(
            'triggered',
            [EffectSpec('create_token', {"count": 1, "power": 1, "toughness": 1, "colors": ['G'], "subtypes": ['Saproling'], "keywords": [], "token_name": 'Saproling'})],
            trigger={"event": [EventType.ENTERS_BATTLEFIELD, EventType.ATTACKS], "condition": {'subject': 'self'}},
            raw_text='whenever ~ enters or attacks, create a 1/1 green saproling creature token.',
        ),
        AbilitySpec("activated", [
            EffectSpec("return_from_graveyard", {"target_kind": "graveyard_creature", "optional": True,
                # RULE 109.5 / 115.1: "up to one OTHER target creature card" -- the source card (in the graveyard) is never
                # the second target, even though its own return is the "this card" half.
                "creature_filter": {"not_reference": True}, "include_source": True, "excludes_source": True}),
            EffectSpec("sorcery_speed_marker", {}),
        ], cost={"text": "{1}{B}{R}{G}, sacrifice a Saproling", "activation_zones": ["graveyard"]}),
    ]


register('Slimefoot and Squee', _slimefoot_and_squee)
