from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _perch_protection() -> list[AbilitySpec]:
    """Gift an extra turn (You may promise an opponent a gift as you cast this spell. If you do, they take an extra
    turn after this one.)
    Create four 2/2 blue Bird creature tokens with flying. If the gift was promised, all permanents you control
    phase out, and until your next turn, your life total can't change and you gain protection from everything.
    Exile Perch Protection.

    — Peace Offering deck batch. Gift is folded in by the keyword catalogue (the extra turn goes to the chosen
    opponent). The Birds are an inline `create_token`; the promised-gift rider is Teferi's Protection's one
    `phase_out_all_you_control` (mass phasing, the life lock and protection from everything, all lapsing at
    your next turn) behind the ``gift_promised`` flag — it runs after the Birds, so they phase out with the rest.
    "Exile ~" is the untargeted self `exile`.
    """
    return [
        AbilitySpec("spell_effect", [
            EffectSpec("create_token", {
                "count": 4, "power": 2, "toughness": 2, "colors": ["U"], "subtypes": ["Bird"],
                "keywords": ["flying"], "token_name": "Bird",
            }),
            EffectSpec("if_else", {
                "condition": {"kind": "flag", "flag": "gift_promised"},
                "then": [{"type": "phase_out_all_you_control", "params": {}}],
            }),
            EffectSpec("exile", {"target_kind": None}),
        ]),
    ]


register("Perch Protection", _perch_protection)
