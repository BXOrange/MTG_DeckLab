from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _vizier_of_many_faces() -> list[AbilitySpec]:
    """You may have this creature enter as a copy of any creature on the battlefield, except if this creature was embalmed, the token has no mana cost, it's white, and it's a Zombie in addition to its other types.
    Embalm {3}{U}{U}

    — PLAY-ALL Step 2 (Eternal Might). Embalm is a printed keyword (`EmbalmEternalizeEffect` makes the token copy).
    The clause is Phantasmal Image's `enter_as_copy` of any creature, with the embalmed-token "except" as
    ``token_add_subtypes``/``token_set_colors`` (applied when the entering object is a token — an Embalm token is the
    only way this card becomes one). "No mana cost" is not modeled, as for Embalm itself.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("enter_as_copy", {
                "target_kind": "creature", "token_add_subtypes": ["Zombie"], "token_set_colors": ["W"],
            })],
        ),
    ]


register("Vizier of Many Faces", _vizier_of_many_faces)
