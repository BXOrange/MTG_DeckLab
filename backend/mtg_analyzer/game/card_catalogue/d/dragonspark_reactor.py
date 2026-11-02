from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _dragonspark_reactor() -> list[AbilitySpec]:
    'Whenever this artifact or another artifact you control enters, put a charge counter on this artifact.\n{4}, Sacrifice this artifact: It deals damage equal to the number of charge counters on it to target player and that much damage to up to one target creature.'
    return [
        AbilitySpec(
            'triggered',
            [EffectSpec('add_counters', {"count": 1, "kind": 'charge'})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {'subject': 'self_or_group', 'controller': 'you', 'other': True, 'type': 'artifact'}},
            raw_text='whenever ~ or another artifact you control enters, put a charge counter on ~.',
        ),
        # RULE 608.2h: the sacrificed Reactor's last-known charge counters (stamped when the cost was paid) set both
        # damage amounts; the player and the optional creature are independent RULE 601.2c targets.
        AbilitySpec(
            'activated',
            [EffectSpec('sacrificed_counters_damage', {"kind": "charge"})],
            cost={"text": "{4}, Sacrifice ~"},
            raw_text='{4}, sacrifice ~: it deals damage equal to the number of charge counters on it to target player and that much damage to up to 1 target creature.',
        ),
    ]


register('Dragonspark Reactor', _dragonspark_reactor)
