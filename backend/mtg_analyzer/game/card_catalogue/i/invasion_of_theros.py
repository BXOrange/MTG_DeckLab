from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _invasion_of_theros() -> list[AbilitySpec]:
    "(As a Siege enters, choose an opponent to protect it. You and others can attack it. When it's defeated, exile it, then cast it transformed.)\nWhen this Siege enters, search your library for an Aura, God, or Demigod card, reveal it, put it into your hand, then shuffle."
    return [
        AbilitySpec(
            'triggered',
            [EffectSpec('search', {"criteria": {'type': ['Aura', 'God', 'Demigod']}, "destination": 'hand', "reveal": True})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {'subject': 'self'}},
            raw_text='',
        ),
    ]


register('Invasion of Theros', _invasion_of_theros)
