from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec
from ...card_registry.core import register


def _necroskitter() -> list[AbilitySpec]:
    """Wither (This deals damage to creatures in the form of -1/-1 counters.)
    Whenever a creature an opponent controls with a -1/-1 counter on it
    dies, you may return that card to the battlefield under your control.

    Wither folds in from the RULE 702 keyword catalogue. The dies trigger
    rides `AbilitySpec.counter_death_return` (`RulesEngine._collect_counter_
    death_return_triggers`) — the Marchesa primitive, with ``opponent`` (the
    dying creature is an opponent's), ``immediate`` (no "next end step"
    delay), ``optional`` ("you may").
    """
    return [
        AbilitySpec(
            "static", [],
            counter_death_return={
                "counter_kind": "-1/-1", "opponent": True,
                "immediate": True, "optional": True,
            },
        )
    ]


register("Necroskitter", _necroskitter)
