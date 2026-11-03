from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _invasion_of_tolvada() -> list[AbilitySpec]:
    "(As a Siege enters, choose an opponent to protect it. You and others can attack it. When it's defeated, exile it, then cast it transformed.)\nWhen this Siege enters, return target nonbattle permanent card from your graveyard to the battlefield."
    return [
        AbilitySpec(
            'triggered',
            [EffectSpec('return_from_graveyard', {"target_kind": 'graveyard_permanent', "destination": 'battlefield', "creature_filter": {'without_card_type': 'battle'}})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {'subject': 'self'}},
            raw_text='',
        ),
    ]


register('Invasion of Tolvada', _invasion_of_tolvada)
