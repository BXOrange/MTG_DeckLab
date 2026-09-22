from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _domri_anarch_of_bolas() -> list[AbilitySpec]:
    """Domri, Anarch of Bolas (Legendary Planeswalker — Domri, {1}{R}{G})

    "Creatures you control get +1/+0.
    +1: Add {R} or {G}. Creature spells you cast this turn can't be
    countered.
    −2: Target creature you control fights target creature you don't
    control."

    The anthem and the fight ability are already parser-claimable as-is.
    The +1's mana half is the existing ``add_mana``/``colors=["ANY"]``
    single-choice shape narrowed to R/G; its "can't be countered" half
    is `cant_be_countered_this_turn` with ``card_types=["creature"]`` (an
    `UncounterableGrant`, RULE 101.2) — no new primitive needed at all.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"power": 1, "toughness": 0, "affects": "creatures_you_control"})],
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("add_mana", {"colors": ["ANY"], "any_color_choices": ["R", "G"]}),
                EffectSpec("cant_be_countered_this_turn", {"card_types": ["creature"]}),
            ],
            cost={"loyalty": 1},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("fight", {"fighter_kind": "creature_you_control", "other_kind": "creature_you_dont_control"})],
            cost={"loyalty": -2},
        ),
    ]


register("Domri, Anarch of Bolas", _domri_anarch_of_bolas)
