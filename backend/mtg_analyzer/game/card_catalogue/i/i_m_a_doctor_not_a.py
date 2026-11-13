from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _i_m_a_doctor_not_a() -> list[AbilitySpec]:
    """Put a +1/+1 counter on target creature you control. Untap it. Until end of turn, it gets +1/+1 and becomes a Doctor. (It loses all other creature types.)

    RULE 608.2c: "it" is the one target throughout (``previous_subject``);
    RULE 205.1a / 205.3m: "becomes a Doctor" replaces the creature types
    until end of turn.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("add_counters", {"count": 1, "kind": "+1/+1", "target_kind": "creature_you_control"}),
                EffectSpec("tap", {"untap": True, "previous_subject": True}),
                EffectSpec("grant_until", {
                    "duration": "end_of_turn", "previous_subject": True,
                    "static": {"type": "anthem", "params": {"power": 1, "toughness": 1}},
                }),
                EffectSpec("grant_until", {
                    "duration": "end_of_turn", "previous_subject": True,
                    "static": {"type": "type_change", "params": {"set_creature_types": ["Doctor"]}},
                }),
            ],
        ),
    ]


register("I'm a Doctor, Not a . . .", _i_m_a_doctor_not_a)
