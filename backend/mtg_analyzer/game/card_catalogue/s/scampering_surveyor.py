
from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _scampering_surveyor() -> list[AbilitySpec]:
    'When this creature enters, search your library for a basic land card or Cave card, put it onto the battlefield tapped, then shuffle.'
    return [
        AbilitySpec("triggered", [EffectSpec("search", {"criteria": {"or": [{"type": "Land", "basic": True}, {"type": "Cave"}]}, "destination": "battlefield_tapped"})], trigger={"event": EventType.ENTERS_BATTLEFIELD}),
    ]


register('Scampering Surveyor', _scampering_surveyor)
