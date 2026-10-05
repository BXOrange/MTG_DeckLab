from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _commence_the_endgame() -> list[AbilitySpec]:
    """This spell can't be countered.
    Draw two cards, then amass Zombies X, where X is the number of cards in your hand.

    — PLAY-ALL Step 2 (Eternal Might). "Can't be countered" is the parser's own claim. The body is a `seq` of a
    draw and a `bind` that measures the hand *after* the draw (``resource: hand_size``) into `amass` Zombies.
    """
    return [
        AbilitySpec("spell_effect", [EffectSpec("cant_be_countered", {})]),
        AbilitySpec("spell_effect", [EffectSpec("seq", {"effects": [
            {"type": "draw", "params": {"count": 2}},
            {"type": "bind", "params": {
                "name": "n",
                "amount": {"kind": "resource", "resource": "hand_size"},
                "effects": [{"type": "amass", "params": {"subtype": "Zombies", "count": "$n"}}],
            }},
        ]})]),
    ]


register("Commence the Endgame", _commence_the_endgame)
