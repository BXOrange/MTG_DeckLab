from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _plan_for_all_outcomes() -> list[AbilitySpec]:
    """When this enchantment enters, the owner of up to one other target nonland permanent puts it on their choice of the top
    or bottom of their library.
    Whenever you cast your first noncreature spell each turn, empower Jace 1. (Put a loyalty counter on a Jace token you
    control. If you don't control one, first create a blue Jace planeswalker token with "[−1]: Surveil 1" and "[−3]: Draw a
    card.")

    — PLAY-ALL (Multiverse Reforged). The enters trigger is `owner_puts_on_top_or_bottom` (a RULE 401.4 `library_position`
    choice opened for the target's *owner*; the "other" is the source-excluding ``nonland_permanent`` frame). The second
    trigger is the shipped `empower_jace` under the new ``is_nth_noncreature_spell_cast_this_turn`` gate.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("owner_puts_on_top_or_bottom", {"target_kind": "nonland_permanent", "optional": True})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("empower_jace", {"count": 1})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "you"},
                "spell_exclude_card_types": ["creature"],
                "is_nth_noncreature_spell_cast_this_turn": 1,
            },
        ),
    ]


register("Plan for All Outcomes", _plan_for_all_outcomes)
