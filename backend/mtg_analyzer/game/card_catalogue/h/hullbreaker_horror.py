from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _hullbreaker_horror() -> list[AbilitySpec]:
    """Flash
    This spell can't be countered.
    Whenever you cast a spell, choose up to one —
    • Return target spell you don't control to its owner's hand.
    • Return target nonland permanent to its owner's hand.

    — MEC-12 (cEDH Kinnan). Flash and "this spell can't be countered" are
    already parser-claimed for free. The modal trigger needs the new
    RULE 700.2 "choose *up to* one —" quantifier (`AbilitySpec.modes`'s
    new ``optional`` key, `TriggeredAbility.modes_optional`) — the 0-or-1
    sibling of the existing plain "choose one" (always exactly 1) and
    "choose one or both" (1 or 2) shapes, which had no way to express a
    real decline. The first mode's target is the new
    ``spell_you_dont_control`` kind (``ReturnToHandEffect``'s
    ``spell_or_permanent`` flag for the stack-aware bounce).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cant_be_countered", {})],
        ),
        AbilitySpec(
            "triggered",
            [],
            trigger={"event": "SPELL_CAST", "condition": {"subject": "you"}},
            modes={
                "choose": 1,
                "optional": True,
                "options": [
                    [EffectSpec("return_to_hand", {
                        "target_kind": "spell_you_dont_control", "spell_or_permanent": True,
                    })],
                    [EffectSpec("return_to_hand", {"target_kind": "nonland_permanent"})],
                ],
                "descriptions": [
                    "Return target spell you don't control to its owner's hand.",
                    "Return target nonland permanent to its owner's hand.",
                ],
            },
        ),
    ]


register("Hullbreaker Horror", _hullbreaker_horror)
