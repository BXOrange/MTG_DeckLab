from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _raphael_ninja_destroyer() -> list[AbilitySpec]:
    """Raphael must be blocked if able.
    Enrage — Whenever Raphael is dealt damage, add that much {R}. Until
    end of turn, you don't lose this mana as steps and phases end.

    Simplified: the "you don't lose this mana as steps and phases end"
    persistence isn't modeled — `ManaPool` has no survives-a-step
    mechanism yet, so this mana empties at the current step's end (RULE
    500.4) like any other, rather than lasting the rest of the turn.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {"keywords": ["must_be_blocked"], "affects": "self"})],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_mana", {"color": "R", "amount_from_trigger_event": "amount"})],
            trigger={"event": "DAMAGE", "condition": {"subject": "self", "recipient": True}},
        ),
    ]


register("Raphael, Ninja Destroyer", _raphael_ninja_destroyer)
