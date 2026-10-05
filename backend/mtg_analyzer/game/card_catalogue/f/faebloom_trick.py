from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _faebloom_trick() -> list[AbilitySpec]:
    """Create two 1/1 blue Faerie creature tokens with flying. When you do,
    tap target creature an opponent controls.

    — PLAY-ALL Step 2 (yshtola). The tokens, then a RULE 603.12 reflexive
    trigger (`reflexive_trigger`, the same carrier Meanders Guide's parsed
    "When you do" uses) whose own target is chosen only when it is put on
    the stack. "An opponent controls" is `creature_you_dont_control`, the
    parser's own spelling for it (Blustersquall).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("create_token", {
                    "count": 2, "power": 1, "toughness": 1, "colors": ["U"],
                    "subtypes": ["Faerie"], "keywords": ["flying"], "token_name": "Faerie",
                }),
                EffectSpec("reflexive_trigger", {"then_trigger": [
                    {"type": "tap", "params": {"target_kind": "creature_you_dont_control", "untap": False}},
                ]}),
            ],
        )
    ]


register("Faebloom Trick", _faebloom_trick)
