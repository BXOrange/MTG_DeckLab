from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _herald_of_secret_streams() -> list[AbilitySpec]:
    """Creatures you control with +1/+1 counters on them can't be blocked.

    — PLAY-ALL Step 2 (Hydranten). The parser already claims the neighbouring
    "creatures you control with +1/+1 counters on them have `<keyword>`"
    (`grant_keyword` with ``object_filter={"has_counter_kind": "+1/+1"}``);
    "can't be blocked" is just the synthetic flag keyword ``cant_be_blocked``
    (`combat.py`'s plain "can't be blocked" static) granted the same way.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "creatures_you_control",
                "object_filter": {"has_counter_kind": "+1/+1"},
                "keywords": ["cant_be_blocked"],
            })],
        ),
    ]


register("Herald of Secret Streams", _herald_of_secret_streams)
