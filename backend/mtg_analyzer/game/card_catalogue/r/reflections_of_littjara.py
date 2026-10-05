from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _reflections_of_littjara() -> list[AbilitySpec]:
    """As this enchantment enters, choose a creature type.
    Whenever you cast a spell of the chosen type, copy that spell. You may choose new targets for the copy.

    — PLAY-ALL Step 2 (Temur Roar). The enter choice is the parser's own claim. The trigger is Vanquisher's
    Banner's ``cast_of_chosen_type`` cast head (the chosen type is read live off the source) with Thunderclap
    Drake's `copy_spell` reading "that spell" off the firing event (``spell_from_trigger_event``), so the copy
    is of the exact spell that triggered it. **Documented simplification** (shared with the whole
    `CopySpellEffect` family): the copy keeps the original's targets rather than offering new ones.
    """
    return [
        AbilitySpec("enter_replacement", [EffectSpec("choose_creature_type_on_enter", {})]),
        AbilitySpec(
            "triggered",
            [EffectSpec("copy_spell", {"spell_from_trigger_event": "instance_id"})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "cast_of_chosen_type": True,
            },
        ),
    ]


register("Reflections of Littjara", _reflections_of_littjara)
