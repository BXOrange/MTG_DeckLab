from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _wings_of_velis_vel() -> list[AbilitySpec]:
    """Changeling
    Target creature has base power and toughness 4/4, gains all creature
    types, and gains flying until end of turn.

    — PLAY-ALL Step 2 (Wick Snail Boom). Water Wings' `grant_until` (a layer-7b
    `pt_set` 4/4, any ``creature`` target) with a flying grant and a layer-4
    `type_change` adding the ``changeling`` marker (`continuous.
    ALL_CREATURE_TYPES`) — how the engine spells "is every creature type"
    (a granted keyword is not enough: `has_subtype` reads the marker or a
    printed/intrinsic changeling). Changeling itself, printed on the card, is
    read from the card's text.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("grant_until", {
                "target_kind": "creature", "duration": "end_of_turn",
                "static": {"type": "pt_set", "params": {"power": 4, "toughness": 4}},
                "extra_statics": [
                    {"type": "grant_keyword", "params": {"keywords": ["flying"]}},
                    # "gains all creature types": the layer-4 marker `has_subtype` reads (PAR-109)
                    {"type": "type_change", "params": {"add_subtypes": ["changeling"]}},
                ],
            })],
        )
    ]


register("Wings of Velis Vel", _wings_of_velis_vel)
