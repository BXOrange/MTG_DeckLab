from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# more singletons on existing primitives
# ===========================================================================


def _curse_of_the_swine() -> list[AbilitySpec]:
    """Exile X target creatures. For each creature exiled this way, its
    controller creates a 2/2 green Boar creature token.

    Documented simplification: all X Boars go to the *first* exiled
    creature's controller (`creators="previous_target_controller"` reads
    only one previous target) — exact in a two-player game where every
    exiled creature has the same controller, a precision loss only in
    multiplayer."""
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("exile", {"target_kind": "creature", "count": "x", "count_max": "x"}),
                EffectSpec("create_token", {
                    "creators": "previous_target_controller", "count": "x",
                    "token_name": "Boar", "power": 2, "toughness": 2,
                    "colors": ["G"], "subtypes": ["Boar"],
                }),
            ],
        ),
    ]


register("Curse of the Swine", _curse_of_the_swine)
