from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _wheel_of_fortune() -> list[AbilitySpec]:
    """Each player discards their hand, then draws seven cards.

    ENG-37 B7 retired the fused `wheel_of_fortune` type: a `seq` of a mass
    `discard` (``scope="each_player"``, ``whole_hand=True`` — every player
    discards whatever they hold) and a mass `draw` (``selector="each_player"``,
    flat 7). Windfall is the same shape with the draw count `bind`-measured
    instead of fixed. No oracle-text recognizer yet — this printed line is a
    one-card template, not a family.
    """
    return [
        AbilitySpec("spell_effect", [EffectSpec("seq", {"effects": [
            {"type": "discard", "params": {"scope": "each_player", "whole_hand": True}},
            {"type": "draw", "params": {"selector": "each_player", "count": 7}},
        ]})])
    ]


register("Wheel of Fortune", _wheel_of_fortune)
