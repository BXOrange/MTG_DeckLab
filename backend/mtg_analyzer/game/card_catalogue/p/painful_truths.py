from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _painful_truths() -> list[AbilitySpec]:
    """Converge — You draw X cards and lose X life, where X is the number
    of colors of mana spent to cast this spell.

    RULE 702.108a Converge: X is ``len(GameObject.colors_spent_to_cast)``,
    the WUBRG frozenset the mana-payment solver stamps on the spell at
    cast. Both ``draw`` and ``lose_life`` read it via the new
    ``amount_from_count_selector="converge"`` (`continuous.count_selector`).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("draw", {"count": 0, "amount_from_count_selector": "converge"}),
                EffectSpec("lose_life", {"amount": 0, "amount_from_count_selector": "converge"}),
            ],
        ),
    ]


register("Painful Truths", _painful_truths)
