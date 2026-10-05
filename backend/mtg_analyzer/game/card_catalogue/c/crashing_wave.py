from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _crashing_wave() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, waterbend {X}.
    Tap up to X target creatures, then distribute three stun counters among
    any number of tapped creatures your opponents control.

    — `tap` up to X targets (`TargetSpec.count_selector="source_x_paid"`,
    resolved at announce time off `x_paid`) → `add_counters` ``divided`` +
    ``previous_subject`` (a 3-stun-counter pool auto-split across the
    creatures this spell just tapped). **Documented simplification:** the
    stun distribution isn't a RULE 115 target (the printed text has no
    "target" for it — it's "any number of tapped creatures your opponents
    control"), so it's modeled as "the creatures this spell tapped", split
    evenly, rather than a fresh interactive "distribute among any number
    of" choice restricted to opponent-controlled creatures.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("tap", {
                    "target_kind": "creature",
                    "count_selector": "source_x_paid", "optional": True,
                }),
                EffectSpec("add_counters", {
                    "kind": "stun", "amount": 3, "divided": True,
                    "previous_subject": True,
                }),
            ],
            additional_cost={"waterbend": "x"},
        ),
    ]


register("Crashing Wave", _crashing_wave)
