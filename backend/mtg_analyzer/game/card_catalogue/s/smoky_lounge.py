from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _smoky_lounge() -> list[AbilitySpec]:
    """At the beginning of your first main phase, add {R}{R}. Spend this mana only to cast Room spells and unlock doors.
    (You may cast either half. That door unlocks on the battlefield. As a sorcery, you may pay the mana cost of a locked door to unlock it.)

    — MEC-111, the left door of Smoky Lounge // Misty Salon. The parser's first-main-phase head over `add_mana` carrying the
    restriction `mana_abilities._parse_restriction` writes for "…cast Room spells and unlock doors": a ``type_spell`` of ``room`` that
    also covers paying an unlock cost (``allow_unlock``, `restriction_predicate_for_unlock`).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_mana", {
                "colors": ["R", "R"],
                "restriction": {"kind": "type_spell", "types": ["room"], "allow_ability": False, "allow_unlock": True},
            })],
            trigger={"event": "STEP_BEGIN", "filter": {"step": "main1"}, "phase_relation": "you"},
        ),
    ]


register("Smoky Lounge", _smoky_lounge)
