from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _archfiend_of_ifnir() -> list[AbilitySpec]:
    """Flying
    Whenever you cycle or discard another card, put a -1/-1 counter on
    each creature your opponents control.
    Cycling {2}

    Flying + Cycling fold in from the RULE 702 catalogue. The trigger is
    two distinct events — `EventType.CYCLED` (cycling's discard is a
    *cost*, not a "discard" game action) and `EventType.DISCARD_CARD` — so
    it's authored as two triggered abilities, each with ``other=True``
    (RULE 109.5 "another card"). The effect is a mass ``add_counters``
    with ``selector="each_creature_opponents_control"``.
    """
    _effect = [EffectSpec("add_counters", {
        "count": 1, "kind": "-1/-1", "selector": "each_creature_opponents_control",
    })]
    return [
        AbilitySpec(
            "triggered", list(_effect),
            trigger={"event": "CYCLED", "condition": {"subject": "you"}, "other": True},
        ),
        AbilitySpec(
            "triggered", list(_effect),
            trigger={"event": "DISCARD_CARD", "condition": {"subject": "you"}, "other": True},
        ),
    ]


register("Archfiend of Ifnir", _archfiend_of_ifnir)
