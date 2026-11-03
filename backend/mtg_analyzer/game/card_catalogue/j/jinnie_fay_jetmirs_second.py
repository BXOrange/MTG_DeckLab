from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _jinnie_fay():
    """If you would create one or more tokens, you may instead create that many 2/2 green Cat creature tokens with haste or that many 3/1 green Dog creature tokens with vigilance."""
    return [AbilitySpec("replacement", [EffectSpec("token_substitution_option", params)]) for params in [
        {"description": "Jinnie Fay: Cat", "to": {"token_name": "Cat", "power": 2, "toughness": 2,
            "colors": ["G"], "subtypes": ["Cat"], "keywords": ["haste"]}},
        {"description": "Jinnie Fay: Dog", "to": {"token_name": "Dog", "power": 3, "toughness": 1,
            "colors": ["G"], "subtypes": ["Dog"], "keywords": ["vigilance"]}},
        {"description": "Jinnie Fay: ursprüngliche Spielsteine behalten"},
    ]]


register("Jinnie Fay, Jetmir's Second", _jinnie_fay)
