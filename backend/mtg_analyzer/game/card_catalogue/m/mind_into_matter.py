from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mind_into_matter() -> list[AbilitySpec]:
    """Draw X cards. Then you may put a permanent card with mana value X or
    less from your hand onto the battlefield tapped.

    — PLAY-ALL Step 2 (Hydranten). Two existing primitives in sequence: `draw`
    with the ``"x"`` sentinel count, then `put_from_hand_onto_battlefield`
    (Horizon of Progress's ``tapped`` flag) with ``max_mana_value: "x"``,
    which `RulesEngine._substitute_x` binds in the effect's criteria (the
    same sentinel Electrodominance's free cast uses). "Permanent card" is the
    six permanent types (Land included, unlike Guardian Sunmare's nonland
    pick); the pick itself is optional by construction (`_request_search`).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("draw", {"count": "x"}),
                EffectSpec("put_from_hand_onto_battlefield", {
                    "criteria": {
                        "type": ["Land", "Creature", "Artifact", "Enchantment", "Planeswalker", "Battle"],
                        "max_mana_value": "x",
                    },
                    "count": 1, "tapped": True,
                }),
            ],
        )
    ]


register("Mind into Matter", _mind_into_matter)
