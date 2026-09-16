from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _scion_of_halaster() -> list[AbilitySpec]:
    """Commander creatures you own have "The first time you would draw a
    card each turn, instead look at the top two cards of your library. Put
    one of them into your graveyard and the other back on top of your
    library. Then draw a card."

    — PAR-32 / MEC-57. Hand-authored: the quoted body is a granted
    *replacement* effect (RULE 616), not a trigger/static/mana/activated
    ability, and `_quoted_ability_grant_effects_list`'s recursion only ever
    emits those four grant kinds. Reduces to a single new
    ``first_draw_look_two`` replacement (`effects._first_draw_look_two_
    replacement`, gated on the new per-turn `GameState.first_draw_replaced_
    this_turn` tracker) granted onto every commander creature the
    controller owns via `grant_static_ability`'s ``static_specs`` — the
    same MEC-55/MEC-56 nested-grant plumbing, now extended
    (`continuous._apply_layer_6_ability`) to also recognize a
    `ReplacementEffect`-typed nested spec and file it onto the new
    `GameObject._granted_replacement_effects`, read by `RulesEngine._all_
    replacement_effects` alongside a permanent's own printed ones.
    """
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("grant_static_ability", {
                    "affects": "commander_creatures_you_own",
                    "static_specs": [
                        {"type": "first_draw_look_two", "params": {}},
                    ],
                }),
            ],
        ),
    ]


register("Scion of Halaster", _scion_of_halaster)
