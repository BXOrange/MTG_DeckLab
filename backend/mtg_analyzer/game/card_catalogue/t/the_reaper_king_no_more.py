from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _the_reaper_king_no_more() -> list[AbilitySpec]:
    """When The Reaper enters, put a -1/-1 counter on each of up to two
    target creatures.
    Whenever a creature an opponent controls with a -1/-1 counter on it
    dies, you may put that card onto the battlefield under your control.
    Do this only once each turn.

    Registered wholesale (so the parser is skipped), so both clauses are
    authored: the ETB as an ordinary ``add_counters`` "each of up to two
    target creatures" triggered ability, the dies trigger as
    `counter_death_return` with ``once_per_turn`` (RULE 603.2) on top of
    Necroskitter's opponent/immediate/optional shape.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {
                "count": 1, "kind": "-1/-1", "target_kind": "creature",
                "target_count": 2, "optional": True,
            })],
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "static", [],
            counter_death_return={
                "counter_kind": "-1/-1", "opponent": True, "immediate": True,
                "optional": True, "once_per_turn": True,
            },
        ),
    ]


register("The Reaper, King No More", _the_reaper_king_no_more)
