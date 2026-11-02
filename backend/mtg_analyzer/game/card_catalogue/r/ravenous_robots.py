
from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ravenous_robots() -> list[AbilitySpec]:
    'Whenever you cast an artifact spell, create a 1/1 colorless Robot artifact creature token.\n{R}, {T}: Creature tokens you control gain haste until end of turn.'
    return [
        AbilitySpec(
            'triggered',
            [EffectSpec('create_token', {"count": 1, "power": 1, "toughness": 1, "colors": [], "subtypes": ['Robot'], "keywords": [], "is_artifact": True, "token_name": 'Robot'})],
            trigger={"event": EventType.SPELL_CAST, "condition": {'subject': 'you'}, "spell_filter": {'card_type': 'artifact'}},
            raw_text='whenever you cast an artifact spell, create a 1/1 colorless robot artifact creature token.',
        ),
        AbilitySpec("activated", [EffectSpec("pump", {"selector": "creatures_you_control", "creature_filter": {"token": True}, "keywords": ["haste"]})], cost={"mana": "{R}", "taps_self": True}),
    ]


register('Ravenous Robots', _ravenous_robots)
