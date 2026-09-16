from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _windfall() -> list[AbilitySpec]:
    """Each player discards their hand, then draws cards equal to the
    greatest number of cards a player discarded this way.

    ENG-37 B7 retired the fused `windfall` type. Every player discards their
    whole hand, so "the greatest number a player discarded this way" is the
    greatest hand size *before* the discard — a `bind` whose ``amount``
    measures ``resource: hand_size`` with ``aggregate: max`` over
    ``each_player`` (taken once, before the body), feeding the mass `draw`.
    The mass `discard` (``scope="each_player"``, ``whole_hand=True``) is the
    same first half as Wheel of Fortune.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("bind", {
                "name": "n",
                "amount": {
                    "kind": "resource", "resource": "hand_size",
                    "aggregate": "max", "scope": "each_player",
                },
                "effects": [
                    {"type": "discard",
                     "params": {"scope": "each_player", "whole_hand": True}},
                    {"type": "draw",
                     "params": {"selector": "each_player", "count": "$n"}},
                ],
            })],
        )
    ]


register("Windfall", _windfall)
