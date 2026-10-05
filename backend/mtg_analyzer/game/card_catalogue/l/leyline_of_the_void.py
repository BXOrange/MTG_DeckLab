from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _leyline_of_the_void() -> list[AbilitySpec]:
    """If this card is in your opening hand, you may begin the game with
    it on the battlefield.
    If a card would be put into an opponent's graveyard from anywhere,
    exile it instead.

    — MEC-43. The opening-hand permission is read straight off oracle text
    by `opening_hand_battlefield_permission` independent of catalogue
    registration (see its own docstring) — nothing to author here. The
    redirect is the new `graveyard_redirect` static (``scope="opponent"``,
    the default), the plain-exile sibling of Dauthi Voidwalker's
    `void_counter_redirect`.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("graveyard_redirect", {"scope": "opponent"})],
        ),
    ]


register("Leyline of the Void", _leyline_of_the_void)
