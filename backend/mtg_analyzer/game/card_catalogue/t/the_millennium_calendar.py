from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "When there are 1,000 or more time counters" — the printed threshold, and the life each opponent then loses.
_TIME_COUNTER_THRESHOLD = 1000


def _the_millennium_calendar() -> list[AbilitySpec]:
    """Whenever you untap one or more permanents during your untap step, put that many time counters on The Millennium Calendar.
    {2}, {T}: Double the number of time counters on The Millennium Calendar.
    When there are 1,000 or more time counters on The Millennium Calendar, sacrifice it and each opponent loses 1,000 life.

    — PLAY-ALL (Shorikai Vehicles). The untap trigger reads the new ``permanents_untapped`` count the UNTAP event now carries (how many of the
    active player's permanents actually untapped in the step) through a `bind` (an untap step that untaps nothing adds zero counters). Doubling is a `bind` of the current time counters into one more
    `add_counters` of that many. The 1,000-counter clause is Midnight Clock's: a self `COUNTER` trigger gated by ``source_counters_at_least``,
    checked each time a counter lands (the only time the count can newly reach the threshold).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("bind", {
                "name": "n", "amount": {"kind": "trigger_event", "field": "permanents_untapped"},
                "effects": [{"type": "add_counters", "params": {"amount": "$n", "kind": "time"}}],
            })],
            trigger={"event": EventType.UNTAP, "condition": {"subject": "you"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("bind", {
                "name": "n", "amount": {"kind": "counters", "counter": "time", "of": "source"},
                "effects": [{"type": "add_counters", "params": {"amount": "$n", "kind": "time"}}],
            })],
            cost={"mana": "{2}", "taps_self": True},
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("sacrifice_self", {}),
                EffectSpec("lose_life", {"selector": "each_opponent", "amount": _TIME_COUNTER_THRESHOLD}),
            ],
            trigger={
                "event": EventType.COUNTER, "filter": {"kind": "time"}, "condition": {"subject": "self"},
                "source_counters_at_least": {"count": _TIME_COUNTER_THRESHOLD, "kind": "time"},
            },
        ),
    ]


register("The Millennium Calendar", _the_millennium_calendar)
