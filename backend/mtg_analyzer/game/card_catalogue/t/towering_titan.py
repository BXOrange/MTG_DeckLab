from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _towering_titan() -> list[AbilitySpec]:
    """This creature enters with X +1/+1 counters on it, where X is the total toughness of other creatures you control.
    Sacrifice a creature with defender: All creatures gain trample until end of turn.

    — PLAY-ALL (Abzan Armor). The sacrifice ability is the parser's. The counters are an `enters_with_counters_count` static (Boss's
    Chauffeur's idiom) over the new ``total_toughness_other_creatures_you_control`` count selector.
    """
    return [
        AbilitySpec("static", [EffectSpec("enters_with_counters_count", {
            "kind": "+1/+1", "count_selector": "total_toughness_other_creatures_you_control",
        })]),
        AbilitySpec(
            "activated",
            [EffectSpec("pump", {"keywords": ["trample"], "selector": "all_creatures"})],
            cost={"text": "Sacrifice a creature with defender"},
        ),
    ]


register("Towering Titan", _towering_titan)
