from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sarkhan_soul_aflame() -> list[AbilitySpec]:
    """Dragon spells you cast cost {1} less to cast.
    Whenever a Dragon you control enters, you may have this creature become a copy of it until end of turn, except its name is Sarkhan, Soul Aflame and it's legendary in addition to its other types.

    — PLAY-ALL Step 2 (Temur Roar). The cost reduction is the parser's own claim. The trigger is a group head
    (RULE 603.1) whose body, wrapped in `trigger_subject_referent`, runs `become_copy_until_eot` *against the
    entering Dragon* (it is the referent, not a chosen target); ``set_name`` (new on the become-copy effects,
    applied after the copied abilities are bound) keeps the name, ``add_types: ["Legendary"]`` the supertype.
    The copy reverts at cleanup (RULE 514.2) through the shared snapshot the until-end-of-turn copy takes.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {"generic": 1, "increase": False, "spell_subtype": "dragon"})],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("trigger_subject_referent", {"effects": [{"type": "become_copy_until_eot", "params": {
                "add_types": ["Legendary"], "set_name": "Sarkhan, Soul Aflame",
            }}]})],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "controller": "you", "other": False, "subtypes": ["dragon"], "nontoken": False},
            },
            optional=True,
        ),
    ]


register("Sarkhan, Soul Aflame", _sarkhan_soul_aflame)
