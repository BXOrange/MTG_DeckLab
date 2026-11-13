from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


#: Time counters at which Kes sacrifices herself (the card's "nine or more").
KES_SACRIFICE_THRESHOLD = 9


def _kes_evolving_telepath() -> list[AbilitySpec]:
    """At the beginning of your end step, put a time counter on Kes, then draw X cards, where X is the number of time counters on her. Then if she has nine or more time counters on her, sacrifice her.

    RULE 608.2c: one resolution performs the three instructions in order;
    X is read after the counter is added (the ``bind`` node measures at
    that moment), and the sacrifice gate reads the same live counters.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("add_counters", {"count": 1, "kind": "time"}),
                EffectSpec("bind", {
                    "name": "n", "amount": {"kind": "counters", "counter": "time", "of": "source"},
                    "effects": [{"type": "draw", "params": {"count": "$n"}}],
                }),
                EffectSpec("if_else", {
                    "condition": {"kind": "source_counters", "counter": "time", "min": KES_SACRIFICE_THRESHOLD},
                    "then": [{"type": "sacrifice_self", "params": {}}],
                }),
            ],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"},
        ),
    ]


register("Kes, Evolving Telepath", _kes_evolving_telepath)
