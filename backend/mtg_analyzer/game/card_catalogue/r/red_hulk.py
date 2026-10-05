from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _red_hulk() -> list[AbilitySpec]:
    """Reach, trample
    Enrage — Whenever Red Hulk is dealt damage, put a +1/+1 counter on
    him. When you do, he deals damage equal to the number of +1/+1
    counters on him to any other target.

    Simplified: RULE 603.10's "when you do" is really a second, reflexive
    triggered ability off the counter-placement — this engine has no such
    primitive yet, so both halves run as one triggered ability's effect
    list instead (RULE 608.2a resolves a list in printed order, and
    nothing has a window to intervene between them either way in an
    automated engine), which is behaviourally indistinguishable from the
    two-trigger original. Reach/trample are bind-on-load from the RULE 702
    keyword catalogue, not hand-authored here.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("add_counters", {}),
                EffectSpec("damage_equal_to_counters", {"target_kind": "any"}),
            ],
            trigger={"event": "DAMAGE", "condition": {"subject": "self", "recipient": True}},
        ),
    ]


register("Red Hulk", _red_hulk)
