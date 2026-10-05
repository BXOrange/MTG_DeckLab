from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "It's a black Zombie in addition to its other colors and types." — RULE 611.2c: no stated duration, so it lasts
#: indefinitely (the Rise from the Grave idiom).
_ZOMBIE = {"type": "grant_until", "params": {
    "previous_subject": True, "duration": "rest_of_game",
    "static": {"type": "type_change", "params": {"add_subtypes": ["Zombie"]}},
}}
_BLACK = {"type": "grant_until", "params": {
    "previous_subject": True, "duration": "rest_of_game",
    "static": {"type": "color_change", "params": {"colors": ["B"], "set": False}},
}}


def _necromantic_selection() -> list[AbilitySpec]:
    """Destroy all creatures, then return a creature card put into a graveyard this way to the battlefield under your
    control. It's a black Zombie in addition to its other colors and types. Exile Necromantic Selection.

    — PLAY-ALL Step 2 (Sultai Arisen). `destroy` over ``all_creatures`` records what it destroyed on
    `GameContext.moved_objects` ("this way"); `return_from_graveyard` with ``pick`` + ``moved_pool`` then lets the
    controller choose one of exactly those cards (tokens never reach a graveyard, regeneration/indestructible
    survivors were never destroyed) and puts it onto the battlefield under their control. ``then_effects`` run with
    the picked card as "it": the Zombie subtype and black colour are added with no duration. The trailing "Exile ~"
    is the untargeted self `exile`.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("destroy", {"selector": "all_creatures"}),
                EffectSpec("return_from_graveyard", {
                    "target_kind": "any_graveyard_creature", "destination": "battlefield",
                    "under_your_control": True, "pick": True, "moved_pool": True,
                    "then_effects": [dict(_ZOMBIE), dict(_BLACK)],
                }),
                EffectSpec("exile", {"target_kind": None}),
            ],
        ),
    ]


register("Necromantic Selection", _necromantic_selection)
