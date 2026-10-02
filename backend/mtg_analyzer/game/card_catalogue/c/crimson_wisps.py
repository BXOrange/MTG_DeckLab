from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _crimson_wisps() -> list[AbilitySpec]:
    """Target creature becomes red and gains haste until end of turn.
    Draw a card.

    — PLAY-ALL Step 2 (Oops! All Night's Whispers). The draw is the parser's own
    claim. The first clause is two `grant_until` effects on the one target (Kamahl's
    `previous_subject` chaining): a layer-5 `color` static that *sets* the colour
    (RULE 105.3 — "becomes red" replaces the colours, Tam's shape) and a
    `grant_keyword`, both until end of turn.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("grant_until", {
                    "target_kind": "creature", "duration": "end_of_turn",
                    "static": {"type": "color", "params": {"colors": ["R"], "set": True}},
                }),
                EffectSpec("grant_until", {
                    "target_kind": None, "previous_subject": True, "duration": "end_of_turn",
                    "static": {"type": "grant_keyword", "params": {"keywords": ["haste"]}},
                }),
                EffectSpec("draw", {"count": 1}),
            ],
        ),
    ]


register("Crimson Wisps", _crimson_wisps)
