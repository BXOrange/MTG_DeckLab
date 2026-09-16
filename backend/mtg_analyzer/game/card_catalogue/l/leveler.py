from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _leveler() -> list[AbilitySpec]:
    """When this creature enters, exile all cards from your library.

    — MEC-43. `ExileLibraryEffect`/`"exile_library"` was already
    registered (built for Paradigm Shift) but had no real consumer yet.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile_library", {})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Leveler", _leveler)
