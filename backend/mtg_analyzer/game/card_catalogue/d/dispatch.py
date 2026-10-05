from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _dispatch() -> list[AbilitySpec]:
    """Tap target creature.
    Metalcraft — If you control three or more artifacts, exile that creature.

    — PLAY-ALL Step 2 (Counter Intelligence). The tap is the parser's own
    claim. "Exile that creature" is `exile` in its new ``previous_target`` mode
    (the creature the tap clause targeted — one target announced), gated by the
    effect condition ``count_selector_at_least`` over ``artifacts_you_control``
    (3), checked as the spell resolves (RULE 608.2c, after the tap).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("tap", {"target_kind": "creature", "untap": False}),
                EffectSpec(
                    "exile", {"target_kind": "previous_target"},
                    condition={"count_selector_at_least": {"selector": "artifacts_you_control", "count": 3}},
                ),
            ],
        )
    ]


register("Dispatch", _dispatch)
