from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ezuri_s_predation() -> list[AbilitySpec]:
    """For each creature your opponents control, create a 4/4 green Phyrexian Beast creature token.
    Each of those tokens fights a different one of those creatures.

    — Tramplesaurus Rex deck batch. One atomic `fight_each_opposing_creature`
    (`FightEachOpposingCreatureEffect`): the pairing between the new tokens and the creatures they
    were made for needs both lists at once, which two separate clauses cannot share.
    """
    return [AbilitySpec("spell_effect", [EffectSpec("fight_each_opposing_creature", {})])]


register("Ezuri's Predation", _ezuri_s_predation)
