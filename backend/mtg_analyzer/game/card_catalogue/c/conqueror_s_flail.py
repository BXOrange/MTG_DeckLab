from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _conquerors_flail() -> list[AbilitySpec]:
    """Equipped creature gets +1/+1 for each color among permanents you
    control.
    As long as this Equipment is attached to a creature, your opponents
    can't cast spells during your turn.
    Equip {2}

    — MEC-43 round 2. The anthem reuses the new `count_selector`
    ``"colors_among_permanents_you_control"`` (the P/T sibling of ENG-27's
    same-named mana-ability selector). The cast lockdown needs two
    independent gates ANDed at once — attached, and only during the
    Equipment's controller's own turn — which no single `static_
    conditions` ``kind`` could express before this batch's new ``"all"``
    combinator. "Equip {2}" is the RULE 702.6 keyword, unaffected by
    hand-authoring.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "affects": "attached_permanent", "power": 1, "toughness": 1,
                "power_count": "colors_among_permanents_you_control",
                "toughness_count": "colors_among_permanents_you_control",
            })],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("cast_prohibition", {
                "scope": "opponents",
                "active_if": {
                    "kind": "all",
                    "conditions": [{"kind": "source_attached"}, {"kind": "your_turn"}],
                },
            })],
        ),
    ]


register("Conqueror's Flail", _conquerors_flail)
