from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Altered Ego (Clone + X counters) — PAR-60
# ===========================================================================
# `EnterAsCopyReplacement` gained ``extra_counters_from_x`` (the copy spell's
# own announced {X} as the extra-+1/+1 count, resolved when the copy is made).


def _altered_ego() -> list[AbilitySpec]:
    """This spell can't be countered (parser-claimed — re-added).
    You may have this creature enter as a copy of any creature on the
    battlefield, except it enters with X additional +1/+1 counters on it."""
    return [
        AbilitySpec("static", [EffectSpec("cant_be_countered", {})]),
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("enter_as_copy", {
                "target_kind": "creature", "optional": True,
                "extra_counters_from_x": True,
            })],
        ),
    ]


register("Altered Ego", _altered_ego)
