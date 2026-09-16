from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _geistwave() -> list[AbilitySpec]:
    """Return target nonland permanent to its owner's hand. If you
    controlled that permanent, draw a card.

    — Geistwave. The bounce and rider are an ordinary sequence: the draw
    names the announced object through `previous_target`.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("return_to_hand", {"target_kind": "nonland_permanent"}),
                EffectSpec(
                    "draw", {"count": 1},
                    condition={"kind": "is_you", "of": "previous_target"},
                ),
            ],
        )
    ]


register("Geistwave", _geistwave)
