from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sanctum_prelate() -> list[AbilitySpec]:
    """As this creature enters, choose a number.
    Noncreature spells with mana value equal to the chosen number can't
    be cast.

    — MEC-43. The other half of `cast_prohibition`'s literal-threshold
    cluster: an "equal to" comparison (`cmp="eq"`, new) against a number
    picked as this enters, not a fixed constant — `ChooseNumberReplacement`
    (new, a fifth `enter_choice_effects` sibling of `ChooseCreatureType
    Replacement`/`ChooseColorReplacement`/`ChooseNamedModeReplacement`/
    `ChooseCardNameReplacement`) offers a free-text numeric pick the same
    way `ChooseCardNameReplacement` offers a free-text name, stamping
    `GameObject.chosen_number`; `max_mana_value`'s new ``"chosen_number"``
    sentinel reads it back live off this object every check, so a Replay-
    mode edit to the choice is honoured immediately.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("choose_number_on_enter", {})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("cast_prohibition", {
                "scope": "all", "noncreature": True,
                "max_mana_value": "chosen_number", "cmp": "eq",
            })],
        ),
    ]


register("Sanctum Prelate", _sanctum_prelate)
