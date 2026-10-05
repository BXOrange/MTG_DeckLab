from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _deceptive_frostkite() -> list[AbilitySpec]:
    """Flying
    You may have this creature enter as a copy of a creature you control with power 4 or greater, except it's a Dragon in addition to its other types and it has flying.

    — PLAY-ALL Step 2 (Temur Roar). Phantasmal Image's `enter_as_copy` with a "you control" kind, the new
    ``creature_filter`` (power 4 or greater, offered at choice time) and the "except" clause as
    ``add_subtypes``/``add_keywords`` (RULE 707.9b: the copy keeps flying, which the copied text would replace).
    Flying itself is a printed keyword.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("enter_as_copy", {
                "target_kind": "creature_you_control", "creature_filter": {"min_power": 4},
                "add_subtypes": ["Dragon"], "add_keywords": ["flying"],
            })],
        ),
    ]


register("Deceptive Frostkite", _deceptive_frostkite)
