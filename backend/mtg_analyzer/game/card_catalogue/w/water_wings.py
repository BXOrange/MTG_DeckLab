from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _water_wings() -> list[AbilitySpec]:
    """Target creature you control has base power and toughness 4/4 and gains
    flying and hexproof until end of turn.

    — PLAY-ALL Step 2 (Wick Snail Boom). A `grant_until` (``end_of_turn``)
    over a ``creature_you_control`` target carrying a layer-7b `pt_set` 4/4
    (the same static Humility uses permanently) plus a `grant_keyword` for
    flying and hexproof as its extra static. *Base* P/T, so counters and
    pumps still apply on top.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("grant_until", {
                "target_kind": "creature_you_control", "duration": "end_of_turn",
                "static": {"type": "pt_set", "params": {"power": 4, "toughness": 4}},
                "extra_statics": [{"type": "grant_keyword", "params": {"keywords": ["flying", "hexproof"]}}],
            })],
        )
    ]


register("Water Wings", _water_wings)
