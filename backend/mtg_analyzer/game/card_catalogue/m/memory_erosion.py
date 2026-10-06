from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _memory_erosion() -> list[AbilitySpec]:
    """Whenever an opponent casts a spell, that player mills two cards.

    — PLAY-ALL (Hope to the last). An opponent-cast group trigger (Rhystic Study's head) over `mill` with the
    ``event_player`` selector (the caster, `SPELL_CAST`'s ``player_id``).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("mill", {"count": 2, "selector": "event_player"})],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "group", "controller": "not_you"}},
        ),
    ]


register("Memory Erosion", _memory_erosion)
