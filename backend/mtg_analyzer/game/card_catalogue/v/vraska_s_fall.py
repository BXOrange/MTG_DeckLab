from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _vraskas_fall() -> list[AbilitySpec]:
    """Each opponent sacrifices a creature or planeswalker of their choice
    and gets a poison counter.

    — Eliferate deck batch. `SacrificeEffect`'s existing `selector=
    "each_opponent"` (Professor Onyx's −3 precedent) already opens a real
    RULE 601.2c-style choice *for that opponent* rather than an auto-pick
    when ``greatest_power`` isn't set, and `what="creature_or_planeswalker"`
    is the one compound sacrifice-type word this catalogue already
    recognizes (Tevesh Szat). The poison half is the plain
    `add_player_counters` every other poison-granting card uses, same
    `selector="each_opponent"`.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("sacrifice", {
                    "selector": "each_opponent", "what": "creature_or_planeswalker",
                }),
                EffectSpec("add_player_counters", {
                    "selector": "each_opponent", "kind": "poison", "amount": 1,
                }),
            ],
        ),
    ]


register("Vraska's Fall", _vraskas_fall)
