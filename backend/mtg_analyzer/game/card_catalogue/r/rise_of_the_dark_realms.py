from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _rise_of_the_dark_realms() -> list[AbilitySpec]:
    """Put all creature cards from all graveyards onto the battlefield under your control.

    — PLAY-ALL (Revival Trance). The Living Death family's mass `return_from_graveyard` (``players="each_player"``,
    every creature card, no target) taking control of each (``under_your_control``).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("return_from_graveyard", {
                "players": "each_player", "destination": "battlefield", "under_your_control": True,
            })],
        ),
    ]


register("Rise of the Dark Realms", _rise_of_the_dark_realms)
