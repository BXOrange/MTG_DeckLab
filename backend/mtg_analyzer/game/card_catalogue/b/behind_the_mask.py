from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec

from ...card_registry.core import register


def _behind_the_mask() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, you may collect evidence 6.
    Until end of turn, target artifact or creature becomes an artifact creature
    with base power and toughness 4/3. If evidence was collected, it has base
    power and toughness 1/1 until end of turn instead.

    — PLAY-ALL Step 2 (Wick Snail Boom). The optional cost is the parser's own
    ``additional_cost {collect_evidence: 6}`` + ``additional_cost_optional``
    (Spirit Water Revival's shape; `additional_cost_paid` records whether it was
    paid). The body is Kamahl's `grant_until` `type_change` (artifact creature,
    base 4/3) on the one target, then — gated on ``additional_cost_paid`` — a
    second `grant_until` on the *same* object (`previous_subject`) setting base
    1/1. Both are layer-7b "set base P/T" effects, so the later timestamp wins
    and "instead" holds without a second target (which a gated second targeted
    effect would have announced).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("grant_until", {
                    "static": {"type": "type_change", "params": {
                        "add_types": ["artifact", "creature"], "power": 4, "toughness": 3,
                    }},
                    "duration": "end_of_turn", "target_kind": "artifact_or_creature",
                }),
                EffectSpec("grant_until", {
                    "static": {"type": "type_change", "params": {"power": 1, "toughness": 1}},
                    "duration": "end_of_turn", "target_kind": None, "previous_subject": True,
                }, condition={"additional_cost_paid": True}),
            ],
            additional_cost={"collect_evidence": 6},
            additional_cost_optional=True,
        ),
    ]


register("Behind the Mask", _behind_the_mask)
