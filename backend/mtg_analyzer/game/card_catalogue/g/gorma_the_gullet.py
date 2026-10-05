from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Gorma, the Gullet (count-scaled extra ETB counters) — PAR-60
# ===========================================================================
# `continuous.extra_etb_counters_for` / the ``extra_etb_counter`` static
# gained ``count_selector`` (live count instead of a fixed ``count``) and a
# ``nontoken`` filter.


def _gorma_the_gullet() -> list[AbilitySpec]:
    """Lifelink (folds in).
    Whenever another creature you control dies, put a +1/+1 counter on Gorma
    (parser-claimed — re-added here).
    Nontoken creatures you control enter with an additional +1/+1 counter on
    them for each creature that died under your control this turn."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "+1/+1"})],
            trigger={"event": EventType.DIES,
                     "condition": {"subject": "group", "type": "creature",
                                   "controller": "you", "other": True}},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("extra_etb_counter", {
                "kind": "+1/+1", "nontoken": True,
                "count_selector": "creatures_died_this_turn"})],
        ),
    ]


register("Gorma, the Gullet", _gorma_the_gullet)
