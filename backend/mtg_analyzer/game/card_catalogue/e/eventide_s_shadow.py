from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _eventides_shadow() -> list[AbilitySpec]:
    """Remove any number of counters from among permanents on the
    battlefield. You draw cards and lose life equal to the number of
    counters removed this way.

    Authored: new bespoke `RemoveCountersFromAmongThenDrawLoseLifeEffect`
    ("remove_counters_from_among_then_draw_lose_life") — an ``optional``
    `_request_choose_objects` over counter-bearing permanents
    (action ``strip_all_counters``), then a draw + life-loss equal to the
    battlefield counter-total delta.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("remove_counters_from_among_then_draw_lose_life", {})],
        )
    ]


register("Eventide's Shadow", _eventides_shadow)
