from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _big_apple_3_am() -> list[AbilitySpec]:
    """This land enters tapped. As it enters, choose a color.
    {T}: Add one mana of the chosen color.
    {5}, {T}: Create a 1/1 black Rat creature token for each opponent you have.

    — PLAY-ALL Step 2 (Wick Snail Boom). Enters-tapped and the chosen-colour
    mana ability are read off the oracle text; the "as it enters, choose a
    color" is the parser's own `choose_color_on_enter` replacement,
    reproduced (a registered card never falls back to the parser). The new
    ability is `create_token` with ``per_opponent`` (Furygale Flocking's "for
    each opponent" token shape, PAR-60): one Rat per living opponent.
    """
    return [
        AbilitySpec("enter_replacement", [EffectSpec("choose_color_on_enter", {})]),
        AbilitySpec(
            "activated",
            [EffectSpec("create_token", {
                "count": 1, "per_opponent": True, "power": 1, "toughness": 1, "colors": ["B"],
                "subtypes": ["Rat"], "keywords": [], "token_name": "Rat",
            })],
            cost={"text": "{5}, {T}"},
        ),
    ]


register("Big Apple, 3 a.m.", _big_apple_3_am)
