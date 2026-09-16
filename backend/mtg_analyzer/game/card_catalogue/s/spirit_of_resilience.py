from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Spirit of Resilience (graveyard-exit +1/+1) — PAR-60
# ===========================================================================
# Advanced Reconstruction share it).


def _spirit_of_resilience() -> list[AbilitySpec]:
    """Whenever one or more cards leave your graveyard, put a +1/+1 counter
    on this creature, then you may have this creature become a copy of an
    artifact or creature card from among those cards until end of turn.

    Documented simplification: the "become a copy of a card from among those
    that left" rider is dropped (no primitive for BecomeCopy chosen from a
    transient set of just-departed graveyard cards) — the +1/+1 growth,
    the card's dominant effect, is kept."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "+1/+1"})],
            trigger={"event": EventType.CARDS_LEFT_GRAVEYARD, "graveyard_owner": "you"},
        ),
    ]


register("Spirit of Resilience", _spirit_of_resilience)
