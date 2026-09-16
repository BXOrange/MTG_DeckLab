from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _lurrus_of_the_dream_den() -> list[AbilitySpec]:
    """Once during each of your turns, you may cast a permanent spell with
    mana value 2 or less from your graveyard.
    Companion — Each permanent card in your starting deck has mana value 2
    or less. (You may begin the game with this card in your sideboard.)

    — Lurrus of the Dream-Den. The graveyard-cast permission
    (`graveyard_cast_permission`, `game/graveyard_cast.py`) is the
    open-ended sibling of `top_library_permission` above (a standing grant
    from a permanent, not a closed alt-cost keyword like Flashback/Escape);
    ``once_per_turn``/``permanent_only`` both default True, so only the
    ``max_mana_value`` gate needs stating. Companion (RULE 702.139, a
    deck-construction legality rule checked at deckbuilding time, not a
    runtime game effect) isn't modeled — out of the game engine's scope,
    same as every other Companion card. "If a spell cast this way would be
    put into a graveyard this turn, exile it instead" *is* now modeled via
    ``exile_if_would_be_put_into_graveyard`` — see
    `GraveyardCastPermissionEffect`'s own docstring for the mechanism
    (`GameObject.cast_via_graveyard_cast_permission_until_turn` +
    `RulesEngine._move_to_graveyard`'s redirect).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("graveyard_cast_permission", {
                "max_mana_value": 2, "exile_if_would_be_put_into_graveyard": True,
            })],
        )
    ]


register("Lurrus of the Dream-Den", _lurrus_of_the_dream_den)
