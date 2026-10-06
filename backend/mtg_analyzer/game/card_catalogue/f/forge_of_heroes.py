from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _forge_of_heroes() -> list[AbilitySpec]:
    """{T}: Add {C}.
    {T}: Choose target commander that entered this turn. Put a +1/+1 counter on it if it's a creature and a loyalty counter on it if it's a planeswalker.

    — PLAY-ALL (Counter Blitz). The mana ability folds in from `mana_abilities_for`. The second is `add_counter_matching_type` over the new
    ``commander_entered_this_turn`` target kind (any permanent, narrowed by the ``is_commander`` + ``entered_this_turn`` object filter).
    """
    return [
        AbilitySpec("activated", [EffectSpec("add_counter_matching_type", {})], cost={"text": "{T}"}),
    ]


register("Forge of Heroes", _forge_of_heroes)
