from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _perplexing_test() -> list[AbilitySpec]:
    """Choose one —
    • Return all creature tokens to their owners' hands.
    • Return all nontoken creatures to their owners' hands."""
    return [
        AbilitySpec(
            "spell_effect", [],
            modes={
                "choose": 1,
                "options": [
                    [EffectSpec("return_to_hand", {
                        "selector": "all_creatures", "filter": {"token": True},
                    })],
                    [EffectSpec("return_to_hand", {
                        "selector": "all_creatures", "filter": {"token": False},
                    })],
                ],
                "descriptions": [
                    "Bringe alle Kreaturtoken auf die Haende ihrer Besitzer zurueck.",
                    "Bringe alle Nichtspielstein-Kreaturen auf die Haende ihrer Besitzer zurueck.",
                ],
            },
        ),
    ]


register("Perplexing Test", _perplexing_test)
