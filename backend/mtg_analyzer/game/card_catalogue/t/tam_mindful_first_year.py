from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tam_mindful_first_year() -> list[AbilitySpec]:
    """Each other creature you control has hexproof from each of its colors.
    {T}: Target creature you control becomes all colors until end of turn.

    — PLAY-ALL Step 2 (SpongeBob). The first line is a `grant_keyword` of the
    synthetic keyword ``hexproof_from_own_colors`` to ``other_creatures_you_control``;
    `targeting._targetable_by` reads it as hexproof against an opponent's source
    that shares a color with the creature (RULE 702.11d). The tap ability is a
    `grant_until` (``end_of_turn``) over a ``creature_you_control`` target with a
    layer-5 `color` static that *sets* all five colors.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "other_creatures_you_control", "keywords": ["hexproof_from_own_colors"],
            })],
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("grant_until", {
                "target_kind": "creature_you_control", "duration": "end_of_turn",
                "static": {"type": "color", "params": {"colors": ["W", "U", "B", "R", "G"], "set": True}},
            })],
            cost={"text": "{T}"},
        ),
    ]


register("Tam, Mindful First-Year", _tam_mindful_first_year)
