from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _dusk_urchins() -> list[AbilitySpec]:
    """Whenever this creature attacks or blocks, put a -1/-1 counter on it.
    When this creature dies, draw a card for each -1/-1 counter on it.

    Authored: the attack/block self-counter trigger (ordinary
    ``add_counters`` on the source), and the dies trigger whose draw count
    is ``count_from_trigger_event_counter="-1/-1"`` — read off the firing
    DIES event's snapshotted ``counters`` dict (RULE 400.7).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "-1/-1"})],
            trigger={"event": "ATTACKS", "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "-1/-1"})],
            trigger={"event": "BLOCKS", "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1, "count_from_trigger_event_counter": "-1/-1"})],
            trigger={"event": "DIES", "condition": {"subject": "self"}},
        ),
    ]


register("Dusk Urchins", _dusk_urchins)
