from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "devour 2": each sacrificed creature adds this many +1/+1 counters (RULE 702.82a).
_DEVOUR_N = 2


def _dragon_broodmother() -> list[AbilitySpec]:
    'Flying\nAt the beginning of each upkeep, create a 1/1 red and green Dragon creature token with flying and devour 2. (As the token enters, you may sacrifice any number of creatures. It enters with twice that many +1/+1 counters on it.)'
    return [
        AbilitySpec(
            'triggered',
            [EffectSpec('devour_token', {
                "devour": _DEVOUR_N,
                "token": {"token_name": "Dragon", "power": 1, "toughness": 1, "colors": ["R", "G"],
                          "subtypes": ["Dragon"], "keywords": ["flying"]},
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}},
            raw_text='at the beginning of each upkeep, create a 1/1 red and green dragon creature token with flying and devour 2.',
        ),
    ]


register('Dragon Broodmother', _dragon_broodmother)
