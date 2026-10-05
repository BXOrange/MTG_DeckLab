from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _storm_of_souls() -> list[AbilitySpec]:
    """Return all creature cards from your graveyard to the battlefield. Each of them is a 1/1 Spirit with
    flying in addition to its other types. Exile Storm of Souls.

    — Family Matters deck batch. The mass return is Living Death's `players="you"` mode, which leaves
    every returned card on `GameContext.created_objects`; `grant_until`'s ``previous_subject`` falls back
    to that list, so one grant (base 1/1 at layer 7b, an added Spirit subtype, flying) reaches every
    creature that came back, `rest_of_game` (RULE 611.2c: no stated duration). The trailing "Exile ~" is
    `exile`'s untargeted self mode (Spirit Water Revival).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("return_from_graveyard", {
                    "target_kind": "graveyard_creature", "players": "you",
                }),
                EffectSpec("grant_until", {
                    "previous_subject": True, "duration": "rest_of_game",
                    "static": {"type": "pt_set", "params": {"power": 1, "toughness": 1}},
                    "extra_statics": [
                        {"type": "type_change", "params": {"add_subtypes": ["Spirit"]}},
                        {"type": "grant_keyword", "params": {"keywords": ["flying"]}},
                    ],
                }),
                EffectSpec("exile", {"target_kind": None}),
            ],
        )
    ]


register("Storm of Souls", _storm_of_souls)
