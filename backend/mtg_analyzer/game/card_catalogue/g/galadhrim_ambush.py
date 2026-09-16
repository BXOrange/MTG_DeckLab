from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _galadhrim_ambush() -> list[AbilitySpec]:
    """Create X 1/1 green Elf Warrior creature tokens, where X is the
    number of attacking creatures.
    Prevent all combat damage that would be dealt this turn by non-Elf
    creatures.

    — Eliferate deck batch. The token creation already parses on its own
    — reproduced verbatim. The prevention clause is `prevent_all_combat_
    damage`'s new `exclude_subtype` qualifier (RULE 615) — see its
    docstring.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("create_token", {
                    "colors": ["G"], "subtypes": ["Elf", "Warrior"], "keywords": [],
                    "token_name": "Elf Warrior", "power": 1, "toughness": 1,
                    "count_selector": "attacking_creatures",
                }),
                EffectSpec("prevent_all_combat_damage", {"exclude_subtype": "elf"}),
            ],
        ),
    ]


register("Galadhrim Ambush", _galadhrim_ambush)
