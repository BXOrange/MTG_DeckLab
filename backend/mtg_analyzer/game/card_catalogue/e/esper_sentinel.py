from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _esper_sentinel() -> list[AbilitySpec]:
    """Whenever an opponent casts their first noncreature spell each turn,
    draw a card unless that player pays {X}, where X is this creature's
    power.

    **Documented simplification**: "their first ... each turn" isn't
    tracked (no per-player per-turn "first qualifying spell" counter exists
    yet) — this fires on *every* qualifying opponent spell instead of just
    the first, a strict upgrade rather than a broken card.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("taxed_draw", {"amount_from_source_power": True})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "not_you"},
                "spell_exclude_card_types": ["creature"],
            },
        )
    ]


register("Esper Sentinel", _esper_sentinel)
