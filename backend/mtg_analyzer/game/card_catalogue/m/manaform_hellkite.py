from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _manaform_hellkite() -> list[AbilitySpec]:
    """Flying
    Whenever you cast a noncreature spell, create an X/X red Dragon Illusion
    creature token with flying and haste, where X is the amount of mana spent
    to cast that spell. Exile that token at the beginning of the next end
    step."""
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("create_token", {
                    "count": 1, "token_name": "Dragon Illusion", "colors": ["R"],
                    "subtypes": ["Dragon", "Illusion"], "keywords": ["flying", "haste"],
                    "pt_from_trigger_event": "mana_spent",
                }),
                EffectSpec("create_delayed_trigger", {
                    "step": "end", "capture": "created_objects",
                    "effects": [{"type": "exile_specific", "params": {}}],
                }),
            ],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "spell_exclude_card_types": ["creature"],
            },
        ),
    ]


register("Manaform Hellkite", _manaform_hellkite)
