from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _spark_double() -> list[AbilitySpec]:
    """You may have this creature enter as a copy of a creature or
    planeswalker you control, except it enters with an additional +1/+1
    counter on it if it's a creature, it enters with an additional
    loyalty counter on it if it's a planeswalker, and it isn't legendary.

    — Spark Double. `effects.EnterAsCopyReplacement` (RULE 614.1c/614.12,
    Clever Impersonator's own mechanism), with two additions this batch
    needed: ``target_kind="creature_or_planeswalker_you_control"``
    (`targeting.py`'s new controller-scoped sibling of the existing bare
    "creature or planeswalker" union kind), and the new
    ``extra_counter_if_creature``/``extra_counter_if_planeswalker`` pair
    (`RulesEngine.add_counters`, applied once the copy is made and the
    resulting permanent's real type is known).

    Documented simplification: "**and it isn't legendary**" is not
    modeled — this engine's copy mechanism (`copy_mechanics.become_copy`)
    has no "strip a supertype" primitive (only `add_types`/`add_subtypes`
    exist), so a Spark Double copying a legendary permanent comes in as a
    second copy of that same legendary permanent and runs into the
    ordinary RULE 704.5j legend-rule SBA like any other route to one,
    rather than being exempted from it the way the real card is.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("enter_as_copy", {
                "target_kind": "creature_or_planeswalker_you_control",
                "extra_counter_if_creature": "+1/+1",
                "extra_counter_if_planeswalker": "loyalty",
            })],
        ),
    ]


register("Spark Double", _spark_double)
