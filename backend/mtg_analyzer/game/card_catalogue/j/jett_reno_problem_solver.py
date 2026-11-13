from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "If her power is 4 or greater, instead draw a card" (the surveil is replaced as the trigger resolves).
_DRAW_INSTEAD_POWER = 4


def _jett_reno_problem_solver() -> list[AbilitySpec]:
    """Whenever Jett Reno becomes tapped, surveil 1. If her power is 4 or greater, instead draw a card.
    Whenever you face a dilemma, put a +1/+1 counter on Jett Reno. (You face a dilemma as you choose one or more modes for a spell or ability.)

    — MEC-141. The "instead" is an `if_else` on Jett's derived power (RULE 613) read as the trigger resolves, so a
    counter put on her earlier in the turn counts. The dilemma trigger is the ordinary `FACED_DILEMMA` head (RULE 700.17).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("if_else", {
                "condition": {"kind": "power", "of": "source", "min": _DRAW_INSTEAD_POWER},
                "then": [{"type": "draw", "params": {"count": 1}}],
                "else": [{"type": "surveil", "params": {"count": 1}}],
            })],
            trigger={"event": EventType.TAPPED, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "+1/+1"})],
            trigger={"event": EventType.FACED_DILEMMA, "condition": {"subject": "you"}},
        ),
    ]


register("Jett Reno, Problem Solver", _jett_reno_problem_solver)
