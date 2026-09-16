from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _nezahal_primal_tide() -> list[AbilitySpec]:
    """This spell can't be countered.
    You have no maximum hand size.
    Whenever an opponent casts a noncreature spell, draw a card.
    Discard three cards: Exile Nezahal. Return it to the battlefield
    tapped under its owner's control at the beginning of the next end
    step.

    — MEC-12 (cEDH Kinnan). The first three abilities are already
    parser-claimed for free (`reuse` confirms it — restated here since
    registering the name turns the parser fallback off for all of them,
    not just the unclaimed one). The activated ability is the new
    `return_self_to_battlefield`, run via the existing RULE 603.7
    `CreateDelayedTriggerEffect`.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cant_be_countered", {})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("no_max_hand_size", {"affects": "you"})],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": "SPELL_CAST", "condition": {"subject": "group", "controller": "not_you"},
                "spell_exclude_card_types": ["creature"],
            },
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("exile", {"target_kind": None}),
                EffectSpec("create_delayed_trigger", {
                    "step": "end", "scope": "any",
                    "effects": [{"type": "return_self_to_battlefield", "params": {"tapped": True}}],
                    "description": "Nezahal: return tapped at the next end step",
                }),
            ],
            cost={"discard": 3},
        ),
    ]


register("Nezahal, Primal Tide", _nezahal_primal_tide)
