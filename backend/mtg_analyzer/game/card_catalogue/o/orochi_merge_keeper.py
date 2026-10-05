from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _orochi_merge_keeper() -> list[AbilitySpec]:
    """{T}: Add {G}.
    As long as this creature is modified, it has "{T}: Add {G}{G}." (Equipment,
    Auras you control, and counters are modifications.)

    — PLAY-ALL Step 2 (Raggadragga). The plain {T}: Add {G} is a printed mana
    ability, read off the oracle text. The conditional second one is
    `grant_mana_ability` scoped to ``self`` and gated by the ``modified``
    object filter (`combat.matches_object_filter`, RULE 700.9). It is a
    *second* mana ability alongside the printed one, as the card says.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_mana_ability", {
                "mana": [{"G": 2}], "affects": "self", "object_filter": {"modified": True},
            })],
        ),
    ]


register("Orochi Merge-Keeper", _orochi_merge_keeper)
