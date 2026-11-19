from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _creatures_sharing_a_type(tapped: bool) -> dict:
    """The creatures in the given tapped state that share a creature type with the creature that died (RULE 205.3m).
    ``reference: trigger_subject`` (ENG-64) makes "it" the dying creature, read as last known information (RULE 608.2h),
    not this enchantment."""
    return {
        "zone": "battlefield", "of": "any",
        "filter": {"tapped": tapped, "card_type": "creature", "shares_creature_type_with_reference": True},
        "reference": "trigger_subject",
    }


def _faces_of_the_past() -> list[AbilitySpec]:
    """Whenever a creature dies, tap all untapped creatures that share a creature type with it or untap all tapped creatures that share a creature type with it.

    — ENG-64. The "or" is not a RULE 700.2 "choose one" mode: the controller picks one of the two instructions as the ability
    resolves (RULE 608.2d), so the choice opens at resolution (`choose_effect_on_resolution`), never when the trigger is put on
    the stack, and the group is judged against the board as it then is. Both options are mass `tap` selectors over the dying
    creature's creature types, read from the trigger subject (last known information).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("choose_effect_on_resolution", {
                "options": [
                    [{"type": "tap", "params": {"selector": _creatures_sharing_a_type(False), "untap": False}}],
                    [{"type": "tap", "params": {"selector": _creatures_sharing_a_type(True), "untap": True}}],
                ],
                "descriptions": [
                    "Alle ungetappten Kreaturen, die einen Kreaturentyp mit ihr teilen, tappen.",
                    "Alle getappten Kreaturen, die einen Kreaturentyp mit ihr teilen, enttappen.",
                ],
            })],
            trigger={
                "event": EventType.DIES,
                "condition": {"subject": "group", "controller": "any", "other": False, "type": "creature"},
            },
        )
    ]


register("Faces of the Past", _faces_of_the_past)
