from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mystic_remora() -> list[AbilitySpec]:
    """Cumulative upkeep {1}.
    Whenever an opponent casts a noncreature spell, you may draw a card
    unless that player pays {4}.

    Cumulative upkeep (RULE 702.24, MEC-16) now ships as real behaviour —
    this entry only ever carried the `taxed_draw` trigger; the keyword
    itself binds independently (`game/binding/core.py`'s keyword dispatch
    table reads `Card.keywords`/oracle text directly, regardless of
    whether the rest of the card is hand-authored), so Mystic Remora
    correctly has to be paid for again, closing the previous "dropped,
    never has to be paid for" simplification without touching this spec
    at all.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("taxed_draw", {"cost": "{4}"})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "not_you"},
                "spell_exclude_card_types": ["creature"],
            },
        )
    ]


register("Mystic Remora", _mystic_remora)
