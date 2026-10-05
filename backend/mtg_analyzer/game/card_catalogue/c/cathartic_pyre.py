from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _cathartic_pyre() -> list[AbilitySpec]:
    """Choose one —
    • Cathartic Pyre deals 3 damage to target creature or planeswalker.
    • Discard up to two cards, then draw that many cards.

    Authored: the whole modal spell (the fail-closed parser can't claim the
    "choose one —" block while mode 2 is an unmodelled family). Mode 1 is an
    ordinary ``damage`` to ``creature_or_planeswalker``; mode 2 is a
    `discard` with ``count_max=2`` + ``then_draw_discarded`` — ENG-37 B7
    retired the fused `discard_up_to_then_draw_that_many` type, folding the
    "up to N, then draw that many" shape into `DiscardEffect` params (the
    draw is the choice's own ``then_specs`` delta, `draw_per_discard`'s
    idiom).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [],
            modes={
                "choose": 1,
                "options": [
                    [EffectSpec("damage", {"amount": 3, "target_kind": "creature_or_planeswalker"})],
                    [EffectSpec("discard", {"count_max": 2, "then_draw_discarded": True})],
                ],
                "descriptions": [
                    "~ fügt einer Zielkreatur oder einem Zielplaneswalker 3 Schadenspunkte zu.",
                    "Wirf bis zu zwei Karten ab, ziehe dann so viele Karten.",
                ],
            },
        )
    ]


register("Cathartic Pyre", _cathartic_pyre)
