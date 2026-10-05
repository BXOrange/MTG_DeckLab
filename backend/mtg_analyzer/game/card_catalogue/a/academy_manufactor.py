from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _academy_manufactor() -> list[AbilitySpec]:
    """If you would create a Clue, Food, or Treasure token, instead create
    one of each.
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("create_one_of_each_named_token", {})],
        ),
    ]


register("Academy Manufactor", _academy_manufactor)
