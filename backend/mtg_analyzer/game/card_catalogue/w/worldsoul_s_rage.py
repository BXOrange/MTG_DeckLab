from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _worldsoul_s_rage() -> list[AbilitySpec]:
    """Worldsoul's Rage deals X damage to any target. Put up to X land cards
    from your hand and/or graveyard onto the battlefield tapped.

    — PLAY-ALL Step 2 (World Shaper). `damage` for X, then Tooth and Nail's
    `put_from_hand_onto_battlefield` (an interactive one-at-a-time pick through
    the search machinery) with ``zones: [hand, graveyard]``, ``tapped`` and the
    new ``count: "x"`` (the announced X, read at resolution).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("damage", {"amount": "x", "target_kind": "any"}),
                EffectSpec("put_from_hand_onto_battlefield", {
                    "criteria": {"type": "land"}, "count": "x", "tapped": True, "zones": ["hand", "graveyard"],
                }),
            ],
        ),
    ]


register("Worldsoul's Rage", _worldsoul_s_rage)
