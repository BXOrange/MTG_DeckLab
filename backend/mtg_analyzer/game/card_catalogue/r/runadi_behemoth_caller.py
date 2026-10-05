from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: Printed thresholds.
_MIN_CAST_MANA_VALUE = 5
_MANA_VALUE_OFFSET = 4
_HASTE_COUNTERS = 3


def _runadi_behemoth_caller() -> list[AbilitySpec]:
    """Whenever you cast a creature spell with mana value 5 or greater, that
    creature enters with X additional +1/+1 counters on it, where X is its mana
    value minus 4.
    Creatures you control with three or more +1/+1 counters on them have haste.
    {T}: Add {G}.

    — PLAY-ALL Step 2 (Hydranten). The mana ability is read off the text. The
    cast clause is the `extra_etb_counter` static (Master Chef / Gorma's out-of-
    band entry-counter grant) with three new params: ``cast_only`` (`GameObject.
    was_cast` — a reanimated creature does not qualify), ``min_mana_value`` and
    ``count_mana_value_minus`` (amount = mana value minus 4). **Simplification:** it
    is a standing replacement-style grant, not a trigger on the stack, so it can't be
    responded to separately. The haste clause is `grant_keyword` over
    ``creatures_you_control`` with ``object_filter {has_counter_kind: +1/+1,
    counter_min: 3}`` (`combat.matches_object_filter`'s new threshold key).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("extra_etb_counter", {
                "kind": "+1/+1", "cast_only": True,
                "min_mana_value": _MIN_CAST_MANA_VALUE, "count_mana_value_minus": _MANA_VALUE_OFFSET,
            })],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "creatures_you_control", "keywords": ["haste"],
                "object_filter": {"has_counter_kind": "+1/+1", "counter_min": _HASTE_COUNTERS},
            })],
        ),
    ]


register("Runadi, Behemoth Caller", _runadi_behemoth_caller)
