from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Zimone, All-Questioning (prime land count) — PAR-60
# ===========================================================================
# New `GameState.lands_entered_this_turn` tracker (creature-sibling) + the
# self-gating `zimone_all_questioning_end_step` effect (prime check inline).


def _zimone_all_questioning() -> list[AbilitySpec]:
    """At the beginning of your end step, if a land entered the battlefield
    under your control this turn and you control a prime number of lands,
    create Primo, the Indivisible, a legendary 0/0 green and blue Fractal
    creature token, then put that many +1/+1 counters on it."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("zimone_all_questioning_end_step", {})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"},
                     "phase_relation": "you"},
        ),
    ]


register("Zimone, All-Questioning", _zimone_all_questioning)
