from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _midnight_clock() -> list[AbilitySpec]:
    """{T}: Add {U}.
    {2}{U}: Put an hour counter on this artifact.
    At the beginning of each upkeep, put an hour counter on this artifact.
    When the twelfth hour counter is put on this artifact, shuffle your hand and graveyard into your library, then draw seven cards. Exile this artifact.

    — PLAY-ALL (Living Energy). The mana ability is auto-bound; the two counter abilities are the parser's. The twelfth-
    counter trigger is Nine Lives' shape: a self `COUNTER` trigger on the hour counter gated by
    ``source_counters_at_least`` (checked fresh each time a counter lands, which is the only time the count can newly reach 12).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("add_counters", {"count": 1, "kind": "hour"})],
            cost={"text": "{2}{u}"},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "hour"})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}},
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("shuffle_hand_and_graveyard_into_library", {}),
                EffectSpec("draw", {"count": 7}),
                EffectSpec("exile", {"target_kind": None}),
            ],
            trigger={
                "event": EventType.COUNTER,
                "filter": {"kind": "hour"},
                "condition": {"subject": "self"},
                "source_counters_at_least": {"count": 12, "kind": "hour"},
            },
        ),
    ]


register("Midnight Clock", _midnight_clock)
